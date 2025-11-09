"""World simulation container."""
from __future__ import annotations

import random
from typing import List, Optional

from pygame.math import Vector3

from game.combat.targeting import update_lock
from game.combat.weapons import HitResult, Projectile, WeaponDatabase, resolve_hitscan
from game.engine.logger import GameLogger
from game.ships.flight import update_ship_flight
from game.ships.ship import Ship, WeaponMount


class SpaceWorld:
    def __init__(self, weapons: WeaponDatabase, logger: GameLogger) -> None:
        self.weapons = weapons
        self.logger = logger
        self.ships: List[Ship] = []
        self.projectiles: List[Projectile] = []
        self.rng = random.Random(1)

    def add_ship(self, ship: Ship) -> None:
        self.ships.append(ship)

    def update(self, dt: float) -> None:
        physics_log = self.logger.channel("physics")
        weapons_log = self.logger.channel("weapons")

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
            return None

    def _apply_damage(self, target: Ship, damage: float) -> None:
        if target.durability > 0.0:
            absorbed = min(target.durability, damage * 0.5)
            target.durability -= absorbed
            damage -= absorbed
        target.hull = max(0.0, target.hull - damage)
        target.hull_regen_cooldown = 3.0


__all__ = ["SpaceWorld"]
