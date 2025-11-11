from pathlib import Path

import pygame

from game.assets.content import ContentManager
from game.engine.logger import GameLogger, LoggerConfig
import game.ui.sandbox_scene as sandbox_module
from game.ui.sandbox_scene import SandboxScene


class _DummySurface:
    def __init__(self, size: tuple[int, int], flags: int = 0) -> None:
        self._size = size
        self._flags = flags

    def get_size(self) -> tuple[int, int]:
        return self._size

    def get_flags(self) -> int:
        return self._flags

    def get_width(self) -> int:
        return self._size[0]

    def get_height(self) -> int:
        return self._size[1]


def _make_scene() -> SandboxScene:
    return SandboxScene(None)


def test_surface_mouse_pos_handles_scaled_display(monkeypatch):
    scene = _make_scene()
    surface = _DummySurface((1280, 720), pygame.SCALED)
    monkeypatch.setattr(pygame.display, "get_surface", lambda: surface)
    monkeypatch.setattr(pygame.display, "get_window_size", lambda: (2560, 1440))

    # Window coordinates should be projected back to the logical surface space.
    assert scene._surface_mouse_pos((1280, 720)) == (640, 360)


def test_surface_mouse_pos_clamps_letterbox_regions(monkeypatch):
    scene = _make_scene()
    surface = _DummySurface((1280, 720))
    monkeypatch.setattr(pygame.display, "get_surface", lambda: surface)
    # Window height is taller than the logical surface, causing letterboxing.
    monkeypatch.setattr(pygame.display, "get_window_size", lambda: (1920, 1200))

    # A click inside the top letterbox should clamp to the nearest logical pixel.
    assert scene._surface_mouse_pos((960, 30)) == (640, 0)


def test_sandbox_scene_initializes_strike_npcs(monkeypatch):
    content = ContentManager(Path("game/assets"))
    content.load()
    logger = GameLogger(LoggerConfig(level=0, channels={}))

    surface = _DummySurface((1280, 720))
    monkeypatch.setattr(pygame.display, "get_surface", lambda: surface)
    monkeypatch.setattr(pygame.display, "get_window_size", surface.get_size)
    monkeypatch.setattr(pygame.mouse, "set_visible", lambda *_: None)
    monkeypatch.setattr(pygame.mouse, "get_pos", lambda: (0, 0))
    monkeypatch.setattr(pygame.event, "set_grab", lambda *_: None)
    monkeypatch.setattr(sandbox_module, "HUD", lambda *_: object())
    monkeypatch.setattr(sandbox_module, "VectorRenderer", lambda *_: object())
    monkeypatch.setattr(sandbox_module, "SectorMapView", lambda *_: object())
    monkeypatch.setattr(sandbox_module, "ShipInfoPanel", lambda *_: object())
    monkeypatch.setattr(sandbox_module, "HangarView", lambda *_: object())

    scene = SandboxScene(None)
    scene.on_enter(content=content, input=None, logger=logger)

    assert scene.world is not None
    assert scene.player is not None

    npc_ships = [ship for ship in scene.world.ships if ship is not scene.player]
    assert npc_ships

    outposts = [ship for ship in npc_ships if ship.frame.size.lower() == "outpost"]
    non_strike = [
        ship
        for ship in npc_ships
        if ship.frame.size.lower() not in {"outpost", "strike"}
    ]

    assert outposts, "Expected sandbox setup to include Outposts"
    assert not non_strike, "NPCs should only field Strike-class hulls"
