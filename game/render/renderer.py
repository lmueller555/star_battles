"""Vector renderer built on pygame."""
from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil, floor
import logging
import math
import random
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import pygame
from pygame.math import Vector3

from game.combat.weapons import Projectile
from game.render.camera import CameraFrameData, ChaseCamera
from game.render.geometry import SHIP_GEOMETRY_CACHE, ShipGeometry
from game.ships.ship import Ship
from game.world.asteroids import Asteroid

from game.render.state import ProjectedVertexCache, RenderSpatialState, TelemetryCounters

BACKGROUND = (5, 8, 12)
GRID_MINOR_COLOR = (20, 32, 44)
GRID_MAJOR_COLOR = (34, 52, 72)
SHIP_COLOR = (120, 220, 255)
ENEMY_COLOR = (255, 80, 100)
PROJECTILE_COLOR = (255, 200, 80)
MISSILE_COLOR = (255, 255, 255)
MISSILE_SMOKE_COLOR = (200, 200, 200)
PROJECTILE_RENDER_DISTANCE = 3000.0
PROJECTILE_RENDER_DISTANCE_SQR = PROJECTILE_RENDER_DISTANCE * PROJECTILE_RENDER_DISTANCE

THORIM_PROJECTILE_GLOW = (120, 40, 200)
THORIM_PROJECTILE_CORE = (220, 140, 255)
THORIM_PROJECTILE_OUTER = (170, 70, 230)
THORIM_FRAME_IDS: set[str] = {"thorim_siege", "advanced_thorim"}
THORIM_CHARGE_LOCAL_CENTER = Vector3(0.0, 0.35, 6.2)
THORIM_CHARGE_MIN_RADIUS = 4.8
THORIM_CHARGE_MAX_RADIUS = 20.4
THORIM_LIGHTNING_THRESHOLD = 0.9

# Engine layout presets by ship size. These are expressed using the same
# lightweight local-space units as the wireframe definitions and roughly align
# with common tail geometries for each hull class.
ENGINE_LAYOUTS: dict[str, list[Vector3]] = {
    "Strike": [
        Vector3(-0.65, -0.12, -2.1),
        Vector3(0.65, -0.12, -2.1),
    ],
    "Escort": [
        Vector3(-28.0, -6.0, -58.0),
        Vector3(28.0, -6.0, -58.0),
        Vector3(-20.0, 4.0, -46.0),
        Vector3(20.0, 4.0, -46.0),
    ],
    "Line": [
        Vector3(-92.0, -18.0, -238.0),
        Vector3(92.0, -18.0, -238.0),
        Vector3(-92.0, 18.0, -238.0),
        Vector3(92.0, 18.0, -238.0),
        Vector3(-52.0, -10.0, -212.0),
        Vector3(52.0, -10.0, -212.0),
    ],
    "Capital": [
        Vector3(-51.0, 33.0, -490.0),
        Vector3(51.0, 33.0, -490.0),
        Vector3(-51.0, -33.0, -490.0),
        Vector3(51.0, -33.0, -490.0),
    ],
    "Outpost": [],
}

@dataclass
class AsteroidScreenCache:
    camera_revision: int = -1
    world_revision: int = -1
    center: tuple[float, float] = (0.0, 0.0)
    polygon_points: list[tuple[int, int]] = field(default_factory=list)
    polygon_outline: list[tuple[float, float]] = field(default_factory=list)
    radius_horizontal: float = 0.0
    radius_vertical: float = 0.0


LOGGER = logging.getLogger(__name__)


def _blend(color_a: tuple[int, int, int], color_b: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    amount = max(0.0, min(1.0, amount))
    return tuple(
        int(round(a + (b - a) * amount))
        for a, b in zip(color_a, color_b)
    )


def _darken(color: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    return _blend(color, (0, 0, 0), amount)


def _lighten(color: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    return _blend(color, (255, 255, 255), amount)


def _ship_axes(ship: Ship) -> tuple[Vector3, Vector3, Vector3]:
    basis = ship.kinematics.basis
    forward = basis.forward
    right = basis.right
    up = basis.up
    return right, up, forward




def _ship_geometry_scale(ship: Ship, geometry: ShipGeometry) -> float:
    """Return a scale factor if the frame defines an explicit length override."""

    length_override = getattr(ship.frame, "length", None)
    if geometry.length <= 0.0:
        return 1.0
    if isinstance(length_override, (int, float)) and length_override > 0.0:
        scale = float(length_override) / geometry.length
        if abs(scale - 1.0) < 0.01:
            return 1.0
        return scale
    return 1.0


def _estimate_ship_radius(ship: Ship, geometry: ShipGeometry, scale: float) -> float:
    radius = geometry.radius * scale
    if ship.frame.hardpoints:
        radius = max(
            radius,
            max(hp.position.length() for hp in ship.frame.hardpoints) * scale + 2.0,
        )
    engine_layout = ENGINE_LAYOUTS.get(ship.frame.size)
    if engine_layout:
        radius = max(radius, max(vector.length() for vector in engine_layout) + 2.0)
    return radius + 2.5


def _ship_detail_factor(ship: Ship, distance: float) -> float:
    if getattr(ship.frame, "size", "") == "Strike":
        return 1.0
    if distance <= 2500.0:
        return 1.0
    if distance >= 5000.0:
        return 0.25
    blend = (distance - 2500.0) / 2500.0
    return max(0.25, min(1.0, 1.0 - 0.75 * blend))


def _resample_polyline(
    points: Sequence[tuple[float, float]], fraction: float
) -> list[tuple[float, float]]:
    if fraction >= 0.999 or len(points) <= 2:
        return list(points)
    segment_count = len(points) - 1
    target_segments = max(1, int(math.ceil(segment_count * fraction)))
    if target_segments >= segment_count:
        return list(points)
    cumulative: list[float] = [0.0]
    total_length = 0.0
    for index in range(1, len(points)):
        ax, ay = points[index - 1]
        bx, by = points[index]
        seg_len = math.hypot(bx - ax, by - ay)
        total_length += seg_len
        cumulative.append(total_length)
    if total_length <= 1e-6:
        return [points[0], points[-1]]
    spacing = total_length / target_segments
    sample_count = target_segments + 1
    result: list[tuple[float, float]] = []
    segment_index = 0
    for sample in range(sample_count):
        if sample == sample_count - 1:
            result.append(points[-1])
            continue
        target_distance = spacing * sample
        while (
            segment_index < segment_count - 1
            and cumulative[segment_index + 1] < target_distance - 1e-6
        ):
            segment_index += 1
        start_x, start_y = points[segment_index]
        end_x, end_y = points[segment_index + 1]
        seg_start = cumulative[segment_index]
        seg_end = cumulative[segment_index + 1]
        seg_length = seg_end - seg_start
        if seg_length <= 1e-6:
            result.append((end_x, end_y))
            continue
        t = (target_distance - seg_start) / seg_length
        t = max(0.0, min(1.0, t))
        result.append(
            (
                start_x + (end_x - start_x) * t,
                start_y + (end_y - start_y) * t,
            )
        )
    return result


def _rect_intersects(rect: tuple[float, float, float, float], width: int, height: int) -> bool:
    left, top, right, bottom = rect
    return not (right < 0 or bottom < 0 or left >= width or top >= height)



class VectorRenderer:
    def __init__(self, surface: pygame.Surface) -> None:
        self.surface = surface
        self._rng = random.Random()
        self._ship_geometry_cache: Dict[str, ShipGeometry] = dict(SHIP_GEOMETRY_CACHE)
        self._vertex_cache: Dict[int, ProjectedVertexCache] = {}
        self._asteroid_screen_cache: Dict[int, AsteroidScreenCache] = {}
        self._frame_counters = TelemetryCounters()
        self._telemetry_accum = TelemetryCounters()
        self._frame_active = False
        self._last_report_ms = pygame.time.get_ticks()
        self._telemetry_interval_ms = 2500
        self._current_camera_frame: CameraFrameData | None = None
        self._frame_index = 0
        self._player_ship: Ship | None = None

    def set_player_ship(self, ship: Ship | None) -> None:
        """Designate the player's ship for distance-based redraw scheduling."""

        self._player_ship = ship

    def _flush_frame_counters(self) -> None:
        if (
            self._frame_counters.objects_total
            or self._frame_counters.vertices_projected_total
        ):
            self._telemetry_accum.accumulate(self._frame_counters)
        now = pygame.time.get_ticks()
        if (
            now - self._last_report_ms >= self._telemetry_interval_ms
            and (
                self._telemetry_accum.objects_total
                or self._telemetry_accum.vertices_projected_total
            )
        ):
            avg_vertices = self._telemetry_accum.average_vertices()
            LOGGER.info(
                "Render telemetry: total=%d culled_frustum=%d culled_viewport=%d "
                "drawn_line=%d drawn_aaline=%d avg_vertices=%.2f",
                self._telemetry_accum.objects_total,
                self._telemetry_accum.objects_culled_frustum,
                self._telemetry_accum.objects_culled_viewport,
                self._telemetry_accum.objects_drawn_line,
                self._telemetry_accum.objects_drawn_aaline,
                avg_vertices,
            )
            self._telemetry_accum.reset()
            self._last_report_ms = now
        self._frame_counters.reset()

    def _start_frame(self) -> None:
        if self._frame_active:
            self._flush_frame_counters()
        else:
            self._frame_counters.reset()
        self._frame_index += 1
        self._frame_active = True
        self._current_camera_frame = None

    def _get_camera_frame(self, camera: ChaseCamera) -> CameraFrameData:
        size = self.surface.get_size()
        frame = camera.prepare_frame(size)
        if (
            self._current_camera_frame
            and self._current_camera_frame.revision == frame.revision
            and self._current_camera_frame.screen_size == frame.screen_size
        ):
            return self._current_camera_frame
        self._current_camera_frame = frame
        return frame

    def _ship_redraw_interval(self, ship: Ship, camera: ChaseCamera) -> int:
        player = self._player_ship
        if player is not None:
            try:
                distance = ship.kinematics.position.distance_to(
                    player.kinematics.position
                )
            except AttributeError:
                distance = (ship.kinematics.position - camera.position).length()
        else:
            distance = (ship.kinematics.position - camera.position).length()
        if not math.isfinite(distance):
            distance = 0.0
        interval = 1 + int(distance // 1000.0)
        return max(1, interval)

    def _evaluate_visibility(
        self,
        state: RenderSpatialState,
        frame: CameraFrameData,
    ) -> tuple[bool, float, float]:
        self._frame_counters.objects_total += 1
        radius = max(0.0, state.radius)
        rel = state.center - frame.position
        distance = rel.length()
        if not math.isfinite(distance):
            distance = float("inf")
        if distance - radius > frame.far:
            self._frame_counters.objects_culled_frustum += 1
            return False, distance, 0.0
        z = rel.dot(frame.forward)
        if z + radius < frame.near or z - radius > frame.far:
            self._frame_counters.objects_culled_frustum += 1
            return False, distance, z
        x = rel.dot(frame.right)
        y = rel.dot(frame.up)
        horizontal_limit = z * frame.tan_half_fov * frame.aspect + radius
        vertical_limit = z * frame.tan_half_fov + radius
        if abs(x) > horizontal_limit + radius or abs(y) > vertical_limit + radius:
            self._frame_counters.objects_culled_frustum += 1
            return False, distance, z
        if (
            state.cached_camera_revision == frame.revision
            and state.cached_screen_rect is not None
        ):
            width, height = frame.screen_size
            if not _rect_intersects(state.cached_screen_rect, width, height):
                self._frame_counters.objects_culled_viewport += 1
                return False, distance, z
        return True, distance, z

    def _project_ship_vertices(
        self,
        ship: Ship,
        geometry: ShipGeometry,
        frame: CameraFrameData,
        state: RenderSpatialState,
        origin: Vector3,
        basis: tuple[Vector3, Vector3, Vector3],
        *,
        scale: float,
    ) -> ProjectedVertexCache:
        cache = self._vertex_cache.setdefault(id(ship), ProjectedVertexCache())
        if (
            cache.camera_revision == frame.revision
            and cache.world_revision == state.world_revision
        ):
            return cache
        right, up, forward = basis
        vertices_2d: List[tuple[float, float]] = []
        visibility: List[bool] = []
        min_x = float("inf")
        max_x = float("-inf")
        min_y = float("inf")
        max_y = float("-inf")
        for local in geometry.vertices:
            scaled = Vector3(local) * scale
            world = origin + right * scaled.x + up * scaled.y + forward * scaled.z
            screen, visible = frame.project_point(world)
            vertices_2d.append((screen.x, screen.y))
            visibility.append(visible)
            if visible:
                min_x = min(min_x, screen.x)
                max_x = max(max_x, screen.x)
                min_y = min(min_y, screen.y)
                max_y = max(max_y, screen.y)
        aaline_strips: list[list[tuple[float, float]]] = []
        line_strips: list[list[tuple[int, int]]] = []
        for strip in geometry.strips:
            if len(strip) < 2:
                continue
            current_float: list[tuple[float, float]] = []
            for index in range(len(strip) - 1):
                a_idx = strip[index]
                b_idx = strip[index + 1]
                if visibility[a_idx] and visibility[b_idx]:
                    ax, ay = vertices_2d[a_idx]
                    bx, by = vertices_2d[b_idx]
                    if not current_float:
                        current_float.append((ax, ay))
                    current_float.append((bx, by))
                elif len(current_float) >= 2:
                    aaline_strips.append(current_float)
                    line_strips.append(
                        [(int(round(px)), int(round(py))) for px, py in current_float]
                    )
                    current_float = []
            if len(current_float) >= 2:
                aaline_strips.append(current_float)
                line_strips.append(
                    [(int(round(px)), int(round(py))) for px, py in current_float]
                )

        cache.update(
            frame.revision,
            state.world_revision,
            vertices_2d,
            visibility,
            aaline_strips,
            line_strips,
        )
        if min_x <= max_x and min_y <= max_y:
            state.cached_screen_rect = (min_x, min_y, max_x, max_y)
            state.cached_camera_revision = frame.revision
        else:
            state.clear_cached_projection()
        self._frame_counters.vertices_projected_total += len(geometry.vertices)
        self._frame_counters.objects_projected += 1
        return cache

    @staticmethod
    def _local_to_world(
        origin: Vector3,
        right: Vector3,
        up: Vector3,
        forward: Vector3,
        local: Vector3,
    ) -> Vector3:
        return origin + right * local.x + up * local.y + forward * local.z

    def _draw_speed_streaks(
        self,
        frame: CameraFrameData,
        origin: Vector3,
        right: Vector3,
        up: Vector3,
        forward: Vector3,
        ship: Ship,
        intensity: float,
    ) -> None:
        if intensity <= 0.0:
            return

        tick = pygame.time.get_ticks() * 0.001
        velocity = ship.kinematics.velocity
        direction = velocity.normalize() if velocity.length_squared() > 1e-3 else forward

        streak_count = 6 + int(24 * intensity)
        base_length = 1.6 + 2.4 * intensity
        seed_phase = (ship.render_state.random_seed & 0xFFFF) * 0.001
        for index in range(streak_count):
            lateral = (
                frame.right * self._rng.uniform(-6.0, 6.0)
                + frame.up * self._rng.uniform(-3.5, 3.5)
            )
            forward_offset = direction * self._rng.uniform(-3.0, 6.0)
            start_world = origin + lateral + forward_offset
            end_world = start_world - direction * (
                base_length + self._rng.uniform(0.0, base_length * 0.8)
            )

            start_screen, vis_start = frame.project_point(start_world)
            end_screen, vis_end = frame.project_point(end_world)
            if not (vis_start and vis_end):
                continue

            phase = tick * 3.0 + index * 0.37 + seed_phase
            brightness = max(
                0.0,
                min(1.0, 0.18 + intensity * 0.6 + math.sin(phase) * 0.12),
            )
            streak_color = _blend(BACKGROUND, (210, 240, 255), brightness)
            width = 1 if intensity < 0.55 else 2
            pygame.draw.line(
                self.surface,
                streak_color,
                (int(start_screen.x), int(start_screen.y)),
                (int(end_screen.x), int(end_screen.y)),
                width,
            )

    def _draw_hardpoints(
        self,
        frame: CameraFrameData,
        origin: Vector3,
        right: Vector3,
        up: Vector3,
        forward: Vector3,
        ship: Ship,
        color: tuple[int, int, int],
        *,
        scale: float,
    ) -> None:
        if not ship.mounts:
            return

        for mount in ship.mounts:
            local = Vector3(mount.hardpoint.position) * scale
            base_world = self._local_to_world(origin, right, up, forward, local)
            muzzle_world = base_world + forward * (0.9 * scale)
            direction = ship.hardpoint_direction(mount.hardpoint)
            debug_length = 12.0 * scale
            debug_tip_world = base_world + direction * debug_length

            base_screen, vis_base = frame.project_point(base_world)
            muzzle_screen, vis_muzzle = frame.project_point(muzzle_world)
            debug_screen, vis_debug = frame.project_point(debug_tip_world)
            if not vis_base:
                continue

            armed = bool(mount.weapon_id)
            base_color = _lighten(color, 0.25) if armed else _darken(color, 0.35)
            muzzle_color = _lighten(color, 0.55) if armed else _darken(color, 0.15)
            debug_color = _lighten(muzzle_color, 0.35)
            radius = 3 if ship.frame.size == "Strike" else 4
            pygame.draw.circle(
                self.surface,
                base_color,
                (int(round(base_screen.x)), int(round(base_screen.y))),
                radius,
                0,
            )
            pygame.draw.circle(
                self.surface,
                _darken(base_color, 0.35),
                (int(round(base_screen.x)), int(round(base_screen.y))),
                max(1, radius - 2),
                0,
            )
            if vis_muzzle:
                pygame.draw.aaline(
                    self.surface,
                    muzzle_color,
                    (base_screen.x, base_screen.y),
                    (muzzle_screen.x, muzzle_screen.y),
                    blend=1,
                )
            if vis_debug:
                pygame.draw.aaline(
                    self.surface,
                    debug_color,
                    (base_screen.x, base_screen.y),
                    (debug_screen.x, debug_screen.y),
                    blend=1,
                )

            self._draw_weapon_effect(
                frame,
                origin,
                ship,
                mount,
                base_world,
                muzzle_world,
            )

    def _draw_weapon_effect(
        self,
        frame: CameraFrameData,
        origin: Vector3,
        ship: Ship,
        mount,
        base_world: Vector3,
        muzzle_world: Vector3,
    ) -> None:
        effect_type = getattr(mount, "effect_type", "")
        timer = getattr(mount, "effect_timer", 0.0)
        if not effect_type or timer <= 0.0:
            return
        if effect_type == "point_defense":
            self._draw_point_defense_effect(
                frame,
                origin,
                ship,
                mount,
                base_world,
                muzzle_world,
            )
        elif effect_type == "flak":
            self._draw_flak_effect(
                frame,
                origin,
                ship,
                mount,
                base_world,
            )

    def _draw_point_defense_effect(
        self,
        frame: CameraFrameData,
        origin: Vector3,
        ship: Ship,
        mount,
        base_world: Vector3,
        muzzle_world: Vector3,
    ) -> None:
        duration = getattr(mount, "effect_duration", 0.0) or 0.3
        timer = getattr(mount, "effect_timer", 0.0)
        intensity = max(0.0, min(1.0, timer / max(0.001, duration)))
        if intensity <= 0.0:
            return
        effect_range = getattr(mount, "effect_range", 0.0)
        if effect_range <= 0.0:
            effect_range = 360.0
        gimbal = getattr(mount, "effect_gimbal", 0.0)
        if gimbal <= 0.0:
            gimbal = getattr(getattr(mount, "hardpoint", None), "gimbal", 45.0)
        base_dir = muzzle_world - base_world
        origin_point = muzzle_world
        if base_dir.length_squared() <= 1e-6:
            origin_point = base_world
            base_dir = base_world - origin
        if base_dir.length_squared() <= 1e-6:
            base_dir = ship.hardpoint_direction(getattr(mount, "hardpoint", None))
        base_dir = base_dir.normalize()
        rng = self._mount_rng(mount)
        particle_count = max(6, int(18 + 26 * intensity))
        steps = 6

        def _travel_fraction(t: float) -> float:
            if t <= 0.0:
                return 0.0
            if t >= 1.0:
                return 1.0
            if t <= 0.75:
                return t
            tail = (t - 0.75) / 0.25
            tail = max(0.0, min(1.0, tail))
            eased = 1.0 - (1.0 - tail) ** 3
            return 0.75 + 0.25 * eased

        for _ in range(particle_count):
            direction = self._sample_direction_in_cone(base_dir, gimbal, rng)
            distance = effect_range * rng.uniform(0.4, 0.85)
            for step in range(1, steps + 1):
                time_fraction = step / steps
                travel = _travel_fraction(time_fraction)
                fraction = travel
                position = origin_point + direction * (distance * travel)
                screen, visible = frame.project_point(position)
                if not visible:
                    continue
                fade = intensity * (1.0 - (fraction - 0.5) * 0.35)
                brightness = 0.6 + 0.4 * rng.random()
                red = int(180 + 70 * brightness)
                green = int(30 + 40 * fade)
                blue = int(30 * fade)
                radius = 1 if step < steps else 2
                pygame.draw.circle(
                    self.surface,
                    (min(255, red), min(120, green), min(100, blue)),
                    (int(round(screen.x)), int(round(screen.y))),
                    radius,
                    0,
                )

    def _draw_flak_effect(
        self,
        frame: CameraFrameData,
        origin: Vector3,
        ship: Ship,
        mount,
        base_world: Vector3,
    ) -> None:
        duration = getattr(mount, "effect_duration", 0.0) or 0.5
        timer = getattr(mount, "effect_timer", 0.0)
        intensity = max(0.0, min(1.0, timer / max(0.001, duration)))
        if intensity <= 0.0:
            return
        effect_range = getattr(mount, "effect_range", 0.0)
        if effect_range <= 0.0:
            effect_range = 600.0
        gimbal = getattr(mount, "effect_gimbal", 0.0)
        if gimbal <= 0.0:
            gimbal = getattr(getattr(mount, "hardpoint", None), "gimbal", 55.0)
        base_dir = base_world - origin
        if base_dir.length_squared() <= 1e-6:
            base_dir = ship.hardpoint_direction(getattr(mount, "hardpoint", None))
        base_dir = base_dir.normalize()
        rng = self._mount_rng(mount)
        burst_count = max(4, int(10 + 24 * intensity))
        for _ in range(burst_count):
            direction = self._sample_direction_in_cone(base_dir, gimbal, rng)
            distance = effect_range * rng.uniform(0.2, 1.0)
            position = base_world + direction * distance
            screen, visible = frame.project_point(position)
            if not visible:
                continue
            radius = max(2, int(round(2 + 3 * rng.random() * (0.6 + intensity))))
            core_color = _blend((255, 170, 90), (255, 220, 180), rng.random() * 0.5 + 0.2)
            halo_color = _blend(core_color, (255, 255, 255), 0.45)
            pygame.draw.circle(
                self.surface,
                core_color,
                (int(round(screen.x)), int(round(screen.y))),
                radius,
                0,
            )
            pygame.draw.circle(
                self.surface,
                halo_color,
                (int(round(screen.x)), int(round(screen.y))),
                radius + 1,
                1,
            )
            spark_count = 3 + rng.randint(0, 2)
            for _ in range(spark_count):
                spark_dir = self._sample_direction_in_cone(base_dir, gimbal * 0.5, rng)
                spark_length = effect_range * 0.05 * rng.uniform(0.2, 1.0)
                spark_start = position
                spark_end = spark_start + spark_dir * spark_length
                start_screen, vis_start = frame.project_point(spark_start)
                end_screen, vis_end = frame.project_point(spark_end)
                if vis_start and vis_end:
                    pygame.draw.aaline(
                        self.surface,
                        _blend(core_color, (255, 255, 255), 0.25),
                        (start_screen.x, start_screen.y),
                        (end_screen.x, end_screen.y),
                        blend=1,
                    )

    @staticmethod
    def _sample_direction_in_cone(base_direction: Vector3, gimbal: float, rng: random.Random) -> Vector3:
        axis = Vector3(base_direction)
        if axis.length_squared() <= 1e-6:
            return Vector3(axis)
        axis = axis.normalize()
        angle = math.radians(max(0.0, min(180.0, gimbal)))
        if angle <= 0.0:
            return axis
        cos_max = math.cos(angle)
        cos_theta = rng.uniform(cos_max, 1.0)
        sin_theta = math.sqrt(max(0.0, 1.0 - cos_theta * cos_theta))
        phi = rng.uniform(0.0, 2.0 * math.pi)
        up = Vector3(0.0, 1.0, 0.0)
        if abs(axis.dot(up)) > 0.98:
            up = Vector3(1.0, 0.0, 0.0)
        tangent = axis.cross(up)
        if tangent.length_squared() <= 1e-6:
            tangent = axis.cross(Vector3(0.0, 0.0, 1.0))
        tangent = tangent.normalize()
        bitangent = tangent.cross(axis)
        if bitangent.length_squared() <= 1e-6:
            bitangent = axis.cross(tangent)
        bitangent = bitangent.normalize()
        direction = (
            axis * cos_theta
            + tangent * (sin_theta * math.cos(phi))
            + bitangent * (sin_theta * math.sin(phi))
        )
        if direction.length_squared() <= 1e-6:
            return axis
        return direction.normalize()

    @staticmethod
    def _mount_rng(mount) -> random.Random:
        tick_ms = pygame.time.get_ticks()
        phase = tick_ms // 33
        seed_base = getattr(mount, "effect_seed", 0)
        seed = (seed_base ^ (phase & 0xFFFFFFFF)) & 0xFFFFFFFF
        return random.Random(seed)

    def _draw_engines(
        self,
        frame: CameraFrameData,
        origin: Vector3,
        right: Vector3,
        up: Vector3,
        forward: Vector3,
        ship: Ship,
        color: tuple[int, int, int],
        *,
        scale: float,
    ) -> None:
        layout = ENGINE_LAYOUTS.get(ship.frame.size, ENGINE_LAYOUTS.get("Strike", []))
        if not layout:
            return

        tick = pygame.time.get_ticks() * 0.001
        for index, local in enumerate(layout):
            base_world = self._local_to_world(origin, right, up, forward, local)
            nozzle_world = base_world - forward * (0.35 * scale)
            base_screen, vis_base = frame.project_point(base_world)
            nozzle_screen, vis_nozzle = frame.project_point(nozzle_world)
            if not vis_base:
                continue

            base_pos = (int(round(base_screen.x)), int(round(base_screen.y)))
            radius = 4 if ship.frame.size == "Strike" else 5
            pygame.draw.circle(self.surface, _darken(color, 0.45), base_pos, radius, 1)
            pygame.draw.circle(self.surface, _lighten(color, 0.15), base_pos, max(1, radius - 2), 0)

            if ship.thrusters_active and vis_nozzle:
                flicker = 0.6 + 0.4 * math.sin(tick * 12.0 + index * 1.3)
                flame_length = (1.6 + 1.2 * flicker) * scale
                flame_base = base_world - forward * (0.2 * scale)
                flame_tip = flame_base - forward * flame_length
                flame_base_screen, vis_base_flame = frame.project_point(flame_base)
                flame_tip_screen, vis_tip_flame = frame.project_point(flame_tip)
                if vis_base_flame and vis_tip_flame:
                    flame_color = _blend((130, 200, 255), (255, 190, 140), flicker * 0.6)
                    width = 2 + int(round(flicker * 2.0))
                    pygame.draw.line(
                        self.surface,
                        flame_color,
                        (int(round(flame_base_screen.x)), int(round(flame_base_screen.y))),
                        (int(round(flame_tip_screen.x)), int(round(flame_tip_screen.y))),
                        width,
                    )
                    glow_radius = max(2, radius - 1)
                    glow_color = _blend((60, 120, 220), (255, 220, 160), flicker * 0.5)
                    pygame.draw.circle(self.surface, glow_color, base_pos, glow_radius, 0)

    def _draw_thorim_charge(
        self,
        frame: CameraFrameData,
        origin: Vector3,
        right: Vector3,
        up: Vector3,
        forward: Vector3,
        ship: Ship,
        *,
        scale: float,
    ) -> None:
        max_power = getattr(ship.stats, "power_points", 0.0)
        if max_power <= 0.0:
            return

        ratio = max(0.0, min(1.0, ship.power / max_power))
        if ratio <= 0.0:
            return

        center_local = THORIM_CHARGE_LOCAL_CENTER * scale
        center_world = self._local_to_world(origin, right, up, forward, center_local)
        center_screen, vis_center = frame.project_point(center_world)
        if not vis_center:
            return

        local_radius = THORIM_CHARGE_MIN_RADIUS + (
            THORIM_CHARGE_MAX_RADIUS - THORIM_CHARGE_MIN_RADIUS
        ) * ratio
        local_radius = min(THORIM_CHARGE_MAX_RADIUS, max(THORIM_CHARGE_MIN_RADIUS, local_radius))
        world_radius = local_radius * scale

        radius_world = center_world + right * world_radius
        radius_screen, vis_radius = frame.project_point(radius_world)
        if not vis_radius:
            radius_world = center_world + up * world_radius
            radius_screen, vis_radius = frame.project_point(radius_world)
        if not vis_radius:
            depth = (center_world - frame.position).dot(frame.forward)
            if depth <= frame.near:
                return
            # Approximate the on-screen radius using the projection parameters.
            pixels_per_unit = (frame.fov_factor / frame.aspect) / depth * frame.screen_size[0] * 0.5
            screen_radius = max(2, int(round(world_radius * pixels_per_unit)))
        else:
            dx = radius_screen.x - center_screen.x
            dy = radius_screen.y - center_screen.y
            screen_radius = max(2, int(round(math.hypot(dx, dy))))

        center_pos = (int(round(center_screen.x)), int(round(center_screen.y)))
        pulse = 0.25 + 0.75 * ratio
        glow_color = _blend(THORIM_PROJECTILE_GLOW, THORIM_PROJECTILE_OUTER, ratio)
        core_color = _blend(THORIM_PROJECTILE_OUTER, THORIM_PROJECTILE_CORE, pulse)
        inner_radius = max(2, int(round(screen_radius * 0.7)))
        highlight_radius = max(1, int(round(screen_radius * 0.35)))

        pygame.draw.circle(self.surface, glow_color, center_pos, screen_radius, 0)
        pygame.draw.circle(self.surface, core_color, center_pos, inner_radius, 0)
        pygame.draw.circle(
            self.surface,
            _blend(core_color, (255, 255, 255), 0.35),
            center_pos,
            highlight_radius,
            0,
        )
        pygame.draw.circle(
            self.surface,
            _blend(glow_color, (255, 255, 255), 0.2 * ratio),
            center_pos,
            screen_radius,
            2,
        )

        if ratio < THORIM_LIGHTNING_THRESHOLD:
            return

        intensity = (ratio - THORIM_LIGHTNING_THRESHOLD) / max(
            1e-6, 1.0 - THORIM_LIGHTNING_THRESHOLD
        )
        tick = pygame.time.get_ticks() * 0.001
        pulse_phase = 0.5 + 0.5 * math.sin(tick * 6.0)
        lightning_color = _blend(
            (170, 80, 255),
            (245, 220, 255),
            min(1.0, 0.45 + 0.35 * pulse_phase + 0.2 * intensity),
        )
        ring_color = _blend(lightning_color, (255, 255, 255), 0.2)
        pygame.draw.circle(self.surface, ring_color, center_pos, screen_radius, 1)

        seed = (ship.render_state.random_seed ^ int(tick * 60.0)) & 0xFFFFFFFF
        rng = random.Random(seed)
        bolt_count = 6 + int(round(6 * intensity))
        for _ in range(bolt_count):
            angle = rng.uniform(0.0, 2.0 * math.pi)
            jitter = rng.uniform(-0.45, 0.45)
            inner_fraction = rng.uniform(0.3, 0.65)
            outer_fraction = rng.uniform(0.9, 1.25)
            start_angle = angle + jitter * 0.5
            end_angle = angle - jitter
            start_radius = screen_radius * inner_fraction
            end_radius = screen_radius * outer_fraction
            start_pos = (
                center_screen.x + math.cos(start_angle) * start_radius,
                center_screen.y + math.sin(start_angle) * start_radius,
            )
            end_pos = (
                center_screen.x + math.cos(end_angle) * end_radius,
                center_screen.y + math.sin(end_angle) * end_radius,
            )
            pygame.draw.aaline(self.surface, lightning_color, start_pos, end_pos, blend=1)
            if rng.random() < 0.4:
                spark_radius = max(1, int(round(2 * rng.uniform(0.6, 1.0))))
                spark_pos = (
                    center_screen.x + math.cos(end_angle) * end_radius,
                    center_screen.y + math.sin(end_angle) * end_radius,
                )
                pygame.draw.circle(
                    self.surface,
                    _blend(lightning_color, (255, 255, 255), 0.5),
                    (int(round(spark_pos[0])), int(round(spark_pos[1]))),
                    spark_radius,
                    0,
                )

    def clear(self) -> None:
        self._start_frame()
        self.surface.fill(BACKGROUND)

    def draw_grid(
        self,
        camera: ChaseCamera,
        focus: Vector3,
        *,
        tile_size: float = 220.0,
        extent: float = 3600.0,
        height_offset: float = -18.0,
    ) -> None:
        """Render a tiled reference grid beneath the focus point."""

        if tile_size <= 0.0 or extent <= 0.0:
            return

        half_extent = extent * 0.5
        grid_y = focus.y + height_offset
        screen_size = self.surface.get_size()

        start_x = int(floor((focus.x - half_extent) / tile_size))
        end_x = int(ceil((focus.x + half_extent) / tile_size))
        start_z = int(floor((focus.z - half_extent) / tile_size))
        end_z = int(ceil((focus.z + half_extent) / tile_size))

        def _draw_segment(a: Vector3, b: Vector3, color: tuple[int, int, int]) -> None:
            a_screen, vis_a = camera.project(a, screen_size)
            b_screen, vis_b = camera.project(b, screen_size)
            if vis_a and vis_b:
                pygame.draw.aaline(
                    self.surface,
                    color,
                    (a_screen.x, a_screen.y),
                    (b_screen.x, b_screen.y),
                    blend=1,
                )

        for xi in range(start_x, end_x + 1):
            x_world = xi * tile_size
            color = GRID_MAJOR_COLOR if xi % 5 == 0 else GRID_MINOR_COLOR
            a = Vector3(x_world, grid_y, start_z * tile_size)
            b = Vector3(x_world, grid_y, end_z * tile_size)
            _draw_segment(a, b, color)

        for zi in range(start_z, end_z + 1):
            z_world = zi * tile_size
            color = GRID_MAJOR_COLOR if zi % 5 == 0 else GRID_MINOR_COLOR
            a = Vector3(start_x * tile_size, grid_y, z_world)
            b = Vector3(end_x * tile_size, grid_y, z_world)
            _draw_segment(a, b, color)

    def draw_asteroids(self, camera: ChaseCamera, asteroids: Iterable[Asteroid]) -> None:
        frame = self._get_camera_frame(camera)
        for asteroid in asteroids:
            state = asteroid.render_state
            state.set_radius(max(asteroid.radius * 1.2, 1.0))
            state.ensure_current(asteroid.position)
            visible, distance, _ = self._evaluate_visibility(state, frame)
            if not visible:
                continue

            cache = self._asteroid_screen_cache.setdefault(
                id(asteroid), AsteroidScreenCache()
            )
            needs_update = (
                cache.camera_revision != frame.revision
                or cache.world_revision != state.world_revision
            )
            if needs_update:
                center_vec, vis_center = frame.project_point(asteroid.position)
                if not vis_center:
                    state.clear_cached_projection()
                    cache.polygon_points.clear()
                    cache.polygon_outline.clear()
                    cache.camera_revision = frame.revision
                    cache.world_revision = state.world_revision
                    continue

                radius_vectors = [
                    asteroid.position + frame.up * asteroid.radius,
                    asteroid.position - frame.up * asteroid.radius,
                    asteroid.position + frame.right * asteroid.radius,
                    asteroid.position - frame.right * asteroid.radius,
                ]
                radii: List[float] = []
                projection_count = 1  # center
                for world_point in radius_vectors:
                    projected, visible_point = frame.project_point(world_point)
                    if not visible_point:
                        radii.append(0.0)
                    else:
                        dx = projected.x - center_vec.x
                        dy = projected.y - center_vec.y
                        radii.append(math.hypot(dx, dy))
                    projection_count += 1
                radius_vertical = max(radii[0], radii[1])
                radius_horizontal = max(radii[2], radii[3])
                if radius_vertical <= 0.0 and radius_horizontal <= 0.0:
                    radius_vertical = radius_horizontal = 2.0
                radius_vertical = max(2.0, radius_vertical)
                radius_horizontal = max(2.0, radius_horizontal)

                profile = asteroid.render_profile()
                if not profile.point_angles:
                    state.clear_cached_projection()
                    cache.polygon_points.clear()
                    cache.polygon_outline.clear()
                    cache.camera_revision = frame.revision
                    cache.world_revision = state.world_revision
                    continue

                points: List[tuple[float, float]] = []
                for angle, offset, h_scale, v_scale in zip(
                    profile.point_angles,
                    profile.point_offsets,
                    profile.horizontal_scale,
                    profile.vertical_scale,
                ):
                    x = center_vec.x + math.cos(angle) * radius_horizontal * h_scale * offset
                    y = center_vec.y + math.sin(angle) * radius_vertical * v_scale * offset
                    points.append((x, y))

                if len(points) < 3:
                    state.clear_cached_projection()
                    cache.polygon_points.clear()
                    cache.polygon_outline.clear()
                    cache.camera_revision = frame.revision
                    cache.world_revision = state.world_revision
                    continue

                polygon_points = [(int(round(px)), int(round(py))) for px, py in points]
                xs = [px for px, _ in points]
                ys = [py for _, py in points]
                state.cached_screen_rect = (min(xs), min(ys), max(xs), max(ys))
                state.cached_camera_revision = frame.revision

                cache.center = (center_vec.x, center_vec.y)
                cache.radius_horizontal = radius_horizontal
                cache.radius_vertical = radius_vertical
                cache.polygon_points = polygon_points
                cache.polygon_outline = points
                cache.camera_revision = frame.revision
                cache.world_revision = state.world_revision

                self._frame_counters.vertices_projected_total += projection_count
                self._frame_counters.objects_projected += 1
            else:
                radius_horizontal = cache.radius_horizontal
                radius_vertical = cache.radius_vertical

            if not cache.polygon_points or not cache.polygon_outline:
                continue

            center_x, center_y = cache.center
            color = asteroid.display_color
            pygame.draw.polygon(self.surface, color, cache.polygon_points)

            outline_color = _darken(color, 0.45)
            line_mode = "line" if distance > 7500.0 else "aaline"
            if line_mode == "line":
                pygame.draw.lines(self.surface, outline_color, True, cache.polygon_points, 1)
                self._frame_counters.objects_drawn_line += 1
            else:
                pygame.draw.aalines(
                    self.surface, outline_color, True, cache.polygon_outline, blend=1
                )
                self._frame_counters.objects_drawn_aaline += 1

            if radius_horizontal > 3.0 or radius_vertical > 3.0:
                highlight_color = _lighten(color, 0.5)
                shadow_color = _darken(color, 0.6)
                accent_radius = max(
                    1,
                    int(round((radius_horizontal + radius_vertical) * 0.05)),
                )
                profile = asteroid.render_profile()
                for accent in profile.accents:
                    px = center_x + math.cos(accent.angle) * radius_horizontal * accent.distance * accent.horizontal_scale
                    py = center_y + math.sin(accent.angle) * radius_vertical * accent.distance * accent.vertical_scale
                    pygame.draw.circle(
                        self.surface,
                        highlight_color if accent.highlight else shadow_color,
                        (int(round(px)), int(round(py))),
                        accent_radius,
                    )

                crater_fill = _darken(color, 0.55)
                crater_rim = _lighten(color, 0.2)
                for crater in profile.craters:
                    px = center_x + math.cos(crater.angle) * radius_horizontal * crater.distance
                    py = center_y + math.sin(crater.angle) * radius_vertical * crater.distance
                    crater_radius = max(
                        1,
                        int(round((radius_horizontal + radius_vertical) * crater.radius_scale)),
                    )
                    pygame.draw.circle(
                        self.surface,
                        crater_fill,
                        (int(round(px)), int(round(py))),
                        crater_radius,
                    )
                    pygame.draw.circle(
                        self.surface,
                        crater_rim,
                        (int(round(px)), int(round(py))),
                        crater_radius,
                        1,
                    )

    def draw_ship(self, camera: ChaseCamera, ship: Ship) -> None:
        frame = self._get_camera_frame(camera)
        geometry = self._ship_geometry_cache.get(
            ship.frame.id,
            self._ship_geometry_cache.get(
                ship.frame.size, self._ship_geometry_cache["Strike"]
            ),
        )
        scale = _ship_geometry_scale(ship, geometry)
        state = getattr(ship, "render_state", None)
        if state is None:
            state = RenderSpatialState()
            ship.render_state = state
        state.set_radius(_estimate_ship_radius(ship, geometry, scale))
        state.ensure_current(ship.kinematics.position, ship.kinematics.rotation)
        visible, distance, _ = self._evaluate_visibility(state, frame)
        if not visible:
            return

        origin = ship.kinematics.position
        right, up, forward = _ship_axes(ship)
        cache = self._vertex_cache.setdefault(id(ship), ProjectedVertexCache())
        interval = self._ship_redraw_interval(ship, camera)
        state.redraw_interval_frames = interval
        needs_refresh = (
            cache.camera_revision != frame.revision
            or state.last_render_frame < 0
            or (self._frame_index - state.last_render_frame) >= interval
        )
        if needs_refresh or (not cache.aaline_strips and not cache.line_strips):
            cache = self._project_ship_vertices(
                ship,
                geometry,
                frame,
                state,
                origin,
                (right, up, forward),
                scale=scale,
            )
            state.last_render_frame = self._frame_index
        color = SHIP_COLOR if ship.team == "player" else ENEMY_COLOR
        detail = _ship_detail_factor(ship, distance)
        line_mode = "line" if distance > 7500.0 else "aaline"
        if line_mode == "line":
            strips_float = self._prepare_ship_strips(
                cache.line_strips,
                detail,
            )
            strips = [
                [(int(round(px)), int(round(py))) for px, py in strip]
                for strip in strips_float
            ]
            for strip in strips:
                pygame.draw.lines(self.surface, color, False, strip, 1)
            if strips:
                self._frame_counters.objects_drawn_line += 1
        else:
            strips = self._prepare_ship_strips(
                cache.aaline_strips,
                detail,
            )
            for strip in strips:
                pygame.draw.aalines(self.surface, color, False, strip, blend=1)
            if strips:
                self._frame_counters.objects_drawn_aaline += 1

        speed = ship.kinematics.velocity.length()
        speed_intensity = 0.0
        if speed > 80.0:
            speed_intensity = min(1.0, (speed - 80.0) / 35.0)
        if speed_intensity > 0.0:
            self._draw_speed_streaks(frame, origin, right, up, forward, ship, speed_intensity)

        self._draw_hardpoints(frame, origin, right, up, forward, ship, color, scale=scale)
        self._draw_engines(frame, origin, right, up, forward, ship, color, scale=scale)
        if ship.frame.id in THORIM_FRAME_IDS:
            self._draw_thorim_charge(
                frame,
                origin,
                right,
                up,
                forward,
                ship,
                scale=scale,
            )

    @staticmethod
    def _prepare_ship_strips(
        strips: Sequence[Sequence[tuple[float, float]]],
        detail: float,
    ) -> list[list[tuple[float, float]]]:
        if detail >= 0.999:
            return [
                [(float(x), float(y)) for x, y in strip]
                for strip in strips
                if len(strip) >= 2
            ]
        prepared: list[list[tuple[float, float]]] = []
        for strip in strips:
            if len(strip) < 2:
                continue
            float_points = [(float(x), float(y)) for x, y in strip]
            reduced = _resample_polyline(float_points, detail)
            if len(reduced) < 2:
                continue
            prepared.append(reduced)
        return prepared

    def draw_projectiles(self, camera: ChaseCamera, projectiles: Iterable[Projectile]) -> None:
        for projectile in projectiles:
            if (
                projectile.position - camera.position
            ).length_squared() > PROJECTILE_RENDER_DISTANCE_SQR:
                continue
            is_missile = projectile.weapon.wclass == "missile"
            color = MISSILE_COLOR if is_missile else PROJECTILE_COLOR
            screen_pos, visible = camera.project(projectile.position, self.surface.get_size())
            if not visible:
                continue
            if getattr(projectile.weapon, "id", "") == "pol_x01":
                center = (int(round(screen_pos.x)), int(round(screen_pos.y)))
                glow_radius = 14
                core_radius = 9
                ember_radius = 4
                pygame.draw.circle(self.surface, THORIM_PROJECTILE_GLOW, center, glow_radius, 0)
                pygame.draw.circle(self.surface, THORIM_PROJECTILE_OUTER, center, glow_radius, 2)
                pygame.draw.circle(self.surface, THORIM_PROJECTILE_CORE, center, core_radius, 0)
                pygame.draw.circle(
                    self.surface,
                    _blend(THORIM_PROJECTILE_CORE, (255, 255, 255), 0.45),
                    center,
                    ember_radius,
                    0,
                )
                pygame.draw.circle(
                    self.surface,
                    _blend(THORIM_PROJECTILE_OUTER, (255, 255, 255), 0.2),
                    center,
                    glow_radius + 2,
                    1,
                )
                continue
            if is_missile:
                trail_points = list(projectile.trail_positions)
                trail_length = len(trail_points)
                if trail_length:
                    for index, point in enumerate(trail_points):
                        smoke_pos, smoke_visible = camera.project(point, self.surface.get_size())
                        if not smoke_visible:
                            continue
                        age = index / max(1, trail_length - 1)
                        shade = int(round(180 + (MISSILE_SMOKE_COLOR[0] - 180) * (1.0 - age)))
                        radius = max(1, int(round(4 - age * 3)))
                        pygame.draw.circle(
                            self.surface,
                            (shade, shade, shade),
                            (int(smoke_pos.x), int(smoke_pos.y)),
                            radius,
                            0,
                        )
            radius = 3
            thickness = 0 if is_missile else 1
            pygame.draw.circle(
                self.surface,
                color,
                (int(screen_pos.x), int(screen_pos.y)),
                radius,
                thickness,
            )


__all__ = ["VectorRenderer"]
