import json
from pathlib import Path

from game.render.ship_miniatures import DEFAULT_MINIATURE, SHIP_MINIATURES, get_ship_miniature


def test_all_exemplar_frames_have_custom_miniatures():
    fixtures = Path("game/assets/data/ships/exemplars.json")
    data = json.loads(fixtures.read_text())
    for entry in data:
        miniature = get_ship_miniature(entry["id"])
        assert miniature is not DEFAULT_MINIATURE
        assert len(miniature.outline) >= 3


def test_all_miniature_coordinates_are_normalized():
    for miniature in SHIP_MINIATURES.values():
        for x, z in miniature.outline:
            assert -1.05 <= x <= 1.05
            assert -1.05 <= z <= 1.05
        for line in miniature.detail_lines:
            for x, z in line:
                assert -1.05 <= x <= 1.05
                assert -1.05 <= z <= 1.05
        for x, z in miniature.engine_points:
            assert -1.05 <= x <= 1.05
            assert -1.05 <= z <= 1.05


def test_unknown_frame_uses_default_miniature():
    miniature = get_ship_miniature("unknown_frame")
    assert miniature is DEFAULT_MINIATURE
