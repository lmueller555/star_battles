"""Equipment upgrade data structures and helpers."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple


@dataclass(frozen=True)
class UpgradeRequirement:
    """Skill gate for a specific level."""

    skill: str
    rank: int


@dataclass(frozen=True)
class UpgradeStep:
    """Costs and rules for advancing to a given level."""

    level: int
    costs: Dict[str, float] = field(default_factory=dict)
    requirement: Optional[UpgradeRequirement] = None
    success_chance: Optional[float] = None
    tuning_kits: Optional[int] = None
    guarantee_kits: Optional[int] = None


@dataclass(frozen=True)
class UpgradeCurve:
    """Defines how a stat progresses across levels."""

    start: float
    increment: float = 0.0
    table: Optional[Dict[int, float]] = None

    def value_for(self, level: int) -> Optional[float]:
        """Return the value for ``level`` if known."""

        if self.table is not None:
            return self.table.get(level)
        return self.start + self.increment * (level - 1)


@dataclass(frozen=True)
class EquipmentUpgradeSpec:
    """Declarative upgrade information for an item."""

    item_id: str
    name: str
    slot: str
    effect: str
    level_cap: int
    upgrade_axes: Tuple[str, ...]
    curves: Dict[str, UpgradeCurve]
    steps: Dict[int, UpgradeStep]

    def curve_for(self, stat: str) -> Optional[UpgradeCurve]:
        return self.curves.get(stat)

    def step_for(self, level: int) -> Optional[UpgradeStep]:
        return self.steps.get(level)


class UpgradeComputationError(RuntimeError):
    """Raised when upgrade preview data is missing critical information."""


class EquipmentUpgradeModel:
    """Compute preview data and gating for upgrade dialogs."""

    def __init__(
        self,
        spec: EquipmentUpgradeSpec,
        current_level: int,
        player_resources: Dict[str, float],
        player_skills: Dict[str, int],
    ) -> None:
        self.spec = spec
        self.current_level = max(1, min(current_level, spec.level_cap))
        self.preview_level = min(self.current_level + 1, spec.level_cap)
        self.player_resources = player_resources
        self.player_skills = player_skills
        self.guarantee: bool = False

    # ------------------------------------------------------------------
    # Preview helpers
    # ------------------------------------------------------------------
    def set_preview_level(self, level: int) -> None:
        level = max(1, min(level, self.spec.level_cap))
        if level == self.current_level:
            level = min(self.spec.level_cap, level + 1)
        self.preview_level = level

    def increment_preview(self, delta: int) -> None:
        level = self.preview_level + delta
        level = max(1, min(level, self.spec.level_cap))
        if level == self.current_level:
            level += 1 if delta > 0 else -1
        self.preview_level = max(1, min(level, self.spec.level_cap))

    def toggle_guarantee(self) -> None:
        self.guarantee = not self.guarantee

    def stat_value(self, stat: str, level: int) -> Tuple[float, bool]:
        """Return (value, known) for the given stat at level."""

        curve = self.spec.curve_for(stat)
        if not curve:
            return 0.0, False
        value = curve.value_for(level)
        if value is None:
            known = False
            # Fall back to highest lower level with data.
            for lvl in range(level - 1, 0, -1):
                prev = curve.value_for(lvl)
                if prev is not None:
                    return prev, known
            return curve.start, known
        return value, True

    # ------------------------------------------------------------------
    # Aggregated costs and gating
    # ------------------------------------------------------------------
    def _iter_steps(self) -> Iterable[UpgradeStep]:
        start = self.current_level + 1
        end = self.preview_level
        if start > end:
            return []
        steps: List[UpgradeStep] = []
        for level in range(start, end + 1):
            step = self.spec.step_for(level)
            if not step:
                steps.append(UpgradeStep(level=level))
            else:
                steps.append(step)
        return steps

    def aggregate_cost(self) -> Tuple[Dict[str, float], bool]:
        totals: Dict[str, float] = {}
        unknown = False
        for step in self._iter_steps():
            if not step.costs:
                unknown = True
            for currency, amount in step.costs.items():
                totals[currency] = totals.get(currency, 0.0) + amount
            if step.tuning_kits:
                kits = step.tuning_kits
                if self.guarantee and step.guarantee_kits:
                    kits = step.guarantee_kits
                totals["tuning_kits"] = totals.get("tuning_kits", 0.0) + float(kits)
        return totals, unknown

    def aggregated_success(self) -> Optional[float]:
        chances: List[float] = []
        for step in self._iter_steps():
            if step.success_chance is None:
                continue
            if self.guarantee and step.guarantee_kits:
                chances.append(1.0)
            else:
                chances.append(step.success_chance)
        if not chances:
            return None
        chance = 1.0
        for value in chances:
            chance *= value
        return max(0.0, min(1.0, chance))

    def highest_requirement(self) -> Optional[Tuple[UpgradeRequirement, int]]:
        highest: Optional[Tuple[UpgradeRequirement, int]] = None
        for step in self._iter_steps():
            if not step.requirement:
                continue
            if not highest or step.requirement.rank > highest[0].rank:
                highest = (step.requirement, step.level)
        return highest

    def missing_resources(self) -> Dict[str, float]:
        totals, _ = self.aggregate_cost()
        shortfalls: Dict[str, float] = {}
        for currency, amount in totals.items():
            available = self.player_resources.get(currency, 0.0)
            if amount > available + 1e-6:
                shortfalls[currency] = amount - available
        return shortfalls

    def meets_skill(self) -> Tuple[bool, Optional[Tuple[UpgradeRequirement, int]]]:
        requirement = self.highest_requirement()
        if not requirement:
            return True, None
        req, level = requirement
        current_rank = self.player_skills.get(req.skill, 0)
        return current_rank >= req.rank, requirement

    def can_upgrade(self) -> Tuple[bool, Optional[str]]:
        if self.current_level >= self.spec.level_cap:
            return False, "Item is at level cap"
        totals, unknown_cost = self.aggregate_cost()
        if unknown_cost and not totals:
            return False, "Upgrade cost data incomplete"
        skill_ok, requirement = self.meets_skill()
        if not skill_ok and requirement:
            req, level = requirement
            return False, f"Requires {req.skill} {req.rank} to reach Level {level}"
        shortfalls = self.missing_resources()
        if shortfalls:
            currency = next(iter(shortfalls))
            deficit = shortfalls[currency]
            need = totals.get(currency, 0.0)
            have = self.player_resources.get(currency, 0.0)
            return (
                False,
                f"Insufficient {currency.title()}: Need {need:,.0f}, Have {have:,.0f} (short {deficit:,.0f})",
            )
        if unknown_cost:
            return False, "Upgrade cost data incomplete"
        return True, None

    def max_affordable_level(self) -> int:
        if self.current_level >= self.spec.level_cap:
            return self.current_level
        level = self.current_level
        resources = dict(self.player_resources)
        skill_ok = True
        for step in self._iter_steps_from(self.current_level + 1):
            if step.requirement:
                rank = self.player_skills.get(step.requirement.skill, 0)
                if rank < step.requirement.rank:
                    skill_ok = False
                    break
            if not step.costs and not step.tuning_kits:
                break
            if step.costs:
                for currency, amount in step.costs.items():
                    resources[currency] = resources.get(currency, 0.0) - amount
                    if resources[currency] < -1e-6:
                        skill_ok = False
                        break
            kits_required = 0.0
            if step.tuning_kits:
                kits_required = float(step.tuning_kits)
                if self.guarantee and step.guarantee_kits:
                    kits_required = float(step.guarantee_kits)
                resources["tuning_kits"] = resources.get("tuning_kits", 0.0) - kits_required
            if any(value < -1e-6 for value in resources.values()):
                skill_ok = False
            if not skill_ok:
                break
            level = step.level
        return level

    def _iter_steps_from(self, start_level: int) -> Iterable[UpgradeStep]:
        for level in range(start_level, self.spec.level_cap + 1):
            step = self.spec.step_for(level)
            if step:
                yield step

    def steps_in_range(self) -> List[UpgradeStep]:
        return list(self._iter_steps())


# ----------------------------------------------------------------------
# Upgrade specification data for Strike equipment
# ----------------------------------------------------------------------


def _linear(start: float, increment: float) -> UpgradeCurve:
    return UpgradeCurve(start=start, increment=increment, table=None)


def _table(start: float, entries: Dict[int, float]) -> UpgradeCurve:
    return UpgradeCurve(start=start, increment=0.0, table=entries)


EQUIPMENT_UPGRADE_SPECS: Dict[str, EquipmentUpgradeSpec] = {
    "mec_a6": EquipmentUpgradeSpec(
        item_id="mec_a6",
        name="MEC-A6 'Fang'",
        slot="weapon",
        effect="Rapid-fire autocannon; Damage and Optimal Range improve per level.",
        level_cap=15,
        upgrade_axes=("damage", "optimal_range"),
        curves={
            "damage_min": _linear(1.0, 0.16),
            "damage_max": _linear(10.0, 1.6),
            "armor_piercing": _linear(5.0, 0.0),
            "range_min": _linear(0.0, 0.0),
            "range_max": _linear(750.0, 0.0),
            "optimal_range": _linear(300.0, 12.0),
            "accuracy": _linear(400.0, 0.0),
            "critical_offense": _linear(100.0, 0.0),
            "reload": _linear(0.5, 0.0),
            "power": _linear(1.0, 0.0),
            "firing_arc": _linear(75.0, 0.0),
            "durability": _linear(2500.0, 0.0),
        },
        steps={
            level: UpgradeStep(
                level=level,
                costs={"tylium": 1200.0 + 400.0 * (level - 2)},
                requirement=UpgradeRequirement("Gunnery", 1 if level <= 5 else 2 if level <= 10 else 3),
                success_chance=1.0 if level <= 10 else 0.7,
                tuning_kits=1 if level > 10 else None,
                guarantee_kits=3 if level > 10 else None,
            )
            for level in range(2, 16)
        },
    ),
    "mec_a6p": EquipmentUpgradeSpec(
        item_id="mec_a6p",
        name="MEC-A6P 'Fang-P'",
        slot="weapon",
        effect="Precision autocannon variant; Damage and Critical Offense scale.",
        level_cap=15,
        upgrade_axes=("damage", "critical_offense"),
        curves={
            "damage_min": _linear(1.0, 0.16),
            "damage_max": _linear(10.0, 1.6),
            "armor_piercing": _linear(5.0, 0.0),
            "range_min": _linear(0.0, 0.0),
            "range_max": _linear(750.0, 0.0),
            "optimal_range": _linear(300.0, 0.0),
            "accuracy": _linear(400.0, 0.0),
            "critical_offense": _linear(100.0, 4.0),
            "reload": _linear(0.5, 0.0),
            "power": _linear(1.0, 0.0),
            "firing_arc": _linear(75.0, 0.0),
            "durability": _linear(2500.0, 0.0),
        },
        steps={
            level: UpgradeStep(
                level=level,
                costs={"tylium": 1200.0 + 400.0 * (level - 2)},
                requirement=UpgradeRequirement("Gunnery", 1 if level <= 5 else 2 if level <= 10 else 3),
                success_chance=1.0 if level <= 10 else 0.7,
                tuning_kits=1 if level > 10 else None,
                guarantee_kits=3 if level > 10 else None,
            )
            for level in range(2, 16)
        },
    ),
    "mec_a8": EquipmentUpgradeSpec(
        item_id="mec_a8",
        name="MEC-A8 'Tornado'",
        slot="weapon",
        effect="Fast-cycling autocannon; Damage and Optimal Range improve.",
        level_cap=15,
        upgrade_axes=("damage", "optimal_range"),
        curves={
            "damage_min": _linear(1.0, 0.18),
            "damage_max": _linear(10.0, 1.8),
            "armor_piercing": _linear(5.0, 0.0),
            "range_min": _linear(0.0, 0.0),
            "range_max": _linear(600.0, 0.0),
            "optimal_range": _linear(250.0, 10.0),
            "accuracy": _linear(400.0, 0.0),
            "critical_offense": _linear(100.0, 0.0),
            "reload": _linear(0.4, 0.0),
            "power": _linear(1.0, 0.0),
            "firing_arc": _linear(75.0, 0.0),
            "durability": _linear(2500.0, 0.0),
        },
        steps={
            level: UpgradeStep(
                level=level,
                costs={"tylium": 1400.0 + 420.0 * (level - 2)},
                requirement=UpgradeRequirement("Gunnery", 1 if level <= 5 else 2 if level <= 10 else 3),
                success_chance=1.0 if level <= 10 else 0.7,
                tuning_kits=1 if level > 10 else None,
                guarantee_kits=3 if level > 10 else None,
            )
            for level in range(2, 16)
        },
    ),
    "mec_a8p": EquipmentUpgradeSpec(
        item_id="mec_a8p",
        name="MEC-A8P 'Tornado-P'",
        slot="weapon",
        effect="Crit-focused Tornado variant; Damage and Crit Offense scale.",
        level_cap=15,
        upgrade_axes=("damage", "critical_offense"),
        curves={
            "damage_min": _linear(1.0, 0.18),
            "damage_max": _linear(10.0, 1.8),
            "armor_piercing": _linear(5.0, 0.0),
            "range_min": _linear(0.0, 0.0),
            "range_max": _linear(600.0, 0.0),
            "optimal_range": _linear(250.0, 0.0),
            "accuracy": _linear(400.0, 0.0),
            "critical_offense": _linear(100.0, 4.5),
            "reload": _linear(0.4, 0.0),
            "power": _linear(1.0, 0.0),
            "firing_arc": _linear(75.0, 0.0),
            "durability": _linear(2500.0, 0.0),
        },
        steps={
            level: UpgradeStep(
                level=level,
                costs={"tylium": 1400.0 + 420.0 * (level - 2)},
                requirement=UpgradeRequirement("Gunnery", 1 if level <= 5 else 2 if level <= 10 else 3),
                success_chance=1.0 if level <= 10 else 0.7,
                tuning_kits=1 if level > 10 else None,
                guarantee_kits=3 if level > 10 else None,
            )
            for level in range(2, 16)
        },
    ),
    "strike_composite_plating": EquipmentUpgradeSpec(
        item_id="strike_composite_plating",
        name="Strike Composite Plating",
        slot="hull",
        effect="Balanced armor and hull boosts with minor maneuver penalties.",
        level_cap=15,
        upgrade_axes=("armor", "hull_hp"),
        curves={
            "armor": _linear(2.25, 0.25),
            "hull_hp": _linear(22.5, 2.25),
            "acceleration": _linear(-0.3, 0.0),
            "turn_accel": _linear(-0.75, 0.0),
            "durability": _linear(2500.0, 0.0),
        },
        steps={
            level: UpgradeStep(
                level=level,
                costs={"cubits": 900.0 + 180.0 * (level - 2)},
                requirement=UpgradeRequirement("Engineering", 1 if level <= 5 else 2 if level <= 10 else 3),
                success_chance=1.0 if level <= 10 else 0.75,
                tuning_kits=1 if level > 10 else None,
                guarantee_kits=2 if level > 10 else None,
            )
            for level in range(2, 16)
        },
    ),
    "strike_hull_plating": EquipmentUpgradeSpec(
        item_id="strike_hull_plating",
        name="Strike Hull Plating",
        slot="hull",
        effect="Heavy hull buffer; penalties remain fixed.",
        level_cap=15,
        upgrade_axes=("hull_hp",),
        curves={
            "armor": _linear(0.0, 0.0),
            "hull_hp": _linear(45.0, 4.5),
            "acceleration": _linear(-0.2, 0.0),
            "turn_accel": _linear(-1.0, 0.0),
            "durability": _linear(2500.0, 0.0),
        },
        steps={
            level: UpgradeStep(
                level=level,
                costs={"cubits": 900.0 + 180.0 * (level - 2)},
                requirement=UpgradeRequirement("Engineering", 1 if level <= 5 else 2 if level <= 10 else 3),
                success_chance=1.0 if level <= 10 else 0.75,
                tuning_kits=1 if level > 10 else None,
                guarantee_kits=2 if level > 10 else None,
            )
            for level in range(2, 16)
        },
    ),
    "strike_armor_plating": EquipmentUpgradeSpec(
        item_id="strike_armor_plating",
        name="Strike Armor Plating",
        slot="hull",
        effect="Focused armor reinforcement; acceleration penalties fixed.",
        level_cap=15,
        upgrade_axes=("armor",),
        curves={
            "armor": _linear(4.5, 0.45),
            "acceleration": _linear(-0.4, 0.0),
            "turn_accel": _linear(-0.5, 0.0),
            "durability": _linear(2500.0, 0.0),
        },
        steps={
            level: UpgradeStep(
                level=level,
                costs={"cubits": 900.0 + 180.0 * (level - 2)},
                requirement=UpgradeRequirement("Engineering", 1 if level <= 5 else 2 if level <= 10 else 3),
                success_chance=1.0 if level <= 10 else 0.75,
                tuning_kits=1 if level > 10 else None,
                guarantee_kits=2 if level > 10 else None,
            )
            for level in range(2, 16)
        },
    ),
    "light_drive_overcharger": EquipmentUpgradeSpec(
        item_id="light_drive_overcharger",
        name="Light Drive Overcharger",
        slot="engine",
        effect="Improves cruise and boost speeds.",
        level_cap=15,
        upgrade_axes=("max_speed", "boost_speed"),
        curves={
            "max_speed": _linear(1.25, 0.1),
            "boost_speed": _linear(1.25, 0.1),
            "acceleration": _linear(0.0, 0.0),
            "turn_rate": _linear(0.0, 0.0),
            "turn_accel": _linear(0.0, 0.0),
            "avoidance_rating": _linear(0.0, 0.0),
            "durability": _linear(2500.0, 0.0),
        },
        steps={
            level: UpgradeStep(
                level=level,
                costs={"merits": 12.0 + 2.0 * (level - 2)},
                requirement=UpgradeRequirement("Propulsion", 1 if level <= 5 else 2 if level <= 10 else 3),
                success_chance=1.0 if level <= 10 else 0.8,
                tuning_kits=1 if level > 10 else None,
                guarantee_kits=2 if level > 10 else None,
            )
            for level in range(2, 16)
        },
    ),
    "light_turbo_boosters": EquipmentUpgradeSpec(
        item_id="light_turbo_boosters",
        name="Light Turbo Boosters",
        slot="engine",
        effect="Adds linear acceleration and boost headroom.",
        level_cap=15,
        upgrade_axes=("acceleration", "boost_speed"),
        curves={
            "max_speed": _linear(0.0, 0.0),
            "boost_speed": _linear(2.5, 0.22),
            "acceleration": _linear(1.0, 0.08),
            "turn_rate": _linear(0.0, 0.0),
            "turn_accel": _linear(0.0, 0.0),
            "avoidance_rating": _linear(0.0, 0.0),
            "durability": _linear(2500.0, 0.0),
        },
        steps={
            level: UpgradeStep(
                level=level,
                costs={"merits": 12.0 + 2.0 * (level - 2)},
                requirement=UpgradeRequirement("Propulsion", 1 if level <= 5 else 2 if level <= 10 else 3),
                success_chance=1.0 if level <= 10 else 0.8,
                tuning_kits=1 if level > 10 else None,
                guarantee_kits=2 if level > 10 else None,
            )
            for level in range(2, 16)
        },
    ),
    "light_gyro_stabilization": EquipmentUpgradeSpec(
        item_id="light_gyro_stabilization",
        name="Light Gyro-Stabilization",
        slot="engine",
        effect="Boosts turn speed and turn acceleration.",
        level_cap=15,
        upgrade_axes=("turn_rate", "turn_accel"),
        curves={
            "max_speed": _linear(0.0, 0.0),
            "boost_speed": _linear(0.0, 0.0),
            "acceleration": _linear(0.0, 0.0),
            "turn_rate": _linear(2.5, 0.18),
            "turn_accel": _linear(2.5, 0.22),
            "avoidance_rating": _linear(0.0, 0.0),
            "durability": _linear(2500.0, 0.0),
        },
        steps={
            level: UpgradeStep(
                level=level,
                costs={"merits": 12.0 + 2.0 * (level - 2)},
                requirement=UpgradeRequirement("Propulsion", 1 if level <= 5 else 2 if level <= 10 else 3),
                success_chance=1.0 if level <= 10 else 0.8,
                tuning_kits=1 if level > 10 else None,
                guarantee_kits=2 if level > 10 else None,
            )
            for level in range(2, 16)
        },
    ),
    "light_rcs_ducting": EquipmentUpgradeSpec(
        item_id="light_rcs_ducting",
        name="Light RCS Ducting",
        slot="engine",
        effect="Improves avoidance rating for light frames.",
        level_cap=15,
        upgrade_axes=("avoidance",),
        curves={
            "avoidance_rating": _linear(15.0, 1.5),
            "durability": _linear(2500.0, 0.0),
        },
        steps={
            level: UpgradeStep(
                level=level,
                costs={"merits": 10.0 + 2.0 * (level - 2)},
                requirement=UpgradeRequirement("Propulsion", 1 if level <= 5 else 2 if level <= 10 else 3),
                success_chance=1.0 if level <= 10 else 0.8,
                tuning_kits=1 if level > 10 else None,
                guarantee_kits=2 if level > 10 else None,
            )
            for level in range(2, 16)
        },
    ),
}


__all__ = [
    "EquipmentUpgradeModel",
    "EquipmentUpgradeSpec",
    "EQUIPMENT_UPGRADE_SPECS",
    "UpgradeCurve",
    "UpgradeRequirement",
    "UpgradeStep",
]

