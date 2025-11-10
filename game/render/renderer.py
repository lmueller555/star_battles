"""Vector renderer built on pygame."""
from __future__ import annotations

from math import ceil, floor
import math
import random
from typing import Iterable

import pygame
from pygame.math import Vector3

from game.combat.weapons import Projectile
from game.render.camera import ChaseCamera
from game.ships.ship import Ship
from game.world.asteroids import Asteroid

BACKGROUND = (5, 8, 12)
GRID_MINOR_COLOR = (20, 32, 44)
GRID_MAJOR_COLOR = (34, 52, 72)
SHIP_COLOR = (120, 220, 255)
ENEMY_COLOR = (255, 80, 100)
PROJECTILE_COLOR = (255, 200, 80)
MISSILE_COLOR = (255, 140, 60)


def _blend(color_a: tuple[int, int, int], color_b: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    amount = max(0.0, min(1.0, amount))
    return tuple(
        int(round(a + (b - a) * amount))
        for a, b in zip(color_a, color_b)
    )


def _darken(color: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    return _blend(color, (0, 0, 0), amount)


def _lighten(color: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    return _blend(color, (255, 255, 255), amount)


def _ship_axes(ship: Ship) -> tuple[Vector3, Vector3, Vector3]:
    forward = ship.kinematics.forward()
    right = ship.kinematics.right()
    up = right.cross(forward)
    if up.length_squared() == 0.0:
        up = Vector3(0.0, 1.0, 0.0)
    else:
        up = up.normalize()
    return right.normalize(), up, forward.normalize()


def _build_outpost_wireframe() -> list[tuple[Vector3, Vector3]]:
    """Construct a multi-tiered station silhouette for Outposts."""

    segments: list[tuple[Vector3, Vector3]] = []

    def _loop_segments(points: list[Vector3]) -> None:
        for index in range(len(points)):
            start = points[index]
            end = points[(index + 1) % len(points)]
            segments.append((start, end))

    core_radius = 140.0
    core_heights = [-160.0, 0.0, 160.0]
    previous_level: list[Vector3] | None = None
    for height in core_heights:
        corners = [
            Vector3( core_radius, height,  core_radius),
            Vector3(-core_radius, height,  core_radius),
            Vector3(-core_radius, height, -core_radius),
            Vector3( core_radius, height, -core_radius),
        ]
        _loop_segments(corners)
        segments.append((corners[0], corners[2]))
        segments.append((corners[1], corners[3]))
        if previous_level is not None:
            for upper, lower in zip(previous_level, corners):
                segments.append((upper, lower))
        previous_level = corners

    segments.append((Vector3(0.0, -240.0, 0.0), Vector3(0.0, 240.0, 0.0)))
    segments.append((Vector3(-core_radius, 0.0, 0.0), Vector3(core_radius, 0.0, 0.0)))
    segments.append((Vector3(0.0, 0.0, -core_radius), Vector3(0.0, 0.0, core_radius)))

    outer_radius = 420.0
    top_height = 210.0
    bottom_height = -210.0
    outer_points: list[Vector3] = []
    for step in range(8):
        angle = step * (math.pi / 4.0)
        outer_points.append(
            Vector3(
                math.cos(angle) * outer_radius,
                0.0,
                math.sin(angle) * outer_radius,
            )
        )

    _loop_segments(outer_points)
    for point in outer_points:
        segments.append((Vector3(0.0, 0.0, 0.0), point))

    top_points = [Vector3(point.x, top_height, point.z) for point in outer_points]
    bottom_points = [Vector3(point.x, bottom_height, point.z) for point in outer_points]
    _loop_segments(top_points)
    _loop_segments(bottom_points)
    for mid, top, bottom in zip(outer_points, top_points, bottom_points):
        segments.append((mid, top))
        segments.append((mid, bottom))
        segments.append((top, bottom))

    for offset in range(4):
        segments.append((top_points[offset], top_points[(offset + 4) % 8]))
        segments.append((bottom_points[offset], bottom_points[(offset + 4) % 8]))

    dock_extension = 560.0
    dock_height = 90.0
    dock_span = 120.0

    def _add_dock(axis: str, sign: float) -> None:
        if axis == "x":
            base = Vector3(sign * outer_radius, 0.0, 0.0)
            tip = Vector3(sign * dock_extension, 0.0, 0.0)
            offsets = [
                Vector3(0.0, dock_height, dock_span),
                Vector3(0.0, dock_height, -dock_span),
                Vector3(0.0, -dock_height, -dock_span),
                Vector3(0.0, -dock_height, dock_span),
            ]
        else:
            base = Vector3(0.0, 0.0, sign * outer_radius)
            tip = Vector3(0.0, 0.0, sign * dock_extension)
            offsets = [
                Vector3(dock_span, dock_height, 0.0),
                Vector3(-dock_span, dock_height, 0.0),
                Vector3(-dock_span, -dock_height, 0.0),
                Vector3(dock_span, -dock_height, 0.0),
            ]

        outer_frame = [base + offset for offset in offsets]
        inner_frame = [tip + offset for offset in offsets]
        _loop_segments(outer_frame)
        _loop_segments(inner_frame)
        for inner, outer in zip(inner_frame, outer_frame):
            segments.append((inner, outer))
        for corner in outer_frame:
            segments.append((corner, base))
        for corner in inner_frame:
            segments.append((corner, tip))
        segments.append((base, tip))

    for axis in ("x", "z"):
        for sign in (-1.0, 1.0):
            _add_dock(axis, sign)

    return segments


WIREFRAMES = {
    "Strike": [
        (Vector3(0, 0.3, 2.5), Vector3(0.9, 0, -2.0)),
        (Vector3(0, 0.3, 2.5), Vector3(-0.9, 0, -2.0)),
        (Vector3(0, -0.3, 2.5), Vector3(0.9, 0, -2.0)),
        (Vector3(0, -0.3, 2.5), Vector3(-0.9, 0, -2.0)),
        (Vector3(0.9, 0, -2.0), Vector3(-0.9, 0, -2.0)),
        (Vector3(0.9, 0, -2.0), Vector3(0, 0.3, 2.5)),
    ],
    "Line": [
        (Vector3(0, 0.6, 3.5), Vector3(1.4, 0, -3.5)),
        (Vector3(0, 0.6, 3.5), Vector3(-1.4, 0, -3.5)),
        (Vector3(0, -0.6, 3.5), Vector3(1.4, 0, -3.5)),
        (Vector3(0, -0.6, 3.5), Vector3(-1.4, 0, -3.5)),
        (Vector3(1.4, 0, -3.5), Vector3(-1.4, 0, -3.5)),
        (Vector3(1.4, 0, -3.5), Vector3(0, 0.6, 3.5)),
    ],
    "Outpost": _build_outpost_wireframe(),
}


class VectorRenderer:
    def __init__(self, surface: pygame.Surface) -> None:
        self.surface = surface

    def clear(self) -> None:
        self.surface.fill(BACKGROUND)

    def draw_grid(
        self,
        camera: ChaseCamera,
        focus: Vector3,
        *,
        tile_size: float = 220.0,
        extent: float = 3600.0,
        height_offset: float = -18.0,
    ) -> None:
        """Render a tiled reference grid beneath the focus point."""

        if tile_size <= 0.0 or extent <= 0.0:
            return

        half_extent = extent * 0.5
        grid_y = focus.y + height_offset
        screen_size = self.surface.get_size()

        start_x = int(floor((focus.x - half_extent) / tile_size))
        end_x = int(ceil((focus.x + half_extent) / tile_size))
        start_z = int(floor((focus.z - half_extent) / tile_size))
        end_z = int(ceil((focus.z + half_extent) / tile_size))

        def _draw_segment(a: Vector3, b: Vector3, color: tuple[int, int, int]) -> None:
            a_screen, vis_a = camera.project(a, screen_size)
            b_screen, vis_b = camera.project(b, screen_size)
            if vis_a and vis_b:
                pygame.draw.aaline(
                    self.surface,
                    color,
                    (a_screen.x, a_screen.y),
                    (b_screen.x, b_screen.y),
                    blend=1,
                )

        for xi in range(start_x, end_x + 1):
            x_world = xi * tile_size
            color = GRID_MAJOR_COLOR if xi % 5 == 0 else GRID_MINOR_COLOR
            a = Vector3(x_world, grid_y, start_z * tile_size)
            b = Vector3(x_world, grid_y, end_z * tile_size)
            _draw_segment(a, b, color)

        for zi in range(start_z, end_z + 1):
            z_world = zi * tile_size
            color = GRID_MAJOR_COLOR if zi % 5 == 0 else GRID_MINOR_COLOR
            a = Vector3(start_x * tile_size, grid_y, z_world)
            b = Vector3(end_x * tile_size, grid_y, z_world)
            _draw_segment(a, b, color)

    def draw_asteroids(self, camera: ChaseCamera, asteroids: Iterable[Asteroid]) -> None:
        screen_size = self.surface.get_size()

        def _screen_radius(center: Vector3, world_point: Vector3) -> int:
            other, visible = camera.project(world_point, screen_size)
            if not visible:
                return 0
            delta = Vector3(other.x - center.x, other.y - center.y, 0.0)
            return int(max(0.0, delta.length()))

        for asteroid in asteroids:
            center, visible = camera.project(asteroid.position, screen_size)
            if not visible:
                continue

            radius_vectors = [
                asteroid.position + camera.up * asteroid.radius,
                asteroid.position - camera.up * asteroid.radius,
                asteroid.position + camera.right * asteroid.radius,
                asteroid.position - camera.right * asteroid.radius,
            ]
            radii = [
                _screen_radius(center, vector)
                for vector in radius_vectors
            ]
            radius_vertical = max(radii[0], radii[1])
            radius_horizontal = max(radii[2], radii[3])
            if radius_vertical <= 0 and radius_horizontal <= 0:
                radius_vertical = radius_horizontal = 2
            radius_vertical = max(2, radius_vertical)
            radius_horizontal = max(2, radius_horizontal)

            color = asteroid.display_color
            rng = random.Random(asteroid.id)
            point_count = rng.randint(8, 14)
            jaggedness = 0.45
            points: list[tuple[int, int]] = []
            angle_step = (2.0 * math.pi) / point_count
            distortion = 0.75
            for i in range(point_count):
                angle = i * angle_step
                offset = 1.0 - jaggedness + rng.random() * jaggedness * 2.0
                horizontal = radius_horizontal * (distortion + rng.random() * (1.0 - distortion))
                vertical = radius_vertical * (distortion + rng.random() * (1.0 - distortion))
                x = center.x + math.cos(angle) * horizontal * offset
                y = center.y + math.sin(angle) * vertical * offset
                points.append((int(round(x)), int(round(y))))

            if len(points) >= 3:
                pygame.draw.polygon(self.surface, color, points)

                outline_color = _darken(color, 0.45)
                pygame.draw.polygon(self.surface, outline_color, points, 1)

                if radius_horizontal > 3 or radius_vertical > 3:
                    highlight_color = _lighten(color, 0.5)
                    shadow_color = _darken(color, 0.6)

                    accent_count = rng.randint(3, 6)
                    for _ in range(accent_count):
                        angle = rng.uniform(0.0, 2.0 * math.pi)
                        distance = rng.uniform(0.1, 0.8)
                        accent_radius = max(1, int(round((radius_horizontal + radius_vertical) * 0.05)))
                        px = center.x + math.cos(angle) * radius_horizontal * distance * rng.uniform(0.6, 1.0)
                        py = center.y + math.sin(angle) * radius_vertical * distance * rng.uniform(0.6, 1.0)
                        color_choice = highlight_color if rng.random() > 0.5 else shadow_color
                        pygame.draw.circle(
                            self.surface,
                            color_choice,
                            (int(round(px)), int(round(py))),
                            accent_radius,
                        )

                    crater_count = rng.randint(2, 4)
                    crater_fill = _darken(color, 0.55)
                    crater_rim = _lighten(color, 0.2)
                    for _ in range(crater_count):
                        angle = rng.uniform(0.0, 2.0 * math.pi)
                        distance = rng.uniform(0.15, 0.65)
                        crater_radius = max(1, int(round((radius_horizontal + radius_vertical) * rng.uniform(0.04, 0.12))))
                        px = center.x + math.cos(angle) * radius_horizontal * distance
                        py = center.y + math.sin(angle) * radius_vertical * distance
                        pygame.draw.circle(
                            self.surface,
                            crater_fill,
                            (int(round(px)), int(round(py))),
                            crater_radius,
                        )
                        pygame.draw.circle(
                            self.surface,
                            crater_rim,
                            (int(round(px)), int(round(py))),
                            crater_radius,
                            1,
                        )

    def draw_ship(self, camera: ChaseCamera, ship: Ship) -> None:
        right, up, forward = _ship_axes(ship)
        color = SHIP_COLOR if ship.team == "player" else ENEMY_COLOR
        edges = WIREFRAMES.get(ship.frame.size, WIREFRAMES["Strike"])
        origin = ship.kinematics.position
        for a_local, b_local in edges:
            a_world = origin + right * a_local.x + up * a_local.y + forward * a_local.z
            b_world = origin + right * b_local.x + up * b_local.y + forward * b_local.z
            a_screen, vis_a = camera.project(a_world, self.surface.get_size())
            b_screen, vis_b = camera.project(b_world, self.surface.get_size())
            if vis_a and vis_b:
                pygame.draw.aaline(
                    self.surface,
                    color,
                    (a_screen.x, a_screen.y),
                    (b_screen.x, b_screen.y),
                    blend=1,
                )

    def draw_projectiles(self, camera: ChaseCamera, projectiles: Iterable[Projectile]) -> None:
        for projectile in projectiles:
            color = MISSILE_COLOR if projectile.weapon.wclass == "missile" else PROJECTILE_COLOR
            screen_pos, visible = camera.project(projectile.position, self.surface.get_size())
            if visible:
                pygame.draw.circle(self.surface, color, (int(screen_pos.x), int(screen_pos.y)), 3, 1)


__all__ = ["VectorRenderer"]
