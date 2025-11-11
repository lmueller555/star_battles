"""Vector renderer built on pygame."""
from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil, floor
import math
import random
from typing import Iterable

import pygame
from pygame.math import Vector3

from game.combat.weapons import Projectile
from game.render.camera import ChaseCamera
from game.ships.ship import Ship
from game.world.asteroids import Asteroid

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
class HullGeometry:
    segments: list[tuple[Vector3, Vector3]]
    sections: list[list[Vector3]] = field(default_factory=list)
    caps: list[list[Vector3]] = field(default_factory=list)


LIGHT_DIRECTION = Vector3(0.35, 0.9, -0.4)
if LIGHT_DIRECTION.length_squared() > 1e-6:
    LIGHT_DIRECTION = LIGHT_DIRECTION.normalize()
else:
    LIGHT_DIRECTION = Vector3(0.0, 1.0, -0.25)


_PALETTE_PRESETS: dict[str, tuple[tuple[int, int, int], tuple[int, int, int]]] = {
    "viper_mk_vii": ((120, 184, 248), (252, 112, 96)),
    "glaive_command": ((214, 172, 116), (255, 214, 138)),
    "vanir_command": ((132, 208, 180), (88, 238, 196)),
    "brimir_carrier": ((162, 154, 226), (124, 206, 255)),
    "outpost_regular": ((186, 208, 232), (248, 228, 152)),
}

_PALETTE_CACHE: dict[str, tuple[tuple[int, int, int], tuple[int, int, int]]] = {}


def _shade_color(color: tuple[int, int, int], shade: float) -> tuple[int, int, int]:
    shade = max(0.1, min(1.4, shade))
    return tuple(
        int(max(0, min(255, round(component * shade))))
        for component in color
    )


def _palette_for_frame(frame_id: str) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    palette = _PALETTE_CACHE.get(frame_id)
    if palette is not None:
        return palette
    preset = _PALETTE_PRESETS.get(frame_id)
    if preset is not None:
        palette = preset
    else:
        seed = (hash(frame_id) ^ 0xACE11235) & 0xFFFFFFFF
        rng = random.Random(seed)
        base = tuple(rng.randint(96, 196) for _ in range(3))
        accent_channels = []
        for component in base:
            factor = 1.15 + rng.random() * 0.4
            offset = rng.randint(-18, 28)
            accent_channels.append(
                int(max(0, min(255, round(component * factor + offset))))
            )
        accent = tuple(accent_channels)
        if sum(abs(a - b) for a, b in zip(base, accent)) < 60:
            accent = tuple(min(255, max(0, channel + 72)) for channel in accent)
        palette = (base, accent)
    _PALETTE_CACHE[frame_id] = palette
    return palette


def _build_mesh_triangles(geometry: HullGeometry) -> list[list[Vector3]]:
    surfaces: list[list[Vector3]] = []
    sections = geometry.sections
    if sections:
        for ring_a, ring_b in zip(sections[:-1], sections[1:]):
            limit = min(len(ring_a), len(ring_b))
            if limit < 2:
                continue
            for index in range(limit):
                next_index = (index + 1) % limit
                surfaces.append(
                    [ring_a[index], ring_b[index], ring_b[next_index]]
                )
                surfaces.append(
                    [ring_a[index], ring_b[next_index], ring_a[next_index]]
                )
    for cap in geometry.caps:
        if len(cap) < 3:
            continue
        anchor = cap[0]
        for index in range(1, len(cap) - 1):
            surfaces.append([anchor, cap[index], cap[index + 1]])
    return surfaces


def _build_strike_skin_mesh() -> list[list[Vector3]]:
    nose_top = Vector3(0.0, 0.34, 2.6)
    nose_bottom = Vector3(0.0, -0.36, 2.55)
    mid_top = Vector3(0.0, 0.3, 1.1)
    mid_bottom = Vector3(0.0, -0.3, 1.1)
    tail_top = Vector3(0.0, 0.22, -2.15)
    tail_bottom = Vector3(0.0, -0.24, -2.15)
    dorsal_spine = Vector3(0.0, 0.4, -0.35)
    ventral_keel = Vector3(0.0, -0.42, -0.9)
    left_wing_front = Vector3(-0.95, 0.04, 0.3)
    right_wing_front = Vector3(0.95, 0.04, 0.3)
    left_tail = Vector3(-0.68, -0.14, -2.05)
    right_tail = Vector3(0.68, -0.14, -2.05)

    return [
        [nose_top, left_wing_front, dorsal_spine],
        [nose_top, dorsal_spine, right_wing_front],
        [dorsal_spine, left_wing_front, tail_top],
        [dorsal_spine, tail_top, right_wing_front],
        [left_wing_front, mid_top, right_wing_front],
        [nose_bottom, ventral_keel, left_tail],
        [nose_bottom, right_tail, ventral_keel],
        [ventral_keel, left_tail, tail_bottom],
        [ventral_keel, tail_bottom, right_tail],
        [left_tail, mid_bottom, right_tail],
    ]


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
    forward = ship.kinematics.forward()
    right = ship.kinematics.right()
    up = right.cross(forward)
    if up.length_squared() == 0.0:
        up = Vector3(0.0, 1.0, 0.0)
    else:
        up = up.normalize()
    return right.normalize(), up, forward.normalize()


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


def _build_outpost_geometry() -> HullGeometry:
    """Construct a capital-ship silhouette for Outposts."""

    segments: list[tuple[Vector3, Vector3]] = []
    caps: list[list[Vector3]] = []

    hull_profile: list[tuple[float, float, float]] = [
        (-520.0, 90.0, 55.0),
        (-440.0, 140.0, 70.0),
        (-360.0, 180.0, 90.0),
        (-240.0, 220.0, 110.0),
        (-120.0, 240.0, 125.0),
        (0.0, 250.0, 140.0),
        (120.0, 230.0, 130.0),
        (240.0, 200.0, 110.0),
        (360.0, 170.0, 95.0),
        (480.0, 140.0, 80.0),
        (560.0, 120.0, 70.0),
    ]

    ring_sides = 24
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
                segments.append((ring[offset], ring[(offset + 6) % ring_sides]))
                segments.append((previous_ring[offset], previous_ring[(offset + 6) % ring_sides]))
                segments.append((ring[offset], previous_ring[(offset + 3) % ring_sides]))
        previous_ring = ring

    nose_tip = Vector3(0.0, 40.0, hull_profile[-1][0] + 80.0)
    ventral_spear = Vector3(0.0, -35.0, hull_profile[-1][0] + 70.0)
    final_section = hull_sections[-1]
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
    caps.append([nose_tip] + final_section)
    caps.append([ventral_spear] + list(reversed(final_section)))

    dorsal_spine_points: list[Vector3] = []
    ventral_keel_points: list[Vector3] = []
    for z_pos, _, half_height in hull_profile:
        dorsal_spine_points.append(Vector3(0.0, half_height * 1.4 + 30.0, z_pos))
        ventral_keel_points.append(Vector3(0.0, -half_height * 1.3 - 20.0, z_pos))
    _loop_segments(segments, dorsal_spine_points, close=False)
    _loop_segments(segments, ventral_keel_points, close=False)
    for top, bottom in zip(dorsal_spine_points, ventral_keel_points):
        segments.append((top, bottom))

    tower_base_z = -60.0
    tower_profile = [
        Vector3(0.0, 220.0, tower_base_z - 40.0),
        Vector3(70.0, 240.0, tower_base_z - 20.0),
        Vector3(70.0, 320.0, tower_base_z + 30.0),
        Vector3(-70.0, 320.0, tower_base_z + 30.0),
        Vector3(-70.0, 240.0, tower_base_z - 20.0),
    ]
    _loop_segments(segments, tower_profile)
    bridge_tip = Vector3(0.0, 360.0, tower_base_z + 60.0)
    for point in tower_profile:
        segments.append((point, bridge_tip))

    flank_ridges: list[list[Vector3]] = []
    for sign in (-1.0, 1.0):
        ridge_points: list[Vector3] = []
        for z_pos, half_width, half_height in hull_profile[1:-1]:
            ridge_points.append(
                Vector3(sign * (half_width * 1.1 + 30.0), half_height * 0.6, z_pos)
            )
        flank_ridges.append(ridge_points)
        _loop_segments(segments, ridge_points, close=False)
        for point, section in zip(ridge_points, hull_sections[1:-1]):
            anchor = section[ring_sides // 4 if sign > 0 else (ring_sides * 3) // 4]
            segments.append((point, anchor))

    wing_span = 520.0
    wing_thickness = 55.0
    wing_points = [
        Vector3(-wing_span, -wing_thickness, -120.0),
        Vector3(-wing_span * 0.4, 20.0, -200.0),
        Vector3(0.0, 60.0, -220.0),
        Vector3(wing_span * 0.4, 20.0, -200.0),
        Vector3(wing_span, -wing_thickness, -120.0),
        Vector3(wing_span * 0.3, -90.0, -40.0),
        Vector3(-wing_span * 0.3, -90.0, -40.0),
    ]
    _loop_segments(segments, wing_points)
    for index in range(len(wing_points)):
        segments.append((wing_points[index], wing_points[(index + 3) % len(wing_points)]))

    engine_clusters: list[list[Vector3]] = []
    tail_z = hull_profile[0][0]
    engine_offset_x = hull_profile[0][1] + 120.0
    for sign in (-1.0, 1.0):
        for vertical in (-1.0, 1.0):
            center = Vector3(sign * engine_offset_x, vertical * 90.0, tail_z - 40.0)
            ring = [
                Vector3(
                    center.x + math.cos(angle) * 70.0,
                    center.y + math.sin(angle) * 70.0,
                    center.z,
                )
                for angle in [step * (2.0 * math.pi / 16) for step in range(16)]
            ]
            engine_clusters.append(ring)
            _loop_segments(segments, ring)
            thruster_end = Vector3(center.x, center.y, center.z - 70.0)
            for point in ring[::2]:
                segments.append((point, thruster_end))
            anchor_index = ring_sides // 6 if sign > 0 else (ring_sides * 5) // 6
            anchor_index += 0 if vertical > 0 else ring_sides // 2
            hull_anchor = hull_sections[0][anchor_index % ring_sides]
            for point in ring[::4]:
                segments.append((point, hull_anchor))

    plating_lines = []
    for fraction in (0.15, 0.35, 0.65, 0.85):
        idx = int(fraction * (len(hull_sections) - 1))
        plating_lines.append(hull_sections[idx])
    for section in plating_lines:
        for offset in range(0, ring_sides, 2):
            segments.append((section[offset], section[(offset + 2) % ring_sides]))

    dorsal_array_z = 200.0
    dorsal_array = [
        Vector3(-140.0, 360.0, dorsal_array_z - 60.0),
        Vector3(0.0, 380.0, dorsal_array_z),
        Vector3(140.0, 360.0, dorsal_array_z - 60.0),
        Vector3(0.0, 340.0, dorsal_array_z - 120.0),
    ]
    _loop_segments(segments, dorsal_array)
    for point in dorsal_array:
        segments.append((point, dorsal_spine_points[len(dorsal_spine_points) // 2]))

    ventral_bay_z = -160.0
    bay_frame = [
        Vector3(-130.0, -220.0, ventral_bay_z - 80.0),
        Vector3(130.0, -220.0, ventral_bay_z - 80.0),
        Vector3(160.0, -160.0, ventral_bay_z + 40.0),
        Vector3(-160.0, -160.0, ventral_bay_z + 40.0),
    ]
    _loop_segments(segments, bay_frame)
    for point in bay_frame:
        segments.append((point, ventral_keel_points[len(ventral_keel_points) // 2]))

    tail_section = hull_sections[0] if hull_sections else []
    if tail_section:
        tail_center = Vector3()
        for point in tail_section:
            tail_center += point
        tail_center /= len(tail_section)
        caps.append([tail_center] + tail_section)

    return HullGeometry(segments=segments, sections=hull_sections, caps=caps)


def _build_line_geometry() -> HullGeometry:
    """Construct a heavy line-ship silhouette with rich surface detail."""

    segments: list[tuple[Vector3, Vector3]] = []
    caps: list[list[Vector3]] = []

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

    ring_sides = 22
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
    caps.append([prow_tip] + final_section)
    caps.append([prow_keel] + list(reversed(final_section)))

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
                for angle in [step * (2.0 * math.pi / 14) for step in range(14)]
            ]
            _loop_segments(segments, ring)
            thruster_end = Vector3(center.x, center.y, center.z - 44.0)
            for point in ring[::2]:
                segments.append((point, thruster_end))
            hull_anchor_index = ring_sides // 6 if sign > 0 else (ring_sides * 5) // 6
            hull_anchor_index += 0 if vertical > 0 else ring_sides // 2
            hull_anchor = hull_sections[0][hull_anchor_index % ring_sides]
            segments.append((center, hull_anchor))

    tail_section = hull_sections[0] if hull_sections else []
    if tail_section:
        tail_center = Vector3()
        for point in tail_section:
            tail_center += point
        tail_center /= len(tail_section)
        caps.append([tail_center] + tail_section)

    return HullGeometry(segments=segments, sections=hull_sections, caps=caps)


def _build_escort_geometry() -> HullGeometry:
    """Construct an escort-class silhouette with layered armor panels."""

    segments: list[tuple[Vector3, Vector3]] = []
    caps: list[list[Vector3]] = []

    hull_profile: list[tuple[float, float, float]] = [
        (-72.0, 22.0, 12.0),
        (-62.0, 27.0, 14.0),
        (-52.0, 32.0, 16.0),
        (-38.0, 36.0, 18.0),
        (-24.0, 40.0, 20.0),
        (-8.0, 42.0, 21.0),
        (8.0, 42.0, 21.0),
        (24.0, 38.0, 19.0),
        (38.0, 32.0, 16.0),
        (52.0, 26.0, 14.0),
        (66.0, 20.0, 12.0),
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
    caps.append([canopy_tip] + final_section)
    caps.append([intake] + list(reversed(final_section)))

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
            for angle in [step * (2.0 * math.pi / 10) for step in range(10)]
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

    tail_section = hull_sections[0] if hull_sections else []
    if tail_section:
        tail_center = Vector3()
        for point in tail_section:
            tail_center += point
        tail_center /= len(tail_section)
        caps.append([tail_center] + tail_section)

    return HullGeometry(segments=segments, sections=hull_sections, caps=caps)

_ESCORT_GEOMETRY = _build_escort_geometry()
_LINE_GEOMETRY = _build_line_geometry()
_OUTPOST_GEOMETRY = _build_outpost_geometry()


WIREFRAMES = {
    "Strike": [
        (Vector3(0, 0.3, 2.5), Vector3(0.9, 0, -2.0)),
        (Vector3(0, 0.3, 2.5), Vector3(-0.9, 0, -2.0)),
        (Vector3(0, -0.3, 2.5), Vector3(0.9, 0, -2.0)),
        (Vector3(0, -0.3, 2.5), Vector3(-0.9, 0, -2.0)),
        (Vector3(0.9, 0, -2.0), Vector3(-0.9, 0, -2.0)),
        (Vector3(0.9, 0, -2.0), Vector3(0, 0.3, 2.5)),
    ],
    "Escort": _ESCORT_GEOMETRY.segments,
    "Line": _LINE_GEOMETRY.segments,
    "Outpost": _OUTPOST_GEOMETRY.segments,
}


SKIN_MESHES = {
    "Strike": _build_strike_skin_mesh(),
    "Escort": _build_mesh_triangles(_ESCORT_GEOMETRY),
    "Line": _build_mesh_triangles(_LINE_GEOMETRY),
    "Outpost": _build_mesh_triangles(_OUTPOST_GEOMETRY),
}

SKIN_OVERRIDES: dict[str, list[list[Vector3]]] = {}


class VectorRenderer:
    def __init__(self, surface: pygame.Surface) -> None:
        self.surface = surface
        self._rng = random.Random()

    @staticmethod
    def _local_to_world(
        origin: Vector3,
        right: Vector3,
        up: Vector3,
        forward: Vector3,
        local: Vector3,
    ) -> Vector3:
        return origin + right * local.x + up * local.y + forward * local.z

    def _draw_skin(
        self,
        camera: ChaseCamera,
        origin: Vector3,
        right: Vector3,
        up: Vector3,
        forward: Vector3,
        ship: Ship,
    ) -> None:
        mesh = SKIN_OVERRIDES.get(ship.frame.id)
        if mesh is None:
            mesh = SKIN_MESHES.get(ship.frame.size, [])
        if not mesh:
            return

        base_color, accent_color = _palette_for_frame(ship.frame.id)
        screen_size = self.surface.get_size()

        local_min_z = min((point.z for triangle in mesh for point in triangle), default=0.0)
        local_max_z = max((point.z for triangle in mesh for point in triangle), default=0.0)
        span = local_max_z - local_min_z
        rng = random.Random((hash(ship.frame.id) ^ 0x6C8E9CF5) & 0xFFFFFFFF)
        accent_bands: list[tuple[float, float]] = []
        if span > 1e-3:
            band_count = 3 if ship.frame.size in {"Line", "Outpost"} else 2
            for _ in range(band_count):
                center = rng.uniform(local_min_z + span * 0.15, local_max_z - span * 0.15)
                width = span * rng.uniform(0.08, 0.18)
                accent_bands.append((center - width * 0.5, center + width * 0.5))
        highlight_push = rng.uniform(0.05, 0.16)

        render_triangles: list[
            tuple[float, list[tuple[int, int]], tuple[int, int, int], tuple[int, int, int]]
        ] = []

        for triangle in mesh:
            if len(triangle) < 3:
                continue
            centroid_local = Vector3()
            centroid_world = Vector3()
            world_points: list[Vector3] = []
            screen_points: list[tuple[int, int]] = []
            depths: list[float] = []
            visible = True
            for local in triangle:
                centroid_local += local
                world = self._local_to_world(origin, right, up, forward, local)
                centroid_world += world
                screen, vis = camera.project(world, screen_size)
                if not vis:
                    visible = False
                    break
                world_points.append(world)
                screen_points.append((int(round(screen.x)), int(round(screen.y))))
                depths.append(screen.z)
            if not visible:
                continue
            centroid_local /= len(triangle)
            centroid_world /= len(triangle)
            edge1 = world_points[1] - world_points[0]
            edge2 = world_points[2] - world_points[0]
            normal = edge1.cross(edge2)
            if normal.length_squared() <= 1e-6:
                continue
            normal = normal.normalize()
            view_dir = camera.position - centroid_world
            if view_dir.length_squared() <= 1e-6:
                continue
            view_dir = view_dir.normalize()
            facing = normal.dot(view_dir)
            if facing <= 0.0:
                normal = -normal
                facing = -facing
            if facing <= 0.01:
                continue

            light_strength = max(0.0, normal.dot(LIGHT_DIRECTION))
            shade = 0.35 + light_strength * 0.65
            if centroid_local.y < 0.0:
                shade *= 0.85
            else:
                shade *= 1.0 + highlight_push * 0.5
            shade = max(0.2, min(1.3, shade))

            color = base_color
            if accent_bands and any(low <= centroid_local.z <= high for low, high in accent_bands):
                color = accent_color
            fill_color = _shade_color(color, shade)
            outline_color = _darken(fill_color, 0.35)
            average_depth = sum(depths) / len(depths)
            render_triangles.append((average_depth, screen_points, fill_color, outline_color))

        render_triangles.sort(reverse=True, key=lambda item: item[0])
        for _, points, fill_color, outline_color in render_triangles:
            if len(points) < 3:
                continue
            pygame.draw.polygon(self.surface, fill_color, points)
            pygame.draw.polygon(self.surface, outline_color, points, 1)

    def _draw_speed_streaks(
        self,
        camera: ChaseCamera,
        origin: Vector3,
        right: Vector3,
        up: Vector3,
        forward: Vector3,
        ship: Ship,
        intensity: float,
    ) -> None:
        if intensity <= 0.0:
            return

        tick = pygame.time.get_ticks()
        self._rng.seed((id(ship) ^ tick) & 0xFFFFFFFF)

        velocity = ship.kinematics.velocity
        direction = velocity.normalize() if velocity.length_squared() > 1e-3 else forward
        screen_size = self.surface.get_size()

        streak_count = 6 + int(24 * intensity)
        base_length = 1.6 + 2.4 * intensity
        for _ in range(streak_count):
            lateral = (
                camera.right * self._rng.uniform(-6.0, 6.0)
                + camera.up * self._rng.uniform(-3.5, 3.5)
            )
            forward_offset = direction * self._rng.uniform(-3.0, 6.0)
            start_world = origin + lateral + forward_offset
            end_world = start_world - direction * (
                base_length + self._rng.uniform(0.0, base_length * 0.8)
            )

            start_screen, vis_start = camera.project(start_world, screen_size)
            end_screen, vis_end = camera.project(end_world, screen_size)
            if not (vis_start and vis_end):
                continue

            brightness = max(
                0.0,
                min(1.0, 0.18 + intensity * 0.6 + self._rng.uniform(-0.1, 0.1)),
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
        camera: ChaseCamera,
        origin: Vector3,
        right: Vector3,
        up: Vector3,
        forward: Vector3,
        ship: Ship,
        color: tuple[int, int, int],
    ) -> None:
        if not ship.mounts:
            return

        screen_size = self.surface.get_size()
        for mount in ship.mounts:
            local = mount.hardpoint.position
            base_world = self._local_to_world(origin, right, up, forward, local)
            muzzle_world = base_world + forward * 0.9

            base_screen, vis_base = camera.project(base_world, screen_size)
            muzzle_screen, vis_muzzle = camera.project(muzzle_world, screen_size)
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
        camera: ChaseCamera,
        origin: Vector3,
        right: Vector3,
        up: Vector3,
        forward: Vector3,
        ship: Ship,
        color: tuple[int, int, int],
    ) -> None:
        layout = ENGINE_LAYOUTS.get(ship.frame.size, ENGINE_LAYOUTS.get("Strike", []))
        if not layout:
            return

        screen_size = self.surface.get_size()
        tick = pygame.time.get_ticks() * 0.001
        for index, local in enumerate(layout):
            base_world = self._local_to_world(origin, right, up, forward, local)
            nozzle_world = base_world - forward * 0.35
            base_screen, vis_base = camera.project(base_world, screen_size)
            nozzle_screen, vis_nozzle = camera.project(nozzle_world, screen_size)
            if not vis_base:
                continue

            base_pos = (int(round(base_screen.x)), int(round(base_screen.y)))
            radius = 4 if ship.frame.size == "Strike" else 5
            pygame.draw.circle(self.surface, _darken(color, 0.45), base_pos, radius, 1)
            pygame.draw.circle(self.surface, _lighten(color, 0.15), base_pos, max(1, radius - 2), 0)

            if ship.thrusters_active and vis_nozzle:
                flicker = 0.6 + 0.4 * math.sin(tick * 12.0 + index * 1.3)
                flame_length = 1.6 + 1.2 * flicker
                flame_base = base_world - forward * 0.2
                flame_tip = flame_base - forward * flame_length
                flame_base_screen, vis_base_flame = camera.project(flame_base, screen_size)
                flame_tip_screen, vis_tip_flame = camera.project(flame_tip, screen_size)
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
        screen_size = self.surface.get_size()

        def _screen_radius(center: Vector3, world_point: Vector3) -> int:
            other, visible = camera.project(world_point, screen_size)
            if not visible:
                return 0
            delta = Vector3(other.x - center.x, other.y - center.y, 0.0)
            return int(max(0.0, delta.length()))

        for asteroid in asteroids:
            center, visible = camera.project(asteroid.position, screen_size)
            if not visible:
                continue

            radius_vectors = [
                asteroid.position + camera.up * asteroid.radius,
                asteroid.position - camera.up * asteroid.radius,
                asteroid.position + camera.right * asteroid.radius,
                asteroid.position - camera.right * asteroid.radius,
            ]
            radii = [
                _screen_radius(center, vector)
                for vector in radius_vectors
            ]
            radius_vertical = max(radii[0], radii[1])
            radius_horizontal = max(radii[2], radii[3])
            if radius_vertical <= 0 and radius_horizontal <= 0:
                radius_vertical = radius_horizontal = 2
            radius_vertical = max(2, radius_vertical)
            radius_horizontal = max(2, radius_horizontal)

            color = asteroid.display_color
            rng = random.Random(asteroid.id)
            point_count = rng.randint(8, 14)
            jaggedness = 0.45
            points: list[tuple[int, int]] = []
            angle_step = (2.0 * math.pi) / point_count
            distortion = 0.75
            for i in range(point_count):
                angle = i * angle_step
                offset = 1.0 - jaggedness + rng.random() * jaggedness * 2.0
                horizontal = radius_horizontal * (distortion + rng.random() * (1.0 - distortion))
                vertical = radius_vertical * (distortion + rng.random() * (1.0 - distortion))
                x = center.x + math.cos(angle) * horizontal * offset
                y = center.y + math.sin(angle) * vertical * offset
                points.append((int(round(x)), int(round(y))))

            if len(points) >= 3:
                pygame.draw.polygon(self.surface, color, points)

                outline_color = _darken(color, 0.45)
                pygame.draw.polygon(self.surface, outline_color, points, 1)

                if radius_horizontal > 3 or radius_vertical > 3:
                    highlight_color = _lighten(color, 0.5)
                    shadow_color = _darken(color, 0.6)

                    accent_count = rng.randint(3, 6)
                    for _ in range(accent_count):
                        angle = rng.uniform(0.0, 2.0 * math.pi)
                        distance = rng.uniform(0.1, 0.8)
                        accent_radius = max(1, int(round((radius_horizontal + radius_vertical) * 0.05)))
                        px = center.x + math.cos(angle) * radius_horizontal * distance * rng.uniform(0.6, 1.0)
                        py = center.y + math.sin(angle) * radius_vertical * distance * rng.uniform(0.6, 1.0)
                        color_choice = highlight_color if rng.random() > 0.5 else shadow_color
                        pygame.draw.circle(
                            self.surface,
                            color_choice,
                            (int(round(px)), int(round(py))),
                            accent_radius,
                        )

                    crater_count = rng.randint(2, 4)
                    crater_fill = _darken(color, 0.55)
                    crater_rim = _lighten(color, 0.2)
                    for _ in range(crater_count):
                        angle = rng.uniform(0.0, 2.0 * math.pi)
                        distance = rng.uniform(0.15, 0.65)
                        crater_radius = max(1, int(round((radius_horizontal + radius_vertical) * rng.uniform(0.04, 0.12))))
                        px = center.x + math.cos(angle) * radius_horizontal * distance
                        py = center.y + math.sin(angle) * radius_vertical * distance
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
        right, up, forward = _ship_axes(ship)
        color = SHIP_COLOR if ship.team == "player" else ENEMY_COLOR
        edges = WIREFRAMES.get(ship.frame.size, WIREFRAMES["Strike"])
        origin = ship.kinematics.position
        speed = ship.kinematics.velocity.length()
        speed_intensity = 0.0
        if speed > 80.0:
            speed_intensity = min(1.0, (speed - 80.0) / 35.0)

        if speed_intensity > 0.0:
            self._draw_speed_streaks(camera, origin, right, up, forward, ship, speed_intensity)

        self._draw_skin(camera, origin, right, up, forward, ship)

        for a_local, b_local in edges:
            a_world = origin + right * a_local.x + up * a_local.y + forward * a_local.z
            b_world = origin + right * b_local.x + up * b_local.y + forward * b_local.z
            a_screen, vis_a = camera.project(a_world, self.surface.get_size())
            b_screen, vis_b = camera.project(b_world, self.surface.get_size())
            if vis_a and vis_b:
                pygame.draw.aaline(
                    self.surface,
                    color,
                    (a_screen.x, a_screen.y),
                    (b_screen.x, b_screen.y),
                    blend=1,
                )

        self._draw_hardpoints(camera, origin, right, up, forward, ship, color)
        self._draw_engines(camera, origin, right, up, forward, ship, color)

    def draw_projectiles(self, camera: ChaseCamera, projectiles: Iterable[Projectile]) -> None:
        for projectile in projectiles:
            color = MISSILE_COLOR if projectile.weapon.wclass == "missile" else PROJECTILE_COLOR
            screen_pos, visible = camera.project(projectile.position, self.surface.get_size())
            if visible:
                pygame.draw.circle(self.surface, color, (int(screen_pos.x), int(screen_pos.y)), 3, 1)


__all__ = ["VectorRenderer"]
