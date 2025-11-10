"""Interior scene shown when the player docks at an Outpost."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pygame
from pygame.math import Vector3

from game.assets.content import ContentManager
from game.engine.input import InputMapper
from game.engine.logger import GameLogger
from game.engine.scene import Scene
from game.ships.ship import Ship, ShipControlState
from game.ui.hangar import HangarView
from game.world.space import SpaceWorld
from game.world.station import DockingStation


@dataclass
class _SceneContext:
    content: ContentManager
    input: InputMapper
    logger: GameLogger
    world: SpaceWorld
    player: Ship
    station: DockingStation
    distance: float


class OutpostInteriorScene(Scene):
    """Represents the Outpost hangar interior instance."""

    def __init__(self, manager) -> None:
        super().__init__(manager)
        self.content: Optional[ContentManager] = None
        self.input: Optional[InputMapper] = None
        self.logger: Optional[GameLogger] = None
        self.world: Optional[SpaceWorld] = None
        self.player: Optional[Ship] = None
        self.station: Optional[DockingStation] = None
        self.distance: float = 0.0
        self.hangar_view: Optional[HangarView] = None
        self.status_font: Optional[pygame.font.Font] = None

    def on_enter(self, **kwargs) -> None:
        context = _SceneContext(
            content=kwargs["content"],
            input=kwargs["input"],
            logger=kwargs["logger"],
            world=kwargs["world"],
            player=kwargs["player"],
            station=kwargs["station"],
            distance=float(kwargs.get("distance", 0.0)),
        )
        self.content = context.content
        self.input = context.input
        self.logger = context.logger
        self.world = context.world
        self.player = context.player
        self.station = context.station
        self.distance = context.distance
        surface = pygame.display.get_surface()
        self.hangar_view = HangarView(surface, self.content)
        self.status_font = pygame.font.SysFont("consolas", 20)
        pygame.mouse.set_visible(True)
        pygame.event.set_grab(False)

    def handle_event(self, event: pygame.event.Event) -> None:
        if self.input:
            self.input.handle_event(event)
        if self.hangar_view and self.hangar_view.handle_event(event):
            return
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            self._undock()

    def update(self, dt: float) -> None:
        if self.input and (self.input.consume_action("open_hangar") or self.input.consume_action("dock_explore")):
            self._undock()
            return
        if self.hangar_view:
            self.hangar_view.update(dt)

    def render(self, surface: pygame.Surface, alpha: float) -> None:
        if not self.hangar_view or not self.player or not self.station:
            surface.fill((0, 0, 0))
            return
        self.hangar_view.set_surface(surface)
        self.hangar_view.draw(surface, self.player, self.station, 0.0)
        if self.status_font:
            message = self.status_font.render("Press H to undock", True, (220, 236, 250))
            surface.blit(
                message,
                (
                    surface.get_width() // 2 - message.get_width() // 2,
                    int(surface.get_height() * 0.88),
                ),
            )

    def _undock(self) -> None:
        if not self.world or not self.player or not self.station:
            self.manager.activate("sandbox", content=self.content, input=self.input, logger=self.logger)
            return
        station_pos = Vector3(*self.station.position)
        exit_offset = Vector3(0.0, 0.0, max(360.0, self.station.docking_radius * 0.6))
        self.player.kinematics.position = station_pos + exit_offset
        self.player.kinematics.velocity = Vector3()
        self.player.kinematics.angular_velocity = Vector3()
        self.player.kinematics.rotation = Vector3(0.0, 0.0, 0.0)
        self.player.control = ShipControlState()
        self.player.target_id = None
        self.world.add_ship(self.player)
        self.manager.activate(
            "sandbox",
            content=self.content,
            input=self.input,
            logger=self.logger,
            world=self.world,
            player=self.player,
        )


__all__ = ["OutpostInteriorScene"]
