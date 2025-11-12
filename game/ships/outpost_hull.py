"""Shared geometry and collision helpers for Outpost-class ships."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from pygame.math import Vector3


@dataclass(frozen=True)
class HullSection:
    """Describes a longitudinal slice of the Outpost hull."""

    z: float
    half_width: float
    half_height: float


OUTPOST_HULL_PROFILE: tuple[HullSection, ...] = (
    HullSection(-640.0, 150.0, 96.0),
    HullSection(-580.0, 146.0, 92.0),
    HullSection(-520.0, 140.0, 88.0),
    HullSection(-440.0, 148.0, 82.0),
    HullSection(-360.0, 184.0, 94.0),
    HullSection(-240.0, 220.0, 110.0),
    HullSection(-120.0, 240.0, 125.0),
    HullSection(0.0, 250.0, 140.0),
    HullSection(120.0, 230.0, 130.0),
    HullSection(240.0, 200.0, 110.0),
    HullSection(360.0, 170.0, 95.0),
    HullSection(480.0, 140.0, 80.0),
    HullSection(560.0, 120.0, 70.0),
)

OUTPOST_RING_SIDES = 24


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _section_interval(index: int) -> float:
    current = OUTPOST_HULL_PROFILE[index]
    nxt = OUTPOST_HULL_PROFILE[index + 1]
    delta = nxt.z - current.z
    return delta if abs(delta) > 1e-6 else 1.0


def interpolate_half_extents(z_pos: float) -> tuple[float, float, float, float]:
    """Return half width/height and their local slopes for the given Z."""

    if z_pos <= OUTPOST_HULL_PROFILE[0].z:
        section = OUTPOST_HULL_PROFILE[0]
        return section.half_width, section.half_height, 0.0, 0.0
    for index in range(len(OUTPOST_HULL_PROFILE) - 1):
        current = OUTPOST_HULL_PROFILE[index]
        nxt = OUTPOST_HULL_PROFILE[index + 1]
        if z_pos <= nxt.z:
            span = _section_interval(index)
            t = (z_pos - current.z) / span
            width = _lerp(current.half_width, nxt.half_width, t)
            height = _lerp(current.half_height, nxt.half_height, t)
            width_slope = (nxt.half_width - current.half_width) / span
            height_slope = (nxt.half_height - current.half_height) / span
            return width, height, width_slope, height_slope
    section = OUTPOST_HULL_PROFILE[-1]
    return section.half_width, section.half_height, 0.0, 0.0


def outpost_half_extents(z_pos: float) -> tuple[float, float]:
    """Public helper that exposes the hull half-width/height at ``z_pos``."""

    width, height, _, _ = interpolate_half_extents(z_pos)
    return width, height


def _ensure_outward(indices: Sequence[int], vertices: Sequence[Vector3]) -> tuple[int, ...]:
    if len(indices) < 3:
        return tuple(indices)
    v0 = vertices[indices[0]]
    v1 = vertices[indices[1]]
    v2 = vertices[indices[2]]
    normal = (v1 - v0).cross(v2 - v0)
    if normal.length_squared() <= 1e-6:
        return tuple(indices)
    center = Vector3()
    for idx in indices:
        center += vertices[idx]
    center /= len(indices)
    if normal.dot(center) < 0.0:
        return tuple(reversed(tuple(indices)))
    return tuple(indices)


def build_outpost_skin_geometry() -> tuple[list[Vector3], list[tuple[int, ...]], float]:
    """Generate a closed surface mesh for the Outpost hull."""

    vertices: list[Vector3] = []
    faces: list[tuple[int, ...]] = []
    ring_indices: list[list[int]] = []

    for section in OUTPOST_HULL_PROFILE:
        ring: list[int] = []
        for side in range(OUTPOST_RING_SIDES):
            angle = 2.0 * math.pi * (side / OUTPOST_RING_SIDES)
            x = math.cos(angle) * section.half_width
            y = math.sin(angle) * section.half_height
            ring.append(len(vertices))
            vertices.append(Vector3(x, y, section.z))
        ring_indices.append(ring)

    for index in range(len(ring_indices) - 1):
        current = ring_indices[index]
        nxt = ring_indices[index + 1]
        for side in range(OUTPOST_RING_SIDES):
            a0 = current[side]
            a1 = current[(side + 1) % OUTPOST_RING_SIDES]
            b1 = nxt[(side + 1) % OUTPOST_RING_SIDES]
            b0 = nxt[side]
            face = _ensure_outward((a0, b0, b1, a1), vertices)
            faces.append(face)

    stern_center = len(vertices)
    vertices.append(Vector3(0.0, 0.0, OUTPOST_HULL_PROFILE[0].z))
    bow_center = len(vertices)
    vertices.append(Vector3(0.0, 0.0, OUTPOST_HULL_PROFILE[-1].z))

    stern_ring = ring_indices[0]
    bow_ring = ring_indices[-1]
    for side in range(OUTPOST_RING_SIDES):
        next_side = (side + 1) % OUTPOST_RING_SIDES
        stern_face = _ensure_outward(
            (stern_center, stern_ring[next_side], stern_ring[side]), vertices
        )
        bow_face = _ensure_outward(
            (bow_center, bow_ring[side], bow_ring[next_side]), vertices
        )
        faces.extend((stern_face, bow_face))

    radius = 0.0
    for vertex in vertices:
        radius = max(radius, vertex.length())

    return vertices, faces, radius


def _to_local(
    position: Vector3,
    origin: Vector3,
    basis_right: Vector3,
    basis_up: Vector3,
    basis_forward: Vector3,
) -> Vector3:
    rel = position - origin
    return Vector3(
        rel.dot(basis_right),
        rel.dot(basis_up),
        rel.dot(basis_forward),
    )


def outpost_collision_response(
    origin: Vector3,
    basis_right: Vector3,
    basis_up: Vector3,
    basis_forward: Vector3,
    other_position: Vector3,
    other_radius: float,
) -> tuple[Vector3, float] | None:
    """Resolve penetration between the Outpost hull and a spherical collider."""

    local = _to_local(other_position, origin, basis_right, basis_up, basis_forward)
    min_z = OUTPOST_HULL_PROFILE[0].z
    max_z = OUTPOST_HULL_PROFILE[-1].z

    if local.z < min_z:
        width, height = outpost_half_extents(min_z)
        expanded_width = width + other_radius
        expanded_height = height + other_radius
        if (local.x / expanded_width) ** 2 + (local.y / expanded_height) ** 2 <= 1.0:
            penetration = min_z - (local.z - other_radius)
            if penetration > 0.0:
                normal_world = (
                    basis_right * 0.0
                    + basis_up * 0.0
                    + basis_forward * -1.0
                )
                return normal_world, penetration
        return None

    if local.z > max_z:
        width, height = outpost_half_extents(max_z)
        expanded_width = width + other_radius
        expanded_height = height + other_radius
        if (local.x / expanded_width) ** 2 + (local.y / expanded_height) ** 2 <= 1.0:
            penetration = (local.z + other_radius) - max_z
            if penetration > 0.0:
                normal_world = (
                    basis_right * 0.0
                    + basis_up * 0.0
                    + basis_forward * 1.0
                )
                return normal_world, penetration
        return None

    width, height, width_slope, height_slope = interpolate_half_extents(local.z)
    expanded_width = width + other_radius
    expanded_height = height + other_radius

    if expanded_width <= 1e-3 or expanded_height <= 1e-3:
        return None

    value = (local.x / expanded_width) ** 2 + (local.y / expanded_height) ** 2
    if value > 1.0:
        return None

    if value < 1e-6:
        normal_local = Vector3(0.0, 1.0, 0.0)
        penetration = other_radius
    else:
        scale = 1.0 / max(math.sqrt(value), 1e-5)
        surface_x = local.x * scale
        surface_y = local.y * scale
        correction = Vector3(surface_x - local.x, surface_y - local.y, 0.0)
        penetration = correction.length()
        if penetration <= 1e-6:
            return None
        normal_local = Vector3(local.x, local.y, 0.0)
        if normal_local.length_squared() <= 1e-6:
            normal_local = Vector3(correction.x, correction.y, 0.0)
        if normal_local.length_squared() <= 1e-6:
            normal_local = Vector3(0.0, 1.0, 0.0)
        normal_local = normal_local.normalize()

    grad_z = -(
        (local.x ** 2 / expanded_width ** 3) * width_slope
        + (local.y ** 2 / expanded_height ** 3) * height_slope
    )
    gradient = Vector3(normal_local.x / expanded_width, normal_local.y / expanded_height, grad_z)
    if gradient.length_squared() > 1e-6:
        normal_local = gradient.normalize()

    normal_world = (
        basis_right * normal_local.x
        + basis_up * normal_local.y
        + basis_forward * normal_local.z
    )
    if normal_world.length_squared() <= 1e-6:
        return None
    normal_world = normal_world.normalize()

    return normal_world, penetration


__all__ = [
    "OUTPOST_HULL_PROFILE",
    "OUTPOST_RING_SIDES",
    "build_outpost_skin_geometry",
    "outpost_collision_response",
    "outpost_half_extents",
]
