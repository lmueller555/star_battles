"""Skin geometry and collision profile for Outpost-class ships."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Dict, Iterable, List, Sequence, Tuple

from pygame.math import Vector3

from game.render.geometry import ShipFace, ShipGeometry


Color = Tuple[int, int, int]


def _blend(color_a: Color, color_b: Color, amount: float) -> Color:
    amount = max(0.0, min(1.0, amount))
    return tuple(int(round(a + (b - a) * amount)) for a, b in zip(color_a, color_b))  # type: ignore[return-value]


def _face_normal(vertices: Sequence[Vector3], indices: Sequence[int]) -> Vector3:
    if len(indices) < 3:
        return Vector3(0.0, 0.0, 1.0)
    a = vertices[indices[0]]
    b = vertices[indices[1]]
    c = vertices[indices[2]]
    normal = (b - a).cross(c - a)
    if normal.length() <= 1e-6:
        return Vector3(0.0, 0.0, 1.0)
    return normal.normalize()


def _average_attribute(vertices: Sequence[Vector3], indices: Sequence[int], axis: str) -> float:
    if not indices:
        return 0.0
    if axis == "x":
        return sum(vertices[idx].x for idx in indices) / len(indices)
    if axis == "y":
        return sum(vertices[idx].y for idx in indices) / len(indices)
    return sum(vertices[idx].z for idx in indices) / len(indices)


def _add_vertex(vertices: List[Vector3], vertex_map: Dict[Tuple[float, float, float], int], point: Vector3) -> int:
    key = (round(point.x, 4), round(point.y, 4), round(point.z, 4))
    if key in vertex_map:
        return vertex_map[key]
    vertex_map[key] = len(vertices)
    vertices.append(Vector3(point))
    return vertex_map[key]


@dataclass(slots=True)
class EllipseSection:
    z: float
    half_width: float
    half_height: float


@dataclass(slots=True)
class Ellipsoid:
    center: Vector3
    radius: Vector3

    def signed_distance(self, point: Vector3) -> tuple[float, Vector3]:
        rel = point - self.center
        if self.radius.x <= 0.0 or self.radius.y <= 0.0 or self.radius.z <= 0.0:
            return rel.length(), Vector3(0.0, 0.0, 1.0)
        nx = rel.x / self.radius.x
        ny = rel.y / self.radius.y
        nz = rel.z / self.radius.z
        radial = math.sqrt(nx * nx + ny * ny + nz * nz)
        if radial == 0.0:
            return -min(self.radius.x, self.radius.y, self.radius.z), Vector3(0.0, 0.0, 1.0)
        surface = Vector3(
            self.radius.x * nx / radial,
            self.radius.y * ny / radial,
            self.radius.z * nz / radial,
        )
        normal = Vector3(nx, ny, nz)
        if normal.length() > 0.0:
            normal = normal.normalize()
        distance = (rel - surface).length()
        signed = distance if radial >= 1.0 else -distance
        return signed, normal


@dataclass(slots=True)
class Capsule:
    center: Vector3
    start_z: float
    end_z: float
    radius_x: float
    radius_y: float

    def signed_distance(self, point: Vector3) -> tuple[float, Vector3]:
        clamped_z = max(self.start_z, min(self.end_z, point.z))
        rel = Vector3(point.x - self.center.x, point.y - self.center.y, clamped_z - self.center.z)
        nx = rel.x / max(self.radius_x, 1e-3)
        ny = rel.y / max(self.radius_y, 1e-3)
        radial = math.hypot(nx, ny)
        if radial == 0.0:
            normal = Vector3(0.0, 1.0, 0.0)
            radial_distance = 0.0
        else:
            surface = Vector3(
                self.center.x + self.radius_x * (nx / radial),
                self.center.y + self.radius_y * (ny / radial),
                clamped_z,
            )
            radial_distance = Vector3(point.x, point.y, clamped_z).distance_to(surface)
            normal = Vector3(point.x - surface.x, point.y - surface.y, 0.0)
            if normal.length() > 0.0:
                normal = normal.normalize()
        axial_offset = 0.0
        if point.z < self.start_z:
            axial_offset = point.z - self.start_z
        elif point.z > self.end_z:
            axial_offset = point.z - self.end_z
        distance = math.hypot(radial_distance, axial_offset)
        inside = radial <= 1.0 and self.start_z <= point.z <= self.end_z
        signed = -distance if inside else distance
        if inside and normal.length() == 0.0:
            normal = Vector3(0.0, 1.0, 0.0)
        elif axial_offset != 0.0:
            axial_normal = Vector3(0.0, 0.0, math.copysign(1.0, axial_offset))
            if normal.length() == 0.0:
                normal = axial_normal
            else:
                normal = (normal + axial_normal).normalize()
        return signed, normal


@dataclass(slots=True)
class OutpostCollisionProfile:
    hull_sections: List[EllipseSection]
    nose_cap: Ellipsoid
    tail_cap: Ellipsoid
    docking_arms: List[Capsule]
    engine_capsules: List[Ellipsoid]

    def signed_distance(self, point: Vector3) -> tuple[float, Vector3]:
        best_distance = float("inf")
        best_normal = Vector3(0.0, 0.0, 1.0)

        def consider(distance: float, normal: Vector3) -> None:
            nonlocal best_distance, best_normal
            if distance < best_distance:
                best_distance = distance
                best_normal = normal

        consider(*self._hull_distance(point))
        for capsule in self.docking_arms:
            consider(*capsule.signed_distance(point))
        for engine in self.engine_capsules:
            consider(*engine.signed_distance(point))
        consider(*self.nose_cap.signed_distance(point))
        consider(*self.tail_cap.signed_distance(point))
        return best_distance, best_normal

    def _hull_distance(self, point: Vector3) -> tuple[float, Vector3]:
        sections = self.hull_sections
        if not sections:
            return point.length(), Vector3(0.0, 0.0, 1.0)
        if point.z <= sections[0].z:
            section = sections[0]
            width = section.half_width
            height = section.half_height
        elif point.z >= sections[-1].z:
            section = sections[-1]
            width = section.half_width
            height = section.half_height
        else:
            for idx in range(len(sections) - 1):
                a = sections[idx]
                b = sections[idx + 1]
                if a.z <= point.z <= b.z or b.z <= point.z <= a.z:
                    span = b.z - a.z
                    t = 0.0 if span == 0.0 else (point.z - a.z) / span
                    width = a.half_width + (b.half_width - a.half_width) * t
                    height = a.half_height + (b.half_height - a.half_height) * t
                    break
            else:
                width = sections[-1].half_width
                height = sections[-1].half_height
        nx = point.x / max(width, 1e-3)
        ny = point.y / max(height, 1e-3)
        radial = math.hypot(nx, ny)
        if radial == 0.0:
            return -min(width, height), Vector3(0.0, 1.0, 0.0)
        surface = Vector3(width * (nx / radial), height * (ny / radial), point.z)
        normal = Vector3(point.x - surface.x, point.y - surface.y, 0.0)
        if normal.length() > 0.0:
            normal = normal.normalize()
        distance = (Vector3(point.x, point.y, point.z) - surface).length()
        signed = distance if radial >= 1.0 else -distance
        return signed, normal if normal.length() > 0.0 else Vector3(0.0, 1.0, 0.0)


@dataclass(slots=True)
class OutpostSkin:
    geometry: ShipGeometry
    collision: OutpostCollisionProfile
    engine_layout: List[Vector3]


def _build_outpost_skin() -> OutpostSkin:
    hull_profile = [
        (-640.0, 150.0, 96.0),
        (-580.0, 146.0, 92.0),
        (-520.0, 140.0, 88.0),
        (-440.0, 148.0, 82.0),
        (-360.0, 184.0, 110.0),
        (-240.0, 220.0, 110.0),
        (-120.0, 240.0, 125.0),
        (0.0, 250.0, 140.0),
        (120.0, 230.0, 130.0),
        (240.0, 200.0, 110.0),
        (360.0, 170.0, 95.0),
        (480.0, 140.0, 80.0),
        (560.0, 120.0, 70.0),
    ]
    hull_sections = [EllipseSection(z, w, h) for z, w, h in hull_profile]
    vertices: List[Vector3] = []
    vertex_map: Dict[Tuple[float, float, float], int] = {}
    faces: List[ShipFace] = []
    ring_sides = 18
    hull_rings: List[List[int]] = []

    for z_pos, half_width, half_height in hull_profile:
        ring: List[int] = []
        for step in range(ring_sides):
            angle = step * (2.0 * math.pi / ring_sides)
            point = Vector3(
                math.cos(angle) * half_width,
                math.sin(angle) * half_height,
                z_pos,
            )
            ring.append(_add_vertex(vertices, vertex_map, point))
        hull_rings.append(ring)

    hull_color_top = (104, 136, 170)
    hull_color_bottom = (58, 78, 102)

    for section_index in range(len(hull_rings) - 1):
        prev_ring = hull_rings[section_index]
        next_ring = hull_rings[section_index + 1]
        for step in range(ring_sides):
            a = prev_ring[step]
            b = prev_ring[(step + 1) % ring_sides]
            c = next_ring[(step + 1) % ring_sides]
            d = next_ring[step]
            indices = (a, b, c, d)
            avg_y = _average_attribute(vertices, indices, "y")
            avg_z = _average_attribute(vertices, indices, "z")
            vertical_factor = max(0.0, min(1.0, (avg_y + 220.0) / 440.0))
            base_color = _blend(hull_color_bottom, hull_color_top, vertical_factor)
            accent = 0.0
            if (section_index + step) % 5 == 0:
                accent = 0.12
            elif (section_index + step) % 3 == 0:
                accent = -0.08
            outline = None
            if step % 6 == 0:
                outline = _blend(base_color, (18, 28, 38), 0.7)
            normal = _face_normal(vertices, indices)
            faces.append(ShipFace(indices=indices, base_color=base_color, normal=normal, accent=accent, outline=outline))

    nose_tip = _add_vertex(vertices, vertex_map, Vector3(0.0, 42.0, hull_profile[-1][0] + 80.0))
    ventral_spear = _add_vertex(vertices, vertex_map, Vector3(0.0, -38.0, hull_profile[-1][0] + 70.0))
    final_ring = hull_rings[-1]
    nose_color = (120, 158, 192)
    for offset in range(0, ring_sides, 2):
        indices = (final_ring[offset], final_ring[(offset + 1) % ring_sides], nose_tip)
        faces.append(
            ShipFace(
                indices=indices,
                base_color=nose_color,
                normal=_face_normal(vertices, indices),
                accent=0.18,
                outline=_blend(nose_color, (28, 44, 64), 0.6),
            )
        )
    for offset in range(0, ring_sides, 2):
        indices = (final_ring[offset], ventral_spear, final_ring[(offset + 1) % ring_sides])
        faces.append(
            ShipFace(
                indices=indices,
                base_color=_blend(hull_color_bottom, (34, 48, 66), 0.6),
                normal=_face_normal(vertices, indices),
                accent=-0.12,
            )
        )

    # Engine housing
    tail_z = hull_profile[0][0]
    tail_half_width = hull_profile[0][1]
    tail_half_height = hull_profile[0][2]
    housing_front_z = tail_z + 18.0
    housing_back_z = tail_z - 48.0
    housing_half_width = tail_half_width + 20.0
    housing_half_height = tail_half_height + 24.0

    housing_points = {
        "top_front_left": Vector3(-housing_half_width, housing_half_height, housing_front_z),
        "top_back_left": Vector3(-housing_half_width + 20.0, housing_half_height + 8.0, housing_back_z),
        "top_back_right": Vector3(housing_half_width - 20.0, housing_half_height + 8.0, housing_back_z),
        "top_front_right": Vector3(housing_half_width, housing_half_height, housing_front_z),
        "bottom_front_left": Vector3(-housing_half_width, -housing_half_height, housing_front_z),
        "bottom_back_left": Vector3(-housing_half_width + 20.0, -housing_half_height - 8.0, housing_back_z),
        "bottom_back_right": Vector3(housing_half_width - 20.0, -housing_half_height - 8.0, housing_back_z),
        "bottom_front_right": Vector3(housing_half_width, -housing_half_height, housing_front_z),
    }
    housing_indices = {name: _add_vertex(vertices, vertex_map, point) for name, point in housing_points.items()}

    panels = [
        ("top_front_left", "top_back_left", "top_back_right", "top_front_right", 0.1),
        ("bottom_front_right", "bottom_back_right", "bottom_back_left", "bottom_front_left", -0.15),
        ("top_front_right", "top_back_right", "bottom_back_right", "bottom_front_right", 0.05),
        ("top_front_left", "bottom_front_left", "bottom_back_left", "top_back_left", 0.05),
    ]
    housing_color = (74, 100, 130)
    for a, b, c, d, accent in panels:
        indices = (
            housing_indices[a],
            housing_indices[b],
            housing_indices[c],
            housing_indices[d],
        )
        normal = _face_normal(vertices, indices)
        outline = _blend(housing_color, (18, 26, 34), 0.7)
        faces.append(
            ShipFace(
                indices=indices,
                base_color=housing_color,
                normal=normal,
                accent=accent,
                outline=outline,
            )
        )

    # Engines
    engine_offset_x = tail_half_width - 36.0
    engine_offset_y = tail_half_height - 30.0
    engine_radius_x = 30.0
    engine_radius_y = 24.0
    engine_depth = 18.0
    nozzle_inset = 5.0
    engine_layout: List[Vector3] = []
    engine_color = (64, 88, 118)
    nozzle_color = (48, 68, 92)
    engine_capsules: List[Ellipsoid] = []
    for sign in (-1, 1):
        for vertical in (-1, 1):
            center = Vector3(
                sign * engine_offset_x,
                vertical * engine_offset_y,
                housing_back_z + engine_depth,
            )
            engine_layout.append(Vector3(center))
            ring_indices: List[int] = []
            nozzle_indices: List[int] = []
            for step in range(12):
                angle = step * (2.0 * math.pi / 12)
                ring_point = Vector3(
                    center.x + math.cos(angle) * engine_radius_x,
                    center.y + math.sin(angle) * engine_radius_y,
                    center.z,
                )
                nozzle_point = Vector3(
                    center.x + math.cos(angle) * engine_radius_x * 0.68,
                    center.y + math.sin(angle) * engine_radius_y * 0.68,
                    housing_back_z + nozzle_inset,
                )
                ring_indices.append(_add_vertex(vertices, vertex_map, ring_point))
                nozzle_indices.append(_add_vertex(vertices, vertex_map, nozzle_point))
            for step in range(12):
                a = ring_indices[step]
                b = ring_indices[(step + 1) % 12]
                c = nozzle_indices[(step + 1) % 12]
                d = nozzle_indices[step]
                indices = (a, b, c, d)
                normal = _face_normal(vertices, indices)
                faces.append(
                    ShipFace(
                        indices=indices,
                        base_color=engine_color,
                        normal=normal,
                        accent=-0.05 if step % 2 == 0 else 0.08,
                        outline=_blend(engine_color, (18, 24, 32), 0.6),
                    )
                )
            thruster_center = _add_vertex(vertices, vertex_map, Vector3(center.x, center.y, housing_back_z + nozzle_inset))
            for step in range(0, 12, 2):
                indices = (nozzle_indices[step], nozzle_indices[(step + 1) % 12], thruster_center)
                faces.append(
                    ShipFace(
                        indices=indices,
                        base_color=nozzle_color,
                        normal=_face_normal(vertices, indices),
                        accent=-0.1,
                    )
                )
            engine_capsules.append(
                Ellipsoid(
                    center=center,
                    radius=Vector3(engine_radius_x, engine_radius_y, engine_depth * 0.85),
                )
            )

    # Docking arms
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
    docking_faces_color = (92, 124, 152)
    docking_faces_dark = (56, 80, 104)
    docking_capsules: List[Capsule] = []

    for sign in (-1, 1):
        previous_ring: List[int] | None = None
        first_ring: List[int] | None = None
        for section_index in range(docking_arm_sections):
            if docking_arm_sections == 1:
                position_fraction = 0.0
            else:
                position_fraction = section_index / (docking_arm_sections - 1)
            z_pos = docking_arm_start_z + (docking_arm_end_z - docking_arm_start_z) * position_fraction
            center = Vector3(sign * docking_arm_offset_x, docking_arm_offset_y, z_pos)
            ring_indices: List[int] = []
            for step in range(docking_arm_ring_sides):
                angle = step * (2.0 * math.pi / docking_arm_ring_sides)
                point = Vector3(
                    center.x + math.cos(angle) * docking_arm_radius,
                    center.y + math.sin(angle) * docking_arm_vertical_radius,
                    center.z,
                )
                ring_indices.append(_add_vertex(vertices, vertex_map, point))
            if previous_ring is not None:
                for step in range(docking_arm_ring_sides):
                    a = previous_ring[step]
                    b = previous_ring[(step + 1) % docking_arm_ring_sides]
                    c = ring_indices[(step + 1) % docking_arm_ring_sides]
                    d = ring_indices[step]
                    indices = (a, b, c, d)
                    normal = _face_normal(vertices, indices)
                    base = docking_faces_color if step % 2 == 0 else docking_faces_dark
                    accent = 0.12 if step % 3 == 0 else -0.04
                    faces.append(
                        ShipFace(
                            indices=indices,
                            base_color=base,
                            normal=normal,
                            accent=accent,
                            outline=_blend(base, (22, 32, 42), 0.6),
                        )
                    )
            if previous_ring is None:
                first_ring = ring_indices
            previous_ring = ring_indices
        if previous_ring:
            tip_center = Vector3(sign * docking_arm_offset_x, docking_arm_offset_y, docking_arm_end_z)
            tip_index = _add_vertex(vertices, vertex_map, tip_center + Vector3(0.0, 0.0, docking_arm_radius * 0.22))
            base_center = Vector3(sign * docking_arm_offset_x, docking_arm_offset_y, docking_arm_start_z)
            base_index = _add_vertex(vertices, vertex_map, base_center - Vector3(0.0, 0.0, docking_arm_radius * 0.22))
            for step in range(0, docking_arm_ring_sides, 2):
                indices_tip = (previous_ring[step], previous_ring[(step + 1) % docking_arm_ring_sides], tip_index)
                faces.append(
                    ShipFace(
                        indices=indices_tip,
                        base_color=_blend(docking_faces_color, (130, 160, 188), 0.4),
                        normal=_face_normal(vertices, indices_tip),
                        accent=0.2,
                    )
                )
            if first_ring:
                for step in range(0, docking_arm_ring_sides, 2):
                    indices_base = (first_ring[step], base_index, first_ring[(step + 1) % docking_arm_ring_sides])
                    faces.append(
                        ShipFace(
                            indices=indices_base,
                            base_color=_blend(docking_faces_dark, (30, 40, 52), 0.5),
                            normal=_face_normal(vertices, indices_base),
                            accent=-0.18,
                        )
                    )
            docking_capsules.append(
                Capsule(
                    center=Vector3(sign * docking_arm_offset_x, docking_arm_offset_y, (docking_arm_start_z + docking_arm_end_z) * 0.5),
                    start_z=docking_arm_start_z,
                    end_z=docking_arm_end_z,
                    radius_x=docking_arm_radius,
                    radius_y=docking_arm_vertical_radius,
                )
            )

    nose_cap = Ellipsoid(
        center=Vector3(0.0, 0.0, hull_profile[-1][0] + 52.0),
        radius=Vector3(80.0, 60.0, 68.0),
    )
    tail_cap = Ellipsoid(
        center=Vector3(0.0, 0.0, tail_z - 40.0),
        radius=Vector3(tail_half_width + 40.0, tail_half_height + 24.0, 52.0),
    )

    geometry = ShipGeometry(vertices=vertices, edges=[], radius=max(vertex.length() for vertex in vertices), faces=faces)
    collision = OutpostCollisionProfile(
        hull_sections=hull_sections,
        nose_cap=nose_cap,
        tail_cap=tail_cap,
        docking_arms=docking_capsules,
        engine_capsules=engine_capsules,
    )
    return OutpostSkin(geometry=geometry, collision=collision, engine_layout=engine_layout)


OUTPOST_SKIN = _build_outpost_skin()
