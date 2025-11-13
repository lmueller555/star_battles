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


def _weapon_steps(base_cost: float, increment: float) -> Dict[int, UpgradeStep]:
    return {
        level: UpgradeStep(
            level=level,
            costs={"tylium": base_cost + increment * (level - 2)},
            requirement=UpgradeRequirement(
                "Gunnery", 1 if level <= 5 else 2 if level <= 10 else 3
            ),
            success_chance=1.0 if level <= 10 else 0.7,
            tuning_kits=1 if level > 10 else None,
            guarantee_kits=3 if level > 10 else None,
        )
        for level in range(2, 16)
    }


def _hull_steps(base_cost: float, increment: float) -> Dict[int, UpgradeStep]:
    return {
        level: UpgradeStep(
            level=level,
            costs={"cubits": base_cost + increment * (level - 2)},
            requirement=UpgradeRequirement(
                "Engineering", 1 if level <= 5 else 2 if level <= 10 else 3
            ),
            success_chance=1.0 if level <= 10 else 0.75,
            tuning_kits=1 if level > 10 else None,
            guarantee_kits=2 if level > 10 else None,
        )
        for level in range(2, 16)
    }


def _engine_steps(base_cost: float, increment: float) -> Dict[int, UpgradeStep]:
    return {
        level: UpgradeStep(
            level=level,
            costs={"merits": base_cost + increment * (level - 2)},
            requirement=UpgradeRequirement(
                "Propulsion", 1 if level <= 5 else 2 if level <= 10 else 3
            ),
            success_chance=1.0 if level <= 10 else 0.8,
            tuning_kits=1 if level > 10 else None,
            guarantee_kits=2 if level > 10 else None,
        )
        for level in range(2, 16)
    }


EQUIPMENT_UPGRADE_SPECS: Dict[str, EquipmentUpgradeSpec] = {
    "mec_a6": EquipmentUpgradeSpec(
        item_id="mec_a6",
        name="MEC-A6 'Fang'",
        slot="weapon",
        effect="Rapid-fire autocannon with scaling damage and optimal range.",
        level_cap=15,
        upgrade_axes=('damage', 'optimal_range'),
        curves={
            "damage_min": _linear(1.0, 0.09999999999999999),
            "damage_max": _linear(10.0, 1.0),
            "armor_piercing": _linear(5.0, 0.0),
            "range_min": _linear(0.0, 0.0),
            "range_max": _linear(750.0, 0.0),
            "optimal_range": _linear(300.0, 15.0),
            "accuracy": _linear(400.0, 0.0),
            "critical_offense": _linear(100.0, 0.0),
            "reload": _linear(0.5, 0.0),
            "power": _linear(1.0, 0.0),
            "firing_arc": _linear(75.0, 0.0),
            "durability": _linear(6000.0, 0.0),
        },
        steps=_weapon_steps(1200.0, 400.0),
    ),
    "fc_39b_blackjack": EquipmentUpgradeSpec(
        item_id="fc_39b_blackjack",
        name="FC-39B 'Blackjack'",
        slot="weapon",
        effect="Raven-exclusive flechette cannon boosting close-range burst damage.",
        level_cap=15,
        upgrade_axes=('damage',),
        curves={
            "damage_min": _linear(26.5, 0.6607142857142857),
            "damage_max": _linear(42.4, 1.0535714285714286),
            "armor_piercing": _linear(0.0, 0.0),
            "range_min": _linear(0.0, 0.0),
            "range_max": _linear(350.0, 0.0),
            "optimal_range": _linear(150.0, 0.0),
            "accuracy": _linear(450.0, 0.0),
            "critical_offense": _linear(110.0, 0.0),
            "reload": _linear(0.8, 0.0),
            "power": _linear(4.5, 0.0),
            "firing_arc": _linear(40.0, 0.0),
            "durability": _linear(6000.0, 0.0),
        },
        steps=_weapon_steps(1800.0, 500.0),
    ),
    "kew_9a_dagger": EquipmentUpgradeSpec(
        item_id="kew_9a_dagger",
        name="KEW-9A 'Dagger'",
        slot="weapon",
        effect="Raven-exclusive autocannon upgrading sustained armor-piercing fire.",
        level_cap=15,
        upgrade_axes=('damage',),
        curves={
            "damage_min": _linear(9.0, 0.22500000000000003),
            "damage_max": _linear(18.0, 0.3857142857142856),
            "armor_piercing": _linear(5.0, 0.0),
            "range_min": _linear(0.0, 0.0),
            "range_max": _linear(650.0, 0.0),
            "optimal_range": _linear(400.0, 0.0),
            "accuracy": _linear(400.0, 0.0),
            "critical_offense": _linear(100.0, 0.0),
            "reload": _linear(0.4, 0.0),
            "power": _linear(2.0, 0.0),
            "firing_arc": _linear(30.0, 0.0),
            "durability": _linear(6000.0, 0.0),
        },
        steps=_weapon_steps(1700.0, 480.0),
    ),
    "kkc_h1_javelin": EquipmentUpgradeSpec(
        item_id="kkc_h1_javelin",
        name="KKC-H1 'Javelin'",
        slot="weapon",
        effect="Rhino kinetic kill cannon scaling its long-range strike damage.",
        level_cap=15,
        upgrade_axes=('damage',),
        curves={
            "damage_min": _linear(65.0, 1.75),
            "damage_max": _linear(100.0, 2.857142857142857),
            "armor_piercing": _linear(35.0, 0.0),
            "range_min": _linear(100.0, 0.0),
            "range_max": _linear(1500.0, 0.0),
            "optimal_range": _linear(1000.0, 0.0),
            "accuracy": _linear(100.0, 0.0),
            "critical_offense": _linear(150.0, 0.0),
            "reload": _linear(2.0, 0.0),
            "power": _linear(6.0, 0.0),
            "firing_arc": _linear(30.0, 0.0),
            "durability": _linear(6000.0, 0.0),
        },
        steps=_weapon_steps(2000.0, 520.0),
    ),
    "kew_2b_stiletto": EquipmentUpgradeSpec(
        item_id="kew_2b_stiletto",
        name="KEW-2B 'Stiletto'",
        slot="weapon",
        effect="Rapid Raven machine gun increasing close-range throughput.",
        level_cap=15,
        upgrade_axes=('damage',),
        curves={
            "damage_min": _linear(5.0, 0.21428571428571427),
            "damage_max": _linear(10.0, 0.35714285714285715),
            "armor_piercing": _linear(2.5, 0.0),
            "range_min": _linear(0.0, 0.0),
            "range_max": _linear(500.0, 0.0),
            "optimal_range": _linear(300.0, 0.0),
            "accuracy": _linear(400.0, 0.0),
            "critical_offense": _linear(90.0, 0.0),
            "reload": _linear(0.2, 0.0),
            "power": _linear(1.4, 0.0),
            "firing_arc": _linear(40.0, 0.0),
            "durability": _linear(6000.0, 0.0),
        },
        steps=_weapon_steps(1700.0, 480.0),
    ),
    "mec_a6p": EquipmentUpgradeSpec(
        item_id="mec_a6p",
        name="MEC-A6P 'Fang-P'",
        slot="weapon",
        effect="Precision Fang variant scaling damage and critical offense.",
        level_cap=15,
        upgrade_axes=('damage', 'critical_offense'),
        curves={
            "damage_min": _linear(1.0, 0.09999999999999999),
            "damage_max": _linear(10.0, 1.0),
            "armor_piercing": _linear(5.0, 0.0),
            "range_min": _linear(0.0, 0.0),
            "range_max": _linear(750.0, 0.0),
            "optimal_range": _linear(300.0, 0.0),
            "accuracy": _linear(400.0, 0.0),
            "critical_offense": _linear(100.0, 5.0),
            "reload": _linear(0.5, 0.0),
            "power": _linear(1.0, 0.0),
            "firing_arc": _linear(75.0, 0.0),
            "durability": _linear(6000.0, 0.0),
        },
        steps=_weapon_steps(1200.0, 400.0),
    ),
    "mec_a8": EquipmentUpgradeSpec(
        item_id="mec_a8",
        name="MEC-A8 'Tornado'",
        slot="weapon",
        effect="Fast autocannon scaling damage and close-range optimal window.",
        level_cap=15,
        upgrade_axes=('damage', 'optimal_range'),
        curves={
            "damage_min": _linear(1.0, 0.09999999999999999),
            "damage_max": _linear(10.0, 1.0),
            "armor_piercing": _linear(5.0, 0.0),
            "range_min": _linear(0.0, 0.0),
            "range_max": _linear(600.0, 0.0),
            "optimal_range": _linear(250.0, 10.0),
            "accuracy": _linear(400.0, 0.0),
            "critical_offense": _linear(100.0, 0.0),
            "reload": _linear(0.4, 0.0),
            "power": _linear(1.0, 0.0),
            "firing_arc": _linear(75.0, 0.0),
            "durability": _linear(6000.0, 0.0),
        },
        steps=_weapon_steps(1400.0, 420.0),
    ),
    "mec_a8p": EquipmentUpgradeSpec(
        item_id="mec_a8p",
        name="MEC-A8P 'Tornado-P'",
        slot="weapon",
        effect="Crit-focused Tornado improving damage output and crit offense.",
        level_cap=15,
        upgrade_axes=('damage', 'critical_offense'),
        curves={
            "damage_min": _linear(1.0, 0.09999999999999999),
            "damage_max": _linear(10.0, 1.0),
            "armor_piercing": _linear(5.0, 0.0),
            "range_min": _linear(0.0, 0.0),
            "range_max": _linear(600.0, 0.0),
            "optimal_range": _linear(250.0, 0.0),
            "accuracy": _linear(400.0, 0.0),
            "critical_offense": _linear(100.0, 5.0),
            "reload": _linear(0.4, 0.0),
            "power": _linear(1.0, 0.0),
            "firing_arc": _linear(75.0, 0.0),
            "durability": _linear(6000.0, 0.0),
        },
        steps=_weapon_steps(1400.0, 420.0),
    ),
    "mec_a9": EquipmentUpgradeSpec(
        item_id="mec_a9",
        name="MEC-A9 'Hawk'",
        slot="weapon",
        effect="Longer-range Strike autocannon extending its optimal envelope.",
        level_cap=15,
        upgrade_axes=('damage', 'optimal_range'),
        curves={
            "damage_min": _linear(1.0, 0.09999999999999999),
            "damage_max": _linear(10.0, 1.0),
            "armor_piercing": _linear(5.0, 0.0),
            "range_min": _linear(0.0, 0.0),
            "range_max": _linear(900.0, 0.0),
            "optimal_range": _linear(350.0, 20.0),
            "accuracy": _linear(400.0, 0.0),
            "critical_offense": _linear(100.0, 0.0),
            "reload": _linear(0.6, 0.0),
            "power": _linear(1.0, 0.0),
            "firing_arc": _linear(75.0, 0.0),
            "durability": _linear(6000.0, 0.0),
        },
        steps=_weapon_steps(1400.0, 420.0),
    ),
    "mec_a9p": EquipmentUpgradeSpec(
        item_id="mec_a9p",
        name="MEC-A9P 'Hawk-P'",
        slot="weapon",
        effect="Precision Hawk variant boosting damage and crit potential.",
        level_cap=15,
        upgrade_axes=('damage', 'critical_offense'),
        curves={
            "damage_min": _linear(1.0, 0.09999999999999999),
            "damage_max": _linear(10.0, 1.0),
            "armor_piercing": _linear(5.0, 0.0),
            "range_min": _linear(0.0, 0.0),
            "range_max": _linear(900.0, 0.0),
            "optimal_range": _linear(350.0, 0.0),
            "accuracy": _linear(400.0, 0.0),
            "critical_offense": _linear(100.0, 5.0),
            "reload": _linear(0.6, 0.0),
            "power": _linear(1.0, 0.0),
            "firing_arc": _linear(75.0, 0.0),
            "durability": _linear(6000.0, 0.0),
        },
        steps=_weapon_steps(1400.0, 420.0),
    ),
    "gopher_light_mining_cannon": EquipmentUpgradeSpec(
        item_id="gopher_light_mining_cannon",
        name="'Gopher' Light Mining Cannon",
        slot="weapon",
        effect="Dual-role mining cannon improving combat damage and optimal range.",
        level_cap=15,
        upgrade_axes=('damage', 'optimal_range'),
        curves={
            "damage_min": _linear(1.0, 0.09999999999999999),
            "damage_max": _linear(4.0, 0.39999999999999997),
            "armor_piercing": _linear(5.0, 0.0),
            "range_min": _linear(0.0, 0.0),
            "range_max": _linear(600.0, 0.0),
            "optimal_range": _linear(250.0, 10.0),
            "accuracy": _linear(400.0, 0.0),
            "critical_offense": _linear(100.0, 0.0),
            "reload": _linear(0.5, 0.0),
            "power": _linear(2.0, 0.0),
            "firing_arc": _linear(75.0, 0.0),
            "mining_yield": _linear(5.0, 0.0),
            "durability": _linear(6000.0, 0.0),
        },
        steps=_weapon_steps(1000.0, 300.0),
    ),
    "dfsr_18_hornet": EquipmentUpgradeSpec(
        item_id="dfsr_18_hornet",
        name="DFSR-18 'Hornet'",
        slot="weapon",
        effect="Raven rocket pack trimming reload and power draw with upgrades.",
        level_cap=15,
        upgrade_axes=('reload', 'power'),
        curves={
            "damage_min": _linear(200.0, 0.0),
            "damage_max": _linear(200.0, 0.0),
            "armor_piercing": _linear(20.0, 0.0),
            "critical_offense": _linear(100.0, 0.0),
            "projectile_speed": _linear(210.0, 0.0),
            "reload": _linear(4.0, -0.14285714285714285),
            "power": _linear(16.2, -0.26428571428571423),
            "firing_arc": _linear(75.0, 0.0),
            "durability": _linear(6000.0, 0.0),
        },
        steps=_weapon_steps(1700.0, 500.0),
    ),
    "hd_70p_lightning_p": EquipmentUpgradeSpec(
        item_id="hd_70p_lightning_p",
        name="HD-70P 'Lightning-P'",
        slot="weapon",
        effect="Precision light missiles improving crit chance and cadence.",
        level_cap=15,
        upgrade_axes=('critical_offense', 'reload', 'power'),
        curves={
            "damage_min": _linear(25.0, 0.0),
            "damage_max": _linear(50.0, 0.0),
            "armor_piercing": _linear(15.0, 0.0),
            "range_min": _linear(200.0, 0.0),
            "range_max": _linear(1000.0, 0.0),
            "optimal_range": _linear(200.0, 0.0),
            "accuracy": _linear(400.0, 0.0),
            "critical_offense": _linear(100.0, 5.0),
            "reload": _linear(10.0, -0.4164285714285714),
            "power": _linear(20.0, -0.8335714285714285),
            "firing_arc": _linear(75.0, 0.0),
            "turn_speed": _linear(100.0, 0.0),
            "projectile_speed": _linear(120.0, 0.0),
            "durability": _linear(6000.0, 0.0),
        },
        steps=_weapon_steps(1500.0, 450.0),
    ),
    "asm_a9_zephyr": EquipmentUpgradeSpec(
        item_id="asm_a9_zephyr",
        name="ASM-A9 'Zephyr'",
        slot="weapon",
        effect="Heavy Raven missile reducing its long reload over levels.",
        level_cap=15,
        upgrade_axes=('reload',),
        curves={
            "damage_min": _linear(750.0, 0.0),
            "damage_max": _linear(750.0, 0.0),
            "armor_piercing": _linear(35.0, 0.0),
            "range_min": _linear(500.0, 0.0),
            "range_max": _linear(1200.0, 0.0),
            "optimal_range": _linear(750.0, 0.0),
            "accuracy": _linear(400.0, 0.0),
            "critical_offense": _linear(0.0, 0.0),
            "reload": _linear(60.0, -1.7142857142857142),
            "power": _linear(5.0, 0.0),
            "firing_arc": _linear(75.0, 0.0),
            "turn_speed": _linear(15.0, 0.0),
            "projectile_speed": _linear(120.0, 0.0),
            "durability": _linear(6000.0, 0.0),
        },
        steps=_weapon_steps(2000.0, 550.0),
    ),
    "hd_70_lightning": EquipmentUpgradeSpec(
        item_id="hd_70_lightning",
        name="HD-70 'Lightning'",
        slot="weapon",
        effect="Baseline Strike missile increasing range and energy efficiency.",
        level_cap=15,
        upgrade_axes=('range_max', 'reload', 'power'),
        curves={
            "damage_min": _linear(25.0, 0.0),
            "damage_max": _linear(50.0, 0.0),
            "armor_piercing": _linear(15.0, 0.0),
            "range_min": _linear(200.0, 0.0),
            "range_max": _linear(1000.0, 25.0),
            "optimal_range": _linear(200.0, 0.0),
            "accuracy": _linear(400.0, 0.0),
            "critical_offense": _linear(100.0, 0.0),
            "reload": _linear(10.0, -0.4164285714285714),
            "power": _linear(20.0, -0.8335714285714285),
            "firing_arc": _linear(75.0, 0.0),
            "turn_speed": _linear(100.0, 0.0),
            "projectile_speed": _linear(120.0, 0.0),
            "durability": _linear(6000.0, 0.0),
        },
        steps=_weapon_steps(1500.0, 450.0),
    ),
    "siw_9m_wasp": EquipmentUpgradeSpec(
        item_id="siw_9m_wasp",
        name="SIW-9M 'Wasp'",
        slot="weapon",
        effect="Raven interceptor missile shortening reload cycles.",
        level_cap=15,
        upgrade_axes=('reload',),
        curves={
            "damage_min": _linear(300.0, 0.0),
            "damage_max": _linear(300.0, 0.0),
            "armor_piercing": _linear(15.0, 0.0),
            "range_min": _linear(300.0, 0.0),
            "range_max": _linear(1000.0, 0.0),
            "optimal_range": _linear(650.0, 0.0),
            "accuracy": _linear(400.0, 0.0),
            "critical_offense": _linear(100.0, 0.0),
            "reload": _linear(30.0, -0.4642857142857143),
            "power": _linear(5.0, 0.0),
            "firing_arc": _linear(75.0, 0.0),
            "turn_speed": _linear(65.0, 0.0),
            "projectile_speed": _linear(150.0, 0.0),
            "durability": _linear(6000.0, 0.0),
        },
        steps=_weapon_steps(1900.0, 520.0),
    ),
    "hd_82_longbow": EquipmentUpgradeSpec(
        item_id="hd_82_longbow",
        name="HD-82 'Longbow'",
        slot="weapon",
        effect="Long-range missile pod expanding reach and reducing upkeep.",
        level_cap=15,
        upgrade_axes=('range_max', 'reload', 'power'),
        curves={
            "damage_min": _linear(25.0, 0.0),
            "damage_max": _linear(50.0, 0.0),
            "armor_piercing": _linear(15.0, 0.0),
            "range_min": _linear(200.0, 0.0),
            "range_max": _linear(1250.0, 32.5),
            "optimal_range": _linear(200.0, 0.0),
            "accuracy": _linear(400.0, 0.0),
            "critical_offense": _linear(100.0, 0.0),
            "reload": _linear(12.0, -0.5),
            "power": _linear(20.0, -0.8335714285714285),
            "firing_arc": _linear(75.0, 0.0),
            "turn_speed": _linear(100.0, 0.0),
            "projectile_speed": _linear(120.0, 0.0),
            "durability": _linear(6000.0, 0.0),
        },
        steps=_weapon_steps(1500.0, 450.0),
    ),
    "hd_82p_longbow_p": EquipmentUpgradeSpec(
        item_id="hd_82p_longbow_p",
        name="HD-82P 'Longbow-P'",
        slot="weapon",
        effect="Precision Longbow improving crit offense and firing cadence.",
        level_cap=15,
        upgrade_axes=('critical_offense', 'reload', 'power'),
        curves={
            "damage_min": _linear(25.0, 0.0),
            "damage_max": _linear(50.0, 0.0),
            "armor_piercing": _linear(15.0, 0.0),
            "range_min": _linear(200.0, 0.0),
            "range_max": _linear(1250.0, 0.0),
            "optimal_range": _linear(200.0, 0.0),
            "accuracy": _linear(400.0, 0.0),
            "critical_offense": _linear(100.0, 5.0),
            "reload": _linear(12.0, -0.5),
            "power": _linear(20.0, -0.8335714285714285),
            "firing_arc": _linear(75.0, 0.0),
            "turn_speed": _linear(100.0, 0.0),
            "projectile_speed": _linear(120.0, 0.0),
            "durability": _linear(6000.0, 0.0),
        },
        steps=_weapon_steps(1500.0, 450.0),
    ),
    "asm_a3_cyclops": EquipmentUpgradeSpec(
        item_id="asm_a3_cyclops",
        name="ASM-A3 'Cyclops'",
        slot="weapon",
        effect="Strike nuclear torpedo boosting power-grid damage and uptime.",
        level_cap=15,
        upgrade_axes=('power_damage', 'range_max', 'reload', 'power'),
        curves={
            "damage_min": _linear(250.0, 0.0),
            "damage_max": _linear(500.0, 0.0),
            "armor_piercing": _linear(35.0, 0.0),
            "range_min": _linear(600.0, 0.0),
            "range_max": _linear(1080.0, 18.214285714285715),
            "optimal_range": _linear(840.0, 0.0),
            "accuracy": _linear(400.0, 0.0),
            "critical_offense": _linear(100.0, 0.0),
            "reload": _linear(120.0, -2.142857142857143),
            "power": _linear(45.0, -0.6428571428571429),
            "firing_arc": _linear(75.0, 0.0),
            "turn_speed": _linear(70.0, 0.0),
            "projectile_speed": _linear(85.0, 0.0),
            "explosion_radius": _linear(400.0, 0.0),
            "power_damage_min": _linear(40.0, 0.7142857142857143),
            "power_damage_max": _linear(60.0, 1.0714285714285714),
            "durability": _linear(6000.0, 0.0),
        },
        steps=_weapon_steps(1600.0, 480.0),
    ),
    "ast_7a_manticore": EquipmentUpgradeSpec(
        item_id="ast_7a_manticore",
        name="AST-7A 'Manticore'",
        slot="weapon",
        effect="Short-range tactical nuke increasing power damage and usability.",
        level_cap=15,
        upgrade_axes=('power_damage', 'range_max', 'reload', 'power'),
        curves={
            "damage_min": _linear(600.0, 0.0),
            "damage_max": _linear(850.0, 0.0),
            "armor_piercing": _linear(35.0, 0.0),
            "range_min": _linear(200.0, 0.0),
            "range_max": _linear(680.0, 12.142857142857142),
            "optimal_range": _linear(440.0, 0.0),
            "accuracy": _linear(400.0, 0.0),
            "critical_offense": _linear(100.0, 0.0),
            "reload": _linear(160.0, -1.8571428571428572),
            "power": _linear(70.0, -0.8214285714285714),
            "firing_arc": _linear(75.0, 0.0),
            "turn_speed": _linear(2.0, 0.0),
            "projectile_speed": _linear(60.0, 0.0),
            "explosion_radius": _linear(200.0, 0.0),
            "power_damage_min": _linear(80.0, 0.7142857142857143),
            "power_damage_max": _linear(120.0, 1.0714285714285714),
            "durability": _linear(6000.0, 0.0),
        },
        steps=_weapon_steps(1600.0, 480.0),
    ),
    "hd_96_nova": EquipmentUpgradeSpec(
        item_id="hd_96_nova",
        name="HD-96 'Nova'",
        slot="weapon",
        effect="Armor-piercing missile improving range, reload, and power draw.",
        level_cap=15,
        upgrade_axes=('range_max', 'reload', 'power'),
        curves={
            "damage_min": _linear(125.0, 0.0),
            "damage_max": _linear(250.0, 0.0),
            "armor_piercing": _linear(40.0, 0.0),
            "range_min": _linear(200.0, 0.0),
            "range_max": _linear(680.0, 12.142857142857142),
            "optimal_range": _linear(440.0, 0.0),
            "accuracy": _linear(400.0, 0.0),
            "critical_offense": _linear(100.0, 0.0),
            "reload": _linear(20.0, -0.7142857142857143),
            "power": _linear(30.0, -0.35714285714285715),
            "firing_arc": _linear(75.0, 0.0),
            "turn_speed": _linear(2.0, 0.0),
            "projectile_speed": _linear(80.0, 0.0),
            "durability": _linear(6000.0, 0.0),
        },
        steps=_weapon_steps(1500.0, 450.0),
    ),
    "strike_composite_plating": EquipmentUpgradeSpec(
        item_id="strike_composite_plating",
        name="Strike Composite Plating",
        slot="hull",
        effect="Composite plating scaling armor and hull bonuses.",
        level_cap=15,
        upgrade_axes=('armor', 'hull_hp'),
        curves={
            "armor": _linear(2.25, 0.22500000000000003),
            "hull_hp": _linear(22.5, 2.25),
            "acceleration": _linear(-0.3, 0.0),
            "turn_accel": _linear(-0.75, 0.0),
            "durability": _linear(6000.0, 0.0),
        },
        steps=_hull_steps(850.0, 180.0),
    ),
    "strike_hull_plating": EquipmentUpgradeSpec(
        item_id="strike_hull_plating",
        name="Strike Hull Plating",
        slot="hull",
        effect="Hull reinforcement increasing maximum hit points per level.",
        level_cap=15,
        upgrade_axes=('hull_hp',),
        curves={
            "hull_hp": _linear(45.0, 4.5),
            "acceleration": _linear(-0.2, 0.0),
            "turn_accel": _linear(-1.0, 0.0),
            "durability": _linear(6000.0, 0.0),
        },
        steps=_hull_steps(850.0, 180.0),
    ),
    "strike_armor_plating": EquipmentUpgradeSpec(
        item_id="strike_armor_plating",
        name="Strike Armor Plating",
        slot="hull",
        effect="Armor-focused plating scaling mitigation at steady penalties.",
        level_cap=15,
        upgrade_axes=('armor',),
        curves={
            "armor": _linear(4.5, 0.45000000000000007),
            "acceleration": _linear(-0.4, 0.0),
            "turn_accel": _linear(-0.5, 0.0),
            "durability": _linear(6000.0, 0.0),
        },
        steps=_hull_steps(850.0, 180.0),
    ),
    "strike_ht_plating": EquipmentUpgradeSpec(
        item_id="strike_ht_plating",
        name="Strike HT Plating",
        slot="hull",
        effect="Critical defense plating scaling resistance to crits.",
        level_cap=15,
        upgrade_axes=('critical_defense',),
        curves={
            "critical_defense": _linear(7.5, 0.75),
            "durability": _linear(6000.0, 0.0),
        },
        steps=_hull_steps(850.0, 180.0),
    ),
    "strike_ht_hull_plating": EquipmentUpgradeSpec(
        item_id="strike_ht_hull_plating",
        name="Strike HT Hull Plating",
        slot="hull",
        effect="Heavy-tuned hull plating scaling hull points and crit defense.",
        level_cap=15,
        upgrade_axes=('critical_defense', 'hull_hp'),
        curves={
            "critical_defense": _linear(2.5, 0.25),
            "hull_hp": _linear(30.0, 3.0),
            "acceleration": _linear(-0.13, 0.0),
            "turn_accel": _linear(-0.67, 0.0),
            "durability": _linear(6000.0, 0.0),
        },
        steps=_hull_steps(850.0, 180.0),
    ),
    "strike_ht_armor_plating": EquipmentUpgradeSpec(
        item_id="strike_ht_armor_plating",
        name="Strike HT Armor Plating",
        slot="hull",
        effect="Heavy-tuned armor blend scaling armor and critical defense.",
        level_cap=15,
        upgrade_axes=('armor', 'critical_defense'),
        curves={
            "armor": _linear(3.0, 0.3),
            "critical_defense": _linear(2.5, 0.25),
            "acceleration": _linear(-0.27, 0.0),
            "turn_accel": _linear(-0.33, 0.0),
            "durability": _linear(6000.0, 0.0),
        },
        steps=_hull_steps(850.0, 180.0),
    ),
    "strike_ht_composite_plating": EquipmentUpgradeSpec(
        item_id="strike_ht_composite_plating",
        name="Strike HT Composite Plating",
        slot="hull",
        effect="All-round heavy-tuned composite scaling armor, crit defense, and hull.",
        level_cap=15,
        upgrade_axes=('armor', 'critical_defense', 'hull_hp'),
        curves={
            "armor": _linear(1.8, 0.18000000000000002),
            "critical_defense": _linear(1.5, 0.15),
            "hull_hp": _linear(18.0, 1.8000000000000003),
            "acceleration": _linear(-0.24, 0.0),
            "turn_accel": _linear(-0.6, 0.0),
            "durability": _linear(6000.0, 0.0),
        },
        steps=_hull_steps(850.0, 180.0),
    ),
    "strike_system_redundancy": EquipmentUpgradeSpec(
        item_id="strike_system_redundancy",
        name="Strike System Redundancy",
        slot="hull",
        effect="Passive hull regeneration scaling recovery per second.",
        level_cap=15,
        upgrade_axes=('hull_recovery',),
        curves={
            "hull_recovery": _linear(0.5, 0.049999999999999996),
            "durability": _linear(6000.0, 0.0),
        },
        steps=_hull_steps(750.0, 150.0),
    ),
    "strike_damage_control": EquipmentUpgradeSpec(
        item_id="strike_damage_control",
        name="Strike Damage Control",
        slot="hull",
        effect="Active repair unit scaling burst hull restoration.",
        level_cap=15,
        upgrade_axes=('hull_restore',),
        curves={
            "hull_restore": _linear(50.0, 5.0),
            "reload": _linear(30.0, 0.0),
            "power": _linear(50.0, 0.0),
            "durability": _linear(6000.0, 0.0),
        },
        steps=_hull_steps(900.0, 190.0),
    ),
    "light_drive_overcharger": EquipmentUpgradeSpec(
        item_id="light_drive_overcharger",
        name="Light Drive Overcharger",
        slot="engine",
        effect="Flat speed bonuses that scale cruise and boost velocity with level.",
        level_cap=15,
        upgrade_axes=('max_speed', 'boost_speed'),
        curves={
            "max_speed": _linear(1.25, 0.125),
            "boost_speed": _linear(1.25, 0.125),
            "durability": _linear(6000.0, 0.0),
        },
        steps=_engine_steps(12.0, 2.0),
    ),
    "light_turbo_boosters": EquipmentUpgradeSpec(
        item_id="light_turbo_boosters",
        name="Light Turbo Boosters",
        slot="engine",
        effect="Acceleration and boost speed bonuses that grow for sharper sprints.",
        level_cap=15,
        upgrade_axes=('acceleration', 'boost_speed'),
        curves={
            "acceleration": _linear(1.0, 0.09999999999999999),
            "boost_speed": _linear(2.5, 0.25),
            "durability": _linear(6000.0, 0.0),
        },
        steps=_engine_steps(13.0, 2.2),
    ),
    "light_gyro_stabilization": EquipmentUpgradeSpec(
        item_id="light_gyro_stabilization",
        name="Light Gyro-Stabilization",
        slot="engine",
        effect="Turn rate and turn acceleration boosts that scale to sharpen agility.",
        level_cap=15,
        upgrade_axes=('turn_rate', 'turn_accel'),
        curves={
            "turn_rate": _linear(2.5, 0.25),
            "turn_accel": _linear(2.5, 0.25),
            "durability": _linear(6000.0, 0.0),
        },
        steps=_engine_steps(13.0, 2.2),
    ),
    "light_rcs_ducting": EquipmentUpgradeSpec(
        item_id="light_rcs_ducting",
        name="Light RCS Ducting",
        slot="engine",
        effect="Avoidance bonus that scales upward to improve survivability.",
        level_cap=15,
        upgrade_axes=('avoidance',),
        curves={
            "avoidance_rating": _linear(15.0, 1.5),
            "durability": _linear(6000.0, 0.0),
        },
        steps=_engine_steps(10.0, 2.0),
    ),
    "t8_drive_turbo_charger": EquipmentUpgradeSpec(
        item_id="t8_drive_turbo_charger",
        name="T8 Drive Turbo Charger",
        slot="engine",
        effect="Raven percentage speed and boost bonuses that scale with level.",
        level_cap=15,
        upgrade_axes=('max_speed_percent', 'boost_speed_percent'),
        curves={
            "max_speed_percent": _linear(3.0, 0.2857142857142857),
            "boost_speed_percent": _linear(4.0, 0.2857142857142857),
            "durability": _linear(6000.0, 0.0),
        },
        steps=_engine_steps(18.0, 3.0),
    ),
    "fog_gyro_stabilization": EquipmentUpgradeSpec(
        item_id="fog_gyro_stabilization",
        name="FoG Gyro-Stabilization System",
        slot="engine",
        effect="Raven gyro suite scaling percentage turn speed and turn acceleration bonuses.",
        level_cap=15,
        upgrade_axes=('turn_rate_percent', 'turn_accel_percent'),
        curves={
            "turn_rate_percent": _linear(10.0, 0.42857142857142855),
            "turn_accel_percent": _linear(10.0, 0.42857142857142855),
            "durability": _linear(6000.0, 0.0),
        },
        steps=_engine_steps(18.0, 3.0),
    ),
    "translation_rcs_thrusters": EquipmentUpgradeSpec(
        item_id="translation_rcs_thrusters",
        name="Translation RCS Thrusters",
        slot="engine",
        effect="Raven RCS package scaling percentage turn rate and strafe speed bonuses.",
        level_cap=15,
        upgrade_axes=('turn_rate_percent', 'strafe_speed_percent'),
        curves={
            "turn_rate_percent": _linear(10.0, 0.7142857142857143),
            "strafe_speed_percent": _linear(15.0, 0.6785714285714286),
            "durability": _linear(6000.0, 0.0),
        },
        steps=_engine_steps(18.0, 3.0),
    ),
    "t15_pulsed_plasma_thruster": EquipmentUpgradeSpec(
        item_id="t15_pulsed_plasma_thruster",
        name="T15 Pulsed Plasma Thruster",
        slot="engine",
        effect="Raven booster scaling percentage boost speed and acceleration bonuses while keeping the cost penalty fixed.",
        level_cap=15,
        upgrade_axes=('boost_speed_percent', 'acceleration_percent'),
        curves={
            "boost_speed_percent": _linear(6.0, 0.35714285714285715),
            "acceleration_percent": _linear(20.0, 0.5714285714285714),
            "boost_cost_percent": _linear(25.0, 0.0),
            "durability": _linear(6000.0, 0.0),
        },
        steps=_engine_steps(20.0, 3.5),
    ),
    "coupled_rcs_ducting": EquipmentUpgradeSpec(
        item_id="coupled_rcs_ducting",
        name="Coupled RCS Ducting",
        slot="engine",
        effect="Raven defensive ducting scaling avoidance percentage while the boost penalty stays fixed.",
        level_cap=15,
        upgrade_axes=('avoidance_percent',),
        curves={
            "avoidance_percent": _linear(4.0, 0.35714285714285715),
            "boost_speed_percent": _linear(-2.5, 0.0),
            "durability": _linear(6000.0, 0.0),
        },
        steps=_engine_steps(18.0, 3.0),
    ),
    "fbs_12_engine_overload": EquipmentUpgradeSpec(
        item_id="fbs_12_engine_overload",
        name="FBS-12 Engine Overload System",
        slot="engine",
        effect="Rhino overdrive extending its active duration while the surge stats remain fixed.",
        level_cap=15,
        upgrade_axes=('duration',),
        curves={
            "boost_speed_active": _linear(16.0, 0.0),
            "boost_acceleration_multiplier": _linear(3.0, 0.0),
            "boost_cost_percent": _linear(200.0, 0.0),
            "duration": _linear(8.0, 0.5714285714285714),
            "reload": _linear(80.0, 0.0),
            "power": _linear(60.0, 0.0),
            "durability": _linear(6000.0, 0.0),
        },
        steps=_engine_steps(22.0, 3.5),
    ),
    "mec_l31": EquipmentUpgradeSpec(
        item_id="mec_l31",
        name="MEC-L31 'Talon'",
        slot="weapon",
        effect="Line heavy cannon improving shot damage and optimal reach.",
        level_cap=15,
        upgrade_axes=('damage', 'optimal_range'),
        curves={
            "damage_min": _linear(35.0, 3.5),
            "damage_max": _linear(70.0, 7.0),
            "armor_piercing": _linear(35.0, 0.0),
            "range_min": _linear(0.0, 0.0),
            "range_max": _linear(1700.0, 0.0),
            "optimal_range": _linear(675.0, 37.5),
            "accuracy": _linear(125.0, 0.0),
            "critical_offense": _linear(100.0, 0.0),
            "reload": _linear(4.0, 0.0),
            "power": _linear(25.0, 0.0),
            "firing_arc": _linear(180.0, 0.0),
            "durability": _linear(17500.0, 0.0),
        },
        steps=_weapon_steps(2400.0, 720.0),
    ),
    "mec_l34": EquipmentUpgradeSpec(
        item_id="mec_l34",
        name="MEC-L34 'Cyclone'",
        slot="weapon",
        effect="Rapid-firing line cannon scaling damage and optimal range.",
        level_cap=15,
        upgrade_axes=('damage', 'optimal_range'),
        curves={
            "damage_min": _linear(35.0, 3.5),
            "damage_max": _linear(70.0, 7.0),
            "armor_piercing": _linear(35.0, 0.0),
            "range_min": _linear(0.0, 0.0),
            "range_max": _linear(1350.0, 0.0),
            "optimal_range": _linear(550.0, 25.0),
            "accuracy": _linear(125.0, 0.0),
            "critical_offense": _linear(100.0, 0.0),
            "reload": _linear(3.2, 0.0),
            "power": _linear(25.0, 0.0),
            "firing_arc": _linear(180.0, 0.0),
            "durability": _linear(17500.0, 0.0),
        },
        steps=_weapon_steps(2400.0, 720.0),
    ),
    "mec_l35": EquipmentUpgradeSpec(
        item_id="mec_l35",
        name="MEC-L35 'Eagle'",
        slot="weapon",
        effect="Long-range line cannon increasing damage and precision range.",
        level_cap=15,
        upgrade_axes=('damage', 'optimal_range'),
        curves={
            "damage_min": _linear(35.0, 3.5),
            "damage_max": _linear(70.0, 7.0),
            "armor_piercing": _linear(35.0, 0.0),
            "range_min": _linear(0.0, 0.0),
            "range_max": _linear(2000.0, 0.0),
            "optimal_range": _linear(800.0, 42.857142857142854),
            "accuracy": _linear(125.0, 0.0),
            "critical_offense": _linear(100.0, 0.0),
            "reload": _linear(4.8, 0.0),
            "power": _linear(25.0, 0.0),
            "firing_arc": _linear(180.0, 0.0),
            "durability": _linear(17500.0, 0.0),
        },
        steps=_weapon_steps(2500.0, 750.0),
    ),
    "hd_h40": EquipmentUpgradeSpec(
        item_id="hd_h40",
        name="HD-H40 'Stormstrike'",
        slot="weapon",
        effect="Heavy missile battery enhancing warhead damage and reach.",
        level_cap=15,
        upgrade_axes=('damage', 'range_max'),
        curves={
            "damage_min": _linear(55.0, 5.5),
            "damage_max": _linear(150.0, 15.0),
            "armor_piercing": _linear(35.0, 0.0),
            "range_min": _linear(200.0, 0.0),
            "range_max": _linear(1800.0, 28.571428571428573),
            "optimal_range": _linear(1000.0, 0.0),
            "accuracy": _linear(125.0, 0.0),
            "critical_offense": _linear(100.0, 0.0),
            "reload": _linear(15.0, 0.0),
            "power": _linear(100.0, 0.0),
            "firing_arc": _linear(180.0, 0.0),
            "turn_speed": _linear(30.0, 0.0),
            "projectile_speed": _linear(80.0, 0.0),
            "durability": _linear(17500.0, 0.0),
        },
        steps=_weapon_steps(2600.0, 780.0),
    ),
    "mec_l39f": EquipmentUpgradeSpec(
        item_id="mec_l39f",
        name="MEC-L39F 'Landslide'",
        slot="weapon",
        effect="Line flak battery expanding defensive saturation coverage.",
        level_cap=15,
        upgrade_axes=('damage', 'range_max', 'optimal_range'),
        curves={
            "damage_min": _linear(1.0, 0.1),
            "damage_max": _linear(35.0, 3.5),
            "armor_piercing": _linear(15.0, 0.0),
            "range_min": _linear(500.0, 0.0),
            "range_max": _linear(800.0, 22.857142857142858),
            "optimal_range": _linear(800.0, 22.857142857142858),
            "accuracy": _linear(300.0, 0.0),
            "critical_offense": _linear(100.0, 0.0),
            "reload": _linear(1.0, 0.0),
            "power": _linear(7.0, 0.0),
            "firing_arc": _linear(180.0, 0.0),
            "durability": _linear(17500.0, 0.0),
        },
        steps=_weapon_steps(2000.0, 600.0),
    ),
    "mec_l30p": EquipmentUpgradeSpec(
        item_id="mec_l30p",
        name="MEC-L30P 'Brushfire'",
        slot="weapon",
        effect="Point defence battery boosting interception damage and coverage.",
        level_cap=15,
        upgrade_axes=('damage', 'range_max', 'optimal_range'),
        curves={
            "damage_min": _linear(1.0, 0.1),
            "damage_max": _linear(5.0, 0.5),
            "armor_piercing": _linear(5.0, 0.0),
            "range_min": _linear(0.0, 0.0),
            "range_max": _linear(540.0, 25.714285714285715),
            "optimal_range": _linear(400.0, 21.428571428571427),
            "accuracy": _linear(500.0, 0.0),
            "critical_offense": _linear(100.0, 0.0),
            "reload": _linear(0.5, 0.0),
            "power": _linear(3.5, 0.0),
            "firing_arc": _linear(180.0, 0.0),
            "durability": _linear(17500.0, 0.0),
        },
        steps=_weapon_steps(2000.0, 600.0),
    ),
    "hd_h48": EquipmentUpgradeSpec(
        item_id="hd_h48",
        name="HD-H48 'Ballista'",
        slot="weapon",
        effect="Long-range missile rack increasing strike damage and reach.",
        level_cap=15,
        upgrade_axes=('damage', 'range_max'),
        curves={
            "damage_min": _linear(55.0, 5.5),
            "damage_max": _linear(150.0, 15.0),
            "armor_piercing": _linear(35.0, 0.0),
            "range_min": _linear(200.0, 0.0),
            "range_max": _linear(2000.0, 42.857142857142854),
            "optimal_range": _linear(1200.0, 0.0),
            "accuracy": _linear(125.0, 0.0),
            "critical_offense": _linear(100.0, 0.0),
            "reload": _linear(18.0, 0.0),
            "power": _linear(100.0, 0.0),
            "firing_arc": _linear(180.0, 0.0),
            "turn_speed": _linear(30.0, 0.0),
            "projectile_speed": _linear(80.0, 0.0),
            "durability": _linear(17500.0, 0.0),
        },
        steps=_weapon_steps(2800.0, 840.0),
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

