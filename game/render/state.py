"""Shared render state helpers for visibility and projection caching."""
from __future__ import annotations

import math
import math
import random
from dataclasses import dataclass, field
from typing import Optional, Sequence

from pygame.math import Vector3


@dataclass
class RenderSpatialState:
    """Tracks world-space bounds and cached visibility data for an object."""

    center: Vector3 = field(default_factory=Vector3)
    radius: float = 1.0
    world_revision: int = 0
    cached_camera_revision: int = -1
    cached_screen_rect: Optional[tuple[float, float, float, float]] = None
    _last_position: Vector3 = field(default_factory=Vector3, repr=False)
    _last_rotation: Optional[Vector3] = field(default=None, repr=False)
    random_seed: int = field(default_factory=lambda: random.randrange(0, 1 << 30), repr=False)

    def ensure_current(self, position: Vector3, rotation: Optional[Vector3] = None) -> None:
        """Update the cached transform and advance the revision when it changes."""

        changed = (position - self._last_position).length_squared() > 1e-6
        if rotation is not None:
            if self._last_rotation is None:
                changed = True
            else:
                changed = changed or (rotation - self._last_rotation).length_squared() > 1e-6
        if changed:
            self.world_revision += 1
            self.center = Vector3(position)
            self._last_position = Vector3(position)
            if rotation is not None:
                self._last_rotation = Vector3(rotation)
        elif self.center != position:
            # Keep the cached center synchronised even when the revision does not change.
            self.center = Vector3(position)

    def set_radius(self, radius: float) -> None:
        if not math.isfinite(radius):
            return
        radius = max(0.0, float(radius))
        if not math.isclose(radius, self.radius):
            self.radius = radius
            self.world_revision += 1

    def clear_cached_projection(self) -> None:
        self.cached_camera_revision = -1
        self.cached_screen_rect = None


@dataclass
class ProjectedVertexCache:
    """Cached projected vertices for a renderable object."""

    camera_revision: int = -1
    world_revision: int = -1
    vertices: list[tuple[float, float]] = field(default_factory=list)
    visibility: list[bool] = field(default_factory=list)
    world_vertices: list[Vector3] = field(default_factory=list)

    def update(
        self,
        camera_revision: int,
        world_revision: int,
        vertices: Sequence[tuple[float, float]],
        visibility: Sequence[bool],
        world_vertices: Sequence[Vector3],
    ) -> None:
        self.camera_revision = camera_revision
        self.world_revision = world_revision
        self.vertices = list(vertices)
        self.visibility = list(visibility)
        self.world_vertices = [Vector3(vector) for vector in world_vertices]


@dataclass
class TelemetryCounters:
    """Aggregated instrumentation for renderer performance."""

    objects_total: int = 0
    objects_culled_frustum: int = 0
    objects_culled_viewport: int = 0
    objects_drawn_line: int = 0
    objects_drawn_aaline: int = 0
    vertices_projected_total: int = 0
    objects_projected: int = 0

    def accumulate(self, other: "TelemetryCounters") -> None:
        self.objects_total += other.objects_total
        self.objects_culled_frustum += other.objects_culled_frustum
        self.objects_culled_viewport += other.objects_culled_viewport
        self.objects_drawn_line += other.objects_drawn_line
        self.objects_drawn_aaline += other.objects_drawn_aaline
        self.vertices_projected_total += other.vertices_projected_total
        self.objects_projected += other.objects_projected

    def reset(self) -> None:
        self.objects_total = 0
        self.objects_culled_frustum = 0
        self.objects_culled_viewport = 0
        self.objects_drawn_line = 0
        self.objects_drawn_aaline = 0
        self.vertices_projected_total = 0
        self.objects_projected = 0

    def average_vertices(self) -> float:
        if self.objects_projected <= 0:
            return 0.0
        return self.vertices_projected_total / max(1, self.objects_projected)


__all__ = [
    "ProjectedVertexCache",
    "RenderSpatialState",
    "TelemetryCounters",
]
