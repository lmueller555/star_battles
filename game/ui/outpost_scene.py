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
from game.render.camera import ChaseCamera, DEFAULT_SHIP_LENGTHS
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
class _RoomLabel:
    text: str
    position: Vector2
    height_offset: float
    color: Tuple[int, int, int]


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
        self.labels: List[_RoomLabel] = []
        self.spawn_point = Vector2()
        self._build()

    def _build(self) -> None:
        tile = self.tile_size
        # Primary hangar with adjacent service corridor and rooms.
        hangar = pygame.Rect(2, 8, 30, 20)
        hangar_entry = pygame.Rect(30, 14, 6, 8)
        main_hall = pygame.Rect(36, 12, 16, 12)
        hall_terminus = pygame.Rect(52, 14, 4, 8)
        upper_door = pygame.Rect(36, 9, 8, 5)
        fleet_shop = pygame.Rect(34, 2, 18, 8)
        lower_door = pygame.Rect(36, 23, 8, 6)
        weapons_bay = pygame.Rect(34, 28, 18, 8)
        maintenance = pygame.Rect(32, 20, 4, 8)
        service_nook = pygame.Rect(48, 18, 4, 8)

        rooms = [
            hangar,
            hangar_entry,
            main_hall,
            hall_terminus,
            upper_door,
            fleet_shop,
            lower_door,
            weapons_bay,
            maintenance,
            service_nook,
        ]

        for rect in rooms:
            self._carve(rect)
            self.rooms.append(rect)

        self.spawn_point = self._tile_center(hangar.left + hangar.width // 2, hangar.top + hangar.height // 2)

        # Decorative floor strips to add visual depth.
        hangar_detail_start = hangar.x * tile + int(tile * 0.6)
        hangar_detail_width = hangar.width * tile - int(tile * 1.2)
        for idx in range(8):
            self.floor_details.append(
                pygame.Rect(
                    hangar_detail_start,
                    (hangar.y * tile) + idx * int(tile * 2.2) + int(tile * 0.5),
                    hangar_detail_width,
                    int(tile * 0.28),
                )
            )

        corridor_strip_left = main_hall.x * tile + int(tile * 0.8)
        corridor_strip_width = main_hall.width * tile - int(tile * 1.6)
        for idx in range(3):
            self.floor_details.append(
                pygame.Rect(
                    corridor_strip_left,
                    (main_hall.y + idx * 4) * tile + int(tile * 0.6),
                    corridor_strip_width,
                    int(tile * 0.24),
                )
            )

        # Area lights to add atmosphere along the hangar and hallway.
        light_tiles = [
            (8, 18),
            (14, 18),
            (20, 18),
            (26, 18),
            (32, 18),
            (36, 14),
            (42, 14),
            (48, 14),
            (36, 22),
            (42, 22),
            (48, 22),
            (40, 6),
            (44, 30),
        ]
        for x, y in light_tiles:
            self.lights.append(
                _LightSource(
                    position=self._tile_center(x, y),
                    radius=tile * 5.8,
                    pulse_speed=0.76 + (x + y) * 0.025,
                    intensity=0.62 + 0.12 * ((x * 11 + y * 7) % 3),
                )
            )

        # Room signage anchors for future interactions.
        self.labels.extend(
            [
                _RoomLabel(
                    text="Hangar Bay",
                    position=self._tile_center(hangar.left + hangar.width // 2, hangar.top + hangar.height // 2),
                    height_offset=tile * 2.4,
                    color=(182, 226, 255),
                ),
                _RoomLabel(
                    text="Fleet Shop",
                    position=self._tile_center(fleet_shop.left + fleet_shop.width // 2, upper_door.top),
                    height_offset=tile * 1.9,
                    color=(180, 220, 255),
                ),
                _RoomLabel(
                    text="Weapons Bay",
                    position=self._tile_center(weapons_bay.left + weapons_bay.width // 2, lower_door.bottom - 1),
                    height_offset=tile * 1.9,
                    color=(220, 200, 180),
                ),
            ]
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
        self.disembark_duration = 4.2
        self.layout = _InteriorLayout(cols=56, rows=36, tile_size=96)
        self.player_position = Vector2(self.layout.spawn_point)
        self.player_velocity = Vector2()
        self.player_heading = Vector2(1.0, 0.0)
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
        self._hangar_ship_ghost: Optional[Ship] = None
        self._hangar_ship_center = Vector3()
        self._initial_forward = Vector2(1.0, 0.0)

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
        self.player_heading = Vector2(1.0, 0.0)
        self.camera_position = self.player_position - self.viewport_size / 2
        self.elapsed_time = 0.0
        self.player_yaw = math.pi / 2
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
        self._hangar_ship_ghost = None
        self._hangar_ship_center = Vector3()
        self._initial_forward = Vector2(math.sin(self.player_yaw), -math.cos(self.player_yaw))
        self._setup_docking_sequence()
        self._prepare_hangar_ship_model()

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

    def _prepare_hangar_ship_model(self) -> None:
        self._hangar_ship_ghost = None
        self._hangar_ship_center = Vector3()
        if not self.player:
            return

        forward_2d = Vector2(math.sin(self.player_yaw), -math.cos(self.player_yaw))
        if forward_2d.length_squared() <= 1e-6:
            forward_2d = Vector2(1.0, 0.0)
        else:
            forward_2d = forward_2d.normalize()
        self._initial_forward = Vector2(forward_2d)

        ghost = Ship(self.player.frame, team=self.player.team)
        ghost.kinematics.velocity = Vector3()
        ghost.kinematics.angular_velocity = Vector3()
        ghost.thrusters_active = False

        length = self._estimate_ship_length(ghost)
        ship_forward = Vector3(forward_2d.x, 0.0, -forward_2d.y)
        if ship_forward.length_squared() <= 1e-6:
            ship_forward = Vector3(1.0, 0.0, 0.0)
        ship_forward = ship_forward.normalize()
        front_tip = -ship_forward * 25.0
        center = front_tip - ship_forward * (length * 0.5)
        center.y = self.layout.tile_size * 0.45

        yaw = math.degrees(math.atan2(ship_forward.x, ship_forward.z))
        ghost.kinematics.position = center
        ghost.kinematics.rotation = Vector3(0.0, yaw, 0.0)

        self._hangar_ship_center = center
        self._hangar_ship_ghost = ghost

    def _estimate_ship_length(self, ship: Ship) -> float:
        length_attr = getattr(ship.frame, "length", None)
        if isinstance(length_attr, (int, float)) and length_attr > 0.0:
            return float(length_attr)

        default_length = DEFAULT_SHIP_LENGTHS.get(ship.frame.size)
        if default_length is not None:
            length = float(default_length)
        else:
            length = float(DEFAULT_SHIP_LENGTHS.get("Strike", 40.0))

        if ship.frame.hardpoints:
            z_values = [hp.position.z for hp in ship.frame.hardpoints]
            if z_values:
                extent = max(z_values) - min(z_values)
                if extent > 0.0:
                    length = float(extent)

        return max(10.0, length)

    def _draw_ship_in_hangar(self, surface: pygame.Surface, horizon: int) -> None:
        ghost = self._hangar_ship_ghost
        if not ghost:
            return

        view_forward_2d = Vector2(math.sin(self.player_yaw), -math.cos(self.player_yaw))
        if view_forward_2d.length_squared() <= 1e-6:
            view_forward_2d = Vector2(self._initial_forward)
        view_forward = Vector3(view_forward_2d.x, 0.0, -view_forward_2d.y)
        if view_forward.length_squared() <= 1e-6:
            view_forward = Vector3(0.0, 0.0, 1.0)
        view_forward = view_forward.normalize()

        up = Vector3(0.0, 1.0, 0.0)
        if abs(view_forward.dot(up)) > 0.98:
            up = Vector3(0.0, 0.0, 1.0)
        right = up.cross(view_forward)
        if right.length_squared() <= 1e-6:
            right = Vector3(1.0, 0.0, 0.0)
        else:
            right = right.normalize()
            up = view_forward.cross(right)
            if up.length_squared() <= 1e-6:
                up = Vector3(0.0, 1.0, 0.0)
            else:
                up = up.normalize()

        eye_height = self.layout.tile_size * 0.45
        camera = ChaseCamera(math.degrees(self._first_person_fov), surface.get_width() / max(1, surface.get_height()))
        camera.position = Vector3(0.0, eye_height, 0.0)
        camera.forward = view_forward
        camera.right = right
        camera.up = up
        camera.distance = 0.0
        camera.height = 0.0
        camera.shoulder = 0.0
        camera.look_ahead_distance = 0.0
        camera.look_ahead_factor = 0.0
        camera.lock_blend = 0.0

        ghost.kinematics.position = self._hangar_ship_center

        to_ship = ghost.kinematics.position - camera.position
        planar = Vector3(to_ship.x, 0.0, to_ship.z)
        look_alignment = 0.0
        if planar.length_squared() > 1e-6:
            look_alignment = max(0.0, view_forward.dot(planar.normalize()))

        visibility = look_alignment
        if visibility <= 1e-3:
            return

        width, height = surface.get_size()
        overlay = pygame.Surface((width, height), pygame.SRCALPHA)
        renderer = VectorRenderer(overlay)
        renderer.draw_ship(camera, ghost)

        fade_start = max(0, min(height, horizon + int(height * 0.18)))
        fade_height = max(int(height * 0.34), height - fade_start)
        if fade_height > 0:
            fade_mask = pygame.Surface((width, fade_height), pygame.SRCALPHA)
            for y in range(fade_height):
                t = y / max(1, fade_height - 1)
                fade_mask.fill((0, 0, 0, int(255 * t)), pygame.Rect(0, y, width, 1))
            overlay.blit(fade_mask, (0, height - fade_height), special_flags=pygame.BLEND_RGBA_SUB)

        shading = pygame.Surface((width, height), pygame.SRCALPHA)
        shading.fill((6, 12, 22, int(120 * (1.0 - visibility))))
        overlay.blit(shading, (0, 0), special_flags=pygame.BLEND_RGBA_ADD)
        overlay.set_alpha(int(220 * visibility))
        surface.blit(overlay, (0, 0))

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
        target_yaw = math.pi / 2
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

    def _render_room_labels(
        self,
        surface: pygame.Surface,
        position: Vector2,
        yaw: float,
        horizon: int,
    ) -> None:
        if not self.layout.labels or not self.status_font:
            return

        width, height = surface.get_size()
        overlay = pygame.Surface((width, height), pygame.SRCALPHA)
        forward = Vector2(math.sin(yaw), -math.cos(yaw))
        right = Vector2(forward.y, -forward.x)
        depth_scale = width / (2.0 * math.tan(self._first_person_fov / 2.0))

        for label in self.layout.labels:
            offset = label.position - position
            forward_dist = offset.dot(forward)
            if forward_dist <= 80.0:
                continue
            lateral = offset.dot(right)
            screen_x = width / 2 + (lateral / max(1e-3, forward_dist)) * depth_scale
            if screen_x < -200 or screen_x > width + 200:
                continue

            depth_factor = max(0.25, min(1.0, 420.0 / (forward_dist + 60.0)))
            screen_y = horizon - int(label.height_offset * depth_factor)
            if screen_y < 40 or screen_y > height - 40:
                continue

            text_surface = self.status_font.render(label.text.upper(), True, label.color)
            text_surface = text_surface.convert_alpha()
            text_surface.set_alpha(int(220 * depth_factor))

            padding_x = 18
            padding_y = 10
            panel_rect = text_surface.get_rect()
            panel_rect.center = (int(screen_x), int(screen_y))
            panel_rect.inflate_ip(padding_x, padding_y)
            panel_color = (18, 32, 52, int(160 * depth_factor))
            border_color = (90, 150, 210, int(200 * depth_factor))

            pygame.draw.rect(overlay, panel_color, panel_rect, border_radius=8)
            pygame.draw.rect(overlay, border_color, panel_rect, 2, border_radius=8)

            text_rect = text_surface.get_rect(center=panel_rect.center)
            overlay.blit(text_surface, text_rect)

        surface.blit(overlay, (0, 0))

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
            surface.blit(walkway, (0, 0), special_flags=pygame.BLEND_ADD)

        self._render_light_markers(surface, position, yaw, horizon)
        self._render_room_labels(surface, position, yaw, horizon)
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
            pygame.draw.polygon(glass_surface, (70, 120, 170, glass_alpha), glass_points)
            highlight = pygame.Surface((width, height), pygame.SRCALPHA)
            pygame.draw.polygon(highlight, (150, 220, 255, glass_alpha // 3), glass_points)
            glass_surface.blit(highlight, (0, 0), special_flags=pygame.BLEND_RGBA_ADD)
            surface.blit(glass_surface, (0, 0))

        cockpit_overlay = pygame.Surface((width, height), pygame.SRCALPHA)
        panel_height = max(56, _to_int(height * (0.28 - egress_ease * 0.12)))
        panel_top = height - panel_height
        panel_rect = pygame.Rect(_to_int(width * 0.06), panel_top, _to_int(width * 0.88), panel_height)
        panel_alpha = int(220 * (1.0 - egress_ease * 0.7))
        pygame.draw.rect(cockpit_overlay, (18, 30, 48, panel_alpha), panel_rect, border_radius=24)
        pygame.draw.rect(cockpit_overlay, (60, 136, 200, 160), panel_rect, 2)

        screen_rect = pygame.Rect(panel_rect.left + 24, panel_top + _to_int(panel_height * 0.12), _to_int(width * 0.12), _to_int(panel_height * 0.22))
        pygame.draw.rect(cockpit_overlay, (26, 50, 90, 200), screen_rect, border_radius=8)
        pygame.draw.rect(cockpit_overlay, (120, 200, 255, 180), screen_rect.inflate(-8, -8), 2)
        mirror_screen = pygame.Rect(panel_rect.right - screen_rect.width - 24, screen_rect.top, screen_rect.width, screen_rect.height)
        pygame.draw.rect(cockpit_overlay, (26, 50, 90, 200), mirror_screen, border_radius=8)
        pygame.draw.rect(cockpit_overlay, (120, 200, 255, 160), mirror_screen.inflate(-8, -8), 2)

        gauge_count = 4
        for idx in range(gauge_count):
            gauge_width = panel_rect.width // (gauge_count + 3)
            gauge_left = panel_rect.left + gauge_width * (idx + 2)
            gauge_rect = pygame.Rect(gauge_left, panel_top + _to_int(panel_height * 0.32), gauge_width, _to_int(panel_height * 0.18))
            pygame.draw.rect(cockpit_overlay, (26, 46, 70, 200), gauge_rect, border_radius=6)
            fill_height = max(6, int(gauge_rect.height * (0.25 + 0.6 * (1.0 - approach_ease) * (1.0 - idx / (gauge_count + 1)))))
            fill_rect = pygame.Rect(gauge_rect.left + 4, gauge_rect.bottom - fill_height - 4, gauge_rect.width - 8, fill_height)
            pygame.draw.rect(cockpit_overlay, (90, 200, 255, 170), fill_rect, border_radius=4)

        holo_radius = max(48, _to_int(panel_height * 0.28))
        holo_center = (_to_int(center_x), panel_top + _to_int(panel_height * 0.42))
        pygame.draw.circle(cockpit_overlay, (30, 56, 90, 180), holo_center, holo_radius, 0)
        scan_radius = max(18, int(holo_radius * (0.32 + 0.6 * (1.0 - brake_ease))))
        pygame.draw.circle(cockpit_overlay, (120, 220, 255, 200), holo_center, scan_radius, 2)
        sweep_angle = approach_ease * math.pi * 0.8 + brake_ease * 0.3
        indicator = (
            _to_int(holo_center[0] + math.sin(sweep_angle) * holo_radius * 0.6),
            _to_int(holo_center[1] - math.cos(sweep_angle) * holo_radius * 0.6),
        )
        pygame.draw.circle(cockpit_overlay, (170, 240, 255, 210), indicator, 6, 0)
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

        if egress_ease > 0.0:
            first_person = pygame.Surface((width, height), pygame.SRCALPHA)
            horizon = self._render_first_person_view(
                first_person,
                self.player_position,
                self.player_yaw,
                0.0,
            )
            self._draw_ship_in_hangar(first_person, horizon)
            first_person.set_alpha(_to_int(255 * egress_ease))
            surface.blit(first_person, (0, -_to_int((1.0 - egress_ease) * height * 0.04)))

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

    def _render_exploration(self, surface: pygame.Surface) -> None:
        horizon = self._render_first_person_view(
            surface,
            self.player_position,
            self.player_yaw,
            self.head_bob_offset,
        )

        width, height = surface.get_size()
        self._draw_ship_in_hangar(surface, horizon)

        if self.caption_font:
            label = self.caption_font.render("OUTPOST INTERIOR", True, (162, 208, 246))
            surface.blit(label, (24, 24))
            if self.status_font:
                location = self.status_font.render("Hangar Bay · Service Concourse", True, (124, 170, 208))
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
