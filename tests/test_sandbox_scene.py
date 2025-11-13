from pathlib import Path

import pygame

from game.assets.content import ContentManager
from game.engine.logger import GameLogger, LoggerConfig
import game.ui.sandbox_scene as sandbox_module
from game.ships.ship import Ship
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


class _StubHUD:
    def __init__(self) -> None:
        self._surface_size = (0, 0)

    def set_surface(self, surface) -> None:  # pragma: no cover - simple stub
        if surface:
            self._surface_size = surface.get_size()
        else:
            self._surface_size = (0, 0)

    def draw(self, *args, **kwargs) -> None:  # pragma: no cover - simple stub
        pass

    def draw_cursor_indicator(self, *args, **kwargs) -> None:  # pragma: no cover - simple stub
        pass

    @property
    def surface_size(self) -> tuple[int, int]:
        return self._surface_size


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
    monkeypatch.setattr(sandbox_module, "HUD", lambda *_: _StubHUD())
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


def test_strike_npcs_mirror_player_loadout(monkeypatch):
    content = ContentManager(Path("game/assets"))
    content.load()
    logger = GameLogger(LoggerConfig(level=0, channels={}))

    surface = _DummySurface((1280, 720))
    monkeypatch.setattr(pygame.display, "get_surface", lambda: surface)
    monkeypatch.setattr(pygame.display, "get_window_size", surface.get_size)
    monkeypatch.setattr(pygame.mouse, "set_visible", lambda *_: None)
    monkeypatch.setattr(pygame.mouse, "get_pos", lambda: (0, 0))
    monkeypatch.setattr(pygame.event, "set_grab", lambda *_: None)
    monkeypatch.setattr(sandbox_module, "HUD", lambda *_: _StubHUD())
    monkeypatch.setattr(sandbox_module, "VectorRenderer", lambda *_: object())
    monkeypatch.setattr(sandbox_module, "SectorMapView", lambda *_: object())
    monkeypatch.setattr(sandbox_module, "ShipInfoPanel", lambda *_: object())
    monkeypatch.setattr(sandbox_module, "HangarView", lambda *_: object())

    original_apply_default = Ship.apply_default_loadout
    call_count = {"value": 0}

    def _custom_default(self: Ship, manager: ContentManager) -> None:
        original_apply_default(self, manager)
        call_count["value"] += 1
        if call_count["value"] == 1:
            # Replace the default ECCM with a Jammer on the player's ship
            while self.modules_by_slot["computer"]:
                self.unequip_module("computer", 0)
            jammer = manager.items.get("jammer_mk1")
            self.equip_module(jammer)
            # Swap the centre cannon to a different model
            self.assign_weapon("hp_viper_center", "mec_a8")

    monkeypatch.setattr(Ship, "apply_default_loadout", _custom_default)

    scene = SandboxScene(None)
    scene.on_enter(content=content, input=None, logger=logger)

    assert scene.player is not None
    player = scene.player
    player_center = next(
        (mount.weapon_id for mount in player.mounts if mount.hardpoint.id == "hp_viper_center"),
        None,
    )
    assert player_center == "mec_a8"
    player_computers = [module.id for module in player.modules_by_slot["computer"]]
    assert player_computers == ["jammer_mk1"]

    strike_npcs = [
        ship
        for ship in scene.world.ships
        if ship is not player and ship.frame.size.lower() == "strike"
    ]
    assert strike_npcs

    for ship in strike_npcs:
        centre_weapon = next(
            (mount.weapon_id for mount in ship.mounts if mount.hardpoint.id == "hp_viper_center"),
            None,
        )
        computer_modules = [module.id for module in ship.modules_by_slot["computer"]]
        assert centre_weapon == player_center
        assert computer_modules == player_computers
