"""Vector renderer built on pygame."""
from __future__ import annotations

from dataclasses import dataclass
from math import ceil, floor
import logging
import math
import random
from typing import Dict, Iterable, List, Sequence, Tuple

import pygame
from pygame.math import Vector3

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
MISSILE_COLOR = (255, 140, 60)

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

    mid_upper_loop = _compress_loop(
        _stretched_oval_loop(
            sides=oval_sides,
            center_y=1.7,
            center_z=0.4,
            half_width_x=1.55,
            half_depth_z=1.7,
            vertical_rake=0.15,
            vertical_crown=0.18,
        )
    )
    _loop_segments(segments, mid_upper_loop)

    mid_lower_loop = _compress_loop(
        _stretched_oval_loop(
            sides=oval_sides,
            center_y=-0.25,
            center_z=0.2,
            half_width_x=1.35,
            half_depth_z=1.6,
            vertical_rake=0.22,
            vertical_crown=-0.12,
        )
    )
    _loop_segments(segments, mid_lower_loop)

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

    upper_loops = [prow_upper_loop, neck_upper_loop, mid_upper_loop, stern_upper_loop]
    lower_loops = [prow_lower_loop, neck_lower_loop, mid_lower_loop, stern_lower_loop]

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
            Vector3(-1.25, 1.5, 0.9),
            Vector3(-1.35, 1.4, -0.1),
            Vector3(-1.35, 1.4, -1.2),
            Vector3(-1.2, 1.5, -2.0),
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

    _loop_segments(segments, port_outer_hull, close=False)
    _loop_segments(segments, port_inner_hull, close=False)

    mirrored_outer_hull = [_mirror_vector(point) for point in port_outer_hull]
    mirrored_inner_hull = [_mirror_vector(point) for point in port_inner_hull]
    _loop_segments(segments, mirrored_outer_hull, close=False)
    _loop_segments(segments, mirrored_inner_hull, close=False)

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

    rear_support_start = 8

    for index in range(len(port_outer_hull)):
        outer = port_outer_hull[index]
        inner = port_inner_hull[index]
        mirrored_outer = mirrored_outer_hull[index]
        mirrored_inner = mirrored_inner_hull[index]

        segments.append((outer, inner))
        segments.append((mirrored_outer, mirrored_inner))

        if index >= rear_support_start:
            segments.append((inner, mirrored_inner))

            anchor = hull_anchor_points[index]
            segments.append((inner, anchor))
            segments.append((mirrored_inner, anchor))

        if index >= len(port_outer_hull) - 2:
            segments.append((outer, stern))
            segments.append((mirrored_outer, stern))

    rear_spine = [
        reactor,
        engine_core,
        engine_tail,
        stern,
    ]
    _loop_segments(segments, rear_spine, close=False)

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

    return segments


def _build_brimir_wireframe() -> list[tuple[Vector3, Vector3]]:
    segments: list[tuple[Vector3, Vector3]] = []

    prow = Vector3(0.0, 12.0, 22.0)
    tower = Vector3(0.0, 18.0, 6.0)
    stern = Vector3(0.0, -10.0, -20.0)

    port_planes = [
        Vector3(-12.0, 6.0, 14.0),
        Vector3(-16.0, 5.0, 6.0),
        Vector3(-14.0, 4.5, -2.0),
        Vector3(-10.0, 4.0, -12.0),
    ]

    for point in port_planes:
        mirrored = _mirror_vector(point)
        segments.append((point, mirrored))
        segments.append((point, prow))
        segments.append((mirrored, prow))
        segments.append((point, stern))
        segments.append((mirrored, stern))
        segments.append((point, tower))
        segments.append((mirrored, tower))

    dorsal_array = [
        Vector3(-4.0, 16.0, -4.0),
        Vector3(0.0, 17.5, -6.0),
        Vector3(4.0, 16.0, -4.0),
        Vector3(0.0, 14.5, 0.0),
    ]
    _loop_segments(segments, dorsal_array)
    for point in dorsal_array:
        segments.append((point, tower))

    ventral_keel = [
        Vector3(-6.0, -12.0, 8.0),
        Vector3(0.0, -13.0, 2.0),
        Vector3(6.0, -12.0, 8.0),
        Vector3(0.0, -11.0, 12.0),
    ]
    _loop_segments(segments, ventral_keel)
    for point in ventral_keel:
        segments.append((point, stern))

    hangar_frame = [
        Vector3(-8.0, -2.0, 4.0),
        Vector3(-8.0, -2.0, -4.0),
        Vector3(8.0, -2.0, -4.0),
        Vector3(8.0, -2.0, 4.0),
    ]
    _loop_segments(segments, hangar_frame)
    for point in hangar_frame:
        segments.append((point, ventral_keel[1]))

    segments.append((prow, tower))
    segments.append((tower, stern))

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


class VectorRenderer:
    def __init__(self, surface: pygame.Surface) -> None:
        self.surface = surface
        self._rng = random.Random()
        self._ship_geometry_cache: Dict[str, ShipGeometry] = dict(SHIP_GEOMETRY_CACHE)
        self._vertex_cache: Dict[int, ProjectedVertexCache] = {}
        self._frame_counters = TelemetryCounters()
        self._telemetry_accum = TelemetryCounters()
        self._frame_active = False
        self._last_report_ms = pygame.time.get_ticks()
        self._telemetry_interval_ms = 2500
        self._current_camera_frame: CameraFrameData | None = None

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
    ) -> tuple[List[tuple[float, float]], List[bool]]:
        cache = self._vertex_cache.setdefault(id(ship), ProjectedVertexCache())
        if (
            cache.camera_revision == frame.revision
            and cache.world_revision == state.world_revision
        ):
            return cache.vertices, cache.visibility
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
        cache.update(frame.revision, state.world_revision, vertices_2d, visibility)
        if min_x <= max_x and min_y <= max_y:
            state.cached_screen_rect = (min_x, min_y, max_x, max_y)
            state.cached_camera_revision = frame.revision
        else:
            state.clear_cached_projection()
        self._frame_counters.vertices_projected_total += len(geometry.vertices)
        self._frame_counters.objects_projected += 1
        return vertices_2d, visibility

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

            base_screen, vis_base = frame.project_point(base_world)
            muzzle_screen, vis_muzzle = frame.project_point(muzzle_world)
            if not vis_base:
                continue

            armed = bool(mount.weapon_id)
            base_color = _lighten(color, 0.25) if armed else _darken(color, 0.35)
            muzzle_color = _lighten(color, 0.55) if armed else _darken(color, 0.15)
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

            center, vis_center = frame.project_point(asteroid.position)
            if not vis_center:
                state.clear_cached_projection()
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
                    dx = projected.x - center.x
                    dy = projected.y - center.y
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
                continue

            points: List[tuple[float, float]] = []
            for angle, offset, h_scale, v_scale in zip(
                profile.point_angles,
                profile.point_offsets,
                profile.horizontal_scale,
                profile.vertical_scale,
            ):
                x = center.x + math.cos(angle) * radius_horizontal * h_scale * offset
                y = center.y + math.sin(angle) * radius_vertical * v_scale * offset
                points.append((x, y))

            if len(points) < 3:
                state.clear_cached_projection()
                continue

            self._frame_counters.vertices_projected_total += projection_count
            self._frame_counters.objects_projected += 1

            polygon_points = [(int(round(px)), int(round(py))) for px, py in points]
            xs = [px for px, _ in points]
            ys = [py for _, py in points]
            state.cached_screen_rect = (min(xs), min(ys), max(xs), max(ys))
            state.cached_camera_revision = frame.revision

            color = asteroid.display_color
            pygame.draw.polygon(self.surface, color, polygon_points)

            outline_color = _darken(color, 0.45)
            line_mode = "line" if distance > 7500.0 else "aaline"
            if line_mode == "line":
                pygame.draw.lines(self.surface, outline_color, True, polygon_points, 1)
                self._frame_counters.objects_drawn_line += 1
            else:
                pygame.draw.aalines(self.surface, outline_color, True, points, blend=1)
                self._frame_counters.objects_drawn_aaline += 1

            if radius_horizontal > 3.0 or radius_vertical > 3.0:
                highlight_color = _lighten(color, 0.5)
                shadow_color = _darken(color, 0.6)
                accent_radius = max(
                    1,
                    int(round((radius_horizontal + radius_vertical) * 0.05)),
                )
                for accent in profile.accents:
                    px = center.x + math.cos(accent.angle) * radius_horizontal * accent.distance * accent.horizontal_scale
                    py = center.y + math.sin(accent.angle) * radius_vertical * accent.distance * accent.vertical_scale
                    pygame.draw.circle(
                        self.surface,
                        highlight_color if accent.highlight else shadow_color,
                        (int(round(px)), int(round(py))),
                        accent_radius,
                    )

                crater_fill = _darken(color, 0.55)
                crater_rim = _lighten(color, 0.2)
                for crater in profile.craters:
                    px = center.x + math.cos(crater.angle) * radius_horizontal * crater.distance
                    py = center.y + math.sin(crater.angle) * radius_vertical * crater.distance
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
        projected, visibility = self._project_ship_vertices(
            ship,
            geometry,
            frame,
            state,
            origin,
            (right, up, forward),
            scale=scale,
        )
        color = SHIP_COLOR if ship.team == "player" else ENEMY_COLOR
        line_mode = "line" if distance > 7500.0 else "aaline"
        drawn_edges = False
        for idx_a, idx_b in geometry.edges:
            if not (visibility[idx_a] and visibility[idx_b]):
                continue
            ax, ay = projected[idx_a]
            bx, by = projected[idx_b]
            if line_mode == "line":
                pygame.draw.line(
                    self.surface,
                    color,
                    (int(round(ax)), int(round(ay))),
                    (int(round(bx)), int(round(by))),
                    1,
                )
            else:
                pygame.draw.aaline(self.surface, color, (ax, ay), (bx, by), blend=1)
            drawn_edges = True

        if drawn_edges:
            if line_mode == "line":
                self._frame_counters.objects_drawn_line += 1
            else:
                self._frame_counters.objects_drawn_aaline += 1

        speed = ship.kinematics.velocity.length()
        speed_intensity = 0.0
        if speed > 80.0:
            speed_intensity = min(1.0, (speed - 80.0) / 35.0)
        if speed_intensity > 0.0:
            self._draw_speed_streaks(frame, origin, right, up, forward, ship, speed_intensity)

        self._draw_hardpoints(frame, origin, right, up, forward, ship, color, scale=scale)
        self._draw_engines(frame, origin, right, up, forward, ship, color, scale=scale)

    def draw_projectiles(self, camera: ChaseCamera, projectiles: Iterable[Projectile]) -> None:
        for projectile in projectiles:
            color = MISSILE_COLOR if projectile.weapon.wclass == "missile" else PROJECTILE_COLOR
            screen_pos, visible = camera.project(projectile.position, self.surface.get_size())
            if visible:
                pygame.draw.circle(self.surface, color, (int(screen_pos.x), int(screen_pos.y)), 3, 1)


__all__ = ["VectorRenderer"]
