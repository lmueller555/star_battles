"""Shared geometric and collision data for Outpost-class stations."""
from __future__ import annotations

from dataclasses import dataclass
from itertools import pairwise
from math import cos, pi, sin
from typing import Iterable, List

from pygame.math import Vector3


# Primary hull cross-section profile expressed as tuples of
# (z_position, half_width, half_height). These values match the historical
# wireframe definition used by the renderer, which keeps the new skin aligned
# with the existing silhouette and camera tuning.
OUTPOST_HULL_PROFILE: List[tuple[float, float, float]] = [
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

# Discretisation constants shared by the renderer and collision routines.
OUTPOST_HULL_RING_SIDES = 20

# Docking arm layout values that match the long cylindrical braces extending
# from the primary hull. The arms extend parallel to the ship's longitudinal
# axis, below the mid-line of the hull.
OUTPOST_DOCKING_ARM_RING_SIDES = 14
OUTPOST_DOCKING_ARM_SECTIONS = 7
OUTPOST_DOCKING_ARM_OFFSET_X = max(width for _, width, _ in OUTPOST_HULL_PROFILE) + 70.0
OUTPOST_DOCKING_ARM_OFFSET_Y = -58.0
OUTPOST_DOCKING_ARM_RADIUS = 38.0
OUTPOST_DOCKING_ARM_VERTICAL_RADIUS = OUTPOST_DOCKING_ARM_RADIUS * 0.78

# Tail housing and engine configuration. These values mirror the historical
# wireframe definitions so thruster placement and collision envelopes align.
_TAIL_Z, _TAIL_HALF_WIDTH, _TAIL_HALF_HEIGHT = OUTPOST_HULL_PROFILE[0]
OUTPOST_ENGINE_HOUSING_FRONT_Z = _TAIL_Z + 18.0
OUTPOST_ENGINE_HOUSING_BACK_Z = _TAIL_Z - 48.0
OUTPOST_ENGINE_HOUSING_HALF_WIDTH = _TAIL_HALF_WIDTH + 18.0
OUTPOST_ENGINE_HOUSING_HALF_HEIGHT = _TAIL_HALF_HEIGHT + 22.0
OUTPOST_ENGINE_OFFSET_X = _TAIL_HALF_WIDTH - 36.0
OUTPOST_ENGINE_OFFSET_Y = _TAIL_HALF_HEIGHT - 30.0
OUTPOST_ENGINE_RADIUS_X = 30.0
OUTPOST_ENGINE_RADIUS_Y = 24.0
OUTPOST_ENGINE_DEPTH = 18.0
OUTPOST_ENGINE_NOZZLE_INSET = 5.0

# Nose spear offsets to close the front of the hull with a reinforced prow.
OUTPOST_NOSE_FORWARD_OFFSET = 80.0
OUTPOST_NOSE_VENTRAL_OFFSET = 70.0


@dataclass(frozen=True)
class CollisionHull:
    """Axis-aligned ellipsoid expressed in the Outpost's local space."""

    center: Vector3
    radii: Vector3


def elliptical_ring(
    z_pos: float,
    half_width: float,
    half_height: float,
    *,
    sides: int,
) -> List[Vector3]:
    """Return an evenly sampled elliptical ring in local Outpost space."""

    if sides <= 2:
        return []
    angle_step = 2.0 * pi / sides
    return [
        Vector3(cos(step * angle_step) * half_width, sin(step * angle_step) * half_height, z_pos)
        for step in range(sides)
    ]


def docking_arm_centerline() -> tuple[float, float, float]:
    """Return key longitudinal positions for the docking arm cylinders."""

    tail_z = OUTPOST_HULL_PROFILE[0][0]
    nose_z = OUTPOST_HULL_PROFILE[-1][0]
    hull_length = nose_z - tail_z
    start_z = tail_z + hull_length * 0.35
    end_z = min(nose_z - 30.0, start_z + hull_length * 0.5)
    return start_z, end_z, hull_length


def build_outpost_collision_hulls() -> List[CollisionHull]:
    """Generate a composite ellipsoidal collision envelope for the Outpost."""

    hulls: List[CollisionHull] = []

    # Approximate the main body using blended ellipsoids between successive
    # cross sections. A generous margin keeps the collision envelope slightly
    # inside the rendered skin so ships rest against the surface rather than
    # penetrating it.
    for (z0, width0, height0), (z1, width1, height1) in pairwise(OUTPOST_HULL_PROFILE):
        z_mid = (z0 + z1) * 0.5
        half_width = max(width0, width1) + 18.0
        half_height = max(height0, height1) + 18.0
        half_depth = abs(z1 - z0) * 0.5 + 34.0
        hulls.append(
            CollisionHull(
                center=Vector3(0.0, 0.0, z_mid),
                radii=Vector3(half_width, half_height, half_depth),
            )
        )

    # Reinforce the prow and tail with dedicated caps to catch glancing blows.
    nose_z = OUTPOST_HULL_PROFILE[-1][0]
    hulls.append(
        CollisionHull(
            center=Vector3(0.0, -6.0, nose_z + 52.0),
            radii=Vector3(120.0, 100.0, 70.0),
        )
    )
    tail_z = OUTPOST_HULL_PROFILE[0][0]
    hulls.append(
        CollisionHull(
            center=Vector3(0.0, 0.0, tail_z - 46.0),
            radii=Vector3(
                OUTPOST_ENGINE_HOUSING_HALF_WIDTH + 16.0,
                OUTPOST_ENGINE_HOUSING_HALF_HEIGHT + 12.0,
                78.0,
            ),
        )
    )

    # Docking arms: treat each arm as a chain of overlapping ellipsoids.
    arm_start_z, arm_end_z, arm_length = docking_arm_centerline()
    arm_segments = [0.12, 0.36, 0.6, 0.84]
    for sign in (-1, 1):
        for fraction in arm_segments:
            z_pos = arm_start_z + (arm_end_z - arm_start_z) * fraction
            hulls.append(
                CollisionHull(
                    center=Vector3(
                        sign * OUTPOST_DOCKING_ARM_OFFSET_X,
                        OUTPOST_DOCKING_ARM_OFFSET_Y,
                        z_pos,
                    ),
                    radii=Vector3(
                        OUTPOST_DOCKING_ARM_RADIUS + 10.0,
                        OUTPOST_DOCKING_ARM_VERTICAL_RADIUS + 8.0,
                        arm_length * 0.08 + 34.0,
                    ),
                )
            )

    # Engine nacelles.
    engine_center_z = OUTPOST_ENGINE_HOUSING_BACK_Z + OUTPOST_ENGINE_DEPTH
    for sign in (-1, 1):
        for vertical in (-1, 1):
            hulls.append(
                CollisionHull(
                    center=Vector3(
                        sign * OUTPOST_ENGINE_OFFSET_X,
                        vertical * OUTPOST_ENGINE_OFFSET_Y,
                        engine_center_z,
                    ),
                    radii=Vector3(
                        OUTPOST_ENGINE_RADIUS_X + 6.0,
                        OUTPOST_ENGINE_RADIUS_Y + 6.0,
                        OUTPOST_ENGINE_DEPTH + 8.0,
                    ),
                )
            )

    return hulls


OUTPOST_COLLISION_HULLS: List[CollisionHull] = build_outpost_collision_hulls()


def iter_collision_hulls() -> Iterable[CollisionHull]:
    """Yield collision hulls for callers that prefer lazy iteration."""

    return iter(OUTPOST_COLLISION_HULLS)


__all__ = [
    "CollisionHull",
    "OUTPOST_COLLISION_HULLS",
    "OUTPOST_DOCKING_ARM_OFFSET_X",
    "OUTPOST_DOCKING_ARM_OFFSET_Y",
    "OUTPOST_DOCKING_ARM_RADIUS",
    "OUTPOST_DOCKING_ARM_RING_SIDES",
    "OUTPOST_DOCKING_ARM_SECTIONS",
    "OUTPOST_DOCKING_ARM_VERTICAL_RADIUS",
    "OUTPOST_ENGINE_DEPTH",
    "OUTPOST_ENGINE_HOUSING_BACK_Z",
    "OUTPOST_ENGINE_HOUSING_FRONT_Z",
    "OUTPOST_ENGINE_HOUSING_HALF_HEIGHT",
    "OUTPOST_ENGINE_HOUSING_HALF_WIDTH",
    "OUTPOST_ENGINE_NOZZLE_INSET",
    "OUTPOST_ENGINE_OFFSET_X",
    "OUTPOST_ENGINE_OFFSET_Y",
    "OUTPOST_ENGINE_RADIUS_X",
    "OUTPOST_ENGINE_RADIUS_Y",
    "OUTPOST_HULL_PROFILE",
    "OUTPOST_HULL_RING_SIDES",
    "OUTPOST_NOSE_FORWARD_OFFSET",
    "OUTPOST_NOSE_VENTRAL_OFFSET",
    "docking_arm_centerline",
    "elliptical_ring",
    "iter_collision_hulls",
]
