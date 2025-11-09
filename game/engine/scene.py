"""Scene management utilities."""
from __future__ import annotations

from typing import Dict, Optional, Type

import pygame


class Scene:
    """Base scene interface."""

    def __init__(self, manager: "SceneManager") -> None:
        self.manager = manager

    def on_enter(self, **kwargs) -> None:  # pragma: no cover - hooks
        pass

    def on_exit(self) -> None:  # pragma: no cover - hooks
        pass

    def handle_event(self, event: pygame.event.Event) -> None:
        pass

    def update(self, dt: float) -> None:
        pass

    def render(self, surface: pygame.Surface, alpha: float) -> None:
        pass


class SceneManager:
    """Registers and swaps scenes."""

    def __init__(self) -> None:
        self._scenes: Dict[str, Type[Scene]] = {}
        self._active: Optional[Scene] = None
        self._active_name: Optional[str] = None
        self.context: Dict[str, object] = {}

    def register(self, name: str, scene_cls: Type[Scene]) -> None:
        self._scenes[name] = scene_cls

    def activate(self, name: str, **kwargs) -> None:
        if name not in self._scenes:
            raise KeyError(f"Scene '{name}' is not registered")
        if self._active:
            self._active.on_exit()
        self._active = self._scenes[name](self)
        self._active_name = name
        context = {**self.context, **kwargs}
        self._active.on_enter(**context)

    def set_context(self, **kwargs) -> None:
        self.context.update(kwargs)

    def active(self) -> Optional[Scene]:
        return self._active

    def handle_event(self, event: pygame.event.Event) -> None:
        if self._active:
            self._active.handle_event(event)

    def update(self, dt: float) -> None:
        if self._active:
            self._active.update(dt)

    def render(self, surface: pygame.Surface, alpha: float) -> None:
        if self._active:
            self._active.render(surface, alpha)


__all__ = ["Scene", "SceneManager"]
