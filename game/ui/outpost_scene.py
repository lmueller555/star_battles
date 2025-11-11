"""Interior scene shown when the player docks at an Outpost."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from enum import Enum, auto
from typing import Iterable, List, Optional, Tuple

import pygame
from pygame.math import Vector2, Vector3

from game.assets.content import ContentManager
from game.engine.input import InputMapper
from game.engine.logger import GameLogger
from game.engine.scene import Scene
from game.ships.ship import Ship, ShipControlState
from game.world.space import SpaceWorld
from game.world.station import DockingStation


class _InteriorState(Enum):
    DOCKING = auto()
    DISEMBARK = auto()
    EXPLORE = auto()


@dataclass
class _SceneContext:
    content: ContentManager
    input: InputMapper
    logger: GameLogger
    world: SpaceWorld
    player: Ship
    station: DockingStation
    distance: float


@dataclass
class _LightSource:
    position: Vector2
    radius: float
    pulse_speed: float
    intensity: float


class _InteriorLayout:
    """Utility used to carve the Outpost interior floorplan."""

    def __init__(self, cols: int, rows: int, tile_size: int) -> None:
        self.cols = cols
        self.rows = rows
        self.tile_size = tile_size
        self.walkable: List[List[bool]] = [[False for _ in range(cols)] for _ in range(rows)]
        self.rooms: List[pygame.Rect] = []
        self.floor_details: List[pygame.Rect] = []
        self.lights: List[_LightSource] = []
        self.spawn_point = Vector2()
        self._build()

    def _build(self) -> None:
        tile = self.tile_size
        # Primary hangar and connected chambers.
        hangar = pygame.Rect(2, 12, 20, 12)
        central_spine = pygame.Rect(20, 14, 12, 10)
        central_hub = pygame.Rect(30, 10, 14, 12)
        north_hall = pygame.Rect(30, 8, 14, 4)
        south_hall = pygame.Rect(30, 22, 14, 8)
        east_connector = pygame.Rect(40, 12, 6, 12)
        observation = pygame.Rect(44, 6, 10, 10)
        engineering = pygame.Rect(44, 18, 10, 10)
        upper_connector = pygame.Rect(36, 6, 12, 6)
        upper_access = pygame.Rect(40, 2, 8, 4)
        far_wing = pygame.Rect(44, 0, 10, 6)
        reactor = pygame.Rect(42, 26, 12, 6)
        atrium = pygame.Rect(32, 28, 16, 6)
        south_link = pygame.Rect(22, 24, 12, 6)
        south_galleria = pygame.Rect(12, 24, 14, 6)
        western_link = pygame.Rect(10, 8, 10, 8)
        north_link = pygame.Rect(16, 6, 10, 6)
        labs = pygame.Rect(16, 0, 10, 6)
        cargo = pygame.Rect(10, 0, 12, 8)
        connector_to_hub = pygame.Rect(24, 10, 6, 6)
        connector_to_labs = pygame.Rect(18, 4, 8, 4)

        rooms = [
            hangar,
            central_spine,
            central_hub,
            north_hall,
            south_hall,
            east_connector,
            observation,
            engineering,
            upper_connector,
            far_wing,
            reactor,
            atrium,
            south_link,
            south_galleria,
            western_link,
            north_link,
            labs,
            cargo,
            connector_to_hub,
            connector_to_labs,
            upper_access,
        ]

        for rect in rooms:
            self._carve(rect)
            self.rooms.append(rect)

        self.spawn_point = self._tile_center(8, 18)

        # Decorative floor strips to add visual depth.
        self.floor_details.extend(
            [
                pygame.Rect(
                    hangar.x * tile + int(tile * 0.9),
                    (hangar.y + idx * 2) * tile + int(tile * 0.25),
                    hangar.width * tile - int(tile * 1.8),
                    int(tile * 0.32),
                )
                for idx in range(4)
            ]
        )
        self.floor_details.extend(
            [
                pygame.Rect(
                    central_hub.x * tile + int(tile * 0.7),
                    central_hub.y * tile + int(tile * 0.5) + idx * int(tile * 1.1),
                    central_hub.width * tile - int(tile * 1.4),
                    int(tile * 0.2),
                )
                for idx in range(6)
            ]
        )

        # Area lights to add atmosphere along the walkways.
        light_tiles = [
            (10, 18),
            (16, 18),
            (22, 18),
            (30, 18),
            (35, 12),
            (36, 24),
            (45, 10),
            (46, 20),
            (24, 8),
            (14, 8),
            (20, 2),
            (42, 2),
        ]
        for x, y in light_tiles:
            self.lights.append(
                _LightSource(
                    position=self._tile_center(x, y),
                    radius=tile * 5.6,
                    pulse_speed=0.8 + (x + y) * 0.03,
                    intensity=0.6 + 0.1 * ((x * 17 + y * 13) % 3),
                )
            )

    def _carve(self, rect: pygame.Rect) -> None:
        for ty in range(rect.top, rect.bottom):
            if 0 <= ty < self.rows:
                for tx in range(rect.left, rect.right):
                    if 0 <= tx < self.cols:
                        self.walkable[ty][tx] = True

    def _tile_center(self, x: int, y: int) -> Vector2:
        return Vector2((x + 0.5) * self.tile_size, (y + 0.5) * self.tile_size)

    def world_rect(self, rect: pygame.Rect) -> pygame.Rect:
        return pygame.Rect(
            rect.x * self.tile_size,
            rect.y * self.tile_size,
            rect.width * self.tile_size,
            rect.height * self.tile_size,
        )

    def is_walkable_point(self, pos: Vector2) -> bool:
        tx = int(pos.x // self.tile_size)
        ty = int(pos.y // self.tile_size)
        if tx < 0 or ty < 0 or tx >= self.cols or ty >= self.rows:
            return False
        return self.walkable[ty][tx]

    def neighbors(self, tx: int, ty: int) -> Iterable[Tuple[int, int, bool]]:
        for nx, ny in ((tx - 1, ty), (tx + 1, ty), (tx, ty - 1), (tx, ty + 1)):
            if 0 <= nx < self.cols and 0 <= ny < self.rows:
                yield nx, ny, self.walkable[ny][nx]
            else:
                yield nx, ny, False


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
        self.state: _InteriorState = _InteriorState.DOCKING
        self.state_timer: float = 0.0
        self.docking_duration = 5.2
        self.disembark_duration = 2.8
        self.layout = _InteriorLayout(cols=56, rows=36, tile_size=96)
        self.player_position = Vector2(self.layout.spawn_point)
        self.player_velocity = Vector2()
        self.player_heading = Vector2(0.0, -1.0)
        self.camera_position = Vector2()
        self.viewport_size = Vector2(1920.0, 1080.0)
        self.status_font: Optional[pygame.font.Font] = None
        self.caption_font: Optional[pygame.font.Font] = None
        self.elapsed_time: float = 0.0
        self.starfield: List[Tuple[int, int, int]] = []
        self._build_starfield()

    def _build_starfield(self) -> None:
        rng = random.Random(20240217)
        self.starfield = []
        for _ in range(120):
            x = rng.randint(0, 3840)
            y = rng.randint(0, 2160)
            brightness = rng.randint(90, 220)
            size = rng.randint(1, 2)
            self.starfield.append((x, y, brightness << 16 | brightness << 8 | brightness | (size << 24)))

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
        if surface:
            self.viewport_size = Vector2(surface.get_width(), surface.get_height())
        self.player_position = Vector2(self.layout.spawn_point)
        self.player_velocity = Vector2()
        self.player_heading = Vector2(0.0, -1.0)
        self.camera_position = self.player_position - self.viewport_size / 2
        self.elapsed_time = 0.0
        self.state = _InteriorState.DOCKING
        self.state_timer = 0.0
        self.status_font = pygame.font.SysFont("consolas", 20)
        self.caption_font = pygame.font.SysFont("consolas", 28)
        pygame.mouse.set_visible(True)
        pygame.event.set_grab(False)

    def handle_event(self, event: pygame.event.Event) -> None:
        if self.input:
            self.input.handle_event(event)
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self._undock()
                return
            if self.state in (_InteriorState.DOCKING, _InteriorState.DISEMBARK):
                if event.key in (pygame.K_SPACE, pygame.K_RETURN):
                    self.state_timer = max(self.docking_duration, self.disembark_duration)
        # No mouse interactions required at this time.

    def update(self, dt: float) -> None:
        self.elapsed_time += dt
        if self.state == _InteriorState.DOCKING:
            self.state_timer += dt
            if self.state_timer >= self.docking_duration:
                self.state = _InteriorState.DISEMBARK
                self.state_timer = 0.0
            return
        if self.state == _InteriorState.DISEMBARK:
            self.state_timer += dt
            if self.state_timer >= self.disembark_duration:
                self.state = _InteriorState.EXPLORE
                self.state_timer = 0.0
            return

        if not self.input:
            return

        if self.input.consume_action("open_hangar") or self.input.consume_action("dock_explore"):
            self._undock()
            return

        self.input.update_axes()
        move_input = Vector2(self.input.axis_state["strafe_x"], -self.input.axis_state["throttle"])
        if move_input.length_squared() > 1e-5:
            move_input = move_input.normalize()
            self.player_heading = move_input
        speed = 320.0
        target_velocity = move_input * speed
        self.player_velocity += (target_velocity - self.player_velocity) * min(1.0, dt * 12.0)
        new_position = self.player_position + self.player_velocity * dt
        if not self._collides(new_position):
            self.player_position = new_position
        else:
            # Attempt axis-aligned resolution for smoother wall sliding.
            axis_pos = Vector2(self.player_position.x + self.player_velocity.x * dt, self.player_position.y)
            if not self._collides(axis_pos):
                self.player_position = axis_pos
            else:
                axis_pos = Vector2(self.player_position.x, self.player_position.y + self.player_velocity.y * dt)
                if not self._collides(axis_pos):
                    self.player_position = axis_pos
                else:
                    self.player_velocity = Vector2()

        target_camera = self.player_position - self.viewport_size / 2
        self.camera_position += (target_camera - self.camera_position) * min(1.0, dt * 4.0)

    def _collides(self, position: Vector2) -> bool:
        radius = self.layout.tile_size * 0.28
        offsets = [
            Vector2(radius, 0.0),
            Vector2(-radius, 0.0),
            Vector2(0.0, radius),
            Vector2(0.0, -radius),
            Vector2(radius * 0.7, radius * 0.7),
            Vector2(-radius * 0.7, radius * 0.7),
            Vector2(radius * 0.7, -radius * 0.7),
            Vector2(-radius * 0.7, -radius * 0.7),
        ]
        for offset in offsets:
            point = position + offset
            if not self.layout.is_walkable_point(point):
                return True
        return False

    def render(self, surface: pygame.Surface, alpha: float) -> None:
        width, height = surface.get_size()
        self.viewport_size = Vector2(width, height)
        if self.state == _InteriorState.DOCKING:
            self._render_docking_cutscene(surface)
            return
        if self.state == _InteriorState.DISEMBARK:
            self._render_disembark_cutscene(surface)
            return
        self._render_exploration(surface)
        if self.status_font:
            message = self.status_font.render("Press H or O to depart the Outpost", True, (214, 232, 255))
            surface.blit(
                message,
                (
                    surface.get_width() // 2 - message.get_width() // 2,
                    int(surface.get_height() * 0.92),
                ),
            )

    def _render_docking_cutscene(self, surface: pygame.Surface) -> None:
        surface.fill((4, 10, 20))
        for x, y, encoded in self.starfield:
            size = encoded >> 24
            color_val = encoded & 0xFFFFFF
            color = ((color_val >> 16) & 0xFF, (color_val >> 8) & 0xFF, color_val & 0xFF)
            pygame.draw.rect(surface, color, pygame.Rect(x % surface.get_width(), y % surface.get_height(), size, size))

        progress = min(1.0, self.state_timer / self.docking_duration)
        eased = 1.0 - (1.0 - progress) ** 2

        width, height = surface.get_size()
        horizon = int(height * 0.56)
        pygame.draw.rect(surface, (8, 18, 28), pygame.Rect(0, horizon, width, height - horizon))
        dock_rect = pygame.Rect(int(width * 0.55), int(height * 0.26), int(width * 0.28), int(height * 0.36))
        pygame.draw.rect(surface, (16, 28, 44), dock_rect)
        pygame.draw.rect(surface, (80, 130, 178), dock_rect, 4)
        clamp_rect = pygame.Rect(dock_rect.left - 24, dock_rect.centery - 64, 24, 128)
        pygame.draw.rect(surface, (40, 66, 90), clamp_rect)
        pygame.draw.rect(surface, (98, 146, 198), clamp_rect, 2)

        ship_width = int(width * 0.18)
        ship_height = int(height * 0.12)
        start_x = -ship_width
        end_x = clamp_rect.left - ship_width + 18
        ship_x = start_x + (end_x - start_x) * eased
        ship_y = dock_rect.centery - ship_height // 2 - int(30 * math.sin(progress * math.pi))
        ship_rect = pygame.Rect(int(ship_x), int(ship_y), ship_width, ship_height)
        pygame.draw.rect(surface, (22, 42, 60), ship_rect)
        pygame.draw.rect(surface, (128, 188, 230), ship_rect, 3)

        # Thruster glow fades as the ship aligns.
        glow_strength = int(200 * (1.0 - progress))
        if glow_strength > 0:
            glow_surface = pygame.Surface((ship_width // 2, ship_height), pygame.SRCALPHA)
            pygame.draw.ellipse(
                glow_surface,
                (80, 180, 255, glow_strength),
                pygame.Rect(0, ship_height // 4, ship_width // 2, ship_height // 2),
            )
            surface.blit(glow_surface, (ship_rect.right - 6, ship_rect.top))

        if self.caption_font:
            caption = self.caption_font.render("Docking sequence engaged", True, (210, 232, 255))
            surface.blit(caption, (width // 2 - caption.get_width() // 2, int(height * 0.12)))

    def _render_disembark_cutscene(self, surface: pygame.Surface) -> None:
        surface.fill((10, 18, 26))
        width, height = surface.get_size()
        progress = min(1.0, self.state_timer / self.disembark_duration)
        eased = progress ** 2

        # Render stylised cockpit frame.
        frame_color = (24, 42, 60)
        pygame.draw.rect(surface, frame_color, pygame.Rect(0, 0, width, int(height * 0.32)))
        pygame.draw.rect(surface, frame_color, pygame.Rect(0, int(height * 0.68), width, int(height * 0.32)))
        pygame.draw.rect(surface, frame_color, pygame.Rect(0, 0, int(width * 0.16), height))
        pygame.draw.rect(surface, frame_color, pygame.Rect(int(width * 0.84), 0, int(width * 0.16), height))

        interior_surface = pygame.Surface((int(width * 0.7), int(height * 0.7)))
        interior_surface.fill((18, 28, 38))
        interior_rect = interior_surface.get_rect()
        interior_rect.center = (width // 2, height // 2)

        floor_y = int(interior_surface.get_height() * (0.75 + 0.25 * eased))
        pygame.draw.rect(interior_surface, (28, 40, 52), pygame.Rect(0, floor_y, interior_surface.get_width(), interior_surface.get_height() - floor_y))
        pygame.draw.rect(interior_surface, (16, 26, 36), pygame.Rect(0, 0, interior_surface.get_width(), floor_y))

        # Simulated descent motion.
        descent_offset = int(220 * (1.0 - eased))
        rails_color = (70, 114, 168)
        for offset in (-0.32, -0.12, 0.12, 0.32):
            x = int(interior_surface.get_width() * (0.5 + offset))
            pygame.draw.line(
                interior_surface,
                rails_color,
                (x, floor_y - descent_offset),
                (x, interior_surface.get_height()),
                4,
            )

        glow_surface = pygame.Surface(interior_surface.get_size(), pygame.SRCALPHA)
        glow_radius = int(interior_surface.get_width() * 0.35)
        glow_center = (interior_surface.get_width() // 2, floor_y + glow_radius // 3)
        glow_alpha = int(200 * min(1.0, eased + 0.2))
        pygame.draw.circle(glow_surface, (120, 220, 255, glow_alpha), glow_center, glow_radius)
        interior_surface.blit(glow_surface, (0, 0), special_flags=pygame.BLEND_ADD)

        # Jump silhouette.
        jumper_height = int(interior_surface.get_height() * 0.28)
        jumper_width = int(jumper_height * 0.35)
        jumper_y = floor_y - jumper_height + int(60 * (1.0 - progress))
        jumper_x = interior_surface.get_width() // 2 - jumper_width // 2
        pygame.draw.ellipse(
            interior_surface,
            (44, 62, 82),
            pygame.Rect(jumper_x, jumper_y, jumper_width, jumper_height),
        )

        surface.blit(interior_surface, interior_rect)

        if self.caption_font:
            caption = self.caption_font.render("Touchdown inside the hangar", True, (214, 236, 255))
            surface.blit(caption, (width // 2 - caption.get_width() // 2, int(height * 0.12)))

    def _render_exploration(self, surface: pygame.Surface) -> None:
        surface.fill((12, 20, 30))
        tile = self.layout.tile_size
        camera = self.camera_position
        time_factor = self.elapsed_time

        def to_screen(rect: pygame.Rect) -> pygame.Rect:
            return pygame.Rect(rect.x - camera.x, rect.y - camera.y, rect.width, rect.height)

        # Draw floor with subtle patterning.
        for ty, row in enumerate(self.layout.walkable):
            for tx, walkable in enumerate(row):
                if not walkable:
                    continue
                world_rect = pygame.Rect(tx * tile, ty * tile, tile, tile)
                screen_rect = to_screen(world_rect)
                if screen_rect.right < 0 or screen_rect.bottom < 0:
                    continue
                if screen_rect.left > surface.get_width() or screen_rect.top > surface.get_height():
                    continue
                base = 26 + ((tx * 7 + ty * 11) % 5) * 2
                flicker = int(6 * math.sin(time_factor * 0.6 + tx * 0.7 + ty * 0.4))
                color = (base + flicker, base + 6 + flicker, base + 14 + flicker)
                pygame.draw.rect(surface, color, screen_rect)

        # Draw decorative floor strips.
        for detail in self.layout.floor_details:
            rect = to_screen(detail)
            if rect.colliderect(surface.get_rect()):
                pygame.draw.rect(surface, (70, 120, 168), rect)

        # Draw walls as outlines around the edges of walkable tiles.
        wall_color = (18, 32, 44)
        edge_color = (108, 150, 198)
        for ty, row in enumerate(self.layout.walkable):
            for tx, walkable in enumerate(row):
                if not walkable:
                    continue
                world_rect = pygame.Rect(tx * tile, ty * tile, tile, tile)
                screen_rect = to_screen(world_rect)
                if screen_rect.right < 0 or screen_rect.bottom < 0 or screen_rect.left > surface.get_width() or screen_rect.top > surface.get_height():
                    continue
                for nx, ny, neighbour_walkable in self.layout.neighbors(tx, ty):
                    if neighbour_walkable:
                        continue
                    # Determine edge orientation.
                    if nx < tx:  # west edge
                        edge = pygame.Rect(screen_rect.left, screen_rect.top, int(tile * 0.08), screen_rect.height)
                    elif nx > tx:  # east edge
                        edge = pygame.Rect(screen_rect.right - int(tile * 0.08), screen_rect.top, int(tile * 0.08), screen_rect.height)
                    elif ny < ty:  # north edge
                        edge = pygame.Rect(screen_rect.left, screen_rect.top, screen_rect.width, int(tile * 0.08))
                    else:  # south edge
                        edge = pygame.Rect(screen_rect.left, screen_rect.bottom - int(tile * 0.08), screen_rect.width, int(tile * 0.08))
                    pygame.draw.rect(surface, wall_color, edge)
                    highlight = edge.inflate(-edge.width * 0.2, -edge.height * 0.2)
                    pygame.draw.rect(surface, edge_color, highlight, 1)

        # Lighting glows.
        light_surface = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        for light in self.layout.lights:
            screen_pos = Vector2(light.position.x - camera.x, light.position.y - camera.y)
            if (
                screen_pos.x + light.radius < 0
                or screen_pos.y + light.radius < 0
                or screen_pos.x - light.radius > surface.get_width()
                or screen_pos.y - light.radius > surface.get_height()
            ):
                continue
            pulse = 0.6 + 0.4 * math.sin(self.elapsed_time * light.pulse_speed)
            alpha = int(180 * light.intensity * pulse)
            radius = int(light.radius)
            gradient = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
            pygame.draw.circle(gradient, (110, 200, 255, alpha), (radius, radius), radius)
            light_surface.blit(
                gradient,
                (int(screen_pos.x - radius), int(screen_pos.y - radius)),
                special_flags=pygame.BLEND_ADD,
            )
        surface.blit(light_surface, (0, 0), special_flags=pygame.BLEND_ADD)

        # Player representation.
        player_screen = Vector2(
            self.player_position.x - camera.x,
            self.player_position.y - camera.y,
        )
        pygame.draw.circle(surface, (240, 250, 255), (int(player_screen.x), int(player_screen.y)), int(tile * 0.18))
        forward = self.player_heading.normalize() if self.player_heading.length_squared() > 1e-5 else Vector2(0.0, -1.0)
        nose = player_screen + forward * tile * 0.32
        pygame.draw.line(surface, (110, 170, 220), (int(player_screen.x), int(player_screen.y)), (int(nose.x), int(nose.y)), 4)

        # Floating signage.
        if self.caption_font:
            label = self.caption_font.render("OUTPOST INTERIOR", True, (162, 208, 246))
            surface.blit(label, (24, 24))
            location = self.status_font.render("Hangar Wing A", True, (124, 170, 208)) if self.status_font else None
            if location:
                surface.blit(location, (26, 24 + label.get_height() + 6))

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
