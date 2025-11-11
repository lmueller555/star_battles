"""First-person interior explorer for the outpost hangar."""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum, auto
from typing import Dict, Iterable, Optional, Sequence

import pygame
from pygame import Surface
from pygame.math import Vector2, Vector3

from game.engine.input import InputMapper
from game.world.interior import (
    InteriorChunk,
    InteriorDefinition,
    InteriorDoor,
    InteriorNavArea,
    InteriorNode,
)


FOV_DEGREES = 86.0
NEAR_PLANE = 0.05
FAR_PLANE = 800.0
PLAYER_HEIGHT = 1.8
PLAYER_RADIUS = 0.35
STEP_HEIGHT = 0.35
GRAVITY = 9.81

LAYER_ORDER = {
    "Floor": 0,
    "Walls": 1,
    "Ceiling": 2,
    "Fixtures": 3,
    "Doors": 4,
    "ShipWire": 5,
    "Signs": 6,
    "FX": 7,
}

STYLE_COLOURS = {
    "primary": (120, 210, 255),
    "secondary": (60, 120, 180),
    "ceiling_primary": (160, 200, 230),
    "ceiling_beam": (200, 240, 255),
    "fixture_light": (255, 255, 240),
    "catwalk": (160, 220, 255),
    "ladder": (255, 210, 140),
    "door_frame": (180, 230, 255),
    "door_panel": (130, 180, 220),
    "service_line": (130, 200, 255),
    "crane_rail": (255, 210, 150),
    "deck_pad": (200, 230, 255),
}

DEFAULT_LAYER_COLOUR = {
    "Floor": (90, 160, 210),
    "Walls": (70, 130, 190),
    "Ceiling": (150, 190, 220),
    "Fixtures": (180, 220, 255),
    "Doors": (160, 200, 240),
    "ShipWire": (120, 220, 255),
    "Signs": (200, 240, 255),
    "FX": (255, 255, 255),
}


class DoorState(Enum):
    CLOSED = auto()
    OPENING = auto()
    OPEN = auto()
    CLOSING = auto()
    LOCKED = auto()


@dataclass
class SlidingDoorRuntime:
    definition: InteriorDoor
    state: DoorState = DoorState.CLOSED
    openness: float = 0.0
    speed: float = 1.4

    def is_open(self) -> bool:
        return self.openness >= 0.99 and self.state in (DoorState.OPEN, DoorState.OPENING)

    def is_closed(self) -> bool:
        return self.openness <= 0.01 and self.state in (DoorState.CLOSED, DoorState.CLOSING)

    def update(self, dt: float, should_open: bool) -> None:
        if self.state == DoorState.LOCKED:
            return
        if should_open:
            self.state = DoorState.OPENING
            self.openness = min(1.0, self.openness + dt * self.speed)
            if self.openness >= 1.0:
                self.state = DoorState.OPEN
        else:
            self.state = DoorState.CLOSING if self.openness > 0.0 else DoorState.CLOSED
            self.openness = max(0.0, self.openness - dt * self.speed)
            if self.openness <= 0.0:
                self.state = DoorState.CLOSED


class DoorManager:
    """Evaluates sliding door triggers and maintains airlock sequencing."""

    def __init__(self, doors: Sequence[InteriorDoor], chunks: Sequence[InteriorChunk]) -> None:
        self.doors: Dict[str, SlidingDoorRuntime] = {door.id: SlidingDoorRuntime(door) for door in doors}
        self.chunks = {chunk.id: chunk for chunk in chunks}

    def _point_in_chunk(self, chunk_id: str, position: Vector3) -> bool:
        chunk = self.chunks.get(chunk_id)
        if not chunk:
            return False
        min_x, min_y, min_z = chunk.aabb_min
        max_x, max_y, max_z = chunk.aabb_max
        return (
            min_x <= position.x <= max_x
            and min_y <= position.y <= max_y
            and min_z <= position.z <= max_z
        )

    def update(self, dt: float, position: Vector3, forward: Vector3) -> None:
        outer = self.doors.get("hangar_airlock_outer")
        inner = self.doors.get("hangar_airlock_inner")
        vestibule_clear = outer.is_closed() if outer else True

        for runtime in self.doors.values():
            should_open = False
            definition = runtime.definition
            trigger_min = Vector3(*definition.trigger_min)
            trigger_max = Vector3(*definition.trigger_max)
            in_trigger = (
                trigger_min.x <= position.x <= trigger_max.x
                and trigger_min.y <= position.y <= trigger_max.y
                and trigger_min.z - STEP_HEIGHT <= position.z <= trigger_max.z + STEP_HEIGHT
            )
            if not in_trigger:
                runtime.update(dt, False)
                continue

            facing = Vector3(*definition.facing)
            facing_alignment = facing.normalize().dot(forward.normalize()) if facing.length_squared() > 1e-6 else 1.0

            if definition.id == "hangar_airlock_outer":
                should_open = facing_alignment > 0.25
            elif definition.id == "hangar_airlock_inner":
                should_open = vestibule_clear and facing_alignment > -0.4 and self._point_in_chunk("vestibule", position)
            elif definition.id == "fleet_shop":
                should_open = True
            elif definition.id == "weapons_bay":
                should_open = True
            else:
                should_open = True

            runtime.update(dt, should_open)


@dataclass
class ProjectedSegment:
    start: Vector2
    end: Vector2
    depth: float
    colour: tuple[int, int, int, int]
    thickness: int


@dataclass
class ProjectedSurface:
    points: list[Vector2]
    depth: float
    colour: tuple[int, int, int, int]


class WireframeProjector:
    """Performs perspective projection for interior wireframe geometry."""

    def __init__(self) -> None:
        self.half_fov = math.radians(FOV_DEGREES * 0.5)

    @staticmethod
    def _clip_polygon_to_near(points: Sequence[Vector3], near_plane: float) -> list[Vector3]:
        if not points:
            return []
        clipped: list[Vector3] = []
        prev = points[-1]
        prev_inside = prev.z > near_plane
        for current in points:
            current_inside = current.z > near_plane
            if current_inside != prev_inside:
                direction = current - prev
                denom = direction.z
                if abs(denom) > 1e-6:
                    t = (near_plane - prev.z) / denom
                    intersection = prev + direction * t
                    clipped.append(intersection)
            if current_inside:
                clipped.append(current)
            prev = current
            prev_inside = current_inside
        return clipped

    def _camera_basis(self, forward: Vector3) -> tuple[Vector3, Vector3, Vector3]:
        up_world = Vector3(0.0, 0.0, 1.0)
        forward_n = forward.normalize() if forward.length_squared() > 1e-6 else Vector3(0.0, 1.0, 0.0)
        right = forward_n.cross(up_world)
        if right.length_squared() < 1e-6:
            right = Vector3(1.0, 0.0, 0.0)
        else:
            right = right.normalize()
        up = right.cross(forward_n).normalize()
        return right, up, forward_n

    def project(
        self,
        camera_pos: Vector3,
        forward: Vector3,
        points: Sequence[Vector3],
        colour: tuple[int, int, int],
        layer: str,
        surface_size: tuple[int, int],
    ) -> Iterable[ProjectedSegment]:
        width, height = surface_size
        aspect = width / max(1, height)
        right, up, forward_n = self._camera_basis(forward)
        proj_segments: list[ProjectedSegment] = []

        def to_camera_space(point: Vector3) -> tuple[float, float, float]:
            rel = point - camera_pos
            x_cam = rel.dot(right)
            y_cam = rel.dot(up)
            z_cam = rel.dot(forward_n)
            return x_cam, y_cam, z_cam

        f = 1.0 / math.tan(self.half_fov)

        def to_screen(vec: tuple[float, float, float]) -> Optional[tuple[float, float]]:
            x_cam, y_cam, z_cam = vec
            if z_cam <= NEAR_PLANE or z_cam >= FAR_PLANE:
                return None
            scale = f / z_cam
            x_ndc = x_cam * scale
            y_ndc = y_cam * scale
            sx = (x_ndc * aspect * 0.5 + 0.5) * width
            sy = (0.5 - y_ndc * 0.5) * height
            return sx, sy

        for start, end in zip(points, points[1:]):
            start_cam = to_camera_space(start)
            end_cam = to_camera_space(end)
            if start_cam[2] <= NEAR_PLANE or end_cam[2] <= NEAR_PLANE:
                continue
            screen_start = to_screen(start_cam)
            screen_end = to_screen(end_cam)
            if not screen_start or not screen_end:
                continue
            depth = (start_cam[2] + end_cam[2]) * 0.5
            distance = depth
            alpha = 255
            if distance > 10.0:
                fade = min(1.0, (distance - 10.0) / 50.0)
                alpha = int(255 - fade * 165)
            if layer == "Ceiling":
                alpha = max(96, int(alpha * 0.85))
            thickness = max(1, int(3 - min(distance * 0.05, 2.0)))
            r, g, b = colour
            proj_segments.append(
                ProjectedSegment(
                    start=Vector2(screen_start),
                    end=Vector2(screen_end),
                    depth=depth,
                    colour=(r, g, b, alpha),
                    thickness=thickness,
                )
            )
        return proj_segments

    def project_point(
        self,
        camera_pos: Vector3,
        forward: Vector3,
        point: Vector3,
        surface_size: tuple[int, int],
    ) -> Optional[tuple[Vector2, float]]:
        width, height = surface_size
        aspect = width / max(1, height)
        right, up, forward_n = self._camera_basis(forward)
        rel = point - camera_pos
        x_cam = rel.dot(right)
        y_cam = rel.dot(up)
        z_cam = rel.dot(forward_n)
        if z_cam <= NEAR_PLANE or z_cam >= FAR_PLANE:
            return None
        scale = 1.0 / math.tan(self.half_fov) / z_cam
        x_ndc = x_cam * scale
        y_ndc = y_cam * scale
        sx = (x_ndc * aspect * 0.5 + 0.5) * width
        sy = (0.5 - y_ndc * 0.5) * height
        return Vector2(sx, sy), z_cam

    def project_polygon(
        self,
        camera_pos: Vector3,
        forward: Vector3,
        points: Sequence[Vector3],
        colour: tuple[int, int, int, int],
        surface_size: tuple[int, int],
    ) -> Optional[ProjectedSurface]:
        width, height = surface_size
        aspect = width / max(1, height)
        right, up, forward_n = self._camera_basis(forward)

        cam_space: list[Vector3] = []
        for point in points:
            rel = point - camera_pos
            x_cam = rel.dot(right)
            y_cam = rel.dot(up)
            z_cam = rel.dot(forward_n)
            cam_space.append(Vector3(x_cam, y_cam, z_cam))

        cam_space = self._clip_polygon_to_near(cam_space, NEAR_PLANE)
        if len(cam_space) < 3:
            return None

        projected: list[Vector2] = []
        depth_accum = 0.0
        count = 0
        f = 1.0 / math.tan(self.half_fov)
        for vertex in cam_space:
            if vertex.z <= 0.0 or vertex.z >= FAR_PLANE:
                return None
            scale = f / vertex.z
            x_ndc = vertex.x * scale
            y_ndc = vertex.y * scale
            sx = (x_ndc * aspect * 0.5 + 0.5) * width
            sy = (0.5 - y_ndc * 0.5) * height
            projected.append(Vector2(sx, sy))
            depth_accum += vertex.z
            count += 1

        depth = depth_accum / max(1, count)
        return ProjectedSurface(projected, depth, colour)


class FirstPersonInteriorView:
    """Interactive first-person rendering of an interior definition."""

    def __init__(self, definition: InteriorDefinition) -> None:
        self.definition = definition
        self.position = Vector3(0.0, 0.0, PLAYER_HEIGHT)
        self.velocity = Vector3(0.0, 0.0, 0.0)
        self.yaw = math.radians(180.0)
        self.pitch = 0.0
        self.nav_areas: tuple[InteriorNavArea, ...] = definition.nav_areas
        self.no_walk = definition.no_walk_zones
        self.chunks = definition.chunks
        self.door_manager = DoorManager(definition.doors, definition.chunks)
        self.dynamic_segments: list[tuple[Vector3, Vector3, str]] = []
        self.dynamic_no_walk: list[tuple[Vector3, Vector3]] = []
        self.projector = WireframeProjector()
        self.hud_font: Optional[pygame.font.Font] = None
        self.prompt_font: Optional[pygame.font.Font] = None
        self.streams_active: set[str] = set()
        self._node_lookup: Dict[str, InteriorNode] = {node.id: node for node in definition.nodes}

    def set_fonts(self, hud_font: Optional[pygame.font.Font], prompt_font: Optional[pygame.font.Font]) -> None:
        self.hud_font = hud_font
        self.prompt_font = prompt_font

    def reset(self) -> None:
        spawn = self.definition.spawn_point
        if spawn:
            self.position = Vector3(spawn[0], spawn[1], PLAYER_HEIGHT)
        else:
            min_x, min_y, max_x, max_y = self.definition.bounds
            self.position = Vector3((min_x + max_x) * 0.5, (min_y + max_y) * 0.5, PLAYER_HEIGHT)
        self.velocity = Vector3()
        self.yaw = math.radians(90.0)
        self.pitch = 0.0

    def set_ship_segments(self, segments: Iterable[tuple[Vector3, Vector3]]) -> None:
        self.dynamic_segments = [(start, end, "ShipWire") for start, end in segments]

    def set_dynamic_no_walk(self, minimum: Vector3, maximum: Vector3) -> None:
        self.dynamic_no_walk = [(Vector3(minimum), Vector3(maximum))]

    def _forward_vector(self) -> Vector3:
        cos_pitch = math.cos(self.pitch)
        return Vector3(
            math.sin(self.yaw) * cos_pitch,
            math.cos(self.yaw) * cos_pitch,
            math.sin(self.pitch),
        ).normalize()

    def _right_vector(self) -> Vector3:
        forward = self._forward_vector()
        right = forward.cross(Vector3(0.0, 0.0, 1.0))
        if right.length_squared() < 1e-6:
            return Vector3(1.0, 0.0, 0.0)
        return right.normalize()

    def update(self, dt: float, input_mapper: InputMapper) -> None:
        mouse_dx, mouse_dy = input_mapper.mouse()
        look_x = input_mapper.axis_state.get("look_x", 0.0)
        look_y = input_mapper.axis_state.get("look_y", 0.0)
        sensitivity = 0.0025
        self.yaw -= (mouse_dx * sensitivity + look_x * dt * 1.8)
        self.pitch -= (mouse_dy * sensitivity + look_y * dt * 1.2)
        self.pitch = max(-math.radians(75.0), min(math.radians(75.0), self.pitch))

        move_forward = input_mapper.axis_state.get("throttle", 0.0)
        move_side = input_mapper.axis_state.get("strafe_x", 0.0)
        move_vertical = input_mapper.axis_state.get("strafe_y", 0.0)

        forward = self._forward_vector()
        right = self._right_vector()
        up = Vector3(0.0, 0.0, 1.0)

        wish_dir = forward * move_forward + right * move_side + up * move_vertical
        if wish_dir.length_squared() > 1e-6:
            wish_dir = wish_dir.normalize()
        speed = 5.0
        desired_velocity = wish_dir * speed
        self.velocity.xy = desired_velocity.xy
        # Vertical movement limited to ladders - keep feet grounded otherwise.
        self.velocity.z = 0.0

        desired_position = self.position + self.velocity * dt
        desired_position.z = PLAYER_HEIGHT
        desired_position = self._constrain_to_nav(desired_position)
        desired_position = self._resolve_no_walk(desired_position)
        self.position = desired_position

        self.door_manager.update(dt, self.position, forward)
        self._update_streaming(self.position)

    def _update_streaming(self, position: Vector3) -> None:
        active: set[str] = set()
        for chunk in self.chunks:
            min_x, min_y, min_z = chunk.aabb_min
            max_x, max_y, max_z = chunk.aabb_max
            if (
                min_x <= position.x <= max_x
                and min_y <= position.y <= max_y
                and min_z <= position.z <= max_z
            ):
                if chunk.stream:
                    active.add(chunk.stream)
        self.streams_active = active

    def _constrain_to_nav(self, desired: Vector3) -> Vector3:
        for area in self.nav_areas:
            if area.contains(desired.x, desired.y):
                return Vector3(desired)
        best: Optional[Vector3] = None
        best_distance = float("inf")
        for area in self.nav_areas:
            left, bottom, right, top = area.bounds
            clamped_x = max(left, min(right, desired.x))
            clamped_y = max(bottom, min(top, desired.y))
            dx = clamped_x - desired.x
            dy = clamped_y - desired.y
            distance_sq = dx * dx + dy * dy
            if distance_sq < best_distance:
                best_distance = distance_sq
                best = Vector3(clamped_x, clamped_y, desired.z)
        if best is None:
            return Vector3(desired)
        return best

    def _resolve_no_walk(self, position: Vector3) -> Vector3:
        corrected = Vector3(position)
        zones = [(Vector3(*zone.aabb_min), Vector3(*zone.aabb_max)) for zone in self.no_walk]
        zones.extend(self.dynamic_no_walk)
        for min_corner, max_corner in zones:
            min_x, min_y, min_z = min_corner
            max_x, max_y, max_z = max_corner
            if (
                min_x <= corrected.x <= max_x
                and min_y <= corrected.y <= max_y
                and min_z <= corrected.z <= max_z
            ):
                distances = {
                    "x_min": corrected.x - min_x,
                    "x_max": max_x - corrected.x,
                    "y_min": corrected.y - min_y,
                    "y_max": max_y - corrected.y,
                }
                axis, amount = min(distances.items(), key=lambda item: item[1])
                if axis == "x_min":
                    corrected.x = min_x - PLAYER_RADIUS
                elif axis == "x_max":
                    corrected.x = max_x + PLAYER_RADIUS
                elif axis == "y_min":
                    corrected.y = min_y - PLAYER_RADIUS
                else:
                    corrected.y = max_y + PLAYER_RADIUS
        for runtime in self.door_manager.doors.values():
            if runtime.openness >= 0.6:
                continue
            frame_min = Vector3(*runtime.definition.frame_min)
            frame_max = Vector3(*runtime.definition.frame_max)
            min_x, min_y, min_z = frame_min
            max_x, max_y, max_z = frame_max
            if (
                min_x <= corrected.x <= max_x
                and min_y <= corrected.y <= max_y
                and min_z - STEP_HEIGHT <= corrected.z <= max_z + STEP_HEIGHT
            ):
                facing = Vector3(*runtime.definition.facing)
                if facing.length_squared() < 1e-6:
                    facing = Vector3(0.0, 1.0, 0.0)
                normal = facing.normalize()
                offset = normal.xy
                if offset.length_squared() < 1e-6:
                    offset = Vector2(0.0, 1.0)
                else:
                    offset = Vector2(offset.x, offset.y).normalize()
                push = offset * PLAYER_RADIUS * 1.05
                corrected.x += push.x
                corrected.y += push.y
        return corrected

    @staticmethod
    def _loop_points(node: InteriorNode) -> list[Vector3]:
        points = [Vector3(*pt) for pt in node.points]
        if len(points) < 2:
            return []
        if points[0].distance_to(points[-1]) < 1e-4:
            points = points[:-1]
        return points

    def _collect_surfaces(self) -> list[tuple[str, list[Vector3], Optional[str]]]:
        surfaces: list[tuple[str, list[Vector3], Optional[str]]] = []
        for node in self.definition.nodes:
            if node.layer not in {"Floor", "Ceiling"}:
                continue
            if len(node.points) < 3:
                continue
            closed = node.type.endswith("closed") or node.points[0] == node.points[-1]
            if not closed:
                continue
            loop = self._loop_points(node)
            if len(loop) < 3:
                continue
            surfaces.append((node.layer, loop, node.style))

        for node in self.definition.nodes:
            if node.layer != "Walls" or not node.id.endswith("_wall_base"):
                continue
            top_id = node.id.replace("_wall_base", "_wall_top")
            top = self._node_lookup.get(top_id)
            if not top:
                continue
            base_loop = self._loop_points(node)
            top_loop = self._loop_points(top)
            if len(base_loop) < 2 or len(base_loop) != len(top_loop):
                continue
            for index in range(len(base_loop)):
                next_index = (index + 1) % len(base_loop)
                b0 = base_loop[index]
                b1 = base_loop[next_index]
                t1 = top_loop[next_index]
                t0 = top_loop[index]
                quad = [b0, b1, t1, t0]
                surfaces.append(("Walls", quad, node.style or top.style))
        return surfaces

    @staticmethod
    def _polygon_centroid(points: Sequence[Vector3]) -> Vector3:
        if not points:
            return Vector3()
        accum = Vector3()
        for point in points:
            accum += point
        return accum / len(points)

    @staticmethod
    def _polygon_normal(points: Sequence[Vector3]) -> Optional[Vector3]:
        if len(points) < 3:
            return None
        normal = Vector3()
        for idx in range(len(points)):
            current = points[idx]
            nxt = points[(idx + 1) % len(points)]
            nxt2 = points[(idx + 2) % len(points)]
            edge1 = nxt - current
            edge2 = nxt2 - current
            cross = edge1.cross(edge2)
            if cross.length_squared() > 1e-6:
                normal += cross
        if normal.length_squared() < 1e-6:
            return None
        return normal.normalize()

    def _shade_surface_colour(
        self,
        layer: str,
        base_colour: tuple[int, int, int],
        points: Sequence[Vector3],
        camera_pos: Vector3,
    ) -> tuple[int, int, int, int]:
        normal = self._polygon_normal(points)
        centroid = self._polygon_centroid(points)
        intensity = 0.7
        if normal and centroid != camera_pos:
            to_camera = camera_pos - centroid
            if to_camera.length_squared() > 1e-6:
                to_camera_n = to_camera.normalize()
                alignment = abs(normal.dot(to_camera_n))
                intensity = 0.35 + 0.65 * alignment
        if layer == "Floor":
            alpha = 235
            intensity *= 1.05
        elif layer == "Ceiling":
            alpha = 210
            intensity *= 0.9
        else:
            alpha = 225
        intensity = max(0.25, min(1.0, intensity))
        r = min(255, int(base_colour[0] * intensity))
        g = min(255, int(base_colour[1] * intensity))
        b = min(255, int(base_colour[2] * intensity))
        return r, g, b, alpha

    def _collect_segments(self) -> list[tuple[str, list[Vector3], Optional[str]]]:
        collected: list[tuple[str, list[Vector3], Optional[str]]] = []
        for node in self.definition.nodes:
            points = [Vector3(*pt) for pt in node.points]
            if not points:
                continue
            if node.type.endswith("closed") and (points[0] != points[-1]):
                points.append(points[0])
            collected.append((node.layer, points, node.style))
        for start, end, layer in self.dynamic_segments:
            collected.append((layer, [start, end], "ship_wire"))
        return collected

    def render(self, surface: Surface) -> None:
        width, height = surface.get_size()
        surface.fill((8, 12, 20))
        camera_pos = Vector3(self.position.x, self.position.y, self.position.z)
        forward = self._forward_vector()

        surfaces_by_layer: Dict[str, list[ProjectedSurface]] = {layer: [] for layer in LAYER_ORDER}
        for layer, points, style in self._collect_surfaces():
            base_colour = STYLE_COLOURS.get(style or "", DEFAULT_LAYER_COLOUR.get(layer, (200, 200, 200)))
            colour = self._shade_surface_colour(layer, base_colour, points, camera_pos)
            projected_surface = self.projector.project_polygon(camera_pos, forward, points, colour, (width, height))
            if projected_surface:
                surfaces_by_layer.setdefault(layer, []).append(projected_surface)

        segments_by_layer: Dict[str, list[ProjectedSegment]] = {layer: [] for layer in LAYER_ORDER}
        for layer, points, style in self._collect_segments():
            base_colour = STYLE_COLOURS.get(style or "", DEFAULT_LAYER_COLOUR.get(layer, (200, 200, 200)))
            projected = self.projector.project(camera_pos, forward, points, base_colour, layer, (width, height))
            for seg in projected:
                segments_by_layer.setdefault(layer, []).append(seg)

        ordered_layers = sorted(
            set(list(surfaces_by_layer.keys()) + list(segments_by_layer.keys())),
            key=lambda key: LAYER_ORDER.get(key, 99),
        )

        for layer in ordered_layers:
            for surface_proj in sorted(surfaces_by_layer.get(layer, []), key=lambda item: item.depth, reverse=True):
                pygame.draw.polygon(surface, surface_proj.colour, surface_proj.points)

            for seg in sorted(segments_by_layer.get(layer, []), key=lambda item: item.depth, reverse=True):
                colour = seg.colour
                pygame.draw.line(surface, colour, seg.start, seg.end, seg.thickness)

        if self.hud_font:
            for label in self.definition.labels:
                if not label.text:
                    continue
                projected = self.projector.project_point(camera_pos, forward, Vector3(*label.position), (width, height))
                if not projected:
                    continue
                screen_pos, depth = projected
                if depth > FAR_PLANE:
                    continue
                text_surface = self.hud_font.render(label.text, True, (200, 235, 255))
                surface.blit(
                    text_surface,
                    (
                        screen_pos.x - text_surface.get_width() * 0.5,
                        screen_pos.y - text_surface.get_height() * 0.5,
                    ),
                )

        if self.prompt_font:
            for runtime in self.door_manager.doors.values():
                sign = runtime.definition.sign
                if not sign:
                    continue
                frame_min = Vector3(*runtime.definition.frame_min)
                frame_max = Vector3(*runtime.definition.frame_max)
                header = Vector3(
                    (frame_min.x + frame_max.x) * 0.5,
                    (frame_min.y + frame_max.y) * 0.5,
                    frame_max.z,
                )
                projected = self.projector.project_point(camera_pos, forward, header, (width, height))
                if not projected:
                    continue
                screen_pos, _ = projected
                text_surface = self.prompt_font.render(sign, True, (190, 225, 255))
                surface.blit(
                    text_surface,
                    (
                        screen_pos.x - text_surface.get_width() * 0.5,
                        screen_pos.y - text_surface.get_height() - 6,
                    ),
                )

        if self.prompt_font:
            prompt = self.prompt_font.render("Inspect Ship [E]", True, (210, 240, 255))
            interact = next((region for region in self.definition.interact_regions if region.id == "inspect_ship"), None)
            if interact:
                min_x, min_y, min_z = interact.aabb_min
                max_x, max_y, max_z = interact.aabb_max
                if (
                    min_x <= self.position.x <= max_x
                    and min_y <= self.position.y <= max_y
                    and min_z <= self.position.z <= max_z + 2.0
                ):
                    surface.blit(prompt, (width // 2 - prompt.get_width() // 2, int(height * 0.8)))

        if self.hud_font:
            location = "HANGAR"
            for chunk in self.chunks:
                if chunk.label and self._point_in_chunk(chunk.id, self.position):
                    location = chunk.label
            hud = self.hud_font.render(location, True, (180, 220, 255))
            surface.blit(hud, (24, 24))

    def _point_in_chunk(self, chunk_id: str, position: Vector3) -> bool:
        chunk = self.door_manager.chunks.get(chunk_id)
        if not chunk:
            return False
        min_x, min_y, min_z = chunk.aabb_min
        max_x, max_y, max_z = chunk.aabb_max
        return (
            min_x <= position.x <= max_x
            and min_y <= position.y <= max_y
            and min_z <= position.z <= max_z
        )


__all__ = ["DoorState", "FirstPersonInteriorView", "SlidingDoorRuntime"]
