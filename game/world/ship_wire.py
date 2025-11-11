"""Utility for embedding the player's ship wireframe inside interior scenes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from pygame.math import Vector3


@dataclass
class ShipWireEmbedResult:
    """Result payload describing the transformed wireframe and safety volume."""

    segments: list[tuple[Vector3, Vector3]]
    scale: float
    translation: Vector3
    safety_min: Vector3
    safety_max: Vector3


class ShipWireEmbed:
    """Normalises the incoming ship wireframe for the hangar display."""

    def __init__(self, *, clearance: float = 5.0) -> None:
        self.clearance = clearance
        self.result: ShipWireEmbedResult | None = None

    def embed(self, segments: Iterable[Sequence[Sequence[float]]]) -> ShipWireEmbedResult | None:
        """Scale and centre the wireframe inside the hangar bounds."""

        # Flatten segments and compute the bounding box.
        points: list[Vector3] = []
        normalised_segments: list[tuple[Vector3, Vector3]] = []
        for segment in segments:
            if len(segment) != 2:
                continue
            start_raw, end_raw = segment
            start = Vector3(float(start_raw[0]), float(start_raw[1]), float(start_raw[2]))
            end = Vector3(float(end_raw[0]), float(end_raw[1]), float(end_raw[2]))
            points.append(start)
            points.append(end)
            normalised_segments.append((start, end))
        if not normalised_segments:
            self.result = None
            return None

        min_corner = Vector3(
            min(pt.x for pt in points),
            min(pt.y for pt in points),
            min(pt.z for pt in points),
        )
        max_corner = Vector3(
            max(pt.x for pt in points),
            max(pt.y for pt in points),
            max(pt.z for pt in points),
        )
        extent = max_corner - min_corner
        if extent.x <= 0.0 or extent.y <= 0.0 or extent.z <= 0.0:
            extent.x = max(extent.x, 1.0)
            extent.y = max(extent.y, 1.0)
            extent.z = max(extent.z, 1.0)

        # Fit inside hangar with desired clearance on each side.
        hangar_half = Vector3(40.0 - self.clearance, 40.0 - self.clearance, 15.0 - self.clearance * 0.5)
        scale = min(
            hangar_half.x / max(extent.x * 0.5, 1e-4),
            hangar_half.y / max(extent.y * 0.5, 1e-4),
            hangar_half.z / max(extent.z * 0.5, 1e-4),
        )
        scale = max(0.01, scale)

        # Centre in hangar at origin and elevate so pads sit at Z=0.2.
        centre = (min_corner + max_corner) * 0.5
        translation = Vector3(0.0, 0.0, 0.2) - Vector3(centre.x, centre.y, min_corner.z) * scale

        world_segments: list[tuple[Vector3, Vector3]] = []
        for start, end in normalised_segments:
            world_segments.append((start * scale + translation, end * scale + translation))

        safety_min = Vector3(min_corner) * scale + translation
        safety_max = Vector3(max_corner) * scale + translation
        safety_min.x -= 2.0
        safety_min.y -= 2.0
        safety_max.x += 2.0
        safety_max.y += 2.0
        safety_max.z += 3.0

        self.result = ShipWireEmbedResult(
            segments=world_segments,
            scale=scale,
            translation=translation,
            safety_min=safety_min,
            safety_max=safety_max,
        )
        return self.result


__all__ = ["ShipWireEmbed", "ShipWireEmbedResult"]
