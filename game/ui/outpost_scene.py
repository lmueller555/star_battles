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
from game.render.camera import ChaseCamera
from game.render.renderer import VectorRenderer


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


@dataclass
class _DockingSequence:
    start: Vector3
    entry: Vector3
    dock: Vector3
    start_forward: Vector3
    dock_forward: Vector3


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
        self.player_yaw: float = 0.0
        self.head_bob_phase: float = 0.0
        self.head_bob_offset: float = 0.0
        self.cutscene_camera: Optional[ChaseCamera] = None
        self.cutscene_station_ship: Optional[Ship] = None
        self._docking_sequence: Optional[_DockingSequence] = None
        self._docking_last_position: Optional[Vector3] = None
        self._first_person_fov: float = math.radians(78.0)
        self._gradient_cache_size: tuple[int, int] = (0, 0)
        self._ceiling_gradient: Optional[pygame.Surface] = None
        self._floor_gradient: Optional[pygame.Surface] = None
        self._proxy_station_ship: bool = False

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
        self.player_yaw = 0.0
        self.head_bob_phase = 0.0
        self.head_bob_offset = 0.0
        self.cutscene_camera = None
        self.cutscene_station_ship = None
        self._docking_sequence = None
        self._docking_last_position = None
        self._gradient_cache_size = (0, 0)
        self._ceiling_gradient = None
        self._floor_gradient = None
        self._proxy_station_ship = False
        self.state = _InteriorState.DOCKING
        self.state_timer = 0.0
        self.status_font = pygame.font.SysFont("consolas", 20)
        self.caption_font = pygame.font.SysFont("consolas", 28)
        pygame.mouse.set_visible(True)
        pygame.event.set_grab(False)
        self._setup_docking_sequence()

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

        start_forward = self.player.kinematics.forward()
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
        if self.viewport_size.y > 1e-5:
            aspect = float(self.viewport_size.x) / float(self.viewport_size.y)
        self.cutscene_camera = ChaseCamera(64.0, aspect)
        self.cutscene_camera.distance = 28.0
        self.cutscene_camera.height = 6.5
        self.cutscene_camera.shoulder = 0.0
        self.cutscene_camera.look_ahead_factor = 0.0
        self.cutscene_camera.look_ahead_response = 6.0
        self.cutscene_camera.lock_response = 4.0
        self.cutscene_camera.position = (
            self.player.kinematics.position
            - self.player.kinematics.forward() * self.cutscene_camera.distance
            + self.player.kinematics.up() * self.cutscene_camera.height
        )
        self.cutscene_camera.forward = self.player.kinematics.forward()
        self.cutscene_camera.up = self.player.kinematics.up()
        right = self.cutscene_camera.forward.cross(self.cutscene_camera.up)
        if right.length_squared() > 1e-6:
            self.cutscene_camera.right = right.normalize()
            self.cutscene_camera.up = self.cutscene_camera.right.cross(self.cutscene_camera.forward).normalize()
        else:
            self.cutscene_camera.right = Vector3(1.0, 0.0, 0.0)

        self.cutscene_station_ship = self._locate_station_visual(station_pos, approach_dir)

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

    def _update_disembark(self, dt: float) -> None:
        self.player_velocity *= max(0.0, 1.0 - dt * 4.0)
        self.head_bob_offset *= max(0.0, 1.0 - dt * 5.0)
        target_yaw = 0.0
        delta = target_yaw - self.player_yaw
        if delta > math.pi:
            delta -= 2.0 * math.pi
        elif delta < -math.pi:
            delta += 2.0 * math.pi
        self.player_yaw += delta * min(1.0, dt * 2.0)
        if abs(self.player_yaw) < 1e-3:
            self.player_yaw = 0.0

    def _ensure_gradients(self, width: int, height: int) -> int:
        if self._gradient_cache_size == (width, height) and self._ceiling_gradient and self._floor_gradient:
            horizon_base = int(height * 0.46)
            return horizon_base

        horizon_base = max(24, int(height * 0.46))
        ceiling = pygame.Surface((width, horizon_base), pygame.SRCALPHA)
        for y in range(horizon_base):
            t = y / max(1, horizon_base - 1)
            shade = int(14 + 26 * t)
            color = (shade, shade + 8, shade + 22, 255)
            pygame.draw.line(ceiling, color, (0, y), (width, y))

        floor_height = max(24, height - horizon_base)
        floor = pygame.Surface((width, floor_height), pygame.SRCALPHA)
        for y in range(floor_height):
            t = y / max(1, floor_height - 1)
            shade = int(24 + 36 * t)
            color = (shade, shade + 14, shade + 24, 255)
            pygame.draw.line(floor, color, (0, y), (width, y))

        self._ceiling_gradient = ceiling
        self._floor_gradient = floor
        self._gradient_cache_size = (width, height)
        return horizon_base

    def _render_light_markers(
        self,
        surface: pygame.Surface,
        position: Vector2,
        yaw: float,
        horizon: int,
    ) -> None:
        if not self.layout.lights:
            return

        width, height = surface.get_size()
        overlay = pygame.Surface((width, height), pygame.SRCALPHA)
        forward = Vector2(math.sin(yaw), -math.cos(yaw))
        right = Vector2(forward.y, -forward.x)
        depth_scale = width / (2.0 * math.tan(self._first_person_fov / 2.0))

        for light in self.layout.lights:
            offset = light.position - position
            forward_dist = offset.dot(forward)
            lateral = offset.dot(right)
            if forward_dist <= 60.0:
                continue
            screen_x = width / 2 + (lateral / forward_dist) * depth_scale
            if screen_x < -180 or screen_x > width + 180:
                continue
            depth_factor = max(0.25, min(1.0, 320.0 / (forward_dist + 1.0)))
            base_y = horizon + int((height - horizon) * depth_factor)
            radius = max(18, int(3600.0 / (forward_dist + 180.0)))
            pulse = 0.6 + 0.4 * math.sin(self.elapsed_time * light.pulse_speed)
            alpha = int(160 * light.intensity * pulse * min(1.0, 480.0 / (forward_dist + 60.0)))
            gradient = pygame.Surface((radius * 2, radius * 2), pygame.SRCALPHA)
            pygame.draw.circle(gradient, (90, 200, 255, max(30, alpha)), (radius, radius), radius)
            overlay.blit(
                gradient,
                (int(screen_x - radius), int(base_y - radius)),
                special_flags=pygame.BLEND_ADD,
            )

        surface.blit(overlay, (0, 0), special_flags=pygame.BLEND_ADD)

    def _render_first_person_view(
        self,
        surface: pygame.Surface,
        position: Vector2,
        yaw: float,
        bob_offset: float,
        *,
        show_walkway: bool = True,
    ) -> int:
        width, height = surface.get_size()
        horizon_base = self._ensure_gradients(width, height)
        offset = int(round(bob_offset))
        surface.fill((10, 16, 26))
        if self._ceiling_gradient:
            surface.blit(self._ceiling_gradient, (0, -offset))
        horizon = horizon_base + offset
        if self._floor_gradient:
            surface.blit(self._floor_gradient, (0, horizon_base - offset))

        tile_size = self.layout.tile_size
        pos_x = position.x / tile_size
        pos_y = position.y / tile_size
        dir_x = math.sin(yaw)
        dir_y = -math.cos(yaw)
        right_x = dir_y
        right_y = -dir_x
        plane_scale = math.tan(self._first_person_fov / 2.0)
        plane_x = right_x * plane_scale
        plane_y = right_y * plane_scale

        column_step = 2 if width >= 960 else 1
        for column in range(0, width, column_step):
            camera_x = 2.0 * column / width - 1.0
            ray_dir_x = dir_x + plane_x * camera_x
            ray_dir_y = dir_y + plane_y * camera_x
            map_x = int(pos_x)
            map_y = int(pos_y)

            if map_x < 0 or map_y < 0 or map_x >= self.layout.cols or map_y >= self.layout.rows:
                continue

            delta_dist_x = float("inf") if abs(ray_dir_x) < 1e-6 else abs(1.0 / ray_dir_x)
            delta_dist_y = float("inf") if abs(ray_dir_y) < 1e-6 else abs(1.0 / ray_dir_y)

            if ray_dir_x < 0:
                step_x = -1
                side_dist_x = (pos_x - map_x) * delta_dist_x
            else:
                step_x = 1
                side_dist_x = (map_x + 1.0 - pos_x) * delta_dist_x

            if ray_dir_y < 0:
                step_y = -1
                side_dist_y = (pos_y - map_y) * delta_dist_y
            else:
                step_y = 1
                side_dist_y = (map_y + 1.0 - pos_y) * delta_dist_y

            hit = False
            side = 0
            for _ in range(128):
                if side_dist_x < side_dist_y:
                    side_dist_x += delta_dist_x
                    map_x += step_x
                    side = 0
                else:
                    side_dist_y += delta_dist_y
                    map_y += step_y
                    side = 1
                if map_x < 0 or map_y < 0 or map_x >= self.layout.cols or map_y >= self.layout.rows:
                    break
                if not self.layout.walkable[map_y][map_x]:
                    hit = True
                    break
            if not hit:
                continue

            if side == 0:
                perp_dist = side_dist_x - delta_dist_x
            else:
                perp_dist = side_dist_y - delta_dist_y
            perp_dist = max(perp_dist, 1e-3)
            world_dist = perp_dist * tile_size
            wall_height = int((height * tile_size * 0.9) / world_dist)
            wall_height = max(2, min(height * 2, wall_height))
            draw_start = max(0, horizon - wall_height // 2)
            draw_end = min(height, horizon + wall_height // 2)

            accent = (map_x + map_y) % 3
            base_color = (
                70 + accent * 12,
                110 + accent * 10,
                150 + accent * 14,
            )
            shading = max(0.25, min(1.0, 1.15 - world_dist / 1100.0))
            if side == 1:
                shading *= 0.82
            color = tuple(int(c * shading) for c in base_color)
            rect = pygame.Rect(column, draw_start, column_step, max(1, draw_end - draw_start))
            surface.fill(color, rect)
            if column_step > 1:
                highlight = tuple(min(255, int(c * 1.08)) for c in color)
                surface.fill(highlight, pygame.Rect(column, draw_start, 1, rect.height))

        if show_walkway:
            walkway = pygame.Surface((width, height), pygame.SRCALPHA)
            stripes = 7
            for idx in range(stripes):
                depth = (idx + 1) / (stripes + 1)
                band_y = horizon + int((height - horizon) * depth * 0.92)
                band_width = width * (0.18 + depth * 0.65)
                alpha = int(160 * max(0.0, 1.0 - depth * 1.05))
                color = (80, 160, 220, alpha)
                left = int(width / 2 - band_width / 2)
                right = int(width / 2 + band_width / 2)
                pygame.draw.line(walkway, color, (left, band_y), (right, band_y), 4)
            pygame.draw.line(
                walkway,
                (120, 220, 255, 80),
                (width // 2, horizon),
                (width // 2, height),
                2,
            )
            surface.blit(walkway, (0, 0), special_flags=pygame.BLEND_ADD)

        self._render_light_markers(surface, position, yaw, horizon)
        return horizon

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
            self._update_docking_animation(dt)
            if self.state_timer >= self.docking_duration:
                self.state = _InteriorState.DISEMBARK
                self.state_timer = 0.0
            return
        if self.state == _InteriorState.DISEMBARK:
            self.state_timer += dt
            self._update_disembark(dt)
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
        mouse_dx, _ = self.input.mouse()
        look_input = self.input.axis_state.get("look_x", 0.0)
        yaw_delta = mouse_dx * 0.003 + look_input * dt * 2.5
        if abs(yaw_delta) > 1e-5:
            self.player_yaw += yaw_delta
            while self.player_yaw > math.pi:
                self.player_yaw -= 2.0 * math.pi
            while self.player_yaw < -math.pi:
                self.player_yaw += 2.0 * math.pi

        forward_dir = Vector2(math.sin(self.player_yaw), -math.cos(self.player_yaw))
        right_dir = Vector2(forward_dir.y, -forward_dir.x)

        forward_input = self.input.axis_state.get("throttle", 0.0)
        strafe_input = self.input.axis_state.get("strafe_x", 0.0)
        move_vector = forward_dir * forward_input + right_dir * strafe_input
        if move_vector.length_squared() > 1e-5:
            move_vector = move_vector.normalize()
        target_speed = 260.0
        target_velocity = move_vector * target_speed
        self.player_velocity += (target_velocity - self.player_velocity) * min(1.0, dt * 10.0)
        if move_vector.length_squared() <= 1e-6:
            self.player_velocity *= max(0.0, 1.0 - dt * 4.0)
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

        self.player_heading = forward_dir
        speed = self.player_velocity.length()
        bob_strength = min(1.0, speed / 180.0)
        if bob_strength > 0.05:
            self.head_bob_phase += dt * (6.0 + bob_strength * 6.0)
            self.head_bob_offset = math.sin(self.head_bob_phase) * 4.0 * bob_strength
        else:
            self.head_bob_offset *= max(0.0, 1.0 - dt * 6.0)
            if abs(self.head_bob_offset) < 1e-2:
                self.head_bob_offset = 0.0

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

        # Overlay subtle starfield to maintain continuity with space backdrop.
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
        progress = min(1.0, self.state_timer / self.disembark_duration)
        eased = progress ** 1.6
        forward = Vector2(math.sin(self.player_yaw), -math.cos(self.player_yaw))
        travel = forward * (self.layout.tile_size * 0.8 * (1.0 - eased))
        virtual_position = self.player_position - travel
        horizon = self._render_first_person_view(surface, virtual_position, self.player_yaw, 0.0)

        door_width = int(width * 0.28)
        gap = int((1.0 - eased) * (door_width + 40))
        door_height = int(height * 0.58)
        center_y = horizon - int(height * 0.08)
        left_rect = pygame.Rect(width // 2 - door_width - gap, center_y - door_height // 2, door_width, door_height)
        right_rect = pygame.Rect(width // 2 + gap, center_y - door_height // 2, door_width, door_height)
        door_color = (18, 42, 68)
        accent_color = (120, 220, 255)
        pygame.draw.rect(surface, door_color, left_rect)
        pygame.draw.rect(surface, door_color, right_rect)
        pygame.draw.rect(surface, accent_color, left_rect, 2)
        pygame.draw.rect(surface, accent_color, right_rect, 2)

        fade_strength = max(0.0, 1.0 - progress * 1.8)
        if fade_strength > 0.0:
            overlay = pygame.Surface((width, height), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, int(255 * fade_strength)))
            surface.blit(overlay, (0, 0))

        if self.caption_font:
            caption = self.caption_font.render("Touchdown inside the hangar", True, (214, 236, 255))
            surface.blit(caption, (width // 2 - caption.get_width() // 2, int(height * 0.08)))

    def _render_exploration(self, surface: pygame.Surface) -> None:
        horizon = self._render_first_person_view(
            surface,
            self.player_position,
            self.player_yaw,
            self.head_bob_offset,
        )

        width, height = surface.get_size()
        crosshair_color = (210, 240, 255)
        center_y = horizon + int(height * 0.06) + int(self.head_bob_offset)
        center = (width // 2, center_y)
        pygame.draw.circle(surface, crosshair_color, center, 6, 1)
        pygame.draw.line(surface, crosshair_color, (center[0] - 12, center[1]), (center[0] + 12, center[1]), 1)
        pygame.draw.line(surface, crosshair_color, (center[0], center[1] - 12), (center[0], center[1] + 12), 1)

        if self.caption_font:
            label = self.caption_font.render("OUTPOST INTERIOR", True, (162, 208, 246))
            surface.blit(label, (24, 24))
            if self.status_font:
                location = self.status_font.render("Hangar Wing A", True, (124, 170, 208))
                surface.blit(location, (26, 24 + label.get_height() + 6))

        status_overlay = pygame.Surface((width, height), pygame.SRCALPHA)
        vignette_alpha = 120
        pygame.draw.rect(status_overlay, (0, 0, 0, vignette_alpha), status_overlay.get_rect(), 8)
        surface.blit(status_overlay, (0, 0), special_flags=pygame.BLEND_RGBA_SUB)

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
