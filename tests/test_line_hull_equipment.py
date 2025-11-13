from pathlib import Path

import pytest

from game.assets.content import ContentManager
from game.ships.ship import Ship
from game.ui.equipment_data import EQUIPMENT_ITEMS
from game.ui.equipment_upgrade import EQUIPMENT_UPGRADE_SPECS
from game.ui.strike_store import StoreFilters, fitting, store


def _line_items() -> dict[str, dict]:
    return {
        item["id"]: item
        for item in EQUIPMENT_ITEMS
        if item["ship_class"] == "Line" and item["slot_family"] == "hull"
    }


def _make_line_ship(*, cubits: float = 50_000.0) -> Ship:
    content = ContentManager(Path("game/assets"))
    content.load()
    frame = content.ships.get("vanir_command")
    ship = Ship(frame)
    ship.resources.cubits = cubits
    store.bind_ship(ship)
    return ship


EXPECTED_LINE_HULL_ITEMS = {
    "line_hull_plating": {
        "price": 16_000,
        "durability": 42_000,
        "upgrades": ("hull_hp",),
        "stats": {"hull_hp": 350.0, "acceleration": -0.05, "turn_accel": -0.2},
    },
    "line_armor_plating": {
        "price": 16_000,
        "durability": 42_000,
        "upgrades": ("armor",),
        "stats": {"armor": 3.5, "acceleration": -0.1, "turn_accel": -0.1},
    },
    "line_ht_plating": {
        "price": 16_000,
        "durability": 42_000,
        "upgrades": ("critical_defense",),
        "stats": {"critical_defense": 7.5},
    },
    "line_composite_plating": {
        "price": 16_000,
        "durability": 42_000,
        "upgrades": ("armor", "hull_hp"),
        "stats": {
            "armor": 1.75,
            "hull_hp": 175.0,
            "acceleration": -0.08,
            "turn_accel": -0.15,
        },
    },
    "line_ht_hull_plating": {
        "price": 16_000,
        "durability": 42_000,
        "upgrades": ("critical_defense", "hull_hp"),
        "stats": {
            "critical_defense": 2.5,
            "hull_hp": pytest.approx(233.33333333333334),
            "acceleration": -0.03,
            "turn_accel": -0.13,
        },
    },
    "line_ht_armor_plating": {
        "price": 16_000,
        "durability": 42_000,
        "upgrades": ("armor", "critical_defense"),
        "stats": {
            "armor": pytest.approx(2.3333333333333335),
            "critical_defense": 2.5,
            "acceleration": -0.07,
            "turn_accel": -0.07,
        },
    },
    "line_ht_composite_plating": {
        "price": 16_000,
        "durability": 42_000,
        "upgrades": ("armor", "critical_defense", "hull_hp"),
        "stats": {
            "armor": 1.4,
            "critical_defense": 1.5,
            "hull_hp": 140.0,
            "acceleration": -0.05,
            "turn_accel": -0.1,
        },
    },
}


def test_line_hull_equipment_data_matches_guidance() -> None:
    index = _line_items()
    assert set(index) == set(EXPECTED_LINE_HULL_ITEMS)
    for item_id, expected in EXPECTED_LINE_HULL_ITEMS.items():
        item = index[item_id]
        assert item["price"] == expected["price"]
        assert item["durability"] == expected["durability"]
        assert item["upgrades"] == expected["upgrades"]
        for key, value in expected["stats"].items():
            assert item["stats"][key] == pytest.approx(value)


def test_line_store_lists_line_hull_modules_for_line_ships() -> None:
    _make_line_ship()
    cards = store.list_items(StoreFilters(sort_by="name"))
    hull_ids = {card.item.id for card in cards if card.item.slot_family == "hull"}
    assert set(EXPECTED_LINE_HULL_ITEMS) <= hull_ids
    assert all(
        card.item.ship_class == "Line"
        for card in cards
        if card.item.slot_family == "hull"
    )


@pytest.mark.parametrize(
    "item_id, expected",
    [
        ("line_hull_plating", {"hull_hp": 350.0, "acceleration": -0.05, "turn_accel": -0.2}),
        ("line_armor_plating", {"armor": 3.5, "acceleration": -0.1, "turn_accel": -0.1}),
        ("line_ht_plating", {"critical_defense": 7.5}),
        (
            "line_composite_plating",
            {"armor": 1.75, "hull_hp": 175.0, "acceleration": -0.08, "turn_accel": -0.15},
        ),
        (
            "line_ht_hull_plating",
            {
                "critical_defense": 2.5,
                "hull_hp": pytest.approx(233.33333333333334),
                "acceleration": -0.03,
                "turn_accel": -0.13,
            },
        ),
        (
            "line_ht_armor_plating",
            {
                "armor": pytest.approx(2.3333333333333335),
                "critical_defense": 2.5,
                "acceleration": -0.07,
                "turn_accel": -0.07,
            },
        ),
        (
            "line_ht_composite_plating",
            {
                "armor": 1.4,
                "critical_defense": 1.5,
                "hull_hp": 140.0,
                "acceleration": -0.05,
                "turn_accel": -0.1,
            },
        ),
    ],
)
def test_line_hull_preview_deltas(item_id: str, expected: dict[str, float]) -> None:
    _make_line_ship()
    preview = fitting.preview_with(item_id)
    deltas = preview["deltas_by_stat"]
    for key, value in expected.items():
        assert deltas[key] == pytest.approx(value)


@pytest.mark.parametrize(
    "item_id, stat, level, expected",
    [
        ("line_hull_plating", "hull_hp", 1, 350.0),
        ("line_hull_plating", "hull_hp", 15, 840.0),
        ("line_armor_plating", "armor", 1, 3.5),
        ("line_armor_plating", "armor", 15, 8.4),
        ("line_ht_plating", "critical_defense", 1, 7.5),
        ("line_ht_plating", "critical_defense", 15, 18.0),
        ("line_composite_plating", "armor", 15, 4.2),
        ("line_composite_plating", "hull_hp", 15, 420.0),
        ("line_ht_hull_plating", "critical_defense", 15, 6.0),
        ("line_ht_hull_plating", "hull_hp", 15, 560.0),
        ("line_ht_armor_plating", "armor", 15, 5.6),
        ("line_ht_armor_plating", "critical_defense", 15, 6.0),
        ("line_ht_composite_plating", "armor", 15, 3.36),
        ("line_ht_composite_plating", "critical_defense", 15, 3.6),
        ("line_ht_composite_plating", "hull_hp", 15, 336.0),
    ],
)
def test_line_hull_upgrade_curves(item_id: str, stat: str, level: int, expected: float) -> None:
    curve = EQUIPMENT_UPGRADE_SPECS[item_id].curve_for(stat)
    assert curve is not None
    value = curve.value_for(level)
    assert value is not None
    assert value == pytest.approx(expected)

