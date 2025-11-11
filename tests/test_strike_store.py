from pathlib import Path

import pytest

from game.assets.content import ContentManager
from game.ships.ship import Ship
from game.ui.strike_store import StoreFilters, fitting, store


def _make_ship() -> Ship:
    content = ContentManager(Path("game/assets"))
    content.load()
    frame = content.ships.get("viper_mk_vii")
    ship = Ship(frame)
    ship.resources.cubits = 20000.0
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


def test_filtering_returns_only_matching_slot() -> None:
    ship = _make_ship()
    filters = StoreFilters(slot_families=("engine",), sort_by="name", descending=False)
    items = store.list_items(filters)
    assert all(card.item.slot_family == "engine" for card in items)
