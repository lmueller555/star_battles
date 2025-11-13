from __future__ import annotations

import pytest

from game.ui.equipment_data import EQUIPMENT_ITEMS


def _item_index() -> dict[str, dict[str, object]]:
    return {item["id"]: item for item in EQUIPMENT_ITEMS if item["ship_class"] == "Line"}


def _assert_stats(actual: dict[str, float], expected: dict[str, float]) -> None:
    for key, value in expected.items():
        assert key in actual, f"Missing stat {key}"
        assert actual[key] == pytest.approx(value), f"{key} mismatch"


EXPECTED_LINE_WEAPONS = {
    "mec_l31": {
        "price": 20_000,
        "durability": 17_500,
        "upgrades": ("damage", "optimal_range"),
        "stats": {
            "damage_min": 35.0,
            "damage_max": 70.0,
            "armor_piercing": 35.0,
            "range_min": 0.0,
            "range_max": 1_700.0,
            "optimal_range": 675.0,
            "accuracy": 125.0,
            "critical_offense": 100.0,
            "reload": 4.0,
            "power": 25.0,
            "firing_arc": 180.0,
        },
    },
    "mec_l34": {
        "price": 20_000,
        "durability": 17_500,
        "upgrades": ("damage", "optimal_range"),
        "stats": {
            "damage_min": 35.0,
            "damage_max": 70.0,
            "armor_piercing": 35.0,
            "range_min": 0.0,
            "range_max": 1_350.0,
            "optimal_range": 550.0,
            "accuracy": 125.0,
            "critical_offense": 100.0,
            "reload": 3.2,
            "power": 25.0,
            "firing_arc": 180.0,
        },
    },
    "mec_l35": {
        "price": 20_000,
        "durability": 17_500,
        "upgrades": ("damage", "optimal_range"),
        "stats": {
            "damage_min": 35.0,
            "damage_max": 70.0,
            "armor_piercing": 35.0,
            "range_min": 0.0,
            "range_max": 2_000.0,
            "optimal_range": 800.0,
            "accuracy": 125.0,
            "critical_offense": 100.0,
            "reload": 4.8,
            "power": 25.0,
            "firing_arc": 180.0,
        },
    },
    "hd_h40": {
        "price": 20_000,
        "durability": 17_500,
        "upgrades": ("damage", "range_max"),
        "stats": {
            "damage_min": 55.0,
            "damage_max": 150.0,
            "armor_piercing": 35.0,
            "range_min": 200.0,
            "range_max": 1_800.0,
            "optimal_range": 1_000.0,
            "accuracy": 125.0,
            "critical_offense": 100.0,
            "reload": 15.0,
            "power": 100.0,
            "firing_arc": 180.0,
            "turn_speed": 30.0,
            "projectile_speed": 80.0,
        },
    },
    "mec_l39f": {
        "price": 20_000,
        "durability": 17_500,
        "upgrades": ("damage", "range_max", "optimal_range"),
        "stats": {
            "damage_min": 1.0,
            "damage_max": 35.0,
            "armor_piercing": 15.0,
            "range_min": 500.0,
            "range_max": 800.0,
            "optimal_range": 800.0,
            "accuracy": 300.0,
            "critical_offense": 100.0,
            "reload": 1.0,
            "power": 7.0,
            "firing_arc": 180.0,
        },
    },
    "mec_l30p": {
        "price": 20_000,
        "durability": 17_500,
        "upgrades": ("damage", "range_max", "optimal_range"),
        "stats": {
            "damage_min": 1.0,
            "damage_max": 5.0,
            "armor_piercing": 5.0,
            "range_min": 0.0,
            "range_max": 540.0,
            "optimal_range": 400.0,
            "accuracy": 500.0,
            "critical_offense": 100.0,
            "reload": 0.5,
            "power": 3.5,
            "firing_arc": 180.0,
        },
    },
    "hd_h48": {
        "price": 20_000,
        "durability": 17_500,
        "upgrades": ("damage", "range_max"),
        "stats": {
            "damage_min": 55.0,
            "damage_max": 150.0,
            "armor_piercing": 35.0,
            "range_min": 200.0,
            "range_max": 2_000.0,
            "optimal_range": 1_200.0,
            "accuracy": 125.0,
            "critical_offense": 100.0,
            "reload": 18.0,
            "power": 100.0,
            "firing_arc": 180.0,
            "turn_speed": 30.0,
            "projectile_speed": 80.0,
        },
    },
}


@pytest.mark.parametrize("item_id", sorted(EXPECTED_LINE_WEAPONS))
def test_line_weapon_entries(item_id: str) -> None:
    index = _item_index()
    assert item_id in index
    item = index[item_id]
    expected = EXPECTED_LINE_WEAPONS[item_id]
    assert item["price"] == expected["price"]
    assert item["durability"] == expected["durability"]
    assert tuple(item["upgrades"]) == expected["upgrades"]
    _assert_stats(item["stats"], expected["stats"])
