"""Cinematic sequences shown when docking with an Outpost."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

import pygame
from pygame.math import Vector3

from game.assets.content import ContentManager
from game.engine.input import InputMapper
from game.engine.logger import GameLogger
from game.engine.scene import Scene
from game.render.camera import ChaseCamera
from game.render.renderer import VectorRenderer, WIREFRAMES
from game.ships.ship import Ship, ShipControlState
from game.world.space import SpaceWorld, SpaceWorldState
from game.world.station import DockingStation
from game.world.interior import InteriorDefinition
from game.ui.interior_fp import FirstPersonInteriorView
from game.world.ship_wire import ShipWireEmbed


class _InteriorState(Enum):
    DOCKING = auto()
    LOADING_IN = auto()
    DISEMBARK = auto()
    EXPLORE = auto()
    LOADING_OUT = auto()


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
class _DockingSequence:
    start: Vector3
    entry: Vector3
    dock: Vector3
    start_forward: Vector3
    dock_forward: Vector3


class OutpostInteriorScene(Scene):
    """Handles the cinematic flow for docking at an Outpost."""

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
        self.disembark_duration = 4.2
        self.loading_duration = 1.25
        self.viewport_size: tuple[float, float] = (1920.0, 1080.0)
        self.status_font: Optional[pygame.font.Font] = None
        self.caption_font: Optional[pygame.font.Font] = None
        self.elapsed_time: float = 0.0
        self.starfield: list[tuple[int, int, int]] = []
        self._build_starfield()
        self.cutscene_camera: Optional[ChaseCamera] = None
        self.cutscene_station_ship: Optional[Ship] = None
        self._docking_sequence: Optional[_DockingSequence] = None
        self._docking_last_position: Optional[Vector3] = None
        self._loading_in_started = False
        self._loading_out_started = False
        self._suspended_world_state: Optional[SpaceWorldState] = None
        self._proxy_station_ship = False
        self.interior: Optional[InteriorDefinition] = None
        self._interior_view: Optional[FirstPersonInteriorView] = None
        self._ship_embedder: Optional[ShipWireEmbed] = None
        self._cursor_locked = False

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
        self.state = _InteriorState.DOCKING
        self.state_timer = 0.0
        self._loading_in_started = False
        self._loading_out_started = False
        self._suspended_world_state = None
        surface = pygame.display.get_surface()
        if surface:
            self.viewport_size = (float(surface.get_width()), float(surface.get_height()))
        else:
            self.viewport_size = (1920.0, 1080.0)
        self.elapsed_time = 0.0
        self.cutscene_camera = None
        self.cutscene_station_ship = None
        self._docking_sequence = None
        self._docking_last_position = None
        self.status_font = pygame.font.SysFont("consolas", 20)
        self.caption_font = pygame.font.SysFont("consolas", 28)
        pygame.mouse.set_visible(True)
        pygame.event.set_grab(False)
        self._proxy_station_ship = False
        self._setup_docking_sequence()
        self._load_interior_definition()
        self._cursor_locked = False

    def handle_event(self, event: pygame.event.Event) -> None:
        if self.input:
            self.input.handle_event(event)
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self._undock()
                return
            if event.key in (pygame.K_SPACE, pygame.K_RETURN):
                if self.state in (_InteriorState.DOCKING, _InteriorState.DISEMBARK):
                    self.state_timer = max(self.docking_duration, self.disembark_duration)

    def update(self, dt: float) -> None:
        self.elapsed_time += dt
        if self.input:
            self.input.update_axes()

        if self.state == _InteriorState.DOCKING:
            self.state_timer += dt
            self._update_docking_animation(dt)
            if self.state_timer >= self.docking_duration:
                self.state = _InteriorState.LOADING_IN
                self.state_timer = 0.0
            return
        if self.state == _InteriorState.LOADING_IN:
            if not self._loading_in_started:
                self._start_loading_in()
            self.state_timer += dt
            if self.state_timer >= self.loading_duration:
                self.state = _InteriorState.DISEMBARK
                self.state_timer = 0.0
            return
        if self.state == _InteriorState.DISEMBARK:
            self.state_timer += dt
            if self.state_timer >= self.disembark_duration:
                self._start_interior_explore()
            return
        if self.state == _InteriorState.EXPLORE:
            if self._interior_view and self.input:
                self._interior_view.update(dt, self.input)
            return
        if self.state == _InteriorState.LOADING_OUT:
            if not self._loading_out_started:
                self._start_loading_out()
            self.state_timer += dt
            if self.state_timer >= self.loading_duration:
                self._complete_undock()

    def _start_loading_in(self) -> None:
        if self._loading_in_started:
            return
        self._loading_in_started = True
        if self.world:
            self._suspended_world_state = self.world.suspend_simulation()

    def _start_loading_out(self) -> None:
        if self._loading_out_started:
            return
        self._loading_out_started = True
        self._release_cursor()
        if self.world and self._suspended_world_state:
            self.world.resume_simulation(self._suspended_world_state)
            self._suspended_world_state = None

    def _complete_undock(self) -> None:
        if not self.world or not self.player or not self.station:
            self.manager.activate(
                "sandbox",
                content=self.content,
                input=self.input,
                logger=self.logger,
            )
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

    def render(self, surface: pygame.Surface, alpha: float) -> None:
        width, height = surface.get_size()
        self.viewport_size = (float(width), float(height))
        if self.state == _InteriorState.DOCKING:
            self._render_docking_cutscene(surface)
            return
        if self.state == _InteriorState.LOADING_IN:
            progress = 0.0
            if self.loading_duration > 0.0:
                progress = max(0.0, min(1.0, self.state_timer / self.loading_duration))
            self._render_loading_screen(
                surface,
                "Sequencing Outpost Interior",
                "Despawning exterior traffic lanes",
                progress,
            )
            return
        if self.state == _InteriorState.DISEMBARK:
            self._render_disembark_cutscene(surface)
            return
        if self.state == _InteriorState.EXPLORE:
            if self._interior_view:
                self._interior_view.render(surface)
            else:
                surface.fill((6, 10, 18))
            return
        if self.state == _InteriorState.LOADING_OUT:
            progress = 0.0
            if self.loading_duration > 0.0:
                progress = max(0.0, min(1.0, self.state_timer / self.loading_duration))
            self._render_loading_screen(
                surface,
                "Restoring Local Space",
                "Repopulating ships and asteroids",
                progress,
            )

    def _render_docking_cutscene(self, surface: pygame.Surface) -> None:
        width, height = surface.get_size()
        renderer = VectorRenderer(surface)
        renderer.clear()

        if self.cutscene_camera and self.player:
            focus = self.player.kinematics.position
            renderer.draw_grid(self.cutscene_camera, focus, tile_size=280.0, extent=3200.0, height_offset=-40.0)

            if self.world:
                for ship in self.world.ships:
                    if ship is self.player:
                        continue
                    renderer.draw_ship(self.cutscene_camera, ship)

            if self.cutscene_station_ship and self._proxy_station_ship:
                renderer.draw_ship(self.cutscene_camera, self.cutscene_station_ship)

            renderer.draw_ship(self.cutscene_camera, self.player)

            if self._docking_sequence:
                dock_target = self._docking_sequence.dock
                entry_point = self._docking_sequence.entry
                screen_dock, vis_dock = self.cutscene_camera.project(dock_target, (width, height))
                screen_entry, vis_entry = self.cutscene_camera.project(entry_point, (width, height))
                if vis_entry and vis_dock:
                    pygame.draw.aaline(
                        surface,
                        (120, 220, 255),
                        (screen_entry.x, screen_entry.y),
                        (screen_dock.x, screen_dock.y),
                        blend=1,
                    )
                    pygame.draw.circle(
                        surface,
                        (180, 240, 255),
                        (int(screen_dock.x), int(screen_dock.y)),
                        16,
                        2,
                    )

        star_surface = pygame.Surface((width, height), pygame.SRCALPHA)
        for x, y, encoded in self.starfield:
            size = encoded >> 24
            color_val = encoded & 0xFFFFFF
            color = (
                (color_val >> 16) & 0xFF,
                (color_val >> 8) & 0xFF,
                color_val & 0xFF,
                130,
            )
            star_surface.fill(color, pygame.Rect(x % width, y % height, size, size))
        surface.blit(star_surface, (0, 0), special_flags=pygame.BLEND_ADD)

        if self.caption_font:
            caption = self.caption_font.render("Docking sequence engaged", True, (210, 232, 255))
            surface.blit(caption, (width // 2 - caption.get_width() // 2, int(height * 0.08)))
            progress = 0.0
            if self.docking_duration > 0.0:
                progress = max(0.0, min(1.0, self.state_timer / self.docking_duration))
            bar_width = int(width * 0.32)
            bar_height = 14
            bar_rect = pygame.Rect(width // 2 - bar_width // 2, int(height * 0.88), bar_width, bar_height)
            pygame.draw.rect(surface, (30, 60, 90), bar_rect)
            fill_rect = bar_rect.copy()
            fill_rect.width = int(bar_rect.width * progress)
            pygame.draw.rect(surface, (110, 200, 255), fill_rect)
            pygame.draw.rect(surface, (180, 220, 255), bar_rect, 2)

    def _render_disembark_cutscene(self, surface: pygame.Surface) -> None:
        width, height = surface.get_size()
        duration = max(1e-5, self.disembark_duration)
        progress = max(0.0, min(1.0, self.state_timer / duration))

        def _segment(start: float, end: float) -> float:
            if progress <= start:
                return 0.0
            if progress >= end:
                return 1.0
            span = end - start
            if span <= 0.0:
                return 1.0
            return (progress - start) / span

        approach = _segment(0.0, 0.5)
        brake = _segment(0.5, 0.72)
        drop = _segment(0.72, 0.85)
        canopy = _segment(0.85, 0.92)
        egress = _segment(0.92, 1.0)

        approach_ease = approach ** 1.2
        brake_ease = brake ** 1.6
        drop_ease = drop ** 2.1
        canopy_ease = canopy ** 1.5
        egress_ease = egress ** 1.35

        def _to_int(value: float) -> int:
            return int(round(value))

        surface.fill((8, 14, 24))

        center_x = width // 2
        vanish_y = _to_int(height * (0.34 - drop_ease * 0.08 + egress_ease * 0.04))
        floor_y = _to_int(height * (0.86 - drop_ease * 0.26 + egress_ease * 0.18))
        neck_y = _to_int(vanish_y + height * (0.18 + approach_ease * 0.12))
        far_half_width = width * (0.18 + approach_ease * 0.32)
        near_half_width = width * (0.48 + approach_ease * 0.36 + brake_ease * 0.18)
        parallax = (1.0 - approach_ease) * 0.4 + (1.0 - brake_ease) * 0.2

        hangar_overlay = pygame.Surface((width, height), pygame.SRCALPHA)

        ceiling_height = height * (0.18 - parallax * 0.12)
        ceiling_poly = [
            (_to_int(center_x - near_half_width * 0.82), _to_int(vanish_y - ceiling_height)),
            (_to_int(center_x + near_half_width * 0.82), _to_int(vanish_y - ceiling_height)),
            (_to_int(center_x + far_half_width * 0.92), neck_y),
            (_to_int(center_x - far_half_width * 0.92), neck_y),
        ]
        pygame.draw.polygon(hangar_overlay, (24, 36, 58, 235), ceiling_poly)

        floor_poly = [
            (_to_int(center_x - near_half_width), floor_y),
            (_to_int(center_x + near_half_width), floor_y),
            (_to_int(center_x + far_half_width * 0.94), neck_y),
            (_to_int(center_x - far_half_width * 0.94), neck_y),
        ]
        pygame.draw.polygon(hangar_overlay, (34, 48, 66, 255), floor_poly)

        side_color = (18, 30, 50, 220)
        left_wall = [
            (_to_int(center_x - near_half_width * 1.08), floor_y),
            (_to_int(center_x - near_half_width * 0.86), floor_y),
            (_to_int(center_x - far_half_width * 0.96), neck_y),
            (_to_int(center_x - far_half_width * 1.28), _to_int(vanish_y - height * (0.12 - parallax * 0.08))),
        ]
        right_wall = [
            (_to_int(center_x + near_half_width * 0.86), floor_y),
            (_to_int(center_x + near_half_width * 1.08), floor_y),
            (_to_int(center_x + far_half_width * 1.28), _to_int(vanish_y - height * (0.12 - parallax * 0.08))),
            (_to_int(center_x + far_half_width * 0.96), neck_y),
        ]
        pygame.draw.polygon(hangar_overlay, side_color, left_wall)
        pygame.draw.polygon(hangar_overlay, side_color, right_wall)

        beam_color = (50, 86, 132, 170)
        beam_count = 5
        for idx in range(-beam_count, beam_count + 1):
            frac = idx / max(1, beam_count)
            top_y = _to_int(vanish_y - height * (0.1 + frac * 0.03) - canopy_ease * height * 0.14)
            bottom_y = _to_int(neck_y + frac * height * 0.06)
            x_far = _to_int(center_x + far_half_width * frac * 0.9)
            x_near = _to_int(center_x + near_half_width * frac * 0.92)
            pygame.draw.polygon(
                hangar_overlay,
                beam_color,
                [
                    (x_far - 8, top_y),
                    (x_far + 8, top_y),
                    (x_near + 18, bottom_y),
                    (x_near - 18, bottom_y),
                ],
            )

        edge_color = (118, 210, 255, 160)
        pygame.draw.aaline(
            hangar_overlay,
            edge_color,
            (_to_int(center_x - near_half_width), floor_y),
            (_to_int(center_x - far_half_width * 0.94), neck_y),
        )
        pygame.draw.aaline(
            hangar_overlay,
            edge_color,
            (_to_int(center_x + near_half_width), floor_y),
            (_to_int(center_x + far_half_width * 0.94), neck_y),
        )

        stripes = 12
        motion = (1.0 - approach_ease) * 6.5 + (1.0 - brake_ease) * 2.2
        for idx in range(stripes + 3):
            depth = (idx + motion) / (stripes + 3)
            if depth >= 0.98:
                continue
            depth = max(0.05, depth)
            y = _to_int(vanish_y + (neck_y - vanish_y) * depth)
            half = far_half_width + (near_half_width - far_half_width) * depth
            alpha = int(150 * (1.0 - depth) ** 0.55)
            color = (80, 160, 220, alpha)
            pygame.draw.line(hangar_overlay, color, (_to_int(center_x - half), y), (_to_int(center_x + half), y), 4)

        for idx in range(6):
            fraction = idx / 5.0 if idx else 0.0
            light_x = _to_int(center_x - near_half_width * 0.9 + fraction * near_half_width * 1.8)
            light_y = _to_int(vanish_y + (neck_y - vanish_y) * 0.22)
            radius = max(3, _to_int(6 + fraction * 5))
            alpha = int(140 * (0.6 + 0.4 * math.sin(self.elapsed_time * 4.0 + idx * 0.7)))
            pygame.draw.circle(hangar_overlay, (30, 50, 70, alpha), (light_x, light_y), radius + 4)
            pygame.draw.circle(hangar_overlay, (120, 210, 255, alpha), (light_x, light_y), radius, 0)

        door_rect = pygame.Rect(
            _to_int(center_x - far_half_width * 0.6),
            _to_int(vanish_y - height * 0.06),
            _to_int(far_half_width * 1.2),
            _to_int(height * 0.16),
        )
        hangar_overlay.fill((32, 52, 84, 220), door_rect)
        pygame.draw.rect(hangar_overlay, (90, 150, 200, 200), door_rect, 2)

        pit_rect = pygame.Rect(
            _to_int(center_x - near_half_width * 0.58),
            _to_int(neck_y + (floor_y - neck_y) * 0.32),
            _to_int(near_half_width * 1.16),
            _to_int((floor_y - neck_y) * 0.42),
        )
        hangar_overlay.fill((18, 26, 40, 200), pit_rect)
        pygame.draw.rect(hangar_overlay, (70, 120, 168, 150), pit_rect, 2)

        crane_color = (60, 90, 130, 170)
        crane_y = _to_int(vanish_y - height * (0.14 + canopy_ease * 0.12))
        pygame.draw.line(hangar_overlay, crane_color, (_to_int(center_x - far_half_width * 0.8), crane_y), (_to_int(center_x + far_half_width * 0.8), crane_y), 6)
        for offset in (-0.55, -0.15, 0.25, 0.65):
            anchor_x = _to_int(center_x + far_half_width * offset)
            pygame.draw.line(hangar_overlay, crane_color, (anchor_x, crane_y), (anchor_x, _to_int(neck_y + height * 0.02)), 4)
            hook_y = _to_int(neck_y + (floor_y - neck_y) * 0.22 - drop_ease * height * 0.08)
            pygame.draw.circle(hangar_overlay, (120, 180, 230, 160), (anchor_x, hook_y), 6, 1)

        glow_surface = pygame.Surface((width, height), pygame.SRCALPHA)
        glow_radius = max(60, _to_int(width * 0.14))
        for offset in (-1, 1):
            glow_center = (_to_int(center_x + near_half_width * 0.94 * offset), floor_y)
            pygame.draw.circle(glow_surface, (40, 90, 150, 140), glow_center, glow_radius)
        hangar_overlay.blit(glow_surface, (0, 0), special_flags=pygame.BLEND_RGBA_ADD)

        surface.blit(hangar_overlay, (0, 0))

        glass_alpha = int(150 * (1.0 - canopy_ease))
        if glass_alpha > 0:
            glass_surface = pygame.Surface((width, height), pygame.SRCALPHA)
            glass_shift = _to_int(height * 0.44 * canopy_ease)
            glass_points = [
                (_to_int(center_x - near_half_width * 0.78), _to_int(height - (height - floor_y) * 1.08) - glass_shift),
                (_to_int(center_x - far_half_width * 0.38), _to_int(vanish_y - height * 0.06) - glass_shift),
                (_to_int(center_x + far_half_width * 0.38), _to_int(vanish_y - height * 0.06) - glass_shift),
                (_to_int(center_x + near_half_width * 0.78), _to_int(height - (height - floor_y) * 1.08) - glass_shift),
            ]
            pygame.draw.polygon(glass_surface, (20, 32, 48, glass_alpha), glass_points)
            pygame.draw.lines(glass_surface, (80, 120, 164, glass_alpha), True, glass_points, 2)
            surface.blit(glass_surface, (0, 0))

        cockpit_overlay = pygame.Surface((width, height), pygame.SRCALPHA)
        panel_height = height * (0.34 + brake_ease * 0.08)
        panel_top = _to_int(height - panel_height)
        panel_rect = pygame.Rect(_to_int(width * 0.12), panel_top, _to_int(width * 0.76), _to_int(panel_height))
        pygame.draw.rect(cockpit_overlay, (18, 28, 42, 230), panel_rect, border_radius=18)
        pygame.draw.rect(cockpit_overlay, (68, 112, 168, 200), panel_rect, 3, border_radius=18)

        indicator = (_to_int(width * 0.5), _to_int(panel_top + panel_height * 0.32))
        pygame.draw.circle(cockpit_overlay, (90, 180, 220, 160), indicator, 12, 2)

        throttle_value = max(0.0, min(1.0, 1.0 - approach_ease * 0.7 - brake_ease * 0.5 + drop_ease * 0.2))
        throttle_slot = pygame.Rect(_to_int(width * 0.74), panel_top - _to_int(panel_height * 0.3), _to_int(width * 0.02), _to_int(panel_height * 0.5))
        pygame.draw.rect(cockpit_overlay, (40, 70, 100, 200), throttle_slot, border_radius=6)
        knob_height = _to_int(panel_height * 0.1)
        knob_top = throttle_slot.bottom - _to_int(throttle_slot.height * (0.18 + throttle_value * 0.78)) - knob_height // 2
        knob_rect = pygame.Rect(throttle_slot.left - _to_int(width * 0.012), knob_top, throttle_slot.width + _to_int(width * 0.024), knob_height)
        pygame.draw.rect(cockpit_overlay, (120, 210, 255, 200), knob_rect, border_radius=4)

        pygame.draw.line(
            cockpit_overlay,
            (90, 150, 210, 160),
            (panel_rect.left + 12, panel_top + _to_int(panel_height * 0.18)),
            (panel_rect.right - 12, panel_top + _to_int(panel_height * 0.18)),
            2,
        )

        arm_alpha = int(255 * (1.0 - egress_ease))
        arm_motion = brake_ease * 36.0 - drop_ease * 18.0
        if arm_alpha > 0:
            arm_color = (58, 92, 132, arm_alpha)
            glove_color = (214, 232, 255, arm_alpha)
            left_arm_points = [
                (_to_int(width * 0.18), _to_int(height - panel_height * 0.08)),
                (_to_int(width * 0.26 - arm_motion * 0.12), _to_int(panel_top - panel_height * 0.25 - arm_motion * 0.32)),
                (_to_int(width * 0.34 - arm_motion * 0.05), _to_int(panel_top - panel_height * 0.12)),
                (_to_int(width * 0.26), _to_int(height - panel_height * 0.02)),
            ]
            right_arm_points = [
                (_to_int(width * 0.82), _to_int(height - panel_height * 0.08)),
                (_to_int(width * 0.74 + arm_motion * 0.12), _to_int(panel_top - panel_height * 0.27 - arm_motion * 0.3)),
                (_to_int(width * 0.66 + arm_motion * 0.05), _to_int(panel_top - panel_height * 0.14)),
                (_to_int(width * 0.74), _to_int(height - panel_height * 0.02)),
            ]
            pygame.draw.polygon(cockpit_overlay, arm_color, left_arm_points)
            pygame.draw.polygon(cockpit_overlay, arm_color, right_arm_points)
            left_hand_center = (_to_int(width * 0.32 - arm_motion * 0.04), _to_int(panel_top - panel_height * 0.16 - arm_motion * 0.38))
            right_hand_center = (_to_int(width * 0.68 + arm_motion * 0.04), _to_int(panel_top - panel_height * 0.18 - arm_motion * 0.28))
            hand_radius = max(14, _to_int(panel_height * 0.12))
            pygame.draw.circle(cockpit_overlay, glove_color, left_hand_center, hand_radius)
            pygame.draw.circle(cockpit_overlay, (140, 180, 220, arm_alpha), left_hand_center, hand_radius, 3)
            pygame.draw.circle(cockpit_overlay, glove_color, right_hand_center, hand_radius)
            pygame.draw.circle(cockpit_overlay, (140, 180, 220, arm_alpha), right_hand_center, hand_radius, 3)
            left_stick_base = (_to_int(width * 0.32), _to_int(height - panel_height * 0.04))
            left_stick_tip = (
                _to_int(width * 0.32 + math.sin(self.elapsed_time * 2.0 + brake_ease) * 18.0),
                _to_int(panel_top - panel_height * (0.52 - drop_ease * 0.12)),
            )
            pygame.draw.line(cockpit_overlay, (90, 150, 210, arm_alpha), left_stick_base, left_stick_tip, 6)
            right_stick_base = (_to_int(width * 0.68), _to_int(height - panel_height * 0.04))
            right_stick_tip = (
                _to_int(width * 0.68 + math.sin(self.elapsed_time * 1.6 + approach_ease) * 16.0),
                _to_int(panel_top - panel_height * (0.46 - drop_ease * 0.08)),
            )
            pygame.draw.line(cockpit_overlay, (90, 150, 210, arm_alpha), right_stick_base, right_stick_tip, 6)

        frame_alpha = int(235 * (1.0 - egress_ease * 0.5))
        frame_color = (12, 20, 32, frame_alpha)
        frame_width = max(6, _to_int(width * 0.01))
        apex_y = _to_int(vanish_y - height * (0.1 + canopy_ease * 0.18))
        pygame.draw.line(cockpit_overlay, frame_color, (_to_int(width * 0.1), panel_top), (center_x, apex_y), frame_width)
        pygame.draw.line(cockpit_overlay, frame_color, (_to_int(width * 0.9), panel_top), (center_x, apex_y), frame_width)
        pygame.draw.line(cockpit_overlay, frame_color, (_to_int(width * 0.08), panel_top + _to_int(panel_height * 0.26)), (_to_int(width * 0.92), panel_top + _to_int(panel_height * 0.26)), frame_width)

        cockpit_overlay.set_alpha(int(255 * (1.0 - egress_ease * 0.08)))
        cockpit_offset = -_to_int(egress_ease * height * 0.18)
        surface.blit(cockpit_overlay, (0, cockpit_offset))

        if self.caption_font:
            if progress < 0.5:
                caption_text = "Approaching Outpost hangar"
            elif progress < 0.85:
                caption_text = "Landing thrusters engaged"
            else:
                caption_text = "Disembarking to Outpost"
            caption = self.caption_font.render(caption_text, True, (214, 236, 255))
            surface.blit(caption, (width // 2 - caption.get_width() // 2, _to_int(height * 0.08)))

        if self.status_font:
            detail = self.status_font.render("Hangar deck pressurized · Line-class clearance", True, (150, 196, 236))
            surface.blit(detail, (width // 2 - detail.get_width() // 2, _to_int(height * 0.9)))

    def _render_loading_screen(self, surface: pygame.Surface, title: str, subtitle: str, progress: float) -> None:
        surface.fill((6, 12, 22))
        width, height = surface.get_size()
        if self.caption_font:
            caption = self.caption_font.render(title, True, (206, 236, 255))
            surface.blit(
                caption,
                (width // 2 - caption.get_width() // 2, int(height * 0.38)),
            )
            caption_bottom = int(height * 0.38) + caption.get_height() + 12
        else:
            caption_bottom = int(height * 0.4)
        if self.status_font:
            detail = self.status_font.render(subtitle, True, (156, 196, 230))
            surface.blit(
                detail,
                (width // 2 - detail.get_width() // 2, caption_bottom),
            )
        bar_width = int(width * 0.34)
        bar_height = 16
        bar_rect = pygame.Rect(
            width // 2 - bar_width // 2,
            int(height * 0.58),
            bar_width,
            bar_height,
        )
        pygame.draw.rect(surface, (26, 52, 88), bar_rect)
        progress = max(0.0, min(1.0, progress))
        fill_rect = bar_rect.copy()
        fill_rect.width = int(bar_rect.width * progress)
        pygame.draw.rect(surface, (112, 210, 255), fill_rect)
        pygame.draw.rect(surface, (182, 224, 255), bar_rect, 2)

    def _undock(self) -> None:
        self._release_cursor()
        if self.state == _InteriorState.LOADING_OUT:
            return
        self.state = _InteriorState.LOADING_OUT
        self.state_timer = 0.0
        self._loading_out_started = False

    def _setup_docking_sequence(self) -> None:
        if not self.player or not self.station:
            return

        station_pos = Vector3(*self.station.position)
        current_pos = Vector3(self.player.kinematics.position)
        to_station = station_pos - current_pos
        distance = to_station.length()
        approach_dir = to_station.normalize() if distance > 1e-3 else Vector3(0.0, 0.0, 1.0)

        entry_distance = max(self.station.docking_radius * 1.1, 480.0)
        dock_offset = max(self.station.docking_radius * 0.32, 180.0)

        entry_point = station_pos - approach_dir * entry_distance
        start_point = Vector3(current_pos)
        if distance < entry_distance * 0.85:
            start_point = station_pos - approach_dir * (entry_distance + max(220.0, self.station.docking_radius * 0.25))
            self.player.kinematics.position = Vector3(start_point)
        dock_point = station_pos - approach_dir * dock_offset

        start_forward = self.player.kinematics.basis.forward
        if start_forward.length_squared() <= 1e-5:
            start_forward = approach_dir
        dock_forward = approach_dir

        self._docking_sequence = _DockingSequence(
            start=start_point,
            entry=entry_point,
            dock=dock_point,
            start_forward=start_forward.normalize(),
            dock_forward=dock_forward.normalize(),
        )
        self._docking_last_position = Vector3(start_point)
        self.player.kinematics.velocity = Vector3()
        self.player.kinematics.angular_velocity = Vector3()

        aspect = 16.0 / 9.0
        if self.viewport_size[1] > 1e-5:
            aspect = float(self.viewport_size[0]) / float(self.viewport_size[1])
        self.cutscene_camera = ChaseCamera(64.0, aspect)
        self.cutscene_camera.distance = 28.0
        self.cutscene_camera.height = 6.5
        self.cutscene_camera.shoulder = 0.0
        self.cutscene_camera.look_ahead_factor = 0.0
        self.cutscene_camera.look_ahead_response = 6.0
        self.cutscene_camera.lock_response = 4.0
        self.cutscene_camera.position = (
            self.player.kinematics.position
            - self.player.kinematics.basis.forward * self.cutscene_camera.distance
            + self.player.kinematics.up() * self.cutscene_camera.height
        )
        self.cutscene_camera.forward = self.player.kinematics.basis.forward
        self.cutscene_camera.up = self.player.kinematics.up()
        right = self.cutscene_camera.forward.cross(self.cutscene_camera.up)
        if right.length_squared() > 1e-6:
            self.cutscene_camera.right = right.normalize()
            self.cutscene_camera.up = self.cutscene_camera.right.cross(self.cutscene_camera.forward).normalize()
        else:
            self.cutscene_camera.right = Vector3(1.0, 0.0, 0.0)

        self.cutscene_station_ship = self._locate_station_visual(station_pos, approach_dir)

    def _load_interior_definition(self) -> None:
        self.interior = None
        self._interior_view = None
        self._ship_embedder = None
        if not self.content:
            return
        interior_id = "outpost_interior_v1"
        try:
            self.interior = self.content.interiors.get(interior_id)
        except KeyError:
            self.interior = None
        if self.interior:
            self._interior_view = FirstPersonInteriorView(self.interior)
            if self.caption_font or self.status_font:
                hud_font = self.caption_font if self.caption_font else None
                prompt_font = self.status_font if self.status_font else None
                self._interior_view.set_fonts(hud_font, prompt_font)
            self._ship_embedder = ShipWireEmbed()
            self._apply_ship_wireframe()

    def _apply_ship_wireframe(self) -> None:
        if not self._interior_view or not self._ship_embedder or not self.player:
            return
        frame = getattr(self.player, "frame", None)
        frame_id = getattr(frame, "id", None)
        frame_size = getattr(frame, "size", "Strike")
        segments = WIREFRAMES.get(frame_id) if frame_id else None
        if segments is None:
            segments = WIREFRAMES.get(frame_size, WIREFRAMES["Strike"])
        embed_input = [
            (
                (segment[0].x, segment[0].y, segment[0].z),
                (segment[1].x, segment[1].y, segment[1].z),
            )
            for segment in segments
        ]
        result = self._ship_embedder.embed(embed_input, frame_size=frame_size)
        if result:
            self._interior_view.set_ship_segments(result.segments)
            self._interior_view.set_dynamic_no_walk(result.safety_min, result.safety_max)

    def _release_cursor(self) -> None:
        if self._cursor_locked:
            pygame.mouse.set_visible(True)
            pygame.event.set_grab(False)
            self._cursor_locked = False

    def _start_interior_explore(self) -> None:
        self.state = _InteriorState.EXPLORE
        self.state_timer = 0.0
        if self._interior_view:
            self._interior_view.reset()
        if not self._cursor_locked:
            pygame.mouse.set_visible(False)
            pygame.event.set_grab(True)
            self._cursor_locked = True

    

    def _locate_station_visual(self, station_pos: Vector3, approach_dir: Vector3) -> Optional[Ship]:
        if not self.station:
            return None

        if self.world:
            best: Optional[Ship] = None
            best_distance = float("inf")
            for candidate in self.world.ships:
                if candidate.frame.size.lower() != "outpost":
                    continue
                distance = candidate.kinematics.position.distance_to(station_pos)
                if distance < best_distance:
                    best = candidate
                    best_distance = distance
            if best and best_distance <= max(self.station.docking_radius * 2.5, 2400.0):
                self._proxy_station_ship = False
                return best

        if not self.content:
            return None

        frame = self.content.ships.get("outpost_regular")
        if not frame:
            return None
        ghost = Ship(frame, team=self.player.team if self.player else "player")
        ghost.kinematics.position = Vector3(station_pos)
        yaw = math.degrees(math.atan2(approach_dir.x, approach_dir.z)) + 180.0
        ghost.kinematics.rotation = Vector3(0.0, yaw, 0.0)
        ghost.thrusters_active = False
        self._proxy_station_ship = True
        return ghost

    def _update_docking_animation(self, dt: float) -> None:
        if not self.player or not self._docking_sequence:
            return

        seq = self._docking_sequence
        duration = max(1e-3, self.docking_duration)
        progress = max(0.0, min(1.0, self.state_timer / duration))
        first_phase = 0.65
        if progress < first_phase:
            phase = progress / first_phase
            eased = 1.0 - (1.0 - phase) ** 2
            target = seq.start + (seq.entry - seq.start) * eased
        else:
            phase = (progress - first_phase) / max(1e-5, 1.0 - first_phase)
            eased = phase * phase * (3.0 - 2.0 * phase)
            target = seq.entry + (seq.dock - seq.entry) * eased

        self.player.kinematics.position = Vector3(target)
        if self._docking_last_position is not None:
            delta = self.player.kinematics.position - self._docking_last_position
            self.player.kinematics.velocity = delta * (1.0 / max(1e-3, dt))
        self._docking_last_position = Vector3(self.player.kinematics.position)

        forward_raw = seq.start_forward.lerp(seq.dock_forward, progress)
        if forward_raw.length_squared() <= 1e-6:
            forward = seq.dock_forward
        else:
            forward = forward_raw.normalize()
        yaw = math.degrees(math.atan2(forward.x, forward.z))
        pitch = math.degrees(math.asin(max(-1.0, min(1.0, -forward.y))))
        self.player.kinematics.rotation = Vector3(pitch, yaw, 0.0)
        self.player.kinematics.angular_velocity = Vector3()
        self.player.thrusters_active = progress < 0.98

        if self.cutscene_camera:
            self.cutscene_camera.distance = 24.0 + 8.0 * (1.0 - progress)
            self.cutscene_camera.height = 5.6 + 1.2 * (1.0 - progress)
            self.cutscene_camera.look_ahead_distance = 0.0
            self.cutscene_camera.update(self.player, dt, freelook_active=False)


__all__ = ["OutpostInteriorScene"]
