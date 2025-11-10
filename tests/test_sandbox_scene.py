import pygame

from game.ui.sandbox_scene import SandboxScene


class _DummySurface:
    def __init__(self, size: tuple[int, int], flags: int = 0) -> None:
        self._size = size
        self._flags = flags

    def get_size(self) -> tuple[int, int]:
        return self._size

    def get_flags(self) -> int:
        return self._flags


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
