"""Interior instance definitions for docking scenes."""
from __future__ import annotations

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
    floor_z: float

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
        zs = [pt[2] for pt in points]
        left = min(xs)
        right = max(xs)
        bottom = min(ys)
        top = max(ys)
        if zs:
            floor_z = sum(zs) / len(zs)
        else:
            floor_z = 0.0
        return cls(
            id=entry.get("id", "nav"),
            points=points,
            bounds=(left, bottom, right, top),
            floor_z=floor_z,
        )


@dataclass(frozen=True)
class InteriorInteractRegion:
    """Simple AABB used for interaction prompts."""

    id: str
    aabb_min: Vec3
    aabb_max: Vec3


@dataclass(frozen=True)
class InteriorDoor:
    """Door definition with frame and trigger volumes."""

    id: str
    frame_min: Vec3
    frame_max: Vec3
    trigger_min: Vec3
    trigger_max: Vec3
    facing: Vec3
    tags: tuple[str, ...]
    sign: Optional[str]
    group: Optional[str]


@dataclass(frozen=True)
class InteriorAabb:
    """Generic axis-aligned bounding box payload."""

    id: str
    aabb_min: Vec3
    aabb_max: Vec3
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class InteriorChunk:
    """Streaming chunk metadata."""

    id: str
    aabb_min: Vec3
    aabb_max: Vec3
    label: Optional[str]
    stream: Optional[str]
    tags: tuple[str, ...]


@dataclass(frozen=True)
class InteriorDefinition:
    """Fully parsed interior asset."""

    name: str
    nodes: tuple[InteriorNode, ...]
    labels: tuple[InteriorLabel, ...]
    nav_areas: tuple[InteriorNavArea, ...]
    interact_regions: tuple[InteriorInteractRegion, ...]
    no_walk_zones: tuple[InteriorAabb, ...]
    ladders: tuple[InteriorAabb, ...]
    chunks: tuple[InteriorChunk, ...]
    doors: tuple[InteriorDoor, ...]
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

        def _parse_aabb_list(entries: Sequence[Dict], *, key: str) -> list[InteriorAabb]:
            boxes: list[InteriorAabb] = []
            for entry in entries:
                aabb_raw = entry.get("aabb") or entry.get("bounds")
                if not isinstance(aabb_raw, Sequence) or len(aabb_raw) != 2:
                    continue
                mins = _as_vec3_list([aabb_raw[0]])
                maxs = _as_vec3_list([aabb_raw[1]])
                if not mins or not maxs:
                    continue
                meta_raw = entry.get("metadata") or entry.get("tags") or []
                if isinstance(meta_raw, Sequence) and not isinstance(meta_raw, str):
                    tags = tuple(str(item) for item in meta_raw)
                elif isinstance(meta_raw, str):
                    tags = (meta_raw,)
                else:
                    tags = ()
                boxes.append(
                    InteriorAabb(
                        id=str(entry.get("id", key)),
                        aabb_min=mins[0],
                        aabb_max=maxs[0],
                        tags=tags,
                    )
                )
            return boxes

        no_walk_zones = _parse_aabb_list(nav.get("noWalk", []), key="noWalk")
        ladder_boxes = _parse_aabb_list(nav.get("ladders", []), key="ladder")
        chunk_boxes: list[InteriorChunk] = []
        for entry in nav.get("chunks", []):
            aabb_raw = entry.get("aabb") or entry.get("bounds")
            if not isinstance(aabb_raw, Sequence) or len(aabb_raw) != 2:
                continue
            mins = _as_vec3_list([aabb_raw[0]])
            maxs = _as_vec3_list([aabb_raw[1]])
            if not mins or not maxs:
                continue
            tags_raw = entry.get("tags") or []
            if isinstance(tags_raw, Sequence) and not isinstance(tags_raw, str):
                tags = tuple(str(tag) for tag in tags_raw)
            elif isinstance(tags_raw, str):
                tags = (tags_raw,)
            else:
                tags = ()
            chunk_boxes.append(
                InteriorChunk(
                    id=str(entry.get("id", "chunk")),
                    aabb_min=mins[0],
                    aabb_max=maxs[0],
                    label=entry.get("label"),
                    stream=entry.get("stream"),
                    tags=tags,
                )
            )

        doors_raw: Sequence[Dict] = data.get("doors", [])
        doors: list[InteriorDoor] = []
        for entry in doors_raw:
            frame_raw = entry.get("frame")
            trigger_raw = entry.get("trigger")
            facing_raw = entry.get("facing")
            if not isinstance(frame_raw, Sequence) or len(frame_raw) != 2:
                continue
            if not isinstance(trigger_raw, Sequence) or len(trigger_raw) != 2:
                continue
            frame_min_list = _as_vec3_list([frame_raw[0]])
            frame_max_list = _as_vec3_list([frame_raw[1]])
            trigger_min_list = _as_vec3_list([trigger_raw[0]])
            trigger_max_list = _as_vec3_list([trigger_raw[1]])
            facing_list = _as_vec3_list([facing_raw]) if isinstance(facing_raw, Sequence) else []
            if not frame_min_list or not frame_max_list or not trigger_min_list or not trigger_max_list:
                continue
            facing = facing_list[0] if facing_list else (0.0, 1.0, 0.0)
            tags_raw = entry.get("tags") or []
            if isinstance(tags_raw, Sequence) and not isinstance(tags_raw, str):
                tags = tuple(str(tag) for tag in tags_raw)
            elif isinstance(tags_raw, str):
                tags = (tags_raw,)
            else:
                tags = ()
            doors.append(
                InteriorDoor(
                    id=str(entry.get("id", "door")),
                    frame_min=frame_min_list[0],
                    frame_max=frame_max_list[0],
                    trigger_min=trigger_min_list[0],
                    trigger_max=trigger_max_list[0],
                    facing=facing,
                    tags=tags,
                    sign=entry.get("sign"),
                    group=entry.get("group"),
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
            no_walk_zones=tuple(no_walk_zones),
            ladders=tuple(ladder_boxes),
            chunks=tuple(chunk_boxes),
            doors=tuple(doors),
            spawn_point=spawn,
            bounds=bounds,
        )


class InteriorDatabase:
    """Registry of hard-coded interior definitions."""

    def __init__(self) -> None:
        self._interiors: Dict[str, InteriorDefinition] = {}
        self._builtins_loaded = False

    def _load_builtins(self) -> None:
        if self._builtins_loaded:
            return
        from game.world.outpost_layouts import build_outpost_interior_v1

        definition = build_outpost_interior_v1()
        self._interiors[definition.name] = definition
        self._builtins_loaded = True

    def load_directory(self, directory: Path | None) -> None:
        """Retained for API compatibility; loads bundled interiors."""

        _ = directory  # Parameter retained to preserve call sites.
        self._load_builtins()

    def register(self, definition: InteriorDefinition) -> None:
        """Manually register an interior definition."""

        self._interiors[definition.name] = definition

    def get(self, name: str) -> InteriorDefinition:
        self._load_builtins()
        return self._interiors[name]

    def names(self) -> Iterable[str]:
        self._load_builtins()
        return self._interiors.keys()


__all__ = [
    "InteriorDatabase",
    "InteriorDefinition",
    "InteriorInteractRegion",
    "InteriorLabel",
    "InteriorNavArea",
    "InteriorNode",
    "InteriorDoor",
    "InteriorAabb",
    "InteriorChunk",
]

