"""Vector renderer accelerated by OpenGL."""
from __future__ import annotations

from array import array
from dataclasses import dataclass
from math import ceil, floor
import ctypes
import logging
import math
import random
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import pygame
from pygame.math import Vector3

try:  # pragma: no cover - import guard for optional dependency
    from OpenGL import GL as gl  # type: ignore
except ImportError as _gl_error:  # pragma: no cover
    gl = None  # type: ignore
    _GL_IMPORT_ERROR = _gl_error
else:  # pragma: no cover
    _GL_IMPORT_ERROR = None

from game.combat.weapons import Projectile
from game.render.camera import CameraFrameData, ChaseCamera, DEFAULT_SHIP_LENGTHS
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


def _require_gl() -> None:
    if gl is None:  # pragma: no cover - exercised when dependency missing
        message = "PyOpenGL is required to use the GPU renderer"
        if _GL_IMPORT_ERROR is not None:
            raise RuntimeError(message) from _GL_IMPORT_ERROR
        raise RuntimeError(message)


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
class ShipGeometry:
    vertices: List[Vector3]
    edges: List[Tuple[int, int]]
    radius: float
    length: float


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


def _vertex_key(vector: Vector3) -> Tuple[float, float, float]:
    return (round(vector.x, 6), round(vector.y, 6), round(vector.z, 6))


def _ship_geometry_from_edges(edges: Sequence[tuple[Vector3, Vector3]]) -> ShipGeometry:
    vertex_map: Dict[Tuple[float, float, float], int] = {}
    vertices: List[Vector3] = []
    index_edges: List[Tuple[int, int]] = []
    max_radius = 0.0
    min_z = float("inf")
    max_z = float("-inf")
    for start, end in edges:
        start_key = _vertex_key(start)
        end_key = _vertex_key(end)
        if start_key not in vertex_map:
            vertex_map[start_key] = len(vertices)
            vertices.append(Vector3(start))
            max_radius = max(max_radius, vertices[-1].length())
            min_z = min(min_z, vertices[-1].z)
            max_z = max(max_z, vertices[-1].z)
        if end_key not in vertex_map:
            vertex_map[end_key] = len(vertices)
            vertices.append(Vector3(end))
            max_radius = max(max_radius, vertices[-1].length())
            min_z = min(min_z, vertices[-1].z)
            max_z = max(max_z, vertices[-1].z)
        index_edges.append((vertex_map[start_key], vertex_map[end_key]))
    if min_z == float("inf") or max_z == float("-inf"):
        length = 0.0
    else:
        length = max(0.0, max_z - min_z)
    return ShipGeometry(vertices=vertices, edges=index_edges, radius=max_radius, length=length)


def _build_ship_geometry_cache() -> Dict[str, ShipGeometry]:
    return {name: _ship_geometry_from_edges(edge_list) for name, edge_list in WIREFRAMES.items()}


def _ship_geometry_scale(ship: Ship, geometry: ShipGeometry) -> float:
    target_length = DEFAULT_SHIP_LENGTHS.get(ship.frame.size)
    if not target_length:
        return 1.0
    if geometry.length <= 0.0:
        return 1.0
    scale = target_length / geometry.length
    if abs(scale - 1.0) < 0.01:
        return 1.0
    return scale


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


def _rect_intersects(rect: tuple[float, float, float, float], width: int, height: int) -> bool:
    left, top, right, bottom = rect
    return not (right < 0 or bottom < 0 or left >= width or top >= height)


def _loop_segments(
    segments: list[tuple[Vector3, Vector3]],
    points: list[Vector3],
    *,
    close: bool = True,
) -> None:
    """Append segment pairs following the provided polyline."""

    if not points:
        return
    limit = len(points) if close else len(points) - 1
    if limit <= 0:
        return
    for index in range(limit):
        start = points[index]
        end = points[(index + 1) % len(points)] if close else points[index + 1]
        segments.append((start, end))


def _elliptical_ring(
    z_pos: float,
    half_width: float,
    half_height: float,
    *,
    sides: int,
) -> list[Vector3]:
    """Create a ring of evenly spaced ellipse points."""

    if sides <= 2:
        return []
    angle_step = 2.0 * math.pi / sides
    return [
        Vector3(
            math.cos(step * angle_step) * half_width,
            math.sin(step * angle_step) * half_height,
            z_pos,
        )
        for step in range(sides)
    ]


def _stretched_oval_loop(
    *,
    sides: int,
    center_y: float,
    center_z: float,
    half_width_x: float,
    half_depth_z: float,
    vertical_rake: float = 0.0,
    vertical_crown: float = 0.0,
    angle_offset: float = math.pi / 2.0,
) -> list[Vector3]:
    """Create an offset oval loop oriented along the ship's longitudinal axis."""

    if sides <= 2:
        return []
    angle_step = 2.0 * math.pi / sides
    points: list[Vector3] = []
    for index in range(sides):
        angle = angle_offset + index * angle_step
        sin_angle = math.sin(angle)
        cos_angle = math.cos(angle)
        x = cos_angle * half_width_x
        z = center_z + sin_angle * half_depth_z
        y = center_y + sin_angle * vertical_rake + cos_angle * vertical_crown
        points.append(Vector3(x, y, z))
    return points


def _connect_rings(
    segments: list[tuple[Vector3, Vector3]],
    ring_a: Sequence[Vector3],
    ring_b: Sequence[Vector3],
) -> None:
    """Connect two perimeter rings, gracefully handling mismatched resolutions."""

    if not ring_a or not ring_b:
        return
    count_a = len(ring_a)
    count_b = len(ring_b)
    for index_a, point_a in enumerate(ring_a):
        fraction = index_a / count_a
        target_index = int(fraction * count_b) % count_b
        segments.append((point_a, ring_b[target_index]))
    for index_b, point_b in enumerate(ring_b):
        fraction = index_b / count_b
        target_index = int(fraction * count_a) % count_a
        segments.append((point_b, ring_a[target_index]))


def _mirror_vector(point: Vector3) -> Vector3:
    return Vector3(-point.x, point.y, point.z)


def _build_outpost_wireframe() -> list[tuple[Vector3, Vector3]]:
    """Construct a capital-ship silhouette for Outposts."""

    segments: list[tuple[Vector3, Vector3]] = []

    hull_profile: list[tuple[float, float, float]] = [
        (-640.0, 150.0, 96.0),
        (-580.0, 146.0, 92.0),
        (-520.0, 140.0, 88.0),
        (-440.0, 148.0, 82.0),
        (-360.0, 184.0, 94.0),
        (-240.0, 220.0, 110.0),
        (-120.0, 240.0, 125.0),
        (0.0, 250.0, 140.0),
        (120.0, 230.0, 130.0),
        (240.0, 200.0, 110.0),
        (360.0, 170.0, 95.0),
        (480.0, 140.0, 80.0),
        (560.0, 120.0, 70.0),
    ]

    ring_sides = 18
    previous_ring: list[Vector3] | None = None
    hull_sections: list[tuple[float, list[Vector3]]] = []
    for z_pos, half_width, half_height in hull_profile:
        ring = _elliptical_ring(z_pos, half_width, half_height, sides=ring_sides)
        hull_sections.append((z_pos, ring))
        _loop_segments(segments, ring)
        if previous_ring is not None:
            for current, previous in zip(ring, previous_ring):
                segments.append((current, previous))
            for offset in range(0, ring_sides, 3):
                segments.append((ring[offset], ring[(offset + 6) % ring_sides]))
                segments.append((previous_ring[offset], previous_ring[(offset + 6) % ring_sides]))
                segments.append((ring[offset], previous_ring[(offset + 3) % ring_sides]))
        previous_ring = ring

    nose_tip = Vector3(0.0, 40.0, hull_profile[-1][0] + 80.0)
    ventral_spear = Vector3(0.0, -35.0, hull_profile[-1][0] + 70.0)
    final_section = hull_sections[-1][1]
    _loop_segments(
        segments,
        [
            nose_tip,
            ventral_spear,
            Vector3(40.0, 0.0, nose_tip.z - 30.0),
            Vector3(-40.0, 0.0, nose_tip.z - 30.0),
        ],
    )
    for point in final_section[::2]:
        segments.append((point, nose_tip))
        segments.append((point, ventral_spear))

    # The remaining structure keeps the focus on the primary hull and engines,
    # avoiding the dorsal and ventral "railings" and other protruding detail
    # elements that previously extended from the silhouette.

    tail_z = hull_profile[0][0]
    tail_half_width = hull_profile[0][1]
    tail_half_height = hull_profile[0][2]
    housing_front_z = tail_z + 18.0
    housing_back_z = tail_z - 48.0
    housing_half_width = tail_half_width + 18.0
    housing_half_height = tail_half_height + 22.0

    top_front_left = Vector3(-housing_half_width, housing_half_height, housing_front_z)
    top_back_left = Vector3(-housing_half_width + 20.0, housing_half_height + 8.0, housing_back_z)
    top_back_right = Vector3(housing_half_width - 20.0, housing_half_height + 8.0, housing_back_z)
    top_front_right = Vector3(housing_half_width, housing_half_height, housing_front_z)
    bottom_front_left = Vector3(-housing_half_width, -housing_half_height, housing_front_z)
    bottom_back_left = Vector3(-housing_half_width + 20.0, -housing_half_height - 8.0, housing_back_z)
    bottom_back_right = Vector3(housing_half_width - 20.0, -housing_half_height - 8.0, housing_back_z)
    bottom_front_right = Vector3(housing_half_width, -housing_half_height, housing_front_z)

    top_frame = [top_front_left, top_back_left, top_back_right, top_front_right]
    bottom_frame = [
        bottom_front_left,
        bottom_back_left,
        bottom_back_right,
        bottom_front_right,
    ]
    _loop_segments(segments, top_frame)
    _loop_segments(segments, bottom_frame)

    side_frames = [
        [top_front_left, top_back_left, bottom_back_left, bottom_front_left],
        [top_front_right, top_back_right, bottom_back_right, bottom_front_right],
    ]
    for frame in side_frames:
        _loop_segments(segments, frame)

    for top_point, bottom_point in zip(top_frame, bottom_frame):
        segments.append((top_point, bottom_point))

    housing_mount_targets: dict[tuple[int, int], Vector3] = {
        (-1, 1): top_front_left,
        (-1, -1): bottom_front_left,
        (1, 1): top_front_right,
        (1, -1): bottom_front_right,
    }

    engine_offset_x = tail_half_width - 36.0
    engine_offset_y = tail_half_height - 30.0
    engine_radius_x = 30.0
    engine_radius_y = 24.0
    engine_depth = 18.0
    nozzle_inset = 5.0
    for sign in (-1, 1):
        for vertical in (-1, 1):
            center = Vector3(
                sign * engine_offset_x,
                vertical * engine_offset_y,
                housing_back_z + engine_depth,
            )
            ring: list[Vector3] = []
            nozzle_ring: list[Vector3] = []
            for step in range(12):
                angle = step * (2.0 * math.pi / 12)
                ring.append(
                    Vector3(
                        center.x + math.cos(angle) * engine_radius_x,
                        center.y + math.sin(angle) * engine_radius_y,
                        center.z,
                    )
                )
                nozzle_ring.append(
                    Vector3(
                        center.x + math.cos(angle) * engine_radius_x * 0.68,
                        center.y + math.sin(angle) * engine_radius_y * 0.68,
                        housing_back_z + nozzle_inset,
                    )
                )
            _loop_segments(segments, ring)
            _loop_segments(segments, nozzle_ring)

            thruster_end = Vector3(center.x, center.y, housing_back_z + nozzle_inset)
            for point in ring[::3]:
                segments.append((point, thruster_end))
            for ring_point, nozzle_point in zip(ring[::2], nozzle_ring[::2]):
                segments.append((ring_point, nozzle_point))

            mount = housing_mount_targets[(sign, vertical)]
            segments.append((center, mount))
            for point in ring[::4]:
                segments.append((point, mount))

            anchor_index = ring_sides // 6 if sign > 0 else (ring_sides * 5) // 6
            anchor_index += 0 if vertical > 0 else ring_sides // 2
            hull_anchor_ring = hull_sections[1][1]
            segments.append((mount, hull_anchor_ring[anchor_index % ring_sides]))

    max_half_width = max(half_width for _, half_width, _ in hull_profile)
    hull_length = hull_profile[-1][0] - tail_z
    docking_arm_length = hull_length * 0.5
    docking_arm_start_z = tail_z + hull_length * 0.35
    docking_arm_end_z = min(hull_profile[-1][0] - 30.0, docking_arm_start_z + docking_arm_length)
    docking_arm_offset_x = max_half_width + 70.0
    docking_arm_offset_y = -58.0
    docking_arm_radius = 38.0
    docking_arm_vertical_radius = docking_arm_radius * 0.78
    docking_arm_ring_sides = 14
    docking_arm_sections = 7

    def _nearest_hull_ring(z_value: float) -> list[Vector3]:
        return min(hull_sections, key=lambda entry: abs(entry[0] - z_value))[1]

    arm_caps: dict[int, dict[str, list[Vector3] | Vector3]] = {sign: {} for sign in (-1, 1)}

    for sign in (-1, 1):
        previous_arm_ring: list[Vector3] | None = None
        for section_index in range(docking_arm_sections):
            if docking_arm_sections == 1:
                position_fraction = 0.0
            else:
                position_fraction = section_index / (docking_arm_sections - 1)
            z_pos = docking_arm_start_z + (docking_arm_end_z - docking_arm_start_z) * position_fraction
            center = Vector3(sign * docking_arm_offset_x, docking_arm_offset_y, z_pos)
            arm_ring: list[Vector3] = []
            for step in range(docking_arm_ring_sides):
                angle = step * (2.0 * math.pi / docking_arm_ring_sides)
                arm_ring.append(
                    Vector3(
                        center.x + math.cos(angle) * docking_arm_radius,
                        center.y + math.sin(angle) * docking_arm_vertical_radius,
                        center.z,
                    )
                )
            _loop_segments(segments, arm_ring)
            if section_index == 0:
                arm_caps[sign]["base_ring"] = arm_ring
                arm_caps[sign]["base_center"] = center
            if section_index == docking_arm_sections - 1:
                arm_caps[sign]["tip_ring"] = arm_ring
                arm_caps[sign]["tip_center"] = center
            if previous_arm_ring is not None:
                for current, previous in zip(arm_ring, previous_arm_ring):
                    segments.append((current, previous))
            previous_arm_ring = arm_ring

    cone_height = docking_arm_radius * 0.18
    for sign in (-1, 1):
        tip_ring = arm_caps[sign].get("tip_ring")
        tip_center = arm_caps[sign].get("tip_center")
        if tip_ring is not None and isinstance(tip_center, Vector3):
            forward_tip = Vector3(tip_center.x, tip_center.y, tip_center.z + cone_height)
            for point in tip_ring[::2]:
                segments.append((point, forward_tip))
        base_ring = arm_caps[sign].get("base_ring")
        base_center = arm_caps[sign].get("base_center")
        if base_ring is not None and isinstance(base_center, Vector3):
            aft_tip = Vector3(base_center.x, base_center.y, base_center.z - cone_height)
            for point in base_ring[::2]:
                segments.append((point, aft_tip))

    hull_attachment_indices = {1: 2, -1: 6}
    connector_positions = [
        docking_arm_start_z + (docking_arm_end_z - docking_arm_start_z) * fraction
        for fraction in (0.1, 0.5, 0.9)
    ]
    for sign in (-1, 1):
        for z_pos in connector_positions:
            hull_ring = _nearest_hull_ring(z_pos)
            hull_point = hull_ring[hull_attachment_indices[sign]]
            arm_surface = Vector3(
                sign * docking_arm_offset_x - sign * docking_arm_radius,
                docking_arm_offset_y,
                z_pos,
            )
            segments.append((hull_point, arm_surface))
            brace_lower = Vector3(
                arm_surface.x,
                docking_arm_offset_y - docking_arm_vertical_radius * 0.6,
                z_pos,
            )
            segments.append((arm_surface, brace_lower))

    plating_lines = []
    for fraction in (0.15, 0.35, 0.65, 0.85):
        idx = int(fraction * (len(hull_sections) - 1))
        plating_lines.append(hull_sections[idx][1])
    for section in plating_lines:
        for offset in range(0, ring_sides, 2):
            segments.append((section[offset], section[(offset + 2) % ring_sides]))

    return segments


def _build_line_wireframe() -> list[tuple[Vector3, Vector3]]:
    """Construct a heavy line-ship silhouette with rich surface detail."""

    segments: list[tuple[Vector3, Vector3]] = []

    hull_profile: list[tuple[float, float, float]] = [
        (-260.0, 70.0, 35.0),
        (-220.0, 95.0, 45.0),
        (-180.0, 118.0, 58.0),
        (-120.0, 142.0, 68.0),
        (-60.0, 156.0, 76.0),
        (0.0, 162.0, 82.0),
        (70.0, 150.0, 78.0),
        (140.0, 132.0, 68.0),
        (200.0, 110.0, 58.0),
        (240.0, 96.0, 50.0),
        (280.0, 82.0, 44.0),
    ]

    ring_sides = 18
    previous_ring: list[Vector3] | None = None
    hull_sections: list[list[Vector3]] = []
    for z_pos, half_width, half_height in hull_profile:
        ring = _elliptical_ring(z_pos, half_width, half_height, sides=ring_sides)
        hull_sections.append(ring)
        _loop_segments(segments, ring)
        if previous_ring is not None:
            for current, previous in zip(ring, previous_ring):
                segments.append((current, previous))
            for offset in range(0, ring_sides, 2):
                segments.append((ring[offset], previous_ring[(offset + 1) % ring_sides]))
        previous_ring = ring

    prow_tip = Vector3(0.0, 46.0, hull_profile[-1][0] + 40.0)
    prow_keel = Vector3(0.0, -34.0, hull_profile[-1][0] + 28.0)
    prow_ridge = Vector3(32.0, 8.0, hull_profile[-1][0] + 12.0)
    prow_ridge_mirror = Vector3(-32.0, 8.0, hull_profile[-1][0] + 12.0)
    _loop_segments(
        segments,
        [prow_tip, prow_ridge, prow_keel, prow_ridge_mirror],
    )
    final_section = hull_sections[-1]
    for point in final_section[::2]:
        segments.append((point, prow_tip))
        segments.append((point, prow_keel))

    dorsal_spine: list[Vector3] = []
    ventral_keel: list[Vector3] = []
    for z_pos, _, half_height in hull_profile:
        dorsal_spine.append(Vector3(0.0, half_height * 1.28 + 26.0, z_pos))
        ventral_keel.append(Vector3(0.0, -half_height * 1.14 - 20.0, z_pos))
    _loop_segments(segments, dorsal_spine, close=False)
    _loop_segments(segments, ventral_keel, close=False)
    for top, bottom in zip(dorsal_spine, ventral_keel):
        segments.append((top, bottom))

    tower_z = 40.0
    tower_profile = [
        Vector3(-26.0, 120.0, tower_z - 16.0),
        Vector3(0.0, 158.0, tower_z + 12.0),
        Vector3(26.0, 120.0, tower_z - 16.0),
        Vector3(0.0, 102.0, tower_z - 48.0),
    ]
    _loop_segments(segments, tower_profile)
    for point in tower_profile:
        segments.append((point, dorsal_spine[len(dorsal_spine) // 2]))

    for sign in (-1.0, 1.0):
        bulwark: list[Vector3] = []
        for index, (z_pos, half_width, half_height) in enumerate(hull_profile[1:-1], start=1):
            lateral = half_width * 1.04 + 20.0
            vertical = half_height * 0.52
            bulwark_point = Vector3(sign * lateral, vertical, z_pos)
            bulwark.append(bulwark_point)
            anchor_index = ring_sides // 4 if sign > 0 else (ring_sides * 3) // 4
            anchor = hull_sections[index][anchor_index % ring_sides]
            segments.append((bulwark_point, anchor))
            if index % 2 == 0:
                offset = 2 if sign > 0 else ring_sides - 2
                segments.append((bulwark_point, hull_sections[index][(anchor_index + offset) % ring_sides]))
        _loop_segments(segments, bulwark, close=False)

    flank_planes = []
    for fraction in (0.18, 0.38, 0.62, 0.82):
        idx = int(fraction * (len(hull_sections) - 1))
        flank_planes.append(hull_sections[idx])
    for section in flank_planes:
        for offset in range(0, ring_sides, 2):
            segments.append((section[offset], section[(offset + 2) % ring_sides]))

    ventral_bay_z = -80.0
    bay_frame = [
        Vector3(-88.0, -112.0, ventral_bay_z - 36.0),
        Vector3(88.0, -112.0, ventral_bay_z - 36.0),
        Vector3(104.0, -72.0, ventral_bay_z + 18.0),
        Vector3(-104.0, -72.0, ventral_bay_z + 18.0),
    ]
    _loop_segments(segments, bay_frame)
    for point in bay_frame:
        segments.append((point, ventral_keel[len(ventral_keel) // 2]))

    tail_z = hull_profile[0][0]
    engine_offset_x = hull_profile[0][1] + 48.0
    engine_offset_y = 56.0
    for sign in (-1.0, 1.0):
        for vertical in (-1.0, 1.0):
            center = Vector3(sign * engine_offset_x, vertical * engine_offset_y, tail_z - 34.0)
            ring = [
                Vector3(
                    center.x + math.cos(angle) * 32.0,
                    center.y + math.sin(angle) * 26.0,
                    center.z,
                )
                for angle in [step * (2.0 * math.pi / 12) for step in range(12)]
            ]
            _loop_segments(segments, ring)
            thruster_end = Vector3(center.x, center.y, center.z - 44.0)
            for point in ring[::2]:
                segments.append((point, thruster_end))
            hull_anchor_index = ring_sides // 6 if sign > 0 else (ring_sides * 5) // 6
            hull_anchor_index += 0 if vertical > 0 else ring_sides // 2
            hull_anchor = hull_sections[0][hull_anchor_index % ring_sides]
            segments.append((center, hull_anchor))

    return segments


def _build_escort_wireframe() -> list[tuple[Vector3, Vector3]]:
    """Construct an escort-class silhouette with layered armor panels."""

    segments: list[tuple[Vector3, Vector3]] = []

    hull_profile: list[tuple[float, float, float]] = [
        (-72.0, 30.0, 13.0),
        (-62.0, 32.0, 14.0),
        (-52.0, 34.0, 15.5),
        (-42.0, 36.0, 17.0),
        (-32.0, 33.0, 18.2),
        (-22.0, 28.0, 19.0),
        (-12.0, 24.5, 19.5),
        (-2.0, 24.0, 19.5),
        (8.0, 25.0, 19.0),
        (20.0, 29.0, 18.5),
        (34.0, 34.0, 17.0),
        (48.0, 38.0, 15.5),
        (58.0, 40.0, 14.0),
        (66.0, 38.0, 12.5),
    ]

    ring_sides = 14
    previous_ring: list[Vector3] | None = None
    hull_sections: list[list[Vector3]] = []
    for z_pos, half_width, half_height in hull_profile:
        ring = _elliptical_ring(z_pos, half_width, half_height, sides=ring_sides)
        hull_sections.append(ring)
        _loop_segments(segments, ring)
        if previous_ring is not None:
            for current, previous in zip(ring, previous_ring):
                segments.append((current, previous))
            for offset in range(0, ring_sides, 3):
                segments.append((ring[offset], previous_ring[(offset + 1) % ring_sides]))
        previous_ring = ring

    canopy_tip = Vector3(0.0, 32.0, hull_profile[-1][0] + 18.0)
    strike_beak = Vector3(18.0, 4.0, hull_profile[-1][0] + 4.0)
    strike_beak_mirror = Vector3(-18.0, 4.0, hull_profile[-1][0] + 4.0)
    intake = Vector3(0.0, -24.0, hull_profile[-1][0] + 6.0)
    _loop_segments(
        segments,
        [canopy_tip, strike_beak, intake, strike_beak_mirror],
    )
    final_section = hull_sections[-1]
    for point in final_section[::2]:
        segments.append((point, canopy_tip))
        segments.append((point, intake))

    dorsal_line: list[Vector3] = []
    ventral_line: list[Vector3] = []
    for z_pos, _, half_height in hull_profile:
        dorsal_line.append(Vector3(0.0, half_height * 1.28 + 16.0, z_pos))
        ventral_line.append(Vector3(0.0, -half_height * 1.1 - 14.0, z_pos))
    _loop_segments(segments, dorsal_line, close=False)
    _loop_segments(segments, ventral_line, close=False)
    for top, bottom in zip(dorsal_line, ventral_line):
        segments.append((top, bottom))

    for sign in (-1.0, 1.0):
        wing_points: list[Vector3] = []
        for index, (z_pos, half_width, half_height) in enumerate(hull_profile[2:-1], start=2):
            lateral = half_width * 1.1 + 8.0
            vertical = half_height * 0.35
            wing_points.append(Vector3(sign * lateral, vertical, z_pos))
            anchor = hull_sections[index][
                (ring_sides // 4 if sign > 0 else (ring_sides * 3) // 4)
            ]
            segments.append((wing_points[-1], anchor))
        _loop_segments(segments, wing_points, close=False)

    plating_indices = [int(fraction * (len(hull_sections) - 1)) for fraction in (0.25, 0.5, 0.75)]
    for index in plating_indices:
        section = hull_sections[index]
        for offset in range(0, ring_sides, 3):
            segments.append((section[offset], section[(offset + 2) % ring_sides]))

    engine_center = hull_profile[0][0] - 10.0
    for sign in (-1.0, 1.0):
        ring = [
            Vector3(
                sign * (hull_profile[0][1] + 12.0 + math.cos(angle) * 10.0),
                math.sin(angle) * 10.0 - 18.0,
                engine_center,
            )
            for angle in [step * (2.0 * math.pi / 8) for step in range(8)]
        ]
        _loop_segments(segments, ring)
        nozzle = Vector3(sign * (hull_profile[0][1] + 12.0), -18.0, engine_center - 18.0)
        for point in ring[::2]:
            segments.append((point, nozzle))
        anchor_index = ring_sides // 4 if sign > 0 else (ring_sides * 3) // 4
        hull_anchor = hull_sections[0][anchor_index % ring_sides]
        segments.append((nozzle, hull_anchor))

    dorsal_fins = [
        Vector3(-12.0, 44.0, -18.0),
        Vector3(0.0, 56.0, 0.0),
        Vector3(12.0, 44.0, -18.0),
    ]
    _loop_segments(segments, dorsal_fins)
    segments.append((dorsal_fins[1], dorsal_line[len(dorsal_line) // 2]))

    return segments


def _build_viper_mk_ii_wireframe() -> list[tuple[Vector3, Vector3]]:
    segments: list[tuple[Vector3, Vector3]] = []

    nose = Vector3(0.0, 0.35, 2.8)
    canopy = Vector3(0.0, 0.7, 1.2)
    tail = Vector3(0.0, -0.25, -2.6)
    ventral = Vector3(0.0, -0.9, -0.4)
    spine = Vector3(0.0, 0.15, -0.8)

    left_points = [
        Vector3(-1.4, -0.05, 1.4),
        Vector3(-1.85, -0.02, 0.0),
        Vector3(-0.65, 0.3, -2.1),
        Vector3(-0.55, 0.35, 1.9),
    ]

    for point in left_points:
        mirrored = _mirror_vector(point)
        segments.append((point, mirrored))
        segments.append((point, nose))
        segments.append((mirrored, nose))
        segments.append((point, tail))
        segments.append((mirrored, tail))
        segments.append((point, spine))
        segments.append((mirrored, spine))

    segments.append((nose, canopy))
    segments.append((canopy, tail))
    segments.append((ventral, tail))
    segments.append((ventral, nose))
    segments.append((ventral, spine))
    segments.append((canopy, spine))
    segments.append((left_points[1], ventral))
    segments.append((_mirror_vector(left_points[1]), ventral))

    return segments


def _build_viper_mk_vii_wireframe() -> list[tuple[Vector3, Vector3]]:
    segments: list[tuple[Vector3, Vector3]] = []

    nose = Vector3(0.0, 0.32, 2.7)
    canopy = Vector3(0.0, 0.58, 1.6)
    tail = Vector3(0.0, -0.18, -2.4)
    ventral = Vector3(0.0, -0.75, -0.6)
    dorsal_spine = Vector3(0.0, 0.42, -1.2)

    left_points = [
        Vector3(-1.25, -0.1, 1.8),
        Vector3(-1.6, -0.05, 0.6),
        Vector3(-1.05, 0.18, -1.8),
        Vector3(-0.55, 0.48, 0.4),
    ]

    for point in left_points:
        mirrored = _mirror_vector(point)
        segments.append((point, mirrored))
        segments.append((point, nose))
        segments.append((mirrored, nose))
        segments.append((point, tail))
        segments.append((mirrored, tail))
        segments.append((point, dorsal_spine))
        segments.append((mirrored, dorsal_spine))

    twin_tail_left = Vector3(-0.5, 0.2, -2.4)
    twin_tail_right = _mirror_vector(twin_tail_left)
    segments.append((twin_tail_left, twin_tail_right))
    segments.append((twin_tail_left, tail))
    segments.append((twin_tail_right, tail))
    segments.append((twin_tail_left, dorsal_spine))
    segments.append((twin_tail_right, dorsal_spine))

    segments.append((nose, canopy))
    segments.append((canopy, dorsal_spine))
    segments.append((ventral, tail))
    segments.append((ventral, nose))
    segments.append((ventral, left_points[1]))
    segments.append((ventral, _mirror_vector(left_points[1])))

    return segments


def _build_raptor_wireframe() -> list[tuple[Vector3, Vector3]]:
    segments: list[tuple[Vector3, Vector3]] = []

    nose = Vector3(0.0, 0.5, 2.2)
    cockpit = Vector3(0.0, 0.8, 0.8)
    tail = Vector3(0.0, 0.1, -2.2)
    ventral = Vector3(0.0, -0.7, -0.8)

    hull_points = [
        Vector3(-1.4, 0.2, 1.4),
        Vector3(-1.6, 0.15, -0.4),
        Vector3(-0.9, 0.35, -2.0),
        Vector3(-1.0, -0.4, 1.0),
    ]

    for point in hull_points:
        mirrored = _mirror_vector(point)
        segments.append((point, mirrored))
        segments.append((point, nose))
        segments.append((mirrored, nose))
        segments.append((point, tail))
        segments.append((mirrored, tail))
        segments.append((point, ventral))
        segments.append((mirrored, ventral))

    boom_left = Vector3(-0.8, 0.1, -2.6)
    boom_right = _mirror_vector(boom_left)
    segments.append((boom_left, boom_right))
    segments.append((boom_left, tail))
    segments.append((boom_right, tail))
    segments.append((boom_left, ventral))
    segments.append((boom_right, ventral))

    segments.append((nose, cockpit))
    segments.append((cockpit, tail))
    segments.append((ventral, nose))
    segments.append((ventral, tail))

    return segments


def _build_viper_mk_iii_wireframe() -> list[tuple[Vector3, Vector3]]:
    segments: list[tuple[Vector3, Vector3]] = []

    nose = Vector3(0.0, 0.4, 2.6)
    canopy = Vector3(0.0, 0.65, 1.3)
    tail = Vector3(0.0, -0.2, -2.5)
    ventral = Vector3(0.0, -0.8, -0.3)
    dorsal = Vector3(0.0, 0.25, -1.1)

    left_points = [
        Vector3(-1.3, -0.05, 1.6),
        Vector3(-1.7, -0.03, 0.2),
        Vector3(-1.0, 0.22, -1.9),
    ]

    for point in left_points:
        mirrored = _mirror_vector(point)
        segments.append((point, mirrored))
        segments.append((point, nose))
        segments.append((mirrored, nose))
        segments.append((point, tail))
        segments.append((mirrored, tail))
        segments.append((point, dorsal))
        segments.append((mirrored, dorsal))

    wing_tip_left = Vector3(-1.9, -0.08, 0.8)
    wing_tip_right = _mirror_vector(wing_tip_left)
    segments.append((wing_tip_left, wing_tip_right))
    segments.append((wing_tip_left, nose))
    segments.append((wing_tip_right, nose))
    segments.append((wing_tip_left, tail))
    segments.append((wing_tip_right, tail))

    segments.append((nose, canopy))
    segments.append((canopy, dorsal))
    segments.append((ventral, tail))
    segments.append((ventral, nose))
    segments.append((ventral, wing_tip_left))
    segments.append((ventral, wing_tip_right))

    return segments


def _build_rhino_wireframe() -> list[tuple[Vector3, Vector3]]:
    segments: list[tuple[Vector3, Vector3]] = []

    nose = Vector3(0.0, 0.55, 2.4)
    canopy = Vector3(0.0, 0.85, 1.1)
    tail = Vector3(0.0, 0.1, -2.3)
    keel = Vector3(0.0, -0.9, -0.5)

    left_points = [
        Vector3(-1.5, 0.15, 1.5),
        Vector3(-1.9, 0.12, 0.2),
        Vector3(-1.2, 0.35, -1.8),
        Vector3(-1.0, -0.4, 1.0),
    ]

    for point in left_points:
        mirrored = _mirror_vector(point)
        segments.append((point, mirrored))
        segments.append((point, nose))
        segments.append((mirrored, nose))
        segments.append((point, tail))
        segments.append((mirrored, tail))
        segments.append((point, keel))
        segments.append((mirrored, keel))

    armor_left = Vector3(-1.3, 0.55, -0.3)
    armor_right = _mirror_vector(armor_left)
    segments.append((armor_left, armor_right))
    segments.append((armor_left, canopy))
    segments.append((armor_right, canopy))
    segments.append((armor_left, keel))
    segments.append((armor_right, keel))

    segments.append((nose, canopy))
    segments.append((canopy, tail))
    segments.append((keel, tail))
    segments.append((keel, nose))

    return segments


def _build_raven_wireframe() -> list[tuple[Vector3, Vector3]]:
    segments: list[tuple[Vector3, Vector3]] = []

    nose = Vector3(0.0, 0.25, 3.0)
    canopy = Vector3(0.0, 0.55, 1.5)
    tail = Vector3(0.0, -0.25, -2.2)
    ventral = Vector3(0.0, -0.75, -0.6)

    left_points = [
        Vector3(-0.95, -0.05, 2.0),
        Vector3(-1.35, -0.02, 0.8),
        Vector3(-0.8, 0.18, -1.6),
    ]

    for point in left_points:
        mirrored = _mirror_vector(point)
        segments.append((point, mirrored))
        segments.append((point, nose))
        segments.append((mirrored, nose))
        segments.append((point, tail))
        segments.append((mirrored, tail))

    strake_left = Vector3(-0.4, 0.4, 0.6)
    strake_right = _mirror_vector(strake_left)
    segments.append((strake_left, strake_right))
    segments.append((strake_left, canopy))
    segments.append((strake_right, canopy))
    segments.append((strake_left, nose))
    segments.append((strake_right, nose))

    segments.append((nose, canopy))
    segments.append((canopy, tail))
    segments.append((ventral, tail))
    segments.append((ventral, nose))
    segments.append((ventral, strake_left))
    segments.append((ventral, strake_right))

    return segments


def _build_glaive_wireframe() -> list[tuple[Vector3, Vector3]]:
    segments: list[tuple[Vector3, Vector3]] = []

    oval_sides = 20

    midplane_y = 0.9
    compression_factor = 0.75

    def _compress(point: Vector3) -> Vector3:
        return Vector3(
            point.x,
            midplane_y + compression_factor * (point.y - midplane_y),
            point.z,
        )

    def _compress_loop(loop: Sequence[Vector3]) -> list[Vector3]:
        return [_compress(point) for point in loop]

    prow_tip = _compress(Vector3(0.0, 2.35, 4.4))
    prow_chin = _compress(Vector3(0.0, 0.65, 4.1))
    dorsal_neck = _compress(Vector3(0.0, 2.35, 3.2))
    dorsal_ridge = _compress(Vector3(0.0, 2.05, 1.6))
    dorsal_mid = _compress(Vector3(0.0, 1.8, -0.8))
    stern_plate = _compress(Vector3(0.0, 1.0, -3.9))
    ventral_neck = _compress(Vector3(0.0, 0.35, 2.4))
    ventral_mid = _compress(Vector3(0.0, -0.45, -0.2))
    stern_keel = _compress(Vector3(0.0, -0.5, -4.2))

    prow_upper_loop = _compress_loop(
        _stretched_oval_loop(
            sides=oval_sides,
            center_y=2.05,
            center_z=3.1,
            half_width_x=3.05,
            half_depth_z=1.25,
            vertical_rake=0.0,
            vertical_crown=0.0,
        )
    )
    _loop_segments(segments, prow_upper_loop)

    prow_lower_loop = _compress_loop(
        _stretched_oval_loop(
            sides=oval_sides,
            center_y=0.6,
            center_z=3.0,
            half_width_x=2.85,
            half_depth_z=1.15,
            vertical_rake=0.0,
            vertical_crown=0.0,
        )
    )
    _loop_segments(segments, prow_lower_loop)

    neck_upper_loop = _compress_loop(
        _stretched_oval_loop(
            sides=oval_sides,
            center_y=1.95,
            center_z=2.2,
            half_width_x=2.25,
            half_depth_z=0.9,
            vertical_rake=0.0,
            vertical_crown=0.0,
        )
    )
    _loop_segments(segments, neck_upper_loop)

    neck_lower_loop = _compress_loop(
        _stretched_oval_loop(
            sides=oval_sides,
            center_y=0.4,
            center_z=2.1,
            half_width_x=2.05,
            half_depth_z=0.85,
            vertical_rake=0.0,
            vertical_crown=0.0,
        )
    )
    _loop_segments(segments, neck_lower_loop)

    mid_forward_upper_loop = _compress_loop(
        _stretched_oval_loop(
            sides=oval_sides,
            center_y=1.75,
            center_z=1.15,
            half_width_x=1.35,
            half_depth_z=1.45,
            vertical_rake=0.12,
            vertical_crown=0.18,
        )
    )
    _loop_segments(segments, mid_forward_upper_loop)

    mid_forward_lower_loop = _compress_loop(
        _stretched_oval_loop(
            sides=oval_sides,
            center_y=-0.1,
            center_z=0.95,
            half_width_x=1.35,
            half_depth_z=1.35,
            vertical_rake=0.2,
            vertical_crown=-0.08,
        )
    )
    _loop_segments(segments, mid_forward_lower_loop)

    mid_central_upper_loop = _compress_loop(
        _stretched_oval_loop(
            sides=oval_sides,
            center_y=1.7,
            center_z=0.35,
            half_width_x=1.35,
            half_depth_z=1.65,
            vertical_rake=0.15,
            vertical_crown=0.18,
        )
    )
    _loop_segments(segments, mid_central_upper_loop)

    mid_central_lower_loop = _compress_loop(
        _stretched_oval_loop(
            sides=oval_sides,
            center_y=-0.25,
            center_z=0.15,
            half_width_x=1.35,
            half_depth_z=1.55,
            vertical_rake=0.22,
            vertical_crown=-0.12,
        )
    )
    _loop_segments(segments, mid_central_lower_loop)

    mid_aft_upper_loop = _compress_loop(
        _stretched_oval_loop(
            sides=oval_sides,
            center_y=1.55,
            center_z=-0.85,
            half_width_x=1.35,
            half_depth_z=1.4,
            vertical_rake=0.18,
            vertical_crown=0.16,
        )
    )
    _loop_segments(segments, mid_aft_upper_loop)

    mid_aft_lower_loop = _compress_loop(
        _stretched_oval_loop(
            sides=oval_sides,
            center_y=-0.35,
            center_z=-1.05,
            half_width_x=1.35,
            half_depth_z=1.45,
            vertical_rake=0.24,
            vertical_crown=-0.1,
        )
    )
    _loop_segments(segments, mid_aft_lower_loop)

    stern_upper_loop = _compress_loop(
        [
            Vector3(0.0, 1.2, -2.2),
            Vector3(2.5, 1.1, -2.6),
            Vector3(3.1, 1.0, -3.4),
            Vector3(2.3, 0.9, -4.1),
            Vector3(0.0, 0.9, -4.2),
            Vector3(-2.3, 0.9, -4.1),
            Vector3(-3.1, 1.0, -3.4),
            Vector3(-2.5, 1.1, -2.6),
        ]
    )
    _loop_segments(segments, stern_upper_loop)

    stern_lower_loop = _compress_loop(
        [
            Vector3(0.0, -0.8, -2.4),
            Vector3(2.3, -0.7, -2.8),
            Vector3(2.9, -0.6, -3.6),
            Vector3(2.1, -0.5, -4.2),
            Vector3(0.0, -0.5, -4.2),
            Vector3(-2.1, -0.5, -4.2),
            Vector3(-2.9, -0.6, -3.6),
            Vector3(-2.3, -0.7, -2.8),
        ]
    )
    _loop_segments(segments, stern_lower_loop)

    upper_loops = [
        prow_upper_loop,
        neck_upper_loop,
        mid_forward_upper_loop,
        mid_central_upper_loop,
        mid_aft_upper_loop,
        stern_upper_loop,
    ]
    lower_loops = [
        prow_lower_loop,
        neck_lower_loop,
        mid_forward_lower_loop,
        mid_central_lower_loop,
        mid_aft_lower_loop,
        stern_lower_loop,
    ]

    for upper_ring, lower_ring in zip(upper_loops, lower_loops):
        _connect_rings(segments, upper_ring, lower_ring)

    for previous, nxt in zip(upper_loops, upper_loops[1:]):
        _connect_rings(segments, previous, nxt)
    for previous, nxt in zip(lower_loops, lower_loops[1:]):
        _connect_rings(segments, previous, nxt)

    dorsal_spine = [
        prow_tip,
        dorsal_neck,
        dorsal_ridge,
        _compress(Vector3(0.0, 1.9, 0.4)),
        dorsal_mid,
        stern_plate,
    ]
    for start, end in zip(dorsal_spine, dorsal_spine[1:]):
        segments.append((start, end))

    ventral_spine = [
        prow_chin,
        ventral_neck,
        _compress(Vector3(0.0, -0.2, 1.2)),
        ventral_mid,
        stern_keel,
    ]
    for start, end in zip(ventral_spine, ventral_spine[1:]):
        segments.append((start, end))

    module_ridges = _compress_loop(
        [
            Vector3(-1.35, 1.5, 0.9),
            Vector3(-1.35, 1.4, -0.1),
            Vector3(-1.35, 1.4, -1.2),
            Vector3(-1.35, 1.5, -2.0),
        ]
    )
    for point in module_ridges:
        mirrored = _mirror_vector(point)
        segments.append((point, mirrored))
        segments.append((point, _compress(Vector3(point.x, 0.9, point.z))))
        segments.append((mirrored, _compress(Vector3(mirrored.x, 0.9, mirrored.z))))

    strake_points = _compress_loop(
        [
            Vector3(-3.1, 1.8, 3.1),
            Vector3(-3.3, 1.5, 2.2),
            Vector3(-3.1, 1.2, 1.0),
        ]
    )
    for point in strake_points:
        mirrored = _mirror_vector(point)
        segments.append((point, mirrored))
        segments.append((point, _compress(Vector3(point.x, 0.6, point.z))))
        segments.append((mirrored, _compress(Vector3(mirrored.x, 0.6, mirrored.z))))

    thruster_points = _compress_loop(
        [
            Vector3(-1.4, 0.6, -4.2),
            Vector3(-0.4, 0.6, -4.2),
            Vector3(0.4, 0.6, -4.2),
            Vector3(1.4, 0.6, -4.2),
        ]
    )
    for point in thruster_points:
        segments.append((point, _compress(Vector3(point.x, -0.4, -4.2))))
    for start, end in zip(thruster_points, thruster_points[1:]):
        segments.append((start, end))

    segments.append((prow_tip, prow_chin))
    segments.append((stern_plate, stern_keel))

    return segments


def _build_scythe_wireframe() -> list[tuple[Vector3, Vector3]]:
    segments: list[tuple[Vector3, Vector3]] = []

    nose = Vector3(0.0, 1.1, 3.2)
    canopy = Vector3(0.0, 1.5, 1.0)
    tail = Vector3(0.0, -0.6, -3.4)

    left_points = [
        Vector3(-3.0, 0.4, 1.6),
        Vector3(-3.4, 0.3, -0.6),
        Vector3(-2.2, 0.6, -2.4),
    ]

    for point in left_points:
        mirrored = _mirror_vector(point)
        segments.append((point, mirrored))
        segments.append((point, nose))
        segments.append((mirrored, nose))
        segments.append((point, tail))
        segments.append((mirrored, tail))

    dorsal_fin = [
        Vector3(-0.6, 1.8, -0.4),
        Vector3(0.0, 2.1, -1.2),
        Vector3(0.6, 1.8, -0.4),
    ]
    _loop_segments(segments, dorsal_fin)
    for point in dorsal_fin:
        segments.append((point, canopy))

    ventral = Vector3(0.0, -1.2, -0.2)
    segments.append((ventral, nose))
    segments.append((ventral, tail))
    segments.append((ventral, left_points[1]))
    segments.append((ventral, _mirror_vector(left_points[1])))
    segments.append((nose, canopy))
    segments.append((canopy, tail))

    return segments


def _build_maul_wireframe() -> list[tuple[Vector3, Vector3]]:
    segments: list[tuple[Vector3, Vector3]] = []

    prow = Vector3(0.0, 1.8, 3.6)
    bridge = Vector3(0.0, 2.6, 1.2)
    stern = Vector3(0.0, -1.4, -3.8)

    armor_ridge_left = [
        Vector3(-3.2, 1.0, 2.0),
        Vector3(-3.6, 0.9, 0.2),
        Vector3(-2.4, 1.1, -2.6),
    ]

    for point in armor_ridge_left:
        mirrored = _mirror_vector(point)
        segments.append((point, mirrored))
        segments.append((point, prow))
        segments.append((mirrored, prow))
        segments.append((point, stern))
        segments.append((mirrored, stern))
        segments.append((point, bridge))
        segments.append((mirrored, bridge))

    lower_keel = [
        Vector3(-2.0, -1.8, 1.6),
        Vector3(0.0, -2.2, -0.4),
        Vector3(2.0, -1.8, 1.6),
    ]
    _loop_segments(segments, lower_keel)
    for point in lower_keel:
        segments.append((point, stern))

    dorsal_plate = [
        Vector3(-1.6, 2.8, 0.4),
        Vector3(0.0, 3.0, -0.8),
        Vector3(1.6, 2.8, 0.4),
        Vector3(0.0, 2.4, 1.6),
    ]
    _loop_segments(segments, dorsal_plate)
    for point in dorsal_plate:
        segments.append((point, bridge))

    segments.append((prow, bridge))
    segments.append((bridge, stern))

    return segments



def _build_vanir_wireframe() -> list[tuple[Vector3, Vector3]]:
    segments: list[tuple[Vector3, Vector3]] = []

    prow = Vector3(0.0, 4.6, 12.4)
    forward_spine = Vector3(0.0, 4.8, 9.8)
    mid_spine = Vector3(0.0, 5.0, 6.4)
    brace_spine = Vector3(0.0, 4.4, 3.0)
    reactor = Vector3(0.0, 3.8, -2.2)
    engine_core = Vector3(0.0, 3.4, -5.6)
    engine_tail = Vector3(0.0, 3.2, -8.8)
    stern = Vector3(0.0, 2.8, -12.0)

    ventral_prow = Vector3(0.0, 1.2, 12.0)
    ventral_forward_spine = Vector3(0.0, 1.0, 9.8)
    ventral_mid_spine = Vector3(0.0, 0.8, 6.4)
    ventral_brace_spine = Vector3(0.0, 0.6, 3.0)
    ventral_reactor = Vector3(0.0, 0.4, -2.2)
    ventral_engine_core = Vector3(0.0, 0.2, -5.6)
    ventral_engine_tail = Vector3(0.0, 0.0, -8.8)
    ventral_stern = Vector3(0.0, -0.2, -12.0)

    port_outer_hull = [
        Vector3(-5.2, 3.4, 12.4),
        Vector3(-5.6, 3.2, 11.0),
        Vector3(-6.1, 3.0, 9.2),
        Vector3(-6.5, 2.8, 7.2),
        Vector3(-6.9, 2.4, 5.0),
        Vector3(-7.0, 2.2, 3.0),
        Vector3(-6.8, 2.0, 1.0),
        Vector3(-6.5, 1.8, -1.2),
        Vector3(-6.2, 1.7, -3.6),
        Vector3(-5.9, 1.8, -6.0),
        Vector3(-5.6, 2.0, -8.6),
        Vector3(-5.3, 2.2, -11.2),
    ]
    port_outer_hull_lower = [
        Vector3(-5.2, 0.2, 12.4),
        Vector3(-5.6, 0.0, 11.0),
        Vector3(-6.1, -0.4, 9.2),
        Vector3(-6.5, -0.8, 7.2),
        Vector3(-6.9, -1.2, 5.0),
        Vector3(-7.0, -1.4, 3.0),
        Vector3(-6.8, -1.6, 1.0),
        Vector3(-6.5, -1.8, -1.2),
        Vector3(-6.2, -1.9, -3.6),
        Vector3(-5.9, -1.8, -6.0),
        Vector3(-5.6, -1.6, -8.6),
        Vector3(-5.3, -1.4, -11.2),
    ]
    port_inner_hull = [
        Vector3(-2.6, 3.6, 12.0),
        Vector3(-2.9, 3.4, 10.6),
        Vector3(-3.2, 3.2, 9.0),
        Vector3(-3.4, 3.0, 7.4),
        Vector3(-3.5, 2.8, 5.6),
        Vector3(-3.4, 2.6, 3.8),
        Vector3(-3.3, 2.4, 2.0),
        Vector3(-3.1, 2.2, 0.0),
        Vector3(-3.0, 2.0, -2.2),
        Vector3(-2.9, 2.0, -4.6),
        Vector3(-2.8, 2.2, -7.2),
        Vector3(-2.8, 2.4, -9.8),
    ]
    port_inner_hull_lower = [
        Vector3(-2.6, 0.2, 12.0),
        Vector3(-2.9, 0.0, 10.6),
        Vector3(-3.2, -0.2, 9.0),
        Vector3(-3.4, -0.4, 7.4),
        Vector3(-3.5, -0.6, 5.6),
        Vector3(-3.4, -0.8, 3.8),
        Vector3(-3.3, -1.0, 2.0),
        Vector3(-3.1, -1.2, 0.0),
        Vector3(-3.0, -1.4, -2.2),
        Vector3(-2.9, -1.4, -4.6),
        Vector3(-2.8, -1.2, -7.2),
        Vector3(-2.8, -1.0, -9.8),
    ]

    _loop_segments(segments, port_outer_hull, close=False)
    _loop_segments(segments, port_inner_hull, close=False)
    _loop_segments(segments, port_outer_hull_lower, close=False)
    _loop_segments(segments, port_inner_hull_lower, close=False)

    mirrored_outer_hull = [_mirror_vector(point) for point in port_outer_hull]
    mirrored_inner_hull = [_mirror_vector(point) for point in port_inner_hull]
    mirrored_outer_hull_lower = [_mirror_vector(point) for point in port_outer_hull_lower]
    mirrored_inner_hull_lower = [_mirror_vector(point) for point in port_inner_hull_lower]
    _loop_segments(segments, mirrored_outer_hull, close=False)
    _loop_segments(segments, mirrored_inner_hull, close=False)
    _loop_segments(segments, mirrored_outer_hull_lower, close=False)
    _loop_segments(segments, mirrored_inner_hull_lower, close=False)

    hull_anchor_points = [
        prow,
        prow,
        forward_spine,
        forward_spine,
        mid_spine,
        mid_spine,
        brace_spine,
        brace_spine,
        reactor,
        reactor,
        engine_core,
        engine_tail,
    ]
    ventral_anchor_points = [
        ventral_prow,
        ventral_prow,
        ventral_forward_spine,
        ventral_forward_spine,
        ventral_mid_spine,
        ventral_mid_spine,
        ventral_brace_spine,
        ventral_brace_spine,
        ventral_reactor,
        ventral_reactor,
        ventral_engine_core,
        ventral_engine_tail,
    ]

    rear_support_start = 8

    for index in range(len(port_outer_hull)):
        outer = port_outer_hull[index]
        inner = port_inner_hull[index]
        lower_outer = port_outer_hull_lower[index]
        lower_inner = port_inner_hull_lower[index]
        mirrored_outer = mirrored_outer_hull[index]
        mirrored_inner = mirrored_inner_hull[index]
        mirrored_lower_outer = mirrored_outer_hull_lower[index]
        mirrored_lower_inner = mirrored_inner_hull_lower[index]

        segments.append((outer, inner))
        segments.append((mirrored_outer, mirrored_inner))
        segments.append((outer, lower_outer))
        segments.append((inner, lower_inner))
        segments.append((mirrored_outer, mirrored_lower_outer))
        segments.append((mirrored_inner, mirrored_lower_inner))
        segments.append((lower_outer, lower_inner))
        segments.append((mirrored_lower_outer, mirrored_lower_inner))

        if index >= rear_support_start:
            segments.append((inner, mirrored_inner))
            segments.append((lower_inner, mirrored_lower_inner))

            anchor = hull_anchor_points[index]
            segments.append((inner, anchor))
            segments.append((mirrored_inner, anchor))
            ventral_anchor = ventral_anchor_points[index]
            segments.append((lower_inner, ventral_anchor))
            segments.append((mirrored_lower_inner, ventral_anchor))

        if index >= len(port_outer_hull) - 2:
            segments.append((outer, stern))
            segments.append((mirrored_outer, stern))
            segments.append((lower_outer, ventral_stern))
            segments.append((mirrored_lower_outer, ventral_stern))

    rear_spine = [
        reactor,
        engine_core,
        engine_tail,
        stern,
    ]
    _loop_segments(segments, rear_spine, close=False)

    ventral_spine = [
        ventral_prow,
        ventral_forward_spine,
        ventral_mid_spine,
        ventral_brace_spine,
        ventral_reactor,
        ventral_engine_core,
        ventral_engine_tail,
        ventral_stern,
    ]
    for start, end in zip(ventral_spine, ventral_spine[1:]):
        segments.append((start, end))

    dorsal_spine = [
        prow,
        forward_spine,
        mid_spine,
        brace_spine,
        reactor,
        engine_core,
        engine_tail,
        stern,
    ]
    for upper, lower in zip(dorsal_spine, ventral_spine):
        segments.append((upper, lower))

    rear_cross_braces = [
        (-3.4, 2.4, 2.0, 8, 9),
        (-5.6, 2.3, 2.1, 9, 10),
    ]
    for z_position, upper_y, lower_y, upper_index, lower_index in rear_cross_braces:
        port_upper = Vector3(port_inner_hull[upper_index].x, upper_y, z_position)
        starboard_upper = _mirror_vector(port_upper)
        port_lower = Vector3(port_inner_hull[lower_index].x, lower_y, z_position - 0.4)
        starboard_lower = _mirror_vector(port_lower)

        brace_loop = [
            port_upper,
            starboard_upper,
            starboard_lower,
            port_lower,
        ]
        _loop_segments(segments, brace_loop)
        segments.append((port_upper, port_inner_hull[upper_index]))
        segments.append((starboard_upper, mirrored_inner_hull[upper_index]))
        segments.append((port_lower, port_inner_hull[lower_index]))
        segments.append((starboard_lower, mirrored_inner_hull[lower_index]))
        segments.append((port_lower, port_inner_hull_lower[lower_index]))
        segments.append((starboard_lower, mirrored_inner_hull_lower[lower_index]))

    vane_pairs = [
        (Vector3(-6.6, 1.8, -0.8), Vector3(-8.2, 1.6, -1.4)),
        (Vector3(-6.8, 1.7, -2.2), Vector3(-8.4, 1.5, -3.0)),
        (Vector3(-6.9, 1.6, -3.6), Vector3(-8.5, 1.4, -4.6)),
        (Vector3(-6.7, 1.6, -5.2), Vector3(-8.1, 1.4, -6.6)),
    ]
    for base, tip in vane_pairs:
        segments.append((base, tip))
        mirrored_base = _mirror_vector(base)
        mirrored_tip = _mirror_vector(tip)
        segments.append((mirrored_base, mirrored_tip))
        lower_base = Vector3(base.x, -1.2, base.z)
        lower_mirrored = _mirror_vector(lower_base)
        segments.append((base, lower_base))
        segments.append((mirrored_base, lower_mirrored))
        segments.append((lower_base, lower_mirrored))

        if base.z > -2.0:
            anchor = ventral_brace_spine
        elif base.z > -4.5:
            anchor = ventral_reactor
        else:
            anchor = ventral_engine_core
        segments.append((lower_base, anchor))
        segments.append((lower_mirrored, anchor))

    engine_rings_z = [-6.0, -7.2, -8.6]
    for ring_z in engine_rings_z:
        ring = [
            Vector3(-1.4, 3.4, ring_z),
            Vector3(-0.8, 3.8, ring_z),
            Vector3(0.0, 4.0, ring_z),
            Vector3(0.8, 3.8, ring_z),
            Vector3(1.4, 3.4, ring_z),
            Vector3(0.0, 3.0, ring_z),
        ]
        _loop_segments(segments, ring)
        for point in ring:
            anchor = engine_core if ring_z > -7.0 else engine_tail
            segments.append((point, anchor))
            ventral_anchor = ventral_engine_core if ring_z > -7.0 else ventral_engine_tail
            segments.append((point, ventral_anchor))

    aft_block_port = [
        Vector3(-4.6, 2.2, -5.8),
        Vector3(-5.2, 2.0, -7.4),
        Vector3(-4.8, 2.2, -9.4),
        Vector3(-4.0, 2.4, -7.6),
    ]
    aft_block = aft_block_port + [_mirror_vector(point) for point in reversed(aft_block_port)]
    _loop_segments(segments, aft_block)
    for point in aft_block:
        segments.append((point, engine_core))
        segments.append((point, ventral_engine_core))

    exhaust_band = [
        Vector3(-2.2, 2.6, -11.0),
        Vector3(-1.2, 2.4, -11.6),
        Vector3(0.0, 2.2, -11.8),
        Vector3(1.2, 2.4, -11.6),
        Vector3(2.2, 2.6, -11.0),
        Vector3(0.0, 3.0, -10.8),
    ]
    _loop_segments(segments, exhaust_band)
    for point in exhaust_band:
        segments.append((point, stern))
        segments.append((point, ventral_stern))

    nose_outline_port = [
        Vector3(-3.2, 3.6, 12.2),
        Vector3(-4.0, 3.4, 11.6),
        Vector3(-3.4, 3.2, 10.6),
    ]
    nose_outline = (
        nose_outline_port
        + [Vector3(0.0, 4.2, 12.4)]
        + [_mirror_vector(point) for point in reversed(nose_outline_port)]
    )
    _loop_segments(segments, nose_outline)
    for point in nose_outline:
        segments.append((point, forward_spine))
        segments.append((point, ventral_prow))

    nose_outline_lower_port = [
        Vector3(-3.2, 0.6, 12.0),
        Vector3(-4.0, 0.4, 11.4),
        Vector3(-3.4, 0.2, 10.6),
    ]
    nose_outline_lower = (
        nose_outline_lower_port
        + [Vector3(0.0, 1.0, 12.2)]
        + [_mirror_vector(point) for point in reversed(nose_outline_lower_port)]
    )
    _loop_segments(segments, nose_outline_lower)
    for point in nose_outline_lower:
        segments.append((point, ventral_forward_spine))
        segments.append((point, ventral_prow))

    return segments


def _build_brimir_wireframe() -> list[tuple[Vector3, Vector3]]:
    segments: list[tuple[Vector3, Vector3]] = []

    length_scale = 0.75
    width_scale = 0.62
    height_scale = 0.62

    base_profile = [
        (-640.0, 150.0, 96.0),
        (-560.0, 146.0, 92.0),
        (-480.0, 140.0, 88.0),
        (-360.0, 180.0, 102.0),
        (-240.0, 210.0, 114.0),
        (-120.0, 232.0, 122.0),
        (0.0, 240.0, 126.0),
        (160.0, 230.0, 120.0),
        (320.0, 200.0, 110.0),
        (440.0, 164.0, 94.0),
        (520.0, 136.0, 80.0),
        (560.0, 120.0, 70.0),
    ]

    ring_sides = 18
    hull_sections: list[tuple[float, float, float, list[Vector3]]] = []
    previous_section: tuple[float, float, float, list[Vector3]] | None = None

    for z_raw, width_raw, height_raw in base_profile:
        z = z_raw * length_scale
        half_width = width_raw * width_scale
        half_height = height_raw * height_scale
        ring = _elliptical_ring(z, half_width, half_height, sides=ring_sides)
        hull_sections.append((z, half_width, half_height, ring))
        _loop_segments(segments, ring)
        if previous_section is not None:
            previous_ring = previous_section[3]
            for current, previous in zip(ring, previous_ring):
                segments.append((current, previous))
            for offset in range(0, ring_sides, 6):
                segments.append((ring[offset], ring[(offset + 3) % ring_sides]))
        previous_section = (z, half_width, half_height, ring)

    def hull_anchor(z_target: float, x_sign: int, y_factor: float) -> Vector3:
        section = min(hull_sections, key=lambda entry: abs(entry[0] - z_target))
        z, half_width, half_height, _ = section
        clamped_y = max(-1.0, min(1.0, y_factor))
        return Vector3(half_width * x_sign * 0.88, half_height * clamped_y, z)

    tail_section = hull_sections[0]
    nose_section = hull_sections[-1]
    mid_section = hull_sections[len(hull_sections) // 2]

    tail_z = tail_section[0]
    nose_z = nose_section[0]
    mid_z = mid_section[0]

    stern = Vector3(0.0, -68.0 * height_scale, tail_z - 5.0 * length_scale)
    nose_tip = Vector3(0.0, 42.0 * height_scale, nose_z + 70.0 * length_scale)
    ventral_spear = Vector3(0.0, -36.0 * height_scale, nose_z + 60.0 * length_scale)

    dorsal_spine = [
        nose_tip,
        Vector3(0.0, 90.0 * height_scale, mid_z + 180.0 * length_scale),
        Vector3(0.0, 96.0 * height_scale, mid_z),
        Vector3(0.0, 84.0 * height_scale, tail_z - 120.0 * length_scale),
        stern,
    ]
    for start, end in zip(dorsal_spine, dorsal_spine[1:]):
        segments.append((start, end))

    ventral_spine = [
        ventral_spear,
        Vector3(0.0, -74.0 * height_scale, mid_z + 120.0 * length_scale),
        Vector3(0.0, -78.0 * height_scale, mid_z - 40.0 * length_scale),
        Vector3(0.0, -70.0 * height_scale, tail_z - 80.0 * length_scale),
        stern,
    ]
    for start, end in zip(ventral_spine, ventral_spine[1:]):
        segments.append((start, end))

    forward_ring = nose_section[3]
    for index in range(0, ring_sides, 2):
        point = forward_ring[index]
        segments.append((point, nose_tip))
        segments.append((point, ventral_spear))

    nose_ridge_port = [
        Vector3(-52.0 * width_scale, 48.0 * height_scale, nose_z + 28.0 * length_scale),
        Vector3(-34.0 * width_scale, 56.0 * height_scale, nose_z + 48.0 * length_scale),
        Vector3(-18.0 * width_scale, 60.0 * height_scale, nose_z + 62.0 * length_scale),
    ]
    nose_ridge = (
        nose_ridge_port
        + [Vector3(0.0, 64.0 * height_scale, nose_z + 66.0 * length_scale)]
        + [_mirror_vector(point) for point in reversed(nose_ridge_port)]
    )
    _loop_segments(segments, nose_ridge)
    for point in nose_ridge:
        segments.append((point, nose_tip))

    ventral_ridge_port = [
        Vector3(-40.0 * width_scale, -38.0 * height_scale, nose_z + 26.0 * length_scale),
        Vector3(-26.0 * width_scale, -46.0 * height_scale, nose_z + 44.0 * length_scale),
        Vector3(-14.0 * width_scale, -48.0 * height_scale, nose_z + 56.0 * length_scale),
    ]
    ventral_ridge = (
        ventral_ridge_port
        + [Vector3(0.0, -52.0 * height_scale, nose_z + 60.0 * length_scale)]
        + [_mirror_vector(point) for point in reversed(ventral_ridge_port)]
    )
    _loop_segments(segments, ventral_ridge)
    for point in ventral_ridge:
        segments.append((point, ventral_spear))

    segments.append((nose_tip, ventral_spear))

    tower_base_z = mid_z + 120.0 * length_scale
    tower_mid = Vector3(0.0, 178.0 * height_scale, tower_base_z - 80.0 * length_scale)
    tower_tip = Vector3(0.0, 214.0 * height_scale, tower_base_z - 160.0 * length_scale)
    tower_back = Vector3(0.0, 150.0 * height_scale, tower_base_z - 250.0 * length_scale)
    tower_frame_port = [
        Vector3(-48.0 * width_scale, 118.0 * height_scale, tower_base_z + 24.0 * length_scale),
        Vector3(-34.0 * width_scale, 142.0 * height_scale, tower_base_z - 12.0 * length_scale),
        Vector3(-26.0 * width_scale, 158.0 * height_scale, tower_base_z - 88.0 * length_scale),
        Vector3(-20.0 * width_scale, 150.0 * height_scale, tower_base_z - 162.0 * length_scale),
    ]
    tower_frame = (
        tower_frame_port
        + [_mirror_vector(point) for point in reversed(tower_frame_port)]
    )
    _loop_segments(segments, tower_frame)
    for point in tower_frame:
        segments.append((point, tower_mid))
    segments.append((tower_mid, tower_tip))
    segments.append((tower_tip, tower_back))
    segments.append((tower_mid, hull_anchor(tower_base_z - 20.0 * length_scale, -1, 0.68)))
    segments.append((tower_mid, hull_anchor(tower_base_z - 20.0 * length_scale, 1, 0.68)))
    segments.append((tower_back, hull_anchor(tower_back.z, -1, 0.52)))
    segments.append((tower_back, hull_anchor(tower_back.z, 1, 0.52)))

    belt_samples = [
        nose_z + 40.0 * length_scale,
        mid_z + 160.0 * length_scale,
        mid_z,
        mid_z - 160.0 * length_scale,
        tail_z - 120.0 * length_scale,
    ]
    upper_belt_port = [hull_anchor(sample, -1, 0.66) for sample in belt_samples]
    upper_belt = upper_belt_port + [
        _mirror_vector(point) for point in reversed(upper_belt_port)
    ]
    _loop_segments(segments, upper_belt)

    lower_belt_port = [hull_anchor(sample, -1, -0.58) for sample in belt_samples]
    lower_belt = lower_belt_port + [
        _mirror_vector(point) for point in reversed(lower_belt_port)
    ]
    _loop_segments(segments, lower_belt)

    for port_point, lower_point in zip(upper_belt_port, lower_belt_port):
        segments.append((port_point, lower_point))
        star_upper = _mirror_vector(port_point)
        star_lower = _mirror_vector(lower_point)
        segments.append((star_upper, star_lower))

    hangar_front_z = mid_z + 120.0 * length_scale
    hangar_back_z = mid_z - 120.0 * length_scale
    hangar_half_width = 188.0 * width_scale
    hangar_frame = [
        Vector3(-hangar_half_width, -60.0 * height_scale, hangar_front_z),
        Vector3(-hangar_half_width, -60.0 * height_scale, hangar_back_z),
        Vector3(hangar_half_width, -60.0 * height_scale, hangar_back_z),
        Vector3(hangar_half_width, -60.0 * height_scale, hangar_front_z),
    ]
    _loop_segments(segments, hangar_frame)
    hangar_pivot = Vector3(0.0, -96.0 * height_scale, mid_z)
    for point in hangar_frame:
        segments.append((point, hangar_pivot))

    pod_front_z = mid_z + 220.0 * length_scale
    pod_back_z = mid_z - 240.0 * length_scale
    pod_outer_x = 320.0 * width_scale
    pod_inner_x = 200.0 * width_scale
    pod_top_y = 72.0 * height_scale
    pod_bottom_y = -74.0 * height_scale
    pod_inner_top_y = 44.0 * height_scale
    pod_inner_bottom_y = -48.0 * height_scale

    port_front = [
        Vector3(-pod_outer_x, pod_top_y, pod_front_z),
        Vector3(-pod_inner_x, pod_inner_top_y, pod_front_z),
        Vector3(-pod_inner_x, pod_inner_bottom_y, pod_front_z),
        Vector3(-pod_outer_x, pod_bottom_y, pod_front_z),
    ]
    port_back = [
        Vector3(-pod_outer_x, pod_top_y, pod_back_z),
        Vector3(-pod_inner_x, pod_inner_top_y, pod_back_z),
        Vector3(-pod_inner_x, pod_inner_bottom_y, pod_back_z),
        Vector3(-pod_outer_x, pod_bottom_y, pod_back_z),
    ]
    _loop_segments(segments, port_front)
    _loop_segments(segments, port_back)
    for index in range(len(port_front)):
        segments.append((port_front[index], port_back[index]))

    star_front = [_mirror_vector(point) for point in port_front]
    star_back = [_mirror_vector(point) for point in port_back]
    _loop_segments(segments, star_front)
    _loop_segments(segments, star_back)
    for index in range(len(star_front)):
        segments.append((star_front[index], star_back[index]))

    for port_point, star_point in zip(port_front, star_front):
        segments.append((port_point, star_point))
    for port_point, star_point in zip(port_back, star_back):
        segments.append((port_point, star_point))

    def attach_pod(points: list[Vector3], x_sign: int) -> None:
        for point in points:
            y_ratio = point.y / (pod_top_y if point.y >= 0.0 else abs(pod_bottom_y))
            anchor = hull_anchor(point.z, x_sign, y_ratio)
            segments.append((point, anchor))

    attach_pod(port_front[1:3], -1)
    attach_pod(port_back[1:3], -1)
    attach_pod(star_front[1:3], 1)
    attach_pod(star_back[1:3], 1)

    for point in (port_front[0], port_back[0]):
        segments.append((point, hull_anchor(point.z, -1, 0.4)))
    for point in (port_front[3], port_back[3]):
        segments.append((point, hull_anchor(point.z, -1, -0.5)))
    for point in (star_front[0], star_back[0]):
        segments.append((point, hull_anchor(point.z, 1, 0.4)))
    for point in (star_front[3], star_back[3]):
        segments.append((point, hull_anchor(point.z, 1, -0.5)))

    catapult_offset = 32.0 * width_scale
    port_catapult_front = Vector3(
        -pod_outer_x + catapult_offset,
        pod_top_y - 10.0 * height_scale,
        pod_front_z,
    )
    port_catapult_back = Vector3(
        -pod_outer_x + catapult_offset,
        pod_top_y - 10.0 * height_scale,
        pod_back_z,
    )
    segments.append((port_catapult_front, port_catapult_back))
    star_catapult_front = _mirror_vector(port_catapult_front)
    star_catapult_back = _mirror_vector(port_catapult_back)
    segments.append((star_catapult_front, star_catapult_back))

    ship_length = nose_tip.z - stern.z
    thruster_length = ship_length * 0.25
    thruster_protrusion = thruster_length * 0.25
    thruster_front_z = stern.z - thruster_protrusion + thruster_length
    thruster_back_z = stern.z - thruster_protrusion
    thruster_cap_z = thruster_back_z - thruster_protrusion * 0.15
    thruster_support_z = thruster_front_z - thruster_length * 0.25

    thruster_offset_x = tail_section[1] * 0.55
    thruster_offset_y = tail_section[2] * 0.55
    thruster_radius_x = tail_section[1] * 0.28
    thruster_radius_y = tail_section[2] * 0.34
    nozzle_radius_x = thruster_radius_x * 0.78
    nozzle_radius_y = thruster_radius_y * 0.74
    thruster_sides = 10

    def thruster_ring(
        center_x: float,
        center_y: float,
        z_pos: float,
        radius_x: float,
        radius_y: float,
    ) -> list[Vector3]:
        angle_step = 2.0 * math.pi / thruster_sides
        return [
            Vector3(
                center_x + math.cos(step * angle_step) * radius_x,
                center_y + math.sin(step * angle_step) * radius_y,
                z_pos,
            )
            for step in range(thruster_sides)
        ]

    for x_sign in (-1, 1):
        for y_sign in (-1, 1):
            center_x = x_sign * thruster_offset_x
            center_y = y_sign * thruster_offset_y
            front_ring = thruster_ring(
                center_x,
                center_y,
                thruster_front_z,
                thruster_radius_x,
                thruster_radius_y,
            )
            nozzle_ring = thruster_ring(
                center_x,
                center_y,
                thruster_back_z,
                nozzle_radius_x,
                nozzle_radius_y,
            )

            _loop_segments(segments, front_ring)
            _loop_segments(segments, nozzle_ring)
            for index in range(0, thruster_sides, 2):
                segments.append((front_ring[index], nozzle_ring[index]))

            nozzle_cap = Vector3(center_x, center_y, thruster_cap_z)
            for point in nozzle_ring[::4]:
                segments.append((point, nozzle_cap))

            support_anchor = hull_anchor(
                thruster_support_z,
                x_sign,
                y_sign * 0.72,
            )
            for index in range(0, thruster_sides, thruster_sides // 2):
                segments.append((front_ring[index], support_anchor))

    segments.append((tower_tip, nose_tip))
    segments.append((tower_back, ventral_spear))

    return segments


WIREFRAMES = {
    "Strike": [
        (Vector3(0, 0.3, 2.5), Vector3(0.9, 0, -2.0)),
        (Vector3(0, 0.3, 2.5), Vector3(-0.9, 0, -2.0)),
        (Vector3(0, -0.3, 2.5), Vector3(0.9, 0, -2.0)),
        (Vector3(0, -0.3, 2.5), Vector3(-0.9, 0, -2.0)),
        (Vector3(0.9, 0, -2.0), Vector3(-0.9, 0, -2.0)),
        (Vector3(0.9, 0, -2.0), Vector3(0, 0.3, 2.5)),
    ],
    "Escort": _build_escort_wireframe(),
    "Line": _build_line_wireframe(),
    "Capital": _build_brimir_wireframe(),
    "Outpost": _build_outpost_wireframe(),
    "viper_mk_ii": _build_viper_mk_ii_wireframe(),
    "viper_mk_vii": _build_viper_mk_vii_wireframe(),
    "raptor_fr": _build_raptor_wireframe(),
    "viper_mk_iii": _build_viper_mk_iii_wireframe(),
    "rhino_strike": _build_rhino_wireframe(),
    "raven_mk_vi_r": _build_raven_wireframe(),
    "glaive_command": _build_glaive_wireframe(),
    "scythe_interceptor": _build_scythe_wireframe(),
    "maul_assault": _build_maul_wireframe(),
    "vanir_command": _build_vanir_wireframe(),
    "brimir_carrier": _build_brimir_wireframe(),
}

SHIP_GEOMETRY_CACHE = _build_ship_geometry_cache()



LINE_VERTEX_SHADER = """
#version 330 core
layout(location = 0) in vec3 a_position;
uniform mat4 u_projection;
uniform mat4 u_view;
uniform mat4 u_model;
void main() {
    gl_Position = u_projection * u_view * u_model * vec4(a_position, 1.0);
}
"""

LINE_FRAGMENT_SHADER = """
#version 330 core
uniform vec4 u_color;
out vec4 fragColor;
void main() {
    fragColor = u_color;
}
"""

UI_VERTEX_SHADER = """
#version 330 core
layout(location = 0) in vec2 a_position;
layout(location = 1) in vec2 a_texcoord;
out vec2 v_texcoord;
void main() {
    v_texcoord = a_texcoord;
    gl_Position = vec4(a_position, 0.0, 1.0);
}
"""

UI_FRAGMENT_SHADER = """
#version 330 core
in vec2 v_texcoord;
uniform sampler2D u_texture;
out vec4 fragColor;
void main() {
    fragColor = texture(u_texture, v_texcoord);
}
"""


def _compile_shader(source: str, shader_type: int) -> int:
    _require_gl()
    shader = gl.glCreateShader(shader_type)
    gl.glShaderSource(shader, source)
    gl.glCompileShader(shader)
    status = gl.glGetShaderiv(shader, gl.GL_COMPILE_STATUS)
    if not status:
        info = gl.glGetShaderInfoLog(shader).decode('utf-8', errors='ignore')
        gl.glDeleteShader(shader)
        raise RuntimeError(f'Failed to compile shader: {info}')
    return shader


def _create_program(vertex_source: str, fragment_source: str) -> int:
    _require_gl()
    program = gl.glCreateProgram()
    vertex = _compile_shader(vertex_source, gl.GL_VERTEX_SHADER)
    fragment = _compile_shader(fragment_source, gl.GL_FRAGMENT_SHADER)
    gl.glAttachShader(program, vertex)
    gl.glAttachShader(program, fragment)
    gl.glLinkProgram(program)
    status = gl.glGetProgramiv(program, gl.GL_LINK_STATUS)
    if not status:
        info = gl.glGetProgramInfoLog(program).decode('utf-8', errors='ignore')
        gl.glDeleteProgram(program)
        raise RuntimeError(f'Failed to link program: {info}')
    gl.glDeleteShader(vertex)
    gl.glDeleteShader(fragment)
    return program


def _color_to_vec4(color: tuple[int, int, int], alpha: float = 1.0) -> list[float]:
    return [color[0] / 255.0, color[1] / 255.0, color[2] / 255.0, alpha]


def _flatten_matrix(rows: Sequence[Sequence[float]]) -> list[float]:
    return [
        rows[0][0], rows[1][0], rows[2][0], rows[3][0],
        rows[0][1], rows[1][1], rows[2][1], rows[3][1],
        rows[0][2], rows[1][2], rows[2][2], rows[3][2],
        rows[0][3], rows[1][3], rows[2][3], rows[3][3],
    ]


def _projection_matrix(frame: CameraFrameData) -> list[float]:
    aspect = frame.aspect if frame.aspect > 0 else 1.0
    tan_half = frame.tan_half_fov if frame.tan_half_fov > 0 else 1.0
    f = 1.0 / tan_half
    near = frame.near if frame.near > 0 else 0.1
    far = frame.far if frame.far > near else near + 1.0
    rows = [
        [f / aspect, 0.0, 0.0, 0.0],
        [0.0, f, 0.0, 0.0],
        [0.0, 0.0, (far + near) / (near - far), (2.0 * far * near) / (near - far)],
        [0.0, 0.0, -1.0, 0.0],
    ]
    return _flatten_matrix(rows)


def _view_matrix(frame: CameraFrameData) -> list[float]:
    position = frame.position
    right = Vector3(frame.right)
    up = Vector3(frame.up)
    forward = Vector3(frame.forward)
    if right.length() > 1e-6:
        right = right.normalize()
    if up.length() > 1e-6:
        up = up.normalize()
    if forward.length() > 1e-6:
        forward = forward.normalize()
    rows = [
        [right.x, right.y, right.z, -right.dot(position)],
        [up.x, up.y, up.z, -up.dot(position)],
        [-forward.x, -forward.y, -forward.z, forward.dot(position)],
        [0.0, 0.0, 0.0, 1.0],
    ]
    return _flatten_matrix(rows)


def _model_matrix(origin: Vector3, axes: tuple[Vector3, Vector3, Vector3], scale: float) -> list[float]:
    right, up, forward = axes
    rows = [
        [right.x * scale, right.y * scale, right.z * scale, 0.0],
        [up.x * scale, up.y * scale, up.z * scale, 0.0],
        [forward.x * scale, forward.y * scale, forward.z * scale, 0.0],
        [origin.x, origin.y, origin.z, 1.0],
    ]
    return _flatten_matrix(rows)


def _identity_matrix() -> list[float]:
    rows = [
        [1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 1.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
    return _flatten_matrix(rows)


@dataclass
class _LineMesh:
    vao: int
    vbo: int
    vertex_count: int

    @classmethod
    def from_segments(cls, vertices: Sequence[float], usage: Optional[int] = None) -> "_LineMesh":
        _require_gl()
        usage = gl.GL_STATIC_DRAW if usage is None else usage
        if not vertices:
            vao = gl.glGenVertexArrays(1)
            vbo = gl.glGenBuffers(1)
            gl.glBindVertexArray(vao)
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo)
            gl.glBufferData(gl.GL_ARRAY_BUFFER, 0, None, usage)
            gl.glEnableVertexAttribArray(0)
            gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, False, 12, ctypes.c_void_p(0))
            gl.glBindVertexArray(0)
            return cls(vao, vbo, 0)
        arr = array('f', vertices)
        vao = gl.glGenVertexArrays(1)
        vbo = gl.glGenBuffers(1)
        gl.glBindVertexArray(vao)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, len(arr) * arr.itemsize, arr, usage)
        gl.glEnableVertexAttribArray(0)
        gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, False, 12, ctypes.c_void_p(0))
        gl.glBindVertexArray(0)
        return cls(vao, vbo, len(vertices) // 3)


class _DynamicLineMesh:
    def __init__(self) -> None:
        _require_gl()
        self.vao = gl.glGenVertexArrays(1)
        self.vbo = gl.glGenBuffers(1)
        gl.glBindVertexArray(self.vao)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, 0, None, gl.GL_DYNAMIC_DRAW)
        gl.glEnableVertexAttribArray(0)
        gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, False, 12, ctypes.c_void_p(0))
        gl.glBindVertexArray(0)
        self.vertex_count = 0

    def update(self, vertices: Sequence[float]) -> None:
        _require_gl()
        arr = array('f', vertices)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.vbo)
        if arr:
            gl.glBufferData(gl.GL_ARRAY_BUFFER, len(arr) * arr.itemsize, arr, gl.GL_DYNAMIC_DRAW)
            self.vertex_count = len(arr) // 3
        else:
            gl.glBufferData(gl.GL_ARRAY_BUFFER, 0, None, gl.GL_DYNAMIC_DRAW)
            self.vertex_count = 0


class _LineProgram:
    def __init__(self) -> None:
        _require_gl()
        self.program = _create_program(LINE_VERTEX_SHADER, LINE_FRAGMENT_SHADER)
        self._u_projection = gl.glGetUniformLocation(self.program, 'u_projection')
        self._u_view = gl.glGetUniformLocation(self.program, 'u_view')
        self._u_model = gl.glGetUniformLocation(self.program, 'u_model')
        self._u_color = gl.glGetUniformLocation(self.program, 'u_color')

    def use(self) -> None:
        _require_gl()
        gl.glUseProgram(self.program)

    def set_projection(self, matrix: Sequence[float]) -> None:
        _require_gl()
        gl.glUniformMatrix4fv(self._u_projection, 1, False, matrix)

    def set_view(self, matrix: Sequence[float]) -> None:
        _require_gl()
        gl.glUniformMatrix4fv(self._u_view, 1, False, matrix)

    def set_model(self, matrix: Sequence[float]) -> None:
        _require_gl()
        gl.glUniformMatrix4fv(self._u_model, 1, False, matrix)

    def set_color(self, color: tuple[int, int, int], alpha: float = 1.0) -> None:
        _require_gl()
        vec = _color_to_vec4(color, alpha)
        gl.glUniform4fv(self._u_color, 1, vec)


class _QuadBlitter:
    def __init__(self) -> None:
        _require_gl()
        self.program = _create_program(UI_VERTEX_SHADER, UI_FRAGMENT_SHADER)
        self._u_texture = gl.glGetUniformLocation(self.program, 'u_texture')
        vertices = array(
            'f',
            [
                -1.0, -1.0, 0.0, 0.0,
                1.0, -1.0, 1.0, 0.0,
                1.0, 1.0, 1.0, 1.0,
                -1.0, -1.0, 0.0, 0.0,
                1.0, 1.0, 1.0, 1.0,
                -1.0, 1.0, 0.0, 1.0,
            ],
        )
        self.vao = gl.glGenVertexArrays(1)
        self.vbo = gl.glGenBuffers(1)
        gl.glBindVertexArray(self.vao)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, len(vertices) * vertices.itemsize, vertices, gl.GL_STATIC_DRAW)
        gl.glEnableVertexAttribArray(0)
        gl.glVertexAttribPointer(0, 2, gl.GL_FLOAT, False, 16, ctypes.c_void_p(0))
        gl.glEnableVertexAttribArray(1)
        gl.glVertexAttribPointer(1, 2, gl.GL_FLOAT, False, 16, ctypes.c_void_p(8))
        gl.glBindVertexArray(0)

    def draw(self, texture: int) -> None:
        _require_gl()
        gl.glUseProgram(self.program)
        gl.glUniform1i(self._u_texture, 0)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, texture)
        gl.glBindVertexArray(self.vao)
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, 6)
        gl.glBindVertexArray(0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, 0)


class VectorRenderer:
    def __init__(self, surface: Optional[pygame.Surface]) -> None:
        _require_gl()
        self._surface: Optional[pygame.Surface] = None
        self.surface = surface
        self._line_program = _LineProgram()
        self._quad_blitter = _QuadBlitter()
        self._ui_texture = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self._ui_texture)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)
        gl.glBindTexture(gl.GL_TEXTURE_2D, 0)
        self._ui_size: tuple[int, int] = (0, 0)
        self._ship_geometry_cache = dict(SHIP_GEOMETRY_CACHE)
        self._ship_meshes: Dict[str, _LineMesh] = self._build_ship_meshes()
        self._grid_mesh = _DynamicLineMesh()
        self._temp_mesh = _DynamicLineMesh()
        self._projectile_mesh = _DynamicLineMesh()
        self._identity = _identity_matrix()
        self._viewport_size: tuple[int, int] = (0, 0)

    @property
    def surface(self) -> Optional[pygame.Surface]:
        return self._surface

    @surface.setter
    def surface(self, value: Optional[pygame.Surface]) -> None:
        self._surface = value
        if value is not None:
            _require_gl()
            width, height = value.get_size()
            self._viewport_size = (int(width), int(height))
            gl.glViewport(0, 0, self._viewport_size[0], self._viewport_size[1])

    def _prepare_frame(self, camera: ChaseCamera) -> Optional[CameraFrameData]:
        if not self._surface:
            return None
        _require_gl()
        frame = camera.prepare_frame(self._surface.get_size())
        projection = _projection_matrix(frame)
        view = _view_matrix(frame)
        self._line_program.use()
        self._line_program.set_projection(projection)
        self._line_program.set_view(view)
        return frame

    def _draw_mesh(
        self,
        mesh: _LineMesh,
        color: tuple[int, int, int],
        model: Sequence[float],
    ) -> None:
        if mesh.vertex_count <= 0:
            return
        _require_gl()
        self._line_program.use()
        self._line_program.set_model(model)
        self._line_program.set_color(color)
        gl.glBindVertexArray(mesh.vao)
        gl.glDrawArrays(gl.GL_LINES, 0, mesh.vertex_count)
        gl.glBindVertexArray(0)

    def _draw_dynamic(
        self,
        mesh: _DynamicLineMesh,
        color: tuple[int, int, int],
        model: Optional[Sequence[float]] = None,
    ) -> None:
        if mesh.vertex_count <= 0:
            return
        _require_gl()
        self._line_program.use()
        self._line_program.set_model(model if model is not None else self._identity)
        self._line_program.set_color(color)
        gl.glBindVertexArray(mesh.vao)
        gl.glDrawArrays(gl.GL_LINES, 0, mesh.vertex_count)
        gl.glBindVertexArray(0)

    def _build_ship_meshes(self) -> Dict[str, _LineMesh]:
        meshes: Dict[str, _LineMesh] = {}
        for key, geometry in self._ship_geometry_cache.items():
            segments: list[float] = []
            for idx_a, idx_b in geometry.edges:
                start = geometry.vertices[idx_a]
                end = geometry.vertices[idx_b]
                segments.extend([start.x, start.y, start.z, end.x, end.y, end.z])
            meshes[key] = _LineMesh.from_segments(segments)
        return meshes

    def clear(self) -> None:
        if self._viewport_size == (0, 0) and self._surface:
            self._viewport_size = self._surface.get_size()
        _require_gl()
        gl.glViewport(0, 0, self._viewport_size[0], self._viewport_size[1])
        gl.glClearColor(
            BACKGROUND[0] / 255.0,
            BACKGROUND[1] / 255.0,
            BACKGROUND[2] / 255.0,
            1.0,
        )
        gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)

    def draw_grid(
        self,
        camera: ChaseCamera,
        focus: Vector3,
        *,
        tile_size: float = 220.0,
        extent: float = 3600.0,
        height_offset: float = -18.0,
    ) -> None:
        frame = self._prepare_frame(camera)
        if not frame or tile_size <= 0.0 or extent <= 0.0:
            return
        half_extent = extent * 0.5
        grid_y = focus.y + height_offset
        start_x = int(floor((focus.x - half_extent) / tile_size))
        end_x = int(ceil((focus.x + half_extent) / tile_size))
        start_z = int(floor((focus.z - half_extent) / tile_size))
        end_z = int(ceil((focus.z + half_extent) / tile_size))
        minor_vertices: list[float] = []
        major_vertices: list[float] = []
        for xi in range(start_x, end_x + 1):
            x_world = xi * tile_size
            a = Vector3(x_world, grid_y, start_z * tile_size)
            b = Vector3(x_world, grid_y, end_z * tile_size)
            target = major_vertices if xi % 5 == 0 else minor_vertices
            target.extend([a.x, a.y, a.z, b.x, b.y, b.z])
        for zi in range(start_z, end_z + 1):
            z_world = zi * tile_size
            a = Vector3(start_x * tile_size, grid_y, z_world)
            b = Vector3(end_x * tile_size, grid_y, z_world)
            target = major_vertices if zi % 5 == 0 else minor_vertices
            target.extend([a.x, a.y, a.z, b.x, b.y, b.z])
        if minor_vertices:
            self._grid_mesh.update(minor_vertices)
            self._draw_dynamic(self._grid_mesh, GRID_MINOR_COLOR)
        if major_vertices:
            self._grid_mesh.update(major_vertices)
            self._draw_dynamic(self._grid_mesh, GRID_MAJOR_COLOR)

    def draw_ship(self, camera: ChaseCamera, ship: Ship) -> None:
        frame = self._prepare_frame(camera)
        if not frame:
            return
        geometry = self._ship_geometry_cache.get(
            ship.frame.id,
            self._ship_geometry_cache.get(
                ship.frame.size, self._ship_geometry_cache.get('Strike')
            ),
        )
        if not geometry:
            return
        mesh = self._ship_meshes.get(ship.frame.id) or self._ship_meshes.get(ship.frame.size)
        if mesh is None:
            mesh = self._ship_meshes.get('Strike')
        if not mesh:
            return
        scale = _ship_geometry_scale(ship, geometry)
        origin = ship.kinematics.position
        basis = ship.kinematics.basis
        model = _model_matrix(origin, (basis.right, basis.up, basis.forward), scale)
        color = SHIP_COLOR if ship.team == 'player' else ENEMY_COLOR
        self._draw_mesh(mesh, color, model)

    def draw_asteroids(self, camera: ChaseCamera, asteroids: Iterable[Asteroid]) -> None:
        frame = self._prepare_frame(camera)
        if not frame:
            return
        right = frame.right
        up = frame.up
        segments = 24
        for asteroid in asteroids:
            radius = max(asteroid.radius, 1.0)
            center = asteroid.position
            vertices: list[float] = []
            for index in range(segments):
                angle_a = (index / segments) * (2.0 * math.pi)
                angle_b = ((index + 1) / segments) * (2.0 * math.pi)
                point_a = center + right * math.cos(angle_a) * radius + up * math.sin(angle_a) * radius
                point_b = center + right * math.cos(angle_b) * radius + up * math.sin(angle_b) * radius
                vertices.extend([point_a.x, point_a.y, point_a.z, point_b.x, point_b.y, point_b.z])
            self._temp_mesh.update(vertices)
            self._draw_dynamic(self._temp_mesh, asteroid.display_color)

    def draw_projectiles(self, camera: ChaseCamera, projectiles: Iterable[Projectile]) -> None:
        frame = self._prepare_frame(camera)
        if not frame:
            return
        projectile_lines: list[float] = []
        missile_lines: list[float] = []
        for projectile in projectiles:
            if projectile.ttl <= 0.0:
                continue
            start = projectile.position
            velocity = projectile.velocity
            direction = velocity.normalize() if velocity.length_squared() > 1e-6 else frame.forward
            length = max(6.0, min(140.0, velocity.length() * 0.04 + 12.0))
            end = start - direction * length
            target = missile_lines if projectile.weapon.wclass == 'missile' else projectile_lines
            target.extend([start.x, start.y, start.z, end.x, end.y, end.z])
        if projectile_lines:
            self._projectile_mesh.update(projectile_lines)
            self._draw_dynamic(self._projectile_mesh, PROJECTILE_COLOR)
        if missile_lines:
            self._projectile_mesh.update(missile_lines)
            self._draw_dynamic(self._projectile_mesh, MISSILE_COLOR)

    def present_ui(self, surface: pygame.Surface) -> None:
        width, height = surface.get_size()
        if width <= 0 or height <= 0:
            return
        _require_gl()
        gl.glDisable(gl.GL_DEPTH_TEST)
        pixel_data = pygame.image.tostring(surface, 'RGBA', True)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self._ui_texture)
        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)
        if (width, height) != self._ui_size:
            gl.glTexImage2D(
                gl.GL_TEXTURE_2D,
                0,
                gl.GL_RGBA,
                width,
                height,
                0,
                gl.GL_RGBA,
                gl.GL_UNSIGNED_BYTE,
                pixel_data,
            )
            self._ui_size = (width, height)
        else:
            gl.glTexSubImage2D(
                gl.GL_TEXTURE_2D,
                0,
                0,
                0,
                width,
                height,
                gl.GL_RGBA,
                gl.GL_UNSIGNED_BYTE,
                pixel_data,
            )
        self._quad_blitter.draw(self._ui_texture)
        gl.glEnable(gl.GL_DEPTH_TEST)


__all__ = ['VectorRenderer']
