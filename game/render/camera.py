"""Camera utilities."""
from __future__ import annotations

from math import radians, tan

from pygame.math import Vector3

from game.ships.ship import Ship


class ChaseCamera:
    def __init__(self, fov_deg: float, aspect: float) -> None:
        self.base_fov = fov_deg
        self.fov = fov_deg
        self.aspect = aspect
        self.position = Vector3(0.0, 0.0, -10.0)
        self.forward = Vector3(0.0, 0.0, 1.0)
        self.up = Vector3(0.0, 1.0, 0.0)
        self.right = Vector3(1.0, 0.0, 0.0)
        self.distance = 12.0
        self.height = 3.0
        self.shoulder = 1.6
        self.recoil = 0.0
        self.recoil_decay = 6.0

    def update(self, ship: Ship, dt: float) -> None:
        ship_forward = ship.kinematics.forward()
        ship_up = ship_forward.cross(ship.kinematics.right()).normalize()
        target_pos = (
            ship.kinematics.position
            - ship_forward * self.distance
            + ship_up * self.height
            + ship.kinematics.right() * self.shoulder
        )
        self.position += (target_pos - self.position) * min(1.0, 5.0 * dt)
        self.forward += (ship_forward - self.forward) * min(1.0, 6.0 * dt)
        self.forward = self.forward.normalize()
        self.right = self.forward.cross(ship_up).normalize()
        self.up = self.right.cross(self.forward).normalize()
        speed = ship.kinematics.velocity.length()
        self.fov = min(self.base_fov + speed * 0.12, self.base_fov + 25.0)
        if self.recoil > 0.0:
            self.position -= self.forward * self.recoil
            self.recoil = max(0.0, self.recoil - self.recoil_decay * dt)

    def apply_recoil(self, strength: float) -> None:
        self.recoil += strength

    def project(self, point: Vector3, screen_size: tuple[int, int]) -> tuple[Vector3, bool]:
        rel = point - self.position
        depth = rel.dot(self.forward)
        if depth <= 0.1:
            return Vector3(), False
        x = rel.dot(self.right)
        y = rel.dot(self.up)
        f = 1.0 / tan(radians(self.fov) / 2.0)
        ndc_x = (x * f / self.aspect) / depth
        ndc_y = (y * f) / depth
        screen_x = (ndc_x * 0.5 + 0.5) * screen_size[0]
        screen_y = (-ndc_y * 0.5 + 0.5) * screen_size[1]
        return Vector3(screen_x, screen_y, depth), True


__all__ = ["ChaseCamera"]
