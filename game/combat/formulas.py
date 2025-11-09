"""Combat math helpers decoupled from rendering libs."""
from __future__ import annotations

from dataclasses import dataclass

AIM_ASSIST_BASE = 0.05
ARMOR_PENETRATION_FLOOR = 0.15
AIM_ASSIST_ANGLE = 0.104719755  # ~6 degrees in radians


def aim_assist(angle_error: float) -> float:
    if angle_error <= 0:
        return AIM_ASSIST_BASE
    falloff = max(0.0, 1.0 - angle_error / AIM_ASSIST_ANGLE)
    return AIM_ASSIST_BASE * falloff


def calculate_hit_chance(
    base_accuracy: float,
    angle_error: float,
    target_avoidance: float,
    accuracy_bonus: float = 0.0,
) -> float:
    chance = base_accuracy + accuracy_bonus + aim_assist(angle_error) - target_avoidance
    return max(0.0, min(1.0, chance))


def calculate_crit(base_crit: float, attacker_bonus: float, target_crit_def: float) -> float:
    chance = base_crit + attacker_bonus - target_crit_def
    return max(0.0, min(1.0, chance))


def apply_armor(damage: float, armor: float) -> float:
    mitigated = max(damage - armor, damage * ARMOR_PENETRATION_FLOOR)
    return max(0.0, mitigated)


@dataclass
class HitResult:
    hit: bool
    crit: bool
    damage: float
    final_hit_chance: float
    final_crit_chance: float


__all__ = [
    "calculate_hit_chance",
    "calculate_crit",
    "apply_armor",
    "HitResult",
]
