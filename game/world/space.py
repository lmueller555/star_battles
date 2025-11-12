"""World simulation container."""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass
from typing import Iterable, List, Optional, TYPE_CHECKING

from pygame.math import Vector3

from game.combat.targeting import update_lock
from game.combat.weapons import (
    HitResult,
    Projectile,
    WeaponDatabase,
    resolve_hitscan,
)
from game.engine.frame_clock import advance_frame
from game.engine.logger import ChannelLogger, GameLogger
from game.engine.telemetry import (
    AITelemetry,
    CollisionTelemetry,
    PerformanceSnapshot,
    basis_snapshot,
    combine_performance,
)
from game.math.ballistics import compute_lead
from game.ships.flight import update_ship_flight
from game.ships.ship import Ship, WeaponMount
from game.world.sector import SectorMap
from game.world.station import DockingStation, StationDatabase
from game.world.mining import (
    MiningDatabase,
    MiningHUDState,
    MiningManager,
    MiningManagerState,
)
from game.ftl.utils import compute_ftl_charge, compute_ftl_cost
from game.world.asteroids import Asteroid, AsteroidField, AsteroidFieldState

COLLISION_RADII = {
    "Strike": 9.0,
    "Escort": 32.0,
    "Line": 130.0,
    "Outpost": 260.0,
}

COLLISION_CELL_SIZE = max(1.0, 2.0 * max(COLLISION_RADII.values()))
COLLISION_INV_CELL_SIZE = 1.0 / COLLISION_CELL_SIZE

COLLISION_MASS = {
    "Strike": 1.0,
    "Escort": 1.5,
    "Line": 2.2,
    "Outpost": 25.0,
}

COLLISION_RESTITUTION = 0.35
COLLISION_DAMAGE_SCALE = 6.0
HITSCAN_BULLET_SPEED = 1800.0

# Offsets used to position player spawns around a friendly Outpost.
_OUTPOST_SPAWN_PATTERN: tuple[tuple[float, float, float], ...] = (
    (0.0, 820.0, 20.0),
    (30.0, 880.0, 60.0),
    (60.0, 940.0, -40.0),
    (90.0, 1000.0, 0.0),
    (120.0, 860.0, 45.0),
    (150.0, 920.0, -60.0),
    (180.0, 800.0, 35.0),
    (210.0, 880.0, -30.0),
    (240.0, 960.0, 55.0),
    (270.0, 900.0, -50.0),
    (300.0, 840.0, 25.0),
    (330.0, 980.0, -20.0),
)

OUTPOST_SPAWN_OFFSETS: tuple[Vector3, ...] = tuple(
    Vector3(
        math.cos(math.radians(angle)) * radius,
        height,
        math.sin(math.radians(angle)) * radius,
    )
    for angle, radius, height in _OUTPOST_SPAWN_PATTERN
)


@dataclass
class SpaceWorldState:
    """Snapshot of the active space instance."""

    current_system_id: Optional[str]
    ships: List[Ship]
    projectiles: List[Projectile]
    ai_controllers: dict[int, "ShipAI"]
    pending_jump_id: Optional[str]
    pending_jump_cost: float
    jump_charge_remaining: float
    jump_ship: Optional[Ship]
    ftl_cooldown: float
    threat_timer: float
    mining: MiningManagerState
    asteroids: AsteroidFieldState


if TYPE_CHECKING:
    from game.world.ai import ShipAI


def _is_strike_ship(ship: "Ship | None") -> bool:
    return ship is not None and ship.frame.size.lower() == "strike"


def _strike_damage_adjustment(damage: float) -> float:
    """Ensure strike weapon damage stays positive without capping output."""

    return max(1.0, damage)


class SpaceWorld:
    def __init__(
        self,
        weapons: WeaponDatabase,
        sector: SectorMap,
        stations: StationDatabase,
        mining: MiningDatabase,
        logger: GameLogger,
        rng: random.Random | None = None,
    ) -> None:
        self.weapons = weapons
        self.sector = sector
        self.stations = stations
        self.logger = logger
        self.ships: List[Ship] = []
        self.projectiles: List[Projectile] = []
        self.rng = rng or random.Random(42)
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
        self.asteroids = AsteroidField()
        self.asteroids.enter_system(self.current_system_id)
        self._ai: dict[int, "ShipAI"] = {}
        self._current_frame_index: int = 0
        self._collision_telemetry = CollisionTelemetry()
        self._ai_telemetry = AITelemetry()
        self._basis_log_accumulator: float = 0.0
        self._performance_snapshot: PerformanceSnapshot = PerformanceSnapshot()

    def _team_outpost_anchor(self, team: str | None) -> Ship | None:
        if team is None:
            return None
        preferred: Ship | None = None
        fallback: Ship | None = None
        for candidate in self._station_ships(team=team):
            if not candidate.is_alive():
                continue
            role = candidate.frame.role.lower()
            size = candidate.frame.size.lower()
            if "outpost" in role or size == "outpost":
                preferred = candidate
                break
            if fallback is None:
                fallback = candidate
        return preferred or fallback

    def pick_outpost_spawn_point(self, team: str | None) -> Optional[Vector3]:
        anchor = self._team_outpost_anchor(team)
        if not anchor:
            return None
        offset = self.rng.choice(OUTPOST_SPAWN_OFFSETS)
        spawn = anchor.kinematics.position + offset
        return Vector3(spawn.x, spawn.y, spawn.z)

    def place_ship_near_outpost(self, ship: Ship, *, zero_velocity: bool = False) -> bool:
        spawn = self.pick_outpost_spawn_point(getattr(ship, "team", None))
        if spawn is None:
            return False
        ship.kinematics.position = spawn
        if zero_velocity:
            ship.kinematics.velocity = Vector3(0.0, 0.0, 0.0)
            ship.kinematics.angular_velocity = Vector3(0.0, 0.0, 0.0)
        return True

    def add_ship(self, ship: Ship, ai: "ShipAI | None" = None) -> None:
        self.ships.append(ship)
        if ai:
            self._ai[id(ship)] = ai

    def remove_ship(self, ship: Ship) -> None:
        """Remove a ship from the active simulation."""

        if ship in self.ships:
            self.ships.remove(ship)
        self._ai.pop(id(ship), None)
        if self.jump_ship is ship:
            self.jump_ship = None
            self.pending_jump_id = None
            self.pending_jump_cost = 0.0
            self.jump_charge_remaining = 0.0
        for candidate in self.ships:
            if candidate.target_id == id(ship):
                candidate.target_id = None

    def suspend_simulation(self) -> SpaceWorldState:
        """Detach active entities so the world can be suspended."""

        mining_state = self.mining.suspend()
        asteroid_state = self.asteroids.suspend()
        state = SpaceWorldState(
            current_system_id=self.current_system_id,
            ships=list(self.ships),
            projectiles=list(self.projectiles),
            ai_controllers=dict(self._ai),
            pending_jump_id=self.pending_jump_id,
            pending_jump_cost=self.pending_jump_cost,
            jump_charge_remaining=self.jump_charge_remaining,
            jump_ship=self.jump_ship,
            ftl_cooldown=self.ftl_cooldown,
            threat_timer=self.threat_timer,
            mining=mining_state,
            asteroids=asteroid_state,
        )
        self.ships = []
        self.projectiles = []
        self._ai = {}
        self.pending_jump_id = None
        self.pending_jump_cost = 0.0
        self.jump_charge_remaining = 0.0
        self.jump_ship = None
        self.ftl_cooldown = 0.0
        self.threat_timer = 0.0
        return state

    def resume_simulation(self, state: Optional[SpaceWorldState]) -> None:
        """Restore ships, projectiles, and timers after suspension."""

        if state is None:
            return
        self.current_system_id = state.current_system_id
        self.ships = list(state.ships)
        self.projectiles = list(state.projectiles)
        self._ai = dict(state.ai_controllers)
        self.pending_jump_id = state.pending_jump_id
        self.pending_jump_cost = state.pending_jump_cost
        self.jump_charge_remaining = state.jump_charge_remaining
        self.jump_ship = state.jump_ship
        self.ftl_cooldown = state.ftl_cooldown
        self.threat_timer = state.threat_timer
        self.mining.resume(state.mining)
        self.asteroids.resume(state.asteroids)

    def update(self, dt: float) -> None:
        frame_index = advance_frame()
        self._current_frame_index = frame_index
        physics_log = self.logger.channel("physics")
        weapons_log = self.logger.channel("weapons")
        ftl_log = self.logger.channel("ftl")

        self.asteroids.update(dt)

        for ship in self.ships:
            ship.collision_recoil = 0.0

        player_positions = [
            ship.kinematics.position
            for ship in self.ships
            if ship.team == "player" and ship.is_alive()
        ]

        self._ai_telemetry.begin_frame(frame_index)

        for ship_id, controller in list(self._ai.items()):
            ship_ref = controller.ship
            if not ship_ref.is_alive():
                continue
            bucket, _ = controller.classify_bucket(player_positions)
            should_run = controller.should_update(frame_index, bucket)
            self._ai_telemetry.record(bucket, should_run)
            if should_run:
                controller.update(self, dt)
                controller.mark_updated(frame_index)

        for ship in self.ships:
            if not ship.is_alive():
                continue
            update_ship_flight(ship, dt, logger=physics_log)

        self._resolve_collisions(physics_log, dt)

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
            target_ship = None
            target_asteroid = None
            if projectile.target_id is not None:
                target_ship = next((s for s in self.ships if id(s) == projectile.target_id), None)
                if target_ship is None:
                    target_asteroid = self._find_asteroid_by_id(projectile.target_id)
            if target_ship and target_ship.is_alive():
                to_target = target_ship.kinematics.position - projectile.position
                distance = to_target.length()
                if distance < 5.0:
                    if not projectile.visual_only:
                        damage = projectile.weapon.base_damage
                        if _is_strike_ship(projectile.source_ship):
                            damage = _strike_damage_adjustment(damage)
                        self._apply_damage(target_ship, damage)
                    self.projectiles.remove(projectile)
                    continue
                if projectile.weapon.wclass == "missile" and to_target.length_squared() > 0.0:
                    desired = to_target.normalize() * projectile.weapon.projectile_speed
                    projectile.velocity += (desired - projectile.velocity) * min(1.0, 3.5 * dt)
            elif target_asteroid and not target_asteroid.is_destroyed():
                to_target = target_asteroid.position - projectile.position
                distance = to_target.length()
                hit_radius = max(5.0, target_asteroid.radius)
                if distance <= hit_radius:
                    if not projectile.visual_only:
                        damage = projectile.weapon.base_damage
                        if _is_strike_ship(projectile.source_ship):
                            damage = _strike_damage_adjustment(damage)
                        self._apply_asteroid_damage(
                            target_asteroid,
                            damage,
                            projectile.source_ship,
                        )
                    self.projectiles.remove(projectile)
                    continue
                if projectile.weapon.wclass == "missile" and to_target.length_squared() > 0.0:
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
            if controller.consume_post_update():
                controller.post_update(self, dt)

        self._ai_telemetry.advance_time(dt, physics_log)

        basis_stats = basis_snapshot()
        collision_stats = self._collision_telemetry.snapshot()
        ai_stats = self._ai_telemetry.snapshot()
        self._performance_snapshot = combine_performance(
            basis_stats, collision_stats, ai_stats
        )

        self._basis_log_accumulator += dt
        if (
            self._basis_log_accumulator >= 3.0
            and (basis_stats.hits > 0 or basis_stats.misses > 0)
        ):
            self._basis_log_accumulator = 0.0
            if physics_log.enabled:
                physics_log.info(
                    "Basis cache: frame=%d hits=%d misses=%d duplicates=%d ships=%d revisions=%s",
                    basis_stats.frame,
                    basis_stats.hits,
                    basis_stats.misses,
                    basis_stats.duplicates,
                    basis_stats.ships,
                    basis_stats.revisions,
                )

    def performance_snapshot(self) -> PerformanceSnapshot:
        return self._performance_snapshot

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

    def fire_mount(
        self,
        ship: Ship,
        mount: WeaponMount,
        target: Ship | Asteroid | None,
    ) -> Optional[HitResult]:
        if not mount.weapon_id:
            return None
        weapon = self.weapons.get(mount.weapon_id)
        if mount.cooldown > 0.0:
            return None
        power_cost = weapon.power_cost
        is_strike = _is_strike_ship(ship)
        if is_strike:
            power_cost = 1.2
        if ship.power < power_cost:
            return None
        ship.power -= power_cost
        mount.cooldown = weapon.cooldown
        if is_strike:
            mount.cooldown = 0.6
        basis = ship.kinematics.basis
        forward = basis.forward
        right = basis.right
        up = basis.up
        muzzle = self._weapon_muzzle_position(ship, mount, forward, right, up)
        target_ship: Ship | None = None
        target_asteroid: Asteroid | None = None
        if isinstance(target, Ship):
            if not target.is_alive():
                return None
            target_ship = target
        elif isinstance(target, Asteroid):
            if target.is_destroyed():
                return None
            target_asteroid = target
        target_position: Vector3 | None = None
        target_velocity = Vector3()
        if target_ship:
            target_position = target_ship.kinematics.position
            target_velocity = target_ship.kinematics.velocity
        elif target_asteroid:
            target_position = target_asteroid.position
        distance = 0.0
        angle_error = 0.0
        aim_direction = forward
        effective_gimbal = weapon.gimbal
        if mount.hardpoint:
            effective_gimbal = min(effective_gimbal, mount.hardpoint.gimbal)
        if target_position is not None:
            to_target = target_position - muzzle
            distance = to_target.length()
            if distance > 0.0:
                aim_direction = to_target.normalize()
                angle_error = forward.angle_to(aim_direction)
            if angle_error > effective_gimbal:
                return None
        if weapon.wclass == "hitscan" and target_position is not None:
            avoidance = 0.0
            crit_defense = 0.0
            armor = 0.0
            if target_ship:
                avoidance = target_ship.stats.avoidance + target_ship.module_stat_total("avoidance")
                crit_defense = target_ship.stats.crit_defense + target_ship.module_stat_total("crit_defense")
                armor = target_ship.stats.armor + target_ship.module_stat_total("armor")
            result = resolve_hitscan(
                muzzle,
                forward,
                weapon,
                target_position,
                target_velocity,
                avoidance,
                crit_defense,
                armor,
                self.rng,
                distance=distance,
                angle_error=angle_error,
                gimbal_limit=effective_gimbal,
                accuracy_bonus=ship.module_stat_total("weapon_accuracy"),
                crit_bonus=ship.module_stat_total("weapon_crit"),
            )
            if is_strike and result.hit:
                result.damage = _strike_damage_adjustment(result.damage)
            if result.hit:
                if target_ship:
                    self._apply_damage(target_ship, result.damage)
                    if ship.team == "player" or target_ship.team == "player":
                        self.threat_timer = max(self.threat_timer, 12.0)
                elif target_asteroid:
                    self._apply_asteroid_damage(target_asteroid, result.damage, ship)
            bullet_speed = weapon.projectile_speed if weapon.projectile_speed > 0.0 else HITSCAN_BULLET_SPEED
            bullet_velocity = aim_direction * bullet_speed + ship.kinematics.velocity
            travel_distance = distance if distance > 0.0 else weapon.max_range
            ttl = max(0.1, travel_distance / max(1.0, bullet_speed))
            target_id = None
            if target_ship:
                target_id = id(target_ship)
            elif target_asteroid:
                target_id = id(target_asteroid)
            tracer = Projectile(
                weapon=weapon,
                position=muzzle,
                velocity=bullet_velocity,
                target_id=target_id,
                ttl=ttl,
                team=ship.team,
                source_ship=ship,
                visual_only=True,
            )
            self.projectiles.append(tracer)
            return result
        else:
            launch_direction = aim_direction
            if target_ship and weapon.projectile_speed > 0.0:
                lead_point = compute_lead(
                    muzzle,
                    target_ship.kinematics.position,
                    target_ship.kinematics.velocity,
                    weapon.projectile_speed,
                )
                to_lead = lead_point - muzzle
                if to_lead.length_squared() > 0:
                    launch_direction = to_lead.normalize()
            if target_position is not None and angle_error > effective_gimbal:
                return None
            velocity = launch_direction * weapon.projectile_speed + ship.kinematics.velocity
            target_id = None
            if target_ship:
                target_id = id(target_ship)
            elif target_asteroid:
                target_id = id(target_asteroid)
            projectile = Projectile(
                weapon=weapon,
                position=muzzle,
                velocity=velocity,
                target_id=target_id,
                ttl=weapon.max_range / max(1.0, weapon.projectile_speed),
                team=ship.team,
                source_ship=ship,
            )
            self.projectiles.append(projectile)
            if target_ship and (ship.team == "player" or target_ship.team == "player"):
                self.threat_timer = max(self.threat_timer, 12.0)
            return None

    @staticmethod
    def _weapon_muzzle_position(
        ship: Ship,
        mount: WeaponMount,
        forward: Vector3,
        right: Vector3,
        up: Vector3,
    ) -> Vector3:
        local = getattr(mount.hardpoint, "position", None)
        if local is None:
            return ship.kinematics.position
        return ship.kinematics.position + right * local.x + up * local.y + forward * local.z

    def _find_asteroid_by_id(self, target_id: int) -> Asteroid | None:
        for asteroid in self.asteroids.current_field():
            if id(asteroid) == target_id:
                return asteroid
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

    def _apply_asteroid_damage(
        self,
        target: Asteroid,
        damage: float,
        source: Ship | None = None,
    ) -> None:
        if damage <= 0.0:
            return
        applied = target.take_damage(damage)
        if applied <= 0.0:
            return
        if target.is_destroyed():
            if source and target.resource_amount > 0.0:
                resource_key = target.inventory_resource_key
                if resource_key and hasattr(source.resources, resource_key):
                    source.resources.add(resource_key, target.resource_amount)
            target.resource_amount = 0.0
            target.resource = None
        self.asteroids.prune_destroyed()

    def _apply_collision_damage(self, target: Ship, damage: float) -> None:
        if damage <= 0.0:
            return
        if target.durability > 0.0:
            absorbed = min(target.durability, damage)
            target.durability -= absorbed
            damage -= absorbed
        if damage > 0.0:
            target.hull = max(0.0, target.hull - damage)
        target.hull_regen_cooldown = max(2.0, target.hull_regen_cooldown)

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
        self.place_ship_near_outpost(ship)
        self.current_system_id = destination
        self.mining.enter_system(destination)
        self.asteroids.enter_system(destination)
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

    def asteroids_in_current_system(self) -> list[Asteroid]:
        return list(self.asteroids.current_field())

    def _station_ships(self, *, team: str | None = None) -> Iterable[Ship]:
        for candidate in self.ships:
            if not candidate.is_alive():
                continue
            if team is not None and candidate.team != team:
                continue
            role = candidate.frame.role.lower()
            size = candidate.frame.size.lower()
            if "station" in role or "outpost" in role or size in {"station", "outpost"}:
                yield candidate

    def _station_docking_radius(self, station_ship: Ship) -> float:
        base_radius = self._collision_radius(station_ship)
        return max(600.0, base_radius + 650.0)

    def _station_anchor_for(self, station: DockingStation, team: str) -> Ship | None:
        station_pos = Vector3(*station.position)
        best: Ship | None = None
        best_distance = float("inf")
        search_radius = max(station.docking_radius, 1.0) * 1.5
        for candidate in self._station_ships(team=team):
            candidate_pos = candidate.kinematics.position
            distance = candidate_pos.distance_to(station_pos)
            if distance <= search_radius and distance < best_distance:
                best = candidate
                best_distance = distance
        return best

    def nearest_station(self, ship: Ship) -> tuple[Optional[DockingStation], float]:
        position = ship.kinematics.position
        best_station: DockingStation | None = None
        best_distance = float("inf")

        def consider(
            station_id: str,
            name: str,
            system_id: str,
            station_pos: Vector3,
            docking_radius: float,
            *,
            prefer: bool = False,
        ) -> None:
            nonlocal best_station, best_distance
            distance = position.distance_to(station_pos)
            if distance < best_distance - 1e-3 or (
                prefer and abs(distance - best_distance) <= 1e-3
            ):
                best_distance = distance
                best_station = DockingStation(
                    id=station_id,
                    name=name,
                    system_id=system_id,
                    position=(station_pos.x, station_pos.y, station_pos.z),
                    docking_radius=docking_radius,
                )

        current_system = self.current_system_id or ""
        for station_ship in self._station_ships(team=getattr(ship, "team", None)):
            consider(
                f"ship:{id(station_ship)}",
                station_ship.frame.name,
                current_system,
                station_ship.kinematics.position,
                self._station_docking_radius(station_ship),
            )

        ship_team = getattr(ship, "team", None)
        if ship_team is not None:
            for station in self.stations_in_current_system():
                anchor = self._station_anchor_for(station, ship_team)
                if not anchor:
                    continue
                consider(
                    station.id,
                    station.name,
                    station.system_id,
                    anchor.kinematics.position,
                    station.docking_radius,
                    prefer=True,
                )

        return best_station, best_distance

    def _collision_radius(self, ship: Ship) -> float:
        return COLLISION_RADII.get(ship.frame.size, 12.0)

    def _collision_mass(self, ship: Ship) -> float:
        return COLLISION_MASS.get(ship.frame.size, 1.5)

    def _resolve_collisions(self, logger: ChannelLogger | None, dt: float) -> None:
        active_ships = [ship for ship in self.ships if ship.is_alive()]
        count = len(active_ships)
        self._collision_telemetry.begin_frame(self._current_frame_index, count)
        if count <= 1:
            self._collision_telemetry.advance_time(dt, logger)
            return

        positions = [ship.kinematics.position for ship in active_ships]
        radii = [self._collision_radius(ship) for ship in active_ships]
        masses = [self._collision_mass(ship) for ship in active_ships]
        grid: dict[tuple[int, int, int], list[int]] = {}

        for idx, position in enumerate(positions):
            radius = radii[idx]
            min_x = int(math.floor((position.x - radius) * COLLISION_INV_CELL_SIZE))
            max_x = int(math.floor((position.x + radius) * COLLISION_INV_CELL_SIZE))
            min_y = int(math.floor((position.y - radius) * COLLISION_INV_CELL_SIZE))
            max_y = int(math.floor((position.y + radius) * COLLISION_INV_CELL_SIZE))
            min_z = int(math.floor((position.z - radius) * COLLISION_INV_CELL_SIZE))
            max_z = int(math.floor((position.z + radius) * COLLISION_INV_CELL_SIZE))
            for cx in range(min_x, max_x + 1):
                for cy in range(min_y, max_y + 1):
                    for cz in range(min_z, max_z + 1):
                        grid.setdefault((cx, cy, cz), []).append(idx)

        start = time.perf_counter()

        for idx, ship_a in enumerate(active_ships):
            radius_a = radii[idx]
            mass_a = masses[idx]
            pos_a = positions[idx]
            min_x = int(math.floor((pos_a.x - radius_a) * COLLISION_INV_CELL_SIZE))
            max_x = int(math.floor((pos_a.x + radius_a) * COLLISION_INV_CELL_SIZE))
            min_y = int(math.floor((pos_a.y - radius_a) * COLLISION_INV_CELL_SIZE))
            max_y = int(math.floor((pos_a.y + radius_a) * COLLISION_INV_CELL_SIZE))
            min_z = int(math.floor((pos_a.z - radius_a) * COLLISION_INV_CELL_SIZE))
            max_z = int(math.floor((pos_a.z + radius_a) * COLLISION_INV_CELL_SIZE))
            checked: set[int] = set()
            for cx in range(min_x - 1, max_x + 2):
                for cy in range(min_y - 1, max_y + 2):
                    for cz in range(min_z - 1, max_z + 2):
                        cell = (cx, cy, cz)
                        for other_idx in grid.get(cell, []):
                            if other_idx <= idx or other_idx in checked:
                                continue
                            checked.add(other_idx)
                            self._collision_telemetry.record_candidates(1)
                            ship_b = active_ships[other_idx]
                            radius_b = radii[other_idx]
                            mass_b = masses[other_idx]
                            pos_b = positions[other_idx]
                            offset = pos_b - pos_a
                            min_distance = radius_a + radius_b
                            distance_sq = offset.length_squared()
                            if distance_sq >= min_distance * min_distance:
                                self._collision_telemetry.record_culled(1)
                                continue
                            self._collision_telemetry.record_tested(1)
                            distance = math.sqrt(max(0.0, distance_sq))
                            if distance <= 1e-3:
                                normal = Vector3(0.0, 0.0, 1.0)
                            else:
                                normal = offset / distance
                            penetration = min_distance - distance
                            correction = normal * (penetration * 0.5)
                            ship_a.kinematics.position -= correction
                            ship_b.kinematics.position += correction
                            relative_velocity = ship_b.kinematics.velocity - ship_a.kinematics.velocity
                            closing_speed = relative_velocity.dot(normal)
                            if closing_speed < 0.0:
                                impulse_mag = -(1.0 + COLLISION_RESTITUTION) * closing_speed
                                impulse_mag /= (1.0 / mass_a + 1.0 / mass_b)
                                impulse = normal * impulse_mag
                                ship_a.kinematics.velocity -= impulse / mass_a
                                ship_b.kinematics.velocity += impulse / mass_b
                            impact_speed = max(0.0, -closing_speed)
                            if impact_speed <= 0.0 and penetration <= 0.01:
                                continue
                            damage_base = impact_speed * (mass_a + mass_b) * 0.5 * COLLISION_DAMAGE_SCALE
                            if damage_base > 0.0:
                                total_mass = mass_a + mass_b
                                self._apply_collision_damage(ship_a, damage_base * (mass_b / total_mass))
                                self._apply_collision_damage(ship_b, damage_base * (mass_a / total_mass))
                                intensity = min(0.7, damage_base / 500.0)
                                ship_a.collision_recoil = max(ship_a.collision_recoil, intensity)
                                ship_b.collision_recoil = max(ship_b.collision_recoil, intensity)
                                if logger and logger.enabled:
                                    logger.debug(
                                        "Collision %s-%s speed=%.2f damage=%.1f",
                                        ship_a.frame.id,
                                        ship_b.frame.id,
                                        impact_speed,
                                        damage_base,
                                    )

        elapsed_ms = (time.perf_counter() - start) * 1000.0
        self._collision_telemetry.add_duration(elapsed_ms)
        self._collision_telemetry.advance_time(dt, logger)

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
            self.asteroids.scan_step(ship, dt)
        else:
            self.asteroids.halt_scanning()
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


__all__ = ["SpaceWorld", "SpaceWorldState"]
