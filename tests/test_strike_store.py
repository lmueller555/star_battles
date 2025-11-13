from pathlib import Path
from typing import Callable, Union

import pytest

from game.assets.content import ContentManager, ItemData
from game.ships.ship import Ship
from game.ui.strike_store import StoreFilters, fitting, store


ExpectedEngineDelta = Union[dict[str, float], Callable[[Ship], dict[str, float]]]


def _make_ship(frame_id: str = "viper_mk_vii", *, cubits: float = 20000.0) -> Ship:
    content = ContentManager(Path("game/assets"))
    content.load()
    frame = content.ships.get(frame_id)
    ship = Ship(frame)
    ship.resources.cubits = cubits
    store.bind_ship(ship)
    return ship


def test_store_purchase_updates_inventory_and_currency() -> None:
    ship = _make_ship()
    starting_cubits = ship.resources.cubits
    result = store.buy("light_drive_overcharger")
    assert result["success"] is True
    assert ship.resources.cubits == pytest.approx(starting_cubits - 5_000)
    preview = fitting.preview_with("light_drive_overcharger")
    assert preview["current"]["max_speed"] == pytest.approx(ship.stats.max_speed + 1.25)


def test_store_purchase_adds_item_to_hold() -> None:
    ship = _make_ship()
    result = store.buy("strike_composite_plating")
    assert result["success"] is True
    assert ship.hold_items["strike_composite_plating"] == 1


def test_store_purchase_respects_hold_capacity() -> None:
    ship = _make_ship()
    assert ship.add_hold_item("strike_composite_plating", ship.hold_capacity)
    store.bind_ship(ship)
    result = store.buy("light_drive_overcharger")
    assert result["success"] is False
    assert "Hold is full" in str(result["error"])  # type: ignore[index]


@pytest.mark.parametrize(
    "item_id,expected",
    [
        (
            "strike_composite_plating",
            {"hull_hp": 22.5, "armor": 2.25, "acceleration": -0.3, "turn_accel": -0.75},
        ),
        (
            "strike_hull_plating",
            {"hull_hp": 45.0, "acceleration": -0.2, "turn_accel": -1.0},
        ),
        (
            "strike_armor_plating",
            {"armor": 4.5, "acceleration": -0.4, "turn_accel": -0.5},
        ),
        (
            "strike_ht_plating",
            {"critical_defense": 7.5},
        ),
        (
            "strike_ht_hull_plating",
            {"critical_defense": 2.5, "hull_hp": 30.0, "acceleration": -0.13, "turn_accel": -0.67},
        ),
        (
            "strike_ht_armor_plating",
            {"armor": 3.0, "critical_defense": 2.5, "acceleration": -0.27, "turn_accel": -0.33},
        ),
        (
            "strike_ht_composite_plating",
            {
                "armor": 1.8,
                "critical_defense": 1.5,
                "hull_hp": 18.0,
                "acceleration": -0.24,
                "turn_accel": -0.6,
            },
        ),
    ],
)
def test_hull_module_preview_deltas(item_id: str, expected: dict[str, float]) -> None:
    ship = _make_ship()
    preview = fitting.preview_with(item_id)
    deltas = preview["deltas_by_stat"]
    for key, value in expected.items():
        assert deltas[key] == pytest.approx(value)


@pytest.mark.parametrize(
    "item_id,frame_id,expected",
    [
        (
            "light_drive_overcharger",
            "viper_mk_vii",
            {"max_speed": 1.25, "boost_speed": 1.25},
        ),
        (
            "light_turbo_boosters",
            "viper_mk_vii",
            {"acceleration": 1.0, "boost_speed": 2.5},
        ),
        (
            "light_gyro_stabilization",
            "viper_mk_vii",
            {"turn_rate": 2.5, "turn_accel": 2.5},
        ),
        (
            "light_rcs_ducting",
            "viper_mk_vii",
            {"avoidance_rating": 15.0},
        ),
        (
            "t8_drive_turbo_charger",
            "raven_mk_vi_r",
            lambda ship: {
                "max_speed": ship.stats.max_speed * 0.03,
                "boost_speed": ship.stats.boost_speed * 0.04,
            },
        ),
        (
            "fog_gyro_stabilization",
            "raven_mk_vi_r",
            lambda ship: {
                "turn_rate": ship.stats.turn_rate * 0.10,
                "turn_accel": ship.stats.turn_accel * 0.10,
            },
        ),
        (
            "translation_rcs_thrusters",
            "raven_mk_vi_r",
            lambda ship: {
                "turn_rate": ship.stats.turn_rate * 0.10,
                "strafe_speed": ship.stats.strafe_speed * 0.15,
            },
        ),
        (
            "t15_pulsed_plasma_thruster",
            "raven_mk_vi_r",
            lambda ship: {
                "boost_speed": ship.stats.boost_speed * 0.06,
                "acceleration": ship.stats.acceleration * 0.20,
                "boost_cost": ship.stats.boost_cost * 0.25,
            },
        ),
        (
            "coupled_rcs_ducting",
            "raven_mk_vi_r",
            lambda ship: {
                "avoidance_rating": ship.stats.avoidance_rating * 0.04,
                "boost_speed": ship.stats.boost_speed * -0.025,
            },
        ),
        (
            "fbs_12_engine_overload",
            "rhino_strike",
            lambda ship: {
                "boost_cost": ship.stats.boost_cost * 2.0,
            },
        ),
    ],
)
def test_engine_module_preview_deltas(
    item_id: str, frame_id: str, expected: ExpectedEngineDelta
) -> None:
    ship = _make_ship(frame_id)
    preview = fitting.preview_with(item_id)
    deltas = preview["deltas_by_stat"]
    expected_values = expected(ship) if callable(expected) else expected
    for key, value in expected_values.items():
        assert deltas[key] == pytest.approx(value)


def test_light_rcs_ducting_updates_avoidance() -> None:
    ship = _make_ship()
    preview = fitting.preview_with("light_rcs_ducting")
    deltas = preview["deltas_by_stat"]
    assert deltas["avoidance_rating"] == pytest.approx(15.0)
    current = preview["current"]["avoidance"]
    future = preview["preview"]["avoidance"]
    assert future - current == pytest.approx(0.015)


def test_strike_store_filters_to_strike_items() -> None:
    ship = _make_ship("viper_mk_vii")
    filters = StoreFilters(sort_by="name")
    items = store.list_items(filters)
    assert {card.item.ship_class for card in items} == {"Strike"}
    assert any(card.item.id == "mec_a6" for card in items)


def test_store_filters_for_escort_ship() -> None:
    ship = _make_ship("glaive_command")
    filters = StoreFilters(sort_by="name")
    items = store.list_items(filters)
    classes = {card.item.ship_class for card in items}
    assert classes == {"Escort"}
    assert any(card.item.id == "mec_e12" for card in items)


def test_filtering_returns_only_matching_slot() -> None:
    ship = _make_ship()
    filters = StoreFilters(slot_families=("engine",), sort_by="name", descending=False)
    items = store.list_items(filters)
    assert all(card.item.slot_family == "engine" for card in items)


def test_ship_percent_modules_modify_stats() -> None:
    content = ContentManager(Path("game/assets"))
    content.load()
    frame = content.ships.get("raven_mk_vi_r")
    ship = Ship(frame)
    base_speed = ship.stats.max_speed
    base_boost = ship.stats.boost_speed
    base_cost = ship.stats.boost_cost
    module = ItemData(
        id="test_percent_module",
        slot_type="engine",
        name="Test Percent Module",
        tags=[],
        stats={
            "max_speed_percent": 10.0,
            "boost_speed_percent": 5.0,
            "boost_cost_percent": 20.0,
        },
    )
    assert ship.equip_module(module)
    assert ship.stats.max_speed == pytest.approx(base_speed * 1.10)
    assert ship.stats.boost_speed == pytest.approx(base_boost * 1.05)
    assert ship.stats.boost_cost == pytest.approx(base_cost * 1.20)
