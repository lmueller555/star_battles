"""Title screen scene."""
from __future__ import annotations

import pygame

from game.engine.scene import Scene


class TitleScene(Scene):
    def __init__(self, manager) -> None:
        super().__init__(manager)
        self.font = None

    def on_enter(self, **kwargs) -> None:
        self.font = pygame.font.SysFont("consolas", 32)

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_q:
                pygame.event.post(pygame.event.Event(pygame.QUIT))
            else:
                self.manager.activate("ship_selection")

    def render(self, surface: pygame.Surface, alpha: float) -> None:
        surface.fill((0, 0, 0))
        title = self.font.render("STAR BATTLES VECTOR PROTOTYPE", True, (200, 240, 255))
        prompt = self.font.render("Press any key to launch", True, (180, 200, 220))
        surface.blit(title, (surface.get_width() / 2 - title.get_width() / 2, surface.get_height() / 2 - 100))
        surface.blit(prompt, (surface.get_width() / 2 - prompt.get_width() / 2, surface.get_height() / 2))


__all__ = ["TitleScene"]
