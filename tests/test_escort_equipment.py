import pytest

from game.ui import equipment_data


def _get_item(item_id: str):
    for item in equipment_data.EQUIPMENT_ITEMS:
        if item["id"] == item_id:
            return item
    raise AssertionError(f"Equipment {item_id!r} not found")


def _assert_stats(item, expected_stats):
    stats = item["stats"]
    for key, expected in expected_stats.items():
        assert stats.get(key) == pytest.approx(expected), f"{item['id']} field {key}"


def test_mec_e12_matches_guidance():
    item = _get_item("mec_e12")
    assert item["ship_class"] == "Escort"
    assert item["price"] == 15_000
    assert item["durability"] == 7_500
    assert item["upgrades"] == ("damage", "optimal_range")
    _assert_stats(
        item,
        {
            "damage_min": 10.0,
            "damage_max": 25.0,
            "armor_piercing": 15.0,
            "range_min": 0.0,
            "range_max": 1_150.0,
            "optimal_range": 450.0,
            "accuracy": 335.0,
            "critical_offense": 100.0,
            "reload": 1.5,
            "power": 6.0,
            "firing_arc": 180.0,
        },
    )


def test_mec_e13_matches_guidance():
    item = _get_item("mec_e13")
    assert item["ship_class"] == "Escort"
    assert item["price"] == 15_000
    assert item["durability"] == 7_500
    assert item["upgrades"] == ("damage", "optimal_range")
    _assert_stats(
        item,
        {
            "damage_min": 10.0,
            "damage_max": 25.0,
            "armor_piercing": 15.0,
            "range_min": 0.0,
            "range_max": 900.0,
            "optimal_range": 350.0,
            "accuracy": 335.0,
            "critical_offense": 100.0,
            "reload": 1.2,
            "power": 6.0,
            "firing_arc": 180.0,
        },
    )


def test_mec_e17_matches_guidance():
    item = _get_item("mec_e17")
    assert item["ship_class"] == "Escort"
    assert item["price"] == 15_000
    assert item["durability"] == 7_500
    assert item["upgrades"] == ("damage", "optimal_range")
    _assert_stats(
        item,
        {
            "damage_min": 10.0,
            "damage_max": 25.0,
            "armor_piercing": 15.0,
            "range_min": 0.0,
            "range_max": 1_350.0,
            "optimal_range": 550.0,
            "accuracy": 335.0,
            "critical_offense": 100.0,
            "reload": 1.8,
            "power": 6.0,
            "firing_arc": 180.0,
        },
    )


def test_hd_m50p_matches_guidance():
    item = _get_item("hd_m50p")
    assert item["ship_class"] == "Escort"
    assert item["price"] == 15_000
    assert item["durability"] == 7_500
    assert item["upgrades"] == ("damage", "critical_offense")
    _assert_stats(
        item,
        {
            "damage_min": 40.0,
            "damage_max": 100.0,
            "armor_piercing": 25.0,
            "range_min": 200.0,
            "range_max": 1_350.0,
            "optimal_range": 850.0,
            "accuracy": 335.0,
            "critical_offense": 100.0,
            "reload": 12.5,
            "power": 50.0,
            "firing_arc": 180.0,
            "turn_speed": 75.0,
            "projectile_speed": 100.0,
        },
    )


def test_hd_m63_matches_guidance():
    item = _get_item("hd_m63")
    assert item["ship_class"] == "Escort"
    assert item["price"] == 15_000
    assert item["durability"] == 7_500
    assert item["upgrades"] == ("damage", "range")
    _assert_stats(
        item,
        {
            "damage_min": 40.0,
            "damage_max": 100.0,
            "armor_piercing": 25.0,
            "range_min": 200.0,
            "range_max": 1_600.0,
            "optimal_range": 900.0,
            "accuracy": 335.0,
            "critical_offense": 100.0,
            "reload": 15.0,
            "power": 50.0,
            "firing_arc": 180.0,
            "turn_speed": 75.0,
            "projectile_speed": 100.0,
        },
    )


def test_hd_m63p_matches_guidance():
    item = _get_item("hd_m63p")
    assert item["ship_class"] == "Escort"
    assert item["price"] == 15_000
    assert item["durability"] == 7_500
    assert item["upgrades"] == ("damage", "critical_offense")
    _assert_stats(
        item,
        {
            "damage_min": 40.0,
            "damage_max": 100.0,
            "armor_piercing": 25.0,
            "range_min": 200.0,
            "range_max": 1_600.0,
            "optimal_range": 900.0,
            "accuracy": 335.0,
            "critical_offense": 100.0,
            "reload": 15.0,
            "power": 50.0,
            "firing_arc": 180.0,
            "turn_speed": 75.0,
            "projectile_speed": 100.0,
        },
    )
