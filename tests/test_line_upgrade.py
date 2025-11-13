from __future__ import annotations

import pytest

from game.ui.equipment_upgrade import EQUIPMENT_UPGRADE_SPECS, EquipmentUpgradeModel


def _resources() -> dict[str, float]:
    return {"tylium": 1_000_000.0, "cubits": 0.0, "merits": 0.0, "tuning_kits": 0.0}


def _skills() -> dict[str, int]:
    return {"Gunnery": 3}


EXPECTED_LINE_UPGRADES = {
    "mec_l31": {"damage_min": 84.0, "damage_max": 168.0, "optimal_range": 1_200.0},
    "mec_l34": {"damage_min": 84.0, "damage_max": 168.0, "optimal_range": 900.0},
    "mec_l35": {"damage_min": 84.0, "damage_max": 168.0, "optimal_range": 1_400.0},
    "hd_h40": {"damage_min": 132.0, "damage_max": 360.0, "range_max": 2_200.0},
    "mec_l39f": {"damage_min": 2.4, "damage_max": 84.0, "range_max": 1_120.0},
    "mec_l30p": {"damage_min": 2.4, "damage_max": 12.0, "range_max": 900.0},
    "hd_h48": {"damage_min": 132.0, "damage_max": 360.0, "range_max": 2_600.0},
}


@pytest.mark.parametrize("item_id", sorted(EXPECTED_LINE_UPGRADES))
def test_line_weapon_upgrade_curves(item_id: str) -> None:
    spec = EQUIPMENT_UPGRADE_SPECS[item_id]
    model = EquipmentUpgradeModel(spec, current_level=1, player_resources=_resources(), player_skills=_skills())
    for stat, expected in EXPECTED_LINE_UPGRADES[item_id].items():
        value, known = model.stat_value(stat, 15)
        assert known, f"{item_id} {stat} value not known"
        assert value == pytest.approx(expected)
