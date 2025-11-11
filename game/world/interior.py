"""Interior instance definitions for docking scenes."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Optional, Sequence, Tuple


Vec3 = Tuple[float, float, float]


def _as_vec3_list(points: Sequence[Sequence[float]]) -> tuple[Vec3, ...]:
    converted: list[Vec3] = []
    for point in points:
        if len(point) < 2:
            continue
        x = float(point[0])
        y = float(point[1])
        z = float(point[2]) if len(point) > 2 else 0.0
        converted.append((x, y, z))
    return tuple(converted)


@dataclass(frozen=True)
class InteriorNode:
    """Raw polyline geometry used to draw the interior."""

    id: str
    layer: str
    type: str
    style: Optional[str]
    points: tuple[Vec3, ...]


@dataclass(frozen=True)
class InteriorLabel:
    text: str
    layer: str
    position: Vec3


@dataclass(frozen=True)
class InteriorNavArea:
    """Axis-aligned navigable region."""

    id: str
    points: tuple[Vec3, ...]
    bounds: tuple[float, float, float, float]

    def contains(self, x: float, y: float) -> bool:
        left, bottom, right, top = self.bounds
        return left <= x <= right and bottom <= y <= top

    @classmethod
    def from_poly(cls, entry: Dict) -> "InteriorNavArea | None":
        points_raw = entry.get("points") or []
        points = _as_vec3_list(points_raw)
        if len(points) < 3:
            return None
        xs = [pt[0] for pt in points]
        ys = [pt[1] for pt in points]
        left = min(xs)
        right = max(xs)
        bottom = min(ys)
        top = max(ys)
        return cls(
            id=entry.get("id", "nav"),
            points=points,
            bounds=(left, bottom, right, top),
        )


@dataclass(frozen=True)
class InteriorInteractRegion:
    """Simple AABB used for interaction prompts."""

    id: str
    aabb_min: Vec3
    aabb_max: Vec3


@dataclass(frozen=True)
class InteriorDefinition:
    """Fully parsed interior asset."""

    name: str
    nodes: tuple[InteriorNode, ...]
    labels: tuple[InteriorLabel, ...]
    nav_areas: tuple[InteriorNavArea, ...]
    interact_regions: tuple[InteriorInteractRegion, ...]
    spawn_point: Optional[Vec3]
    bounds: tuple[float, float, float, float]

    @classmethod
    def from_dict(cls, data: Dict) -> "InteriorDefinition | None":
        metadata = data.get("metadata", {})
        name = metadata.get("name")
        if not name:
            return None

        nodes: list[InteriorNode] = []
        for entry in data.get("nodes", []):
            points = _as_vec3_list(entry.get("points", []))
            if not points:
                continue
            nodes.append(
                InteriorNode(
                    id=entry.get("id", ""),
                    layer=entry.get("layer", "DEFAULT"),
                    type=entry.get("type", "polyline"),
                    style=entry.get("style"),
                    points=points,
                )
            )

        nav = data.get("nav", {})
        nav_areas: list[InteriorNavArea] = []
        for entry in nav.get("navmesh", []):
            area = InteriorNavArea.from_poly(entry)
            if area:
                nav_areas.append(area)

        interact_regions: list[InteriorInteractRegion] = []
        for entry in nav.get("interact", []):
            aabb = entry.get("aabb") or []
            if len(aabb) != 2:
                continue
            min_pt = _as_vec3_list([aabb[0]])
            max_pt = _as_vec3_list([aabb[1]])
            if not min_pt or not max_pt:
                continue
            interact_regions.append(
                InteriorInteractRegion(
                    id=entry.get("id", ""),
                    aabb_min=min_pt[0],
                    aabb_max=max_pt[0],
                )
            )

        labels: list[InteriorLabel] = []
        for entry in data.get("labels", []):
            pos_raw = entry.get("pos") or entry.get("position") or []
            pos_list = _as_vec3_list([pos_raw])
            if not pos_list:
                continue
            labels.append(
                InteriorLabel(
                    text=entry.get("text", ""),
                    layer=entry.get("layer", "TEXT"),
                    position=pos_list[0],
                )
            )

        spawn_raw = nav.get("spawn", {}).get("position")
        spawn = None
        if isinstance(spawn_raw, Sequence):
            spawn_list = _as_vec3_list([spawn_raw])
            if spawn_list:
                spawn = spawn_list[0]

        xs: list[float] = []
        ys: list[float] = []
        for node in nodes:
            xs.extend(pt[0] for pt in node.points)
            ys.extend(pt[1] for pt in node.points)
        for area in nav_areas:
            xs.extend(pt[0] for pt in area.points)
            ys.extend(pt[1] for pt in area.points)
        if not xs or not ys:
            bounds = (0.0, 0.0, 0.0, 0.0)
        else:
            bounds = (min(xs), min(ys), max(xs), max(ys))

        return cls(
            name=name,
            nodes=tuple(nodes),
            labels=tuple(labels),
            nav_areas=tuple(nav_areas),
            interact_regions=tuple(interact_regions),
            spawn_point=spawn,
            bounds=bounds,
        )


class InteriorDatabase:
    """Loads interior definitions from asset JSON files."""

    def __init__(self) -> None:
        self._interiors: Dict[str, InteriorDefinition] = {}

    def load_directory(self, directory: Path) -> None:
        if not directory.exists():
            return
        for path in directory.glob("*_interior_*.json"):
            definition = self._load_file(path)
            if definition:
                self._interiors[definition.name] = definition

    def _load_file(self, path: Path) -> InteriorDefinition | None:
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        if isinstance(data, dict):
            return InteriorDefinition.from_dict(data)
        return None

    def get(self, name: str) -> InteriorDefinition:
        return self._interiors[name]

    def names(self) -> Iterable[str]:
        return self._interiors.keys()


__all__ = [
    "InteriorDatabase",
    "InteriorDefinition",
    "InteriorInteractRegion",
    "InteriorLabel",
    "InteriorNavArea",
    "InteriorNode",
]

