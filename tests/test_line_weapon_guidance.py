from __future__ import annotations

import json
from pathlib import Path

import pytest

from game.combat.weapons import GUIDANCE_ACCURACY_SCALE, WeaponDatabase


@pytest.fixture(scope="module")
def _line_guidance_data() -> dict[str, dict]:
    data_path = Path(__file__).resolve().parents[1] / "game" / "assets" / "data" / "weapons" / "weapons.json"
    guidance_entries = json.loads(data_path.read_text())
    return {entry["id"]: entry for entry in guidance_entries if entry["id"].startswith("mec_l3") or entry["id"].startswith("hd_h4")}


@pytest.fixture(scope="module")
def _line_weapons() -> dict[str, object]:
    data_dir = Path(__file__).resolve().parents[1] / "game" / "assets" / "data" / "weapons"
    db = WeaponDatabase()
    db.load_directory(data_dir)
    ids = ("mec_l31", "mec_l34", "mec_l35", "hd_h40", "mec_l39f", "mec_l30p", "hd_h48")
    return {weapon_id: db.get(weapon_id) for weapon_id in ids}


@pytest.mark.parametrize(
    "weapon_id",
    ("mec_l31", "mec_l34", "mec_l35", "hd_h40", "mec_l39f", "mec_l30p", "hd_h48"),
)
def test_line_weapon_damage_alignment(weapon_id: str, _line_weapons, _line_guidance_data) -> None:
    guidance = _line_guidance_data[weapon_id]
    weapon = _line_weapons[weapon_id]
    expected_min = guidance.get("damageMin", guidance.get("damage", weapon.damage_min))
    expected_max = guidance.get("damageMax", guidance.get("damage", weapon.damage_max))
    assert weapon.damage_min == pytest.approx(expected_min)
    assert weapon.damage_max == pytest.approx(expected_max)


@pytest.mark.parametrize(
    "weapon_id",
    ("mec_l31", "mec_l34", "mec_l35", "hd_h40", "mec_l39f", "mec_l30p", "hd_h48"),
)
def test_line_weapon_accuracy_alignment(weapon_id: str, _line_weapons, _line_guidance_data) -> None:
    guidance = _line_guidance_data[weapon_id]
    weapon = _line_weapons[weapon_id]
    expected_accuracy = min(1.0, guidance["accuracyRating"] / GUIDANCE_ACCURACY_SCALE)
    assert weapon.base_accuracy == pytest.approx(expected_accuracy)


@pytest.mark.parametrize(
    "weapon_id",
    ("mec_l31", "mec_l34", "mec_l35", "hd_h40", "mec_l39f", "mec_l30p", "hd_h48"),
)
def test_line_weapon_power_alignment(weapon_id: str, _line_weapons, _line_guidance_data) -> None:
    guidance = _line_guidance_data[weapon_id]
    weapon = _line_weapons[weapon_id]
    expected_power = guidance.get("power", guidance["powerCost"])
    assert weapon.power_cost == pytest.approx(expected_power)


@pytest.mark.parametrize(
    "weapon_id",
    ("mec_l31", "mec_l34", "mec_l35", "hd_h40", "mec_l39f", "mec_l30p", "hd_h48"),
)
def test_line_weapon_firing_arc_alignment(weapon_id: str, _line_weapons, _line_guidance_data) -> None:
    guidance = _line_guidance_data[weapon_id]
    weapon = _line_weapons[weapon_id]
    assert weapon.gimbal == pytest.approx(guidance["firingArc"])
