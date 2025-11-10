"""Vector renderer built on pygame."""
from __future__ import annotations

from math import ceil, floor
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


def _ship_axes(ship: Ship) -> tuple[Vector3, Vector3, Vector3]:
    forward = ship.kinematics.forward()
    right = ship.kinematics.right()
    up = right.cross(forward)
    if up.length_squared() == 0.0:
        up = Vector3(0.0, 1.0, 0.0)
    else:
        up = up.normalize()
    return right.normalize(), up, forward.normalize()


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
                asteroid.position + camera.right * asteroid.radius,
                asteroid.position - camera.up * asteroid.radius,
                asteroid.position - camera.right * asteroid.radius,
            ]
            radii = [
                _screen_radius(center, vector)
                for vector in radius_vectors
            ]
            radius = max(radii)
            if radius <= 0:
                radius = 2
            color = asteroid.display_color
            pygame.draw.circle(
                self.surface,
                color,
                (int(center.x), int(center.y)),
                radius,
            )
            pygame.draw.circle(
                self.surface,
                (60, 40, 24),
                (int(center.x), int(center.y)),
                radius,
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
