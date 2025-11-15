"""Shared ship wireframe geometry helpers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Sequence, Tuple

from pygame.math import Vector3

from .wireframes import WIREFRAMES


@dataclass
class ShipGeometry:
    """Cached geometry information derived from a wireframe."""

    vertices: list[Vector3]
    edges: list[tuple[int, int]]
    strips: list[list[int]]
    radius: float
    length: float


def _vertex_key(vector: Vector3) -> Tuple[float, float, float]:
    return (round(vector.x, 6), round(vector.y, 6), round(vector.z, 6))


def _build_edge_strips(index_edges: Sequence[Tuple[int, int]]) -> list[list[int]]:
    """Group unordered edge pairs into drawable polyline strips."""

    adjacency: Dict[int, Dict[int, int]] = {}

    def _link(a: int, b: int) -> None:
        neighbors = adjacency.setdefault(a, {})
        neighbors[b] = neighbors.get(b, 0) + 1

    for start, end in index_edges:
        if start == end:
            continue
        _link(start, end)
        _link(end, start)

    def _remove_edge(a: int, b: int) -> None:
        neighbors = adjacency.get(a)
        if not neighbors:
            return
        count = neighbors.get(b, 0)
        if count <= 1:
            neighbors.pop(b, None)
        else:
            neighbors[b] = count - 1
        if not neighbors:
            adjacency.pop(a, None)

    def _select_neighbor(vertex: int, previous: Optional[int]) -> Optional[int]:
        neighbors = adjacency.get(vertex)
        if not neighbors:
            return None
        # Prefer continuing forward instead of immediately doubling back when possible.
        for target, count in neighbors.items():
            if count > 0 and target != previous:
                return target
        for target, count in neighbors.items():
            if count > 0:
                return target
        return None

    strips: list[list[int]] = []

    while adjacency:
        start_vertex, neighbors = next(iter(adjacency.items()))
        if not neighbors:
            adjacency.pop(start_vertex)
            continue
        strip: list[int] = [start_vertex]
        current = start_vertex
        previous: Optional[int] = None
        while True:
            next_vertex = _select_neighbor(current, previous)
            if next_vertex is None:
                break
            _remove_edge(current, next_vertex)
            _remove_edge(next_vertex, current)
            strip.append(next_vertex)
            previous, current = current, next_vertex
        if len(strip) > 1:
            strips.append(strip)
        else:
            # No edges remain touching this vertex; discard the singleton.
            adjacency.pop(start_vertex, None)
    return strips


def _ship_geometry_from_edges(edges: Sequence[tuple[Vector3, Vector3]]) -> ShipGeometry:
    vertex_map: Dict[Tuple[float, float, float], int] = {}
    vertices: list[Vector3] = []
    index_edges: list[tuple[int, int]] = []
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
    strips = _build_edge_strips(index_edges)
    return ShipGeometry(
        vertices=vertices,
        edges=index_edges,
        strips=strips,
        radius=max_radius,
        length=length,
    )


def build_ship_geometry_cache() -> Dict[str, ShipGeometry]:
    return {name: _ship_geometry_from_edges(edge_list) for name, edge_list in WIREFRAMES.items()}


SHIP_GEOMETRY_CACHE: Dict[str, ShipGeometry] = build_ship_geometry_cache()


def get_ship_geometry(frame_id: str, frame_size: str | None = None) -> ShipGeometry:
    geometry = SHIP_GEOMETRY_CACHE.get(frame_id)
    if geometry is None and frame_size:
        geometry = SHIP_GEOMETRY_CACHE.get(frame_size)
    if geometry is None:
        geometry = SHIP_GEOMETRY_CACHE.get("Strike")
    if geometry is None:
        raise KeyError("Strike wireframe geometry is missing")
    return geometry


def get_ship_geometry_length(frame_id: str, frame_size: str | None = None) -> float:
    return get_ship_geometry(frame_id, frame_size).length


__all__ = [
    "ShipGeometry",
    "SHIP_GEOMETRY_CACHE",
    "build_ship_geometry_cache",
    "get_ship_geometry",
    "get_ship_geometry_length",
]
