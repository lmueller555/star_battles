"""World simulation container."""
from __future__ import annotations

import random
from typing import List, Optional

from pygame.math import Vector3

from game.combat.targeting import update_lock
from game.combat.weapons import HitResult, Projectile, WeaponDatabase, resolve_hitscan
from game.engine.logger import ChannelLogger, GameLogger
from game.ships.flight import update_ship_flight
from game.ships.ship import Ship, WeaponMount
from game.world.sector import SectorMap
from game.ftl.utils import compute_ftl_charge, compute_ftl_cost


class SpaceWorld:
    def __init__(self, weapons: WeaponDatabase, sector: SectorMap, logger: GameLogger) -> None:
        self.weapons = weapons
        self.sector = sector
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

    def add_ship(self, ship: Ship) -> None:
        self.ships.append(ship)

    def update(self, dt: float) -> None:
        physics_log = self.logger.channel("physics")
        weapons_log = self.logger.channel("weapons")
        ftl_log = self.logger.channel("ftl")

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

        # Simple PD: ships with PD module attempt to destroy missiles within 400m.
        for ship in self.ships:
            if "pd" not in ship.modules:
                continue
            for projectile in list(self.projectiles):
                if projectile.weapon.wclass != "missile" or projectile.team == ship.team:
                    continue
                distance = ship.kinematics.position.distance_to(projectile.position)
                if distance < 400.0 and self.rng.random() < 0.6:
                    self.projectiles.remove(projectile)

        if self.threat_timer > 0.0:
            self.threat_timer = max(0.0, self.threat_timer - dt)
        if self.ftl_cooldown > 0.0:
            self.ftl_cooldown = max(0.0, self.ftl_cooldown - dt)
        if self.jump_charge_remaining > 0.0 and self.jump_ship:
            self.jump_charge_remaining = max(0.0, self.jump_charge_remaining - dt)
            if self.jump_charge_remaining == 0.0 and self.pending_jump_id:
                self._execute_jump(ftl_log)

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
        if weapon.wclass == "hitscan" and target:
            result = resolve_hitscan(
                ship.kinematics.position,
                forward,
                weapon,
                target.kinematics.position,
                target.kinematics.velocity,
                target.stats.avoidance,
                target.stats.crit_defense,
                target.stats.armor,
                self.rng,
            )
            if result.hit:
                self._apply_damage(target, result.damage)
                if ship.team == "player" or target.team == "player":
                    self.threat_timer = max(self.threat_timer, 12.0)
            return result
        else:
            velocity = forward * weapon.projectile_speed + ship.kinematics.velocity
            projectile = Projectile(
                weapon=weapon,
                position=ship.kinematics.position + forward * 3.0,
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
        self.pending_jump_id = None
        self.pending_jump_cost = 0.0
        self.jump_ship = None
        self.ftl_cooldown = 8.0
        if logger:
            logger.info("FTL jump complete to %s", destination)


__all__ = ["SpaceWorld"]
