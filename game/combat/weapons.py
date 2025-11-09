"""Weapon data, firing logic, and hit formulas."""
from __future__ import annotations

import json
from dataclasses import dataclass
from math import radians
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from pygame.math import Vector3

from game.combat.formulas import (
    HitResult,
    apply_armor,
    calculate_crit,
    calculate_hit_chance,
)
from game.engine.logger import ChannelLogger


def _range_accuracy_modifier(distance: float, optimal: float, max_range: float) -> float:
    """Return a 0-1 multiplier for accuracy based on range bands."""

    if distance <= 0.0:
        return 1.0
    if distance <= optimal:
        return 1.0
    if max_range <= optimal:
        return 0.0 if distance > optimal else 1.0
    if distance >= max_range:
        return 0.0
    falloff = (distance - optimal) / (max_range - optimal)
    return max(0.0, 1.0 - falloff)


def _gimbal_accuracy_modifier(angle: float, gimbal_limit: float) -> float:
    """Return a 0-1 multiplier that softens aim near the gimbal edge."""

    if gimbal_limit <= 0.0:
        return 0.0
    if angle <= 0.0:
        return 1.0
    if angle >= gimbal_limit:
        return 0.0
    inner_cone = gimbal_limit * 0.5
    if angle <= inner_cone:
        return 1.0
    ratio = (angle - inner_cone) / max(1e-3, gimbal_limit - inner_cone)
    return max(0.0, 1.0 - ratio)


@dataclass
class WeaponData:
    id: str
    name: str
    slot_type: str
    wclass: str
    base_damage: float
    base_accuracy: float
    crit_chance: float
    crit_multiplier: float
    rof: float
    power_per_shot: float
    optimal_range: float
    max_range: float
    projectile_speed: float
    ammo: int
    reload: float
    gimbal: float

    @classmethod
    def from_dict(cls, data: Dict) -> "WeaponData":
        return cls(
            id=data["id"],
            name=data.get("name", data["id"]),
            slot_type=data.get("slotType", "cannon"),
            wclass=data.get("class", "hitscan"),
            base_damage=float(data.get("damage", 100.0)),
            base_accuracy=float(data.get("accuracy", 0.75)),
            crit_chance=float(data.get("crit", 0.1)),
            crit_multiplier=float(data.get("critMult", 1.5)),
            rof=float(data.get("rof", 3.0)),
            power_per_shot=float(data.get("power", 10.0)),
            optimal_range=float(data.get("optimal", 800.0)),
            max_range=float(data.get("maxRange", 1200.0)),
            projectile_speed=float(data.get("projectileSpeed", 0.0)),
            ammo=int(data.get("ammo", 0)),
            reload=float(data.get("reload", 0.0)),
            gimbal=float(data.get("gimbal", 20.0)),
        )

    @property
    def cooldown(self) -> float:
        return 1.0 / max(0.01, self.rof)


class WeaponDatabase:
    def __init__(self) -> None:
        self.weapons: Dict[str, WeaponData] = {}

    def load_directory(self, directory: Path) -> None:
        if not directory.exists():
            return
        for path in directory.glob("*.json"):
            try:
                data = json.loads(path.read_text())
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                data = [data]
            for entry in data:
                weapon = WeaponData.from_dict(entry)
                self.weapons[weapon.id] = weapon

    def get(self, weapon_id: str) -> WeaponData:
        return self.weapons[weapon_id]


def resolve_hitscan(
    origin: Vector3,
    direction: Vector3,
    weapon: WeaponData,
    target_position: Vector3,
    target_velocity: Vector3,
    target_avoidance: float,
    target_crit_def: float,
    armor: float,
    rng,
    *,
    distance: Optional[float] = None,
    angle_error: Optional[float] = None,
    gimbal_limit: Optional[float] = None,
    accuracy_bonus: float = 0.0,
    crit_bonus: float = 0.0,
) -> HitResult:
    offset = target_position - origin
    if distance is None:
        distance = offset.length()
    if angle_error is None:
        if direction.length_squared() > 0 and offset.length_squared() > 0:
            angle_error = direction.angle_to(offset.normalize())
        else:
            angle_error = 0.0
    effective_gimbal = gimbal_limit if gimbal_limit is not None else weapon.gimbal
    gimbal_modifier = _gimbal_accuracy_modifier(angle_error, effective_gimbal)
    range_modifier = _range_accuracy_modifier(distance, weapon.optimal_range, weapon.max_range)
    if gimbal_modifier <= 0.0 or range_modifier <= 0.0:
        return HitResult(False, False, 0.0, 0.0, 0.0)
    base_accuracy = weapon.base_accuracy * gimbal_modifier * range_modifier
    hit_chance = calculate_hit_chance(base_accuracy, radians(angle_error), target_avoidance, accuracy_bonus=accuracy_bonus)
    hit_chance = max(0.0, min(1.0, hit_chance))
    crit_chance = calculate_crit(weapon.crit_chance, crit_bonus, target_crit_def)
    hit = rng.random() <= hit_chance
    crit = False
    damage = 0.0
    if hit:
        crit = rng.random() <= crit_chance
        damage = weapon.base_damage * (weapon.crit_multiplier if crit else 1.0)
        damage = apply_armor(damage, armor)
    return HitResult(hit, crit, damage, hit_chance, crit_chance)


class Projectile:
    """Projectile for missiles or ballistic shots."""

    def __init__(
        self,
        weapon: WeaponData,
        position: Vector3,
        velocity: Vector3,
        target_id: Optional[int],
        ttl: float,
        team: str,
    ) -> None:
        self.weapon = weapon
        self.position = position
        self.velocity = velocity
        self.target_id = target_id
        self.ttl = ttl
        self.team = team
        self.lock_strength = 1.0

    def update(self, dt: float, logger: Optional[ChannelLogger] = None) -> None:
        self.position += self.velocity * dt
        self.ttl -= dt
        if logger and logger.enabled:
            logger.debug(
                "Projectile update pos=%s vel=%s ttl=%.2f",
                self.position,
                self.velocity,
                self.ttl,
            )

    def alive(self) -> bool:
        return self.ttl > 0.0


__all__ = [
    "WeaponData",
    "WeaponDatabase",
    "Projectile",
    "calculate_hit_chance",
    "calculate_crit",
    "apply_armor",
    "resolve_hitscan",
    "HitResult",
]
