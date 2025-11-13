from pathlib import Path

import pytest

from game.assets.content import ContentManager
from game.ships.ship import Ship
from game.ui.strike_store import StoreFilters, fitting, store


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
            "strike_ablative_lattice",
            {"armor": 6.0, "hull_hp": 10.0, "acceleration": -0.5, "turn_accel": -0.3},
        ),
        (
            "strike_bulkhead_reinforcement",
            {"hull_hp": 70.0, "acceleration": -0.3, "turn_accel": -1.2},
        ),
        (
            "strike_reactive_plating",
            {"armor": 3.0, "avoidance_rating": 5.0, "acceleration": -0.2},
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
    "item_id,expected",
    [
        (
            "light_drive_overcharger",
            {"max_speed": 1.25, "boost_speed": 1.25},
        ),
        (
            "light_turbo_boosters",
            {"acceleration": 1.0, "boost_speed": 2.5},
        ),
        (
            "light_gyro_stabilization",
            {"turn_rate": 2.5, "turn_accel": 2.5},
        ),
        (
            "light_afterburn_coupling",
            {"max_speed": 0.5, "boost_speed": 3.5, "acceleration": 0.5},
        ),
        (
            "light_vectoring_nozzles",
            {"turn_rate": 3.5, "turn_accel": 3.0, "acceleration": -0.2},
        ),
        (
            "light_inertial_dampeners",
            {"acceleration": 1.5, "turn_accel": 1.0, "max_speed": -0.5},
        ),
        (
            "light_ecm_weave",
            {"avoidance_rating": 12.0, "turn_rate": 1.0},
        ),
    ],
)
def test_engine_module_preview_deltas(item_id: str, expected: dict[str, float]) -> None:
    ship = _make_ship()
    preview = fitting.preview_with(item_id)
    deltas = preview["deltas_by_stat"]
    for key, value in expected.items():
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
    assert any(card.item.id == "mel_n2" for card in items)


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
