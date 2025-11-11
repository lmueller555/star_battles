import math

from game.ui.equipment_upgrade import (
    EQUIPMENT_UPGRADE_SPECS,
    EquipmentUpgradeModel,
    EquipmentUpgradeSpec,
    UpgradeCurve,
    UpgradeStep,
)
from game.ships.data import ShipFrame
from game.ships.ship import Ship
from game.ships.stats import ShipSlotLayout, ShipStats


def _resources(**kwargs):
    base = {"tylium": 0.0, "cubits": 0.0, "merits": 0.0, "tuning_kits": 0.0}
    base.update({key: float(value) for key, value in kwargs.items()})
    return base


def _skills(**kwargs):
    return {key: int(value) for key, value in kwargs.items()}


def test_weapon_upgrade_costs_and_stats():
    spec = EQUIPMENT_UPGRADE_SPECS["mec_a6"]
    model = EquipmentUpgradeModel(spec, current_level=1, player_resources=_resources(tylium=10_000), player_skills=_skills(Gunnery=3))
    model.set_preview_level(3)
    totals, unknown = model.aggregate_cost()
    assert not unknown
    assert math.isclose(totals["tylium"], 2_800.0)
    damage_value, known = model.stat_value("damage_min", model.preview_level)
    assert known
    assert math.isclose(damage_value, 1.32, rel_tol=1e-3)


def test_skill_requirement_gate_blocks_upgrade():
    spec = EQUIPMENT_UPGRADE_SPECS["mec_a6"]
    model = EquipmentUpgradeModel(spec, current_level=1, player_resources=_resources(tylium=50_000), player_skills=_skills(Gunnery=1))
    model.set_preview_level(8)
    allowed, reason = model.can_upgrade()
    assert not allowed
    assert reason and "Gunnery" in reason


def test_guarantee_increases_tuning_kit_cost():
    spec = EQUIPMENT_UPGRADE_SPECS["mec_a6"]
    model = EquipmentUpgradeModel(
        spec,
        current_level=10,
        player_resources=_resources(tylium=100_000, tuning_kits=10),
        player_skills=_skills(Gunnery=3),
    )
    model.set_preview_level(12)
    totals, _ = model.aggregate_cost()
    assert math.isclose(totals.get("tuning_kits", 0.0), 2.0)
    model.toggle_guarantee()
    totals, _ = model.aggregate_cost()
    assert math.isclose(totals.get("tuning_kits", 0.0), 6.0)


def test_stat_value_marks_unknown_when_curve_missing():
    spec = EquipmentUpgradeSpec(
        item_id="demo",
        name="Demo",
        slot="weapon",
        effect="",
        level_cap=5,
        upgrade_axes=("damage",),
        curves={
            "damage_min": UpgradeCurve(start=1.0, increment=0.0, table={1: 1.0, 2: 1.5}),
            "damage_max": UpgradeCurve(start=2.0, increment=0.0, table={1: 2.0, 2: 2.5}),
        },
        steps={
            2: UpgradeStep(level=2, costs={"tylium": 100.0}),
            3: UpgradeStep(level=3, costs={"tylium": 120.0}),
        },
    )
    model = EquipmentUpgradeModel(spec, current_level=2, player_resources=_resources(tylium=5_000), player_skills={})
    value, known = model.stat_value("damage_min", 3)
    assert not known
    assert math.isclose(value, 1.5)


def _make_test_ship() -> Ship:
    stats = ShipStats.from_dict({})
    slots = ShipSlotLayout.from_dict({})
    frame = ShipFrame("test", "Test", "Interceptor", "Strike", stats, slots, [])
    return Ship(frame)


def test_hold_item_levels_are_instance_specific():
    ship = _make_test_ship()
    assert ship.add_hold_item("light_turbo_boosters", quantity=3)
    ship.set_hold_item_level("light_turbo_boosters", 0, 15)
    assert ship.hold_item_level("light_turbo_boosters", 0) == 15
    assert ship.hold_item_level("light_turbo_boosters", 1) == 1
    assert ship.hold_item_level("light_turbo_boosters", 2) == 1
