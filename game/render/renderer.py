"""Vector renderer built on pygame."""
from __future__ import annotations

from math import cos, radians, sin
from typing import Iterable, List, Sequence

import pygame
from pygame.math import Vector3

from game.combat.weapons import Projectile
from game.render.camera import ChaseCamera
from game.ships.ship import Ship

BACKGROUND = (5, 8, 12)
SHIP_COLOR = (120, 220, 255)
ENEMY_COLOR = (255, 80, 100)
PROJECTILE_COLOR = (255, 200, 80)
MISSILE_COLOR = (255, 140, 60)


def _rotation_matrix(rotation: Vector3) -> List[List[float]]:
    pitch, yaw, roll = map(radians, (rotation.x, rotation.y, rotation.z))
    cp, sp = cos(pitch), sin(pitch)
    cy, sy = cos(yaw), sin(yaw)
    cr, sr = cos(roll), sin(roll)
    return [
        [cy * cr + sy * sp * sr, sr * cp, cy * -sr + sy * sp * cr],
        [-sy * cr + cy * sp * sr, cr * cp, -sy * -sr + cy * sp * cr],
        [sy * cp, -sp, cy * cp],
    ]


def _apply_transform(point: Vector3, matrix: Sequence[Sequence[float]]) -> Vector3:
    return Vector3(
        matrix[0][0] * point.x + matrix[0][1] * point.y + matrix[0][2] * point.z,
        matrix[1][0] * point.x + matrix[1][1] * point.y + matrix[1][2] * point.z,
        matrix[2][0] * point.x + matrix[2][1] * point.y + matrix[2][2] * point.z,
    )


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

    def draw_ship(self, camera: ChaseCamera, ship: Ship) -> None:
        matrix = _rotation_matrix(ship.kinematics.rotation)
        color = SHIP_COLOR if ship.team == "player" else ENEMY_COLOR
        edges = WIREFRAMES.get(ship.frame.size, WIREFRAMES["Strike"])
        for a_local, b_local in edges:
            a_world = ship.kinematics.position + _apply_transform(a_local, matrix)
            b_world = ship.kinematics.position + _apply_transform(b_local, matrix)
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
