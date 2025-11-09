"""World simulation container."""
from __future__ import annotations

import random
from typing import List, Optional, TYPE_CHECKING

from pygame.math import Vector3

from game.combat.targeting import update_lock
from game.combat.weapons import HitResult, Projectile, WeaponDatabase, resolve_hitscan
from game.engine.logger import ChannelLogger, GameLogger
from game.math.ballistics import compute_lead
from game.ships.flight import update_ship_flight
from game.ships.ship import Ship, WeaponMount
from game.world.sector import SectorMap
from game.world.station import DockingStation, StationDatabase
from game.world.mining import MiningDatabase, MiningManager, MiningHUDState
from game.ftl.utils import compute_ftl_charge, compute_ftl_cost

if TYPE_CHECKING:
    from game.world.ai import ShipAI


class SpaceWorld:
    def __init__(
        self,
        weapons: WeaponDatabase,
        sector: SectorMap,
        stations: StationDatabase,
        mining: MiningDatabase,
        logger: GameLogger,
    ) -> None:
        self.weapons = weapons
        self.sector = sector
        self.stations = stations
        self.logger = logger
        self.ships: List[Ship] = []
        self.projectiles: List[Projectile] = []
        self.rng = random.Random(1)
        default_system = sector.default_system()
        self.current_system_id: Optional[str] = default_system.id if default_system else None
        self.pending_jump_id: Optional[str] = None
        self.pending_jump_cost: float = 0.0
        self.jump_charge_remaining: float = 0.0
        self.jump_ship: Optional[Ship] = None
        self.ftl_cooldown: float = 0.0
        self.threat_timer: float = 0.0
        self._station_cache: dict[str, list[DockingStation]] = {}
        self.mining = MiningManager(mining)
        self.mining.enter_system(self.current_system_id)
        self._ai: dict[int, "ShipAI"] = {}

    def add_ship(self, ship: Ship, ai: "ShipAI | None" = None) -> None:
        self.ships.append(ship)
        if ai:
            self._ai[id(ship)] = ai

    def update(self, dt: float) -> None:
        physics_log = self.logger.channel("physics")
        weapons_log = self.logger.channel("weapons")
        ftl_log = self.logger.channel("ftl")

        # Update any AI controllers before physics so they can steer.
        for ship_id, controller in list(self._ai.items()):
            if not controller.ship.is_alive():
                continue
            controller.update(self, dt)

        for ship in self.ships:
            if not ship.is_alive():
                continue
            update_ship_flight(ship, dt, logger=physics_log)

        for ship in self.ships:
            if ship.target_id is not None:
                target = next((s for s in self.ships if id(s) == ship.target_id), None)
            else:
                target = None
            update_lock(ship, target, dt)

        for projectile in list(self.projectiles):
            projectile.update(dt, weapons_log)
            if not projectile.alive():
                self.projectiles.remove(projectile)
                continue
            if projectile.target_id is not None:
                target = next((s for s in self.ships if id(s) == projectile.target_id), None)
            else:
                target = None
            if target and target.is_alive():
                to_target = target.kinematics.position - projectile.position
                distance = to_target.length()
                if distance < 5.0:
                    self._apply_damage(target, projectile.weapon.base_damage)
                    self.projectiles.remove(projectile)
                    continue
                if projectile.weapon.wclass == "missile":
                    desired = to_target.normalize() * projectile.weapon.projectile_speed
                    projectile.velocity += (desired - projectile.velocity) * min(1.0, 3.5 * dt)

        # Simple PD: ships with PD grid attempt to destroy missiles within module-defined range.
        for ship in self.ships:
            pd_range = ship.module_stat_total("pd_range")
            if pd_range <= 0.0:
                continue
            pd_accuracy = ship.module_stat_total("pd_accuracy") or 0.5
            power_cost = ship.module_stat_total("power")
            for projectile in list(self.projectiles):
                if projectile.weapon.wclass != "missile" or projectile.team == ship.team:
                    continue
                distance = ship.kinematics.position.distance_to(projectile.position)
                if distance > pd_range:
                    continue
                if power_cost > 0.0 and ship.power < power_cost:
                    continue
                if self.rng.random() < min(0.95, pd_accuracy):
                    self.projectiles.remove(projectile)
                    if power_cost > 0.0:
                        ship.power = max(0.0, ship.power - power_cost)

        if self.threat_timer > 0.0:
            self.threat_timer = max(0.0, self.threat_timer - dt)
        if self.ftl_cooldown > 0.0:
            self.ftl_cooldown = max(0.0, self.ftl_cooldown - dt)
        if self.jump_charge_remaining > 0.0 and self.jump_ship:
            self.jump_charge_remaining = max(0.0, self.jump_charge_remaining - dt)
            if self.jump_charge_remaining == 0.0 and self.pending_jump_id:
                self._execute_jump(ftl_log)

        # Allow AI controllers to react post-physics (weapon fire, state machines).
        for ship_id, controller in list(self._ai.items()):
            if not controller.ship.is_alive():
                continue
            controller.post_update(self, dt)

    def activate_countermeasure(self, ship: Ship) -> tuple[bool, str]:
        if ship.countermeasure_cooldown > 0.0:
            return False, "Countermeasures recharging"
        radius = ship.module_stat_total("cm_radius")
        if radius <= 0.0:
            radius = ship.module_stat_total("pd_range")
        if radius <= 0.0:
            radius = 420.0
        lock_break = ship.module_stat_total("cm_lock_break")
        if lock_break <= 0.0:
            lock_break = 0.6
        power_cost = ship.module_stat_total("cm_power")
        if power_cost <= 0.0:
            power_cost = 18.0
        cooldown = ship.module_stat_total("cm_cooldown")
        if cooldown <= 0.0:
            cooldown = 9.0
        if ship.power < power_cost:
            return False, "Insufficient power"
        ship.power = max(0.0, ship.power - power_cost)
        missiles_removed = 0
        for projectile in list(self.projectiles):
            if projectile.weapon.wclass != "missile" or projectile.team == ship.team:
                continue
            distance = ship.kinematics.position.distance_to(projectile.position)
            if distance <= radius:
                self.projectiles.remove(projectile)
                missiles_removed += 1
        previous_lock = ship.lock_progress
        if lock_break > 0.0:
            ship.lock_progress = max(0.0, ship.lock_progress - lock_break)
        ship.countermeasure_cooldown = cooldown
        if missiles_removed and ship.lock_progress < previous_lock:
            return True, f"Countermeasures intercepted {missiles_removed} missiles and broke locks"
        if missiles_removed:
            return True, f"Countermeasures intercepted {missiles_removed} missiles"
        if ship.lock_progress < previous_lock:
            return True, "Countermeasures disrupted hostile locks"
        return True, "Countermeasures deployed"

    def fire_mount(self, ship: Ship, mount: WeaponMount, target: Optional[Ship]) -> Optional[HitResult]:
        if not mount.weapon_id:
            return None
        weapon = self.weapons.get(mount.weapon_id)
        if mount.cooldown > 0.0:
            return None
        if ship.power < weapon.power_per_shot:
            return None
        ship.power -= weapon.power_per_shot
        mount.cooldown = weapon.cooldown
        forward = ship.kinematics.forward()
        to_target = None
        distance = 0.0
        angle_error = 0.0
        effective_gimbal = weapon.gimbal
        if mount.hardpoint:
            effective_gimbal = min(effective_gimbal, mount.hardpoint.gimbal)
        if target:
            to_target = target.kinematics.position - ship.kinematics.position
            distance = to_target.length()
            if distance > 0.0:
                angle_error = forward.angle_to(to_target.normalize())
            if angle_error > effective_gimbal:
                return None
        if weapon.wclass == "hitscan" and target:
            result = resolve_hitscan(
                ship.kinematics.position,
                forward,
                weapon,
                target.kinematics.position,
                target.kinematics.velocity,
                target.stats.avoidance + target.module_stat_total("avoidance"),
                target.stats.crit_defense + target.module_stat_total("crit_defense"),
                target.stats.armor + target.module_stat_total("armor"),
                self.rng,
                distance=distance,
                angle_error=angle_error,
                gimbal_limit=effective_gimbal,
                accuracy_bonus=ship.module_stat_total("weapon_accuracy"),
                crit_bonus=ship.module_stat_total("weapon_crit"),
            )
            if result.hit:
                self._apply_damage(target, result.damage)
                if ship.team == "player" or target.team == "player":
                    self.threat_timer = max(self.threat_timer, 12.0)
            return result
        else:
            launch_direction = forward
            if target and weapon.projectile_speed > 0.0:
                lead_point = compute_lead(
                    ship.kinematics.position,
                    target.kinematics.position,
                    target.kinematics.velocity,
                    weapon.projectile_speed,
                )
                to_lead = lead_point - ship.kinematics.position
                if to_lead.length_squared() > 0:
                    launch_direction = to_lead.normalize()
            if target and angle_error > effective_gimbal:
                return None
            velocity = launch_direction * weapon.projectile_speed + ship.kinematics.velocity
            projectile = Projectile(
                weapon=weapon,
                position=ship.kinematics.position + launch_direction * 3.0,
                velocity=velocity,
                target_id=id(target) if target else None,
                ttl=weapon.max_range / max(1.0, weapon.projectile_speed),
                team=ship.team,
            )
            self.projectiles.append(projectile)
            if target and (ship.team == "player" or target.team == "player"):
                self.threat_timer = max(self.threat_timer, 12.0)
            return None

    def _apply_damage(self, target: Ship, damage: float) -> None:
        if target.durability > 0.0:
            absorbed = min(target.durability, damage * 0.5)
            target.durability -= absorbed
            damage -= absorbed
        target.hull = max(0.0, target.hull - damage)
        target.hull_regen_cooldown = 3.0
        if target.team == "player":
            self.threat_timer = max(self.threat_timer, 12.0)

    def in_threat(self) -> bool:
        return self.threat_timer > 0.0

    def begin_jump(self, ship: Ship, destination_id: str) -> tuple[bool, str]:
        if self.pending_jump_id or self.jump_charge_remaining > 0.0:
            return False, "FTL already charging"
        if self.ftl_cooldown > 0.0:
            return False, "FTL cooling down"
        if self.current_system_id is None:
            return False, "No current system"
        if destination_id == self.current_system_id:
            return False, "Already in system"
        try:
            distance = self.sector.distance(self.current_system_id, destination_id)
        except KeyError:
            return False, "Unknown destination"
        if distance > ship.stats.ftl_range:
            return False, "Destination out of range"
        cost = compute_ftl_cost(distance, ship.stats.ftl_cost_per_ly)
        if ship.resources.tylium < cost:
            return False, "Insufficient Tylium"
        charge = compute_ftl_charge(ship.stats.ftl_charge, ship.stats.ftl_threat_charge, self.in_threat())
        self.pending_jump_id = destination_id
        self.pending_jump_cost = cost
        self.jump_charge_remaining = charge
        self.jump_ship = ship
        ftl_log = self.logger.channel("ftl")
        ftl_log.info(
            "FTL charging for %.1fs from %s to %s (distance %.2fly)",
            charge,
            self.current_system_id,
            destination_id,
            distance,
        )
        return True, f"Charging FTL ({charge:.1f}s)"

    def cancel_jump(self) -> None:
        if self.pending_jump_id:
            self.pending_jump_id = None
            self.jump_charge_remaining = 0.0
            self.jump_ship = None
            self.pending_jump_cost = 0.0

    def _execute_jump(self, logger: Optional[ChannelLogger] = None) -> None:
        if not self.pending_jump_id or not self.jump_ship:
            self.cancel_jump()
            return
        destination = self.pending_jump_id
        ship = self.jump_ship
        ship.resources.tylium = max(0.0, ship.resources.tylium - self.pending_jump_cost)
        ship.kinematics.position = Vector3(0.0, 0.0, 0.0)
        ship.kinematics.velocity = Vector3(0.0, 0.0, 0.0)
        ship.kinematics.angular_velocity = Vector3(0.0, 0.0, 0.0)
        self.current_system_id = destination
        self.mining.enter_system(destination)
        self.pending_jump_id = None
        self.pending_jump_cost = 0.0
        self.jump_ship = None
        self.ftl_cooldown = 8.0
        if logger:
            logger.info("FTL jump complete to %s", destination)

    def stations_in_current_system(self) -> list[DockingStation]:
        if self.current_system_id is None:
            return []
        if self.current_system_id not in self._station_cache:
            stations = list(self.stations.in_system(self.current_system_id))
            self._station_cache[self.current_system_id] = stations
        return self._station_cache[self.current_system_id]

    def nearest_station(self, ship: Ship) -> tuple[Optional[DockingStation], float]:
        position = ship.kinematics.position
        best_station = None
        best_distance = float("inf")
        for station in self.stations_in_current_system():
            station_pos = Vector3(*station.position)
            distance = position.distance_to(station_pos)
            if distance < best_distance:
                best_distance = distance
                best_station = station
        return best_station, best_distance

    def start_mining(self, ship: Ship) -> tuple[bool, str]:
        mining_log = self.logger.channel("mining")
        success, message = self.mining.start_mining(ship)
        if mining_log.enabled:
            if success:
                mining_log.info("Mining engaged: %s", message)
            else:
                mining_log.info("Mining failed: %s", message)
        return success, message

    def stop_mining(self) -> None:
        if self.mining.active_node():
            mining_log = self.logger.channel("mining")
            self.mining.stop_mining()
            if mining_log.enabled:
                mining_log.info("Mining disengaged by pilot")

    def mining_active(self) -> bool:
        node = self.mining.active_node()
        return bool(node and node.active)

    def step_mining(
        self,
        ship: Ship,
        dt: float,
        scanning: bool,
        stabilizing: bool,
    ) -> MiningHUDState:
        if scanning:
            self.mining.scan_step(ship, dt)
        mining_log = self.logger.channel("mining")
        state = self.mining.step(
            ship,
            dt,
            stabilizing=stabilizing,
            scanning_active=scanning,
            logger=mining_log,
        )
        if state.alert_triggered:
            self.threat_timer = max(self.threat_timer, 12.0)
        return state


__all__ = ["SpaceWorld"]
