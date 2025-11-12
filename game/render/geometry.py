"""Shared geometry data structures for ship rendering."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Tuple

from pygame.math import Vector3


@dataclass(slots=True)
class ShipFace:
    """A polygonal face used by ship skins."""

    indices: Tuple[int, ...]
    base_color: Tuple[int, int, int]
    normal: Vector3
    accent: float = 0.0
    outline: Tuple[int, int, int] | None = None


@dataclass(slots=True)
class ShipGeometry:
    """Indexed geometry shared between wireframe and skinned render paths."""

    vertices: List[Vector3]
    edges: List[Tuple[int, int]]
    radius: float
    faces: List[ShipFace] = field(default_factory=list)

    @classmethod
    def from_edges(cls, edges: Sequence[tuple[Vector3, Vector3]]) -> "ShipGeometry":
        vertex_map: Dict[Tuple[float, float, float], int] = {}
        vertices: List[Vector3] = []
        index_edges: List[Tuple[int, int]] = []
        max_radius = 0.0

        def key(vector: Vector3) -> Tuple[float, float, float]:
            return (round(vector.x, 6), round(vector.y, 6), round(vector.z, 6))

        for start, end in edges:
            start_key = key(start)
            end_key = key(end)
            if start_key not in vertex_map:
                vertex_map[start_key] = len(vertices)
                vertices.append(Vector3(start))
                max_radius = max(max_radius, vertices[-1].length())
            if end_key not in vertex_map:
                vertex_map[end_key] = len(vertices)
                vertices.append(Vector3(end))
                max_radius = max(max_radius, vertices[-1].length())
            index_edges.append((vertex_map[start_key], vertex_map[end_key]))

        return cls(vertices=vertices, edges=index_edges, radius=max_radius)
