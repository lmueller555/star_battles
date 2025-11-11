"""Camera utilities."""
from __future__ import annotations

from math import radians, tan
from typing import Optional

from pygame.math import Vector3

from game.ships.ship import Ship


def _approach(value: float, target: float, rate: float) -> float:
    if value < target:
        return min(target, value + rate)
    if value > target:
        return max(target, value - rate)
    return value


def _lerp_vector(a: Vector3, b: Vector3, t: float) -> Vector3:
    """Linear interpolate between two vectors with clamped factor."""
    t = max(0.0, min(1.0, t))
    return a + (b - a) * t


class ChaseCamera:
    """Third-person chase camera with freelook, look-ahead, and lock framing."""

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
        self.freelook_angles = Vector3(0.0, 0.0, 0.0)
        self.freelook_sensitivity = 0.12
        self.freelook_max_yaw = 28.0
        self.freelook_max_pitch = 18.0
        self.freelook_return = 80.0
        self.freelook_snap_delay = 3.0
        self.look_ahead_distance = 0.0
        self.look_ahead_direction = Vector3(0.0, 0.0, 1.0)
        self.look_ahead_response = 4.0
        self.look_ahead_factor = 0.03
        self.look_ahead_max = 12.0
        self.lock_blend = 0.0
        self.lock_response = 4.0
        self.lock_side_offset = 3.0
        self.lock_back_offset = 4.5
        self.lock_up_offset = 1.4
        self.lock_zoom_min = max(15.0, fov_deg - 6.0)
        self.lock_zoom_max = fov_deg + 18.0
        self.lock_zoom_rate = 5.0
        self._lock_direction = Vector3(0.0, 0.0, 1.0)
        self._lock_distance = 0.0
        self._freelook_idle_time = 0.0

    def update(
        self,
        ship: Ship,
        dt: float,
        freelook_active: bool = False,
        freelook_delta: tuple[float, float] = (0.0, 0.0),
        target: Optional[Ship] = None,
        lock_mode: bool = False,
    ) -> None:
        ship_forward = ship.kinematics.forward()
        ship_right = ship.kinematics.right()
        ship_up = ship_forward.cross(ship_right).normalize()

        if freelook_active:
            yaw_delta = freelook_delta[0] * self.freelook_sensitivity
            pitch_delta = freelook_delta[1] * self.freelook_sensitivity
            self._freelook_idle_time = 0.0
            self.freelook_angles.y = max(
                -self.freelook_max_yaw,
                min(self.freelook_max_yaw, self.freelook_angles.y + yaw_delta),
            )
            self.freelook_angles.x = max(
                -self.freelook_max_pitch,
                min(self.freelook_max_pitch, self.freelook_angles.x + pitch_delta),
            )
        else:
            self._freelook_idle_time += dt
            if (
                self._freelook_idle_time >= self.freelook_snap_delay
                and (abs(self.freelook_angles.x) > 1e-3 or abs(self.freelook_angles.y) > 1e-3)
            ):
                self.freelook_angles.x = 0.0
                self.freelook_angles.y = 0.0
            self.freelook_angles.y = _approach(
                self.freelook_angles.y,
                0.0,
                self.freelook_return * dt,
            )
            self.freelook_angles.x = _approach(
                self.freelook_angles.x,
                0.0,
                self.freelook_return * dt,
            )
            if abs(self.freelook_angles.x) <= 1e-3 and abs(self.freelook_angles.y) <= 1e-3:
                self._freelook_idle_time = 0.0

        focus_forward = ship_forward
        focus_right = ship_right
        focus_up = ship_up
        if abs(self.freelook_angles.y) > 1e-3:
            focus_forward = focus_forward.rotate(ship_up, -self.freelook_angles.y)
            focus_right = focus_right.rotate(ship_up, -self.freelook_angles.y)
        if abs(self.freelook_angles.x) > 1e-3:
            focus_forward = focus_forward.rotate(focus_right, self.freelook_angles.x)
            focus_up = focus_up.rotate(focus_right, self.freelook_angles.x)

        focus_forward = focus_forward.normalize()
        focus_right = focus_forward.cross(focus_up).normalize()
        focus_up = focus_right.cross(focus_forward).normalize()

        lock_direction = self._lock_direction
        lock_distance = self._lock_distance
        lock_active = bool(lock_mode and target is not None and target.is_alive())
        if lock_active:
            to_target = target.kinematics.position - ship.kinematics.position
            lock_distance = to_target.length()
            if lock_distance > 1e-3:
                lock_direction = to_target.normalize()
            else:
                lock_distance = 0.0
                lock_direction = focus_forward
            self._lock_direction = lock_direction
            self._lock_distance = lock_distance
        else:
            lock_distance = _approach(lock_distance, 0.0, self.lock_response * dt)
            self._lock_distance = lock_distance

        self.lock_blend = _approach(self.lock_blend, 1.0 if lock_active else 0.0, self.lock_response * dt)

        base_target_pos = (
            ship.kinematics.position
            - focus_forward * self.distance
            + focus_up * self.height
            + focus_right * self.shoulder
        )
        lock_target_pos = base_target_pos
        if lock_distance > 0.0:
            side_sign = 1.0 if focus_right.dot(lock_direction) >= 0 else -1.0
            lateral_scale = min(1.0, lock_distance / 900.0)
            back_scale = min(1.0, lock_distance / 600.0)
            height_scale = min(1.0, lock_distance / 800.0)
            lock_target_pos = (
                base_target_pos
                + focus_right * (self.lock_side_offset * lateral_scale * side_sign)
                - focus_forward * (self.lock_back_offset * back_scale)
                + focus_up * (self.lock_up_offset * 0.5 * height_scale)
            )
        target_pos = _lerp_vector(base_target_pos, lock_target_pos, self.lock_blend)
        self.position += (target_pos - self.position) * min(1.0, 10.0 * dt)

        velocity = ship.kinematics.velocity
        speed = velocity.length()
        if speed > 1.0:
            self.look_ahead_direction = velocity.normalize()
        desired_look_ahead = min(self.look_ahead_max, speed * self.look_ahead_factor)
        self.look_ahead_distance += (desired_look_ahead - self.look_ahead_distance) * min(
            1.0, self.look_ahead_response * dt
        )
        base_focus_point = (
            ship.kinematics.position
            + focus_forward * (self.distance * 0.2)
            + self.look_ahead_direction * self.look_ahead_distance
        )
        lock_focus_point = base_focus_point
        if lock_distance > 0.0:
            midpoint = ship.kinematics.position + lock_direction * (lock_distance * 0.5)
            lock_focus_point = midpoint + focus_up * self.lock_up_offset
            lock_focus_point += lock_direction * min(6.0, lock_distance * 0.3)
            lock_focus_point += self.look_ahead_direction * (self.look_ahead_distance * 0.4)
        focus_point = _lerp_vector(base_focus_point, lock_focus_point, self.lock_blend)

        desired_forward = focus_point - self.position
        if desired_forward.length_squared() > 1e-6:
            desired_forward = desired_forward.normalize()
            self.forward += (desired_forward - self.forward) * min(1.0, 6.0 * dt)
            self.forward = self.forward.normalize()

        desired_up = focus_up
        self.up += (desired_up - self.up) * min(1.0, 5.0 * dt)
        if self.up.length_squared() > 1e-6:
            self.up = self.up.normalize()
        self.right = self.forward.cross(self.up)
        if self.right.length_squared() > 1e-6:
            self.right = self.right.normalize()
            self.up = self.right.cross(self.forward).normalize()

        base_fov = self.base_fov
        desired_fov = base_fov
        if lock_distance > 0.0:
            distance_ratio = min(1.0, lock_distance / 1200.0)
            lock_fov_target = self.lock_zoom_min + (self.lock_zoom_max - self.lock_zoom_min) * distance_ratio
            desired_fov = base_fov * (1.0 - self.lock_blend) + lock_fov_target * self.lock_blend
        self.fov += (desired_fov - self.fov) * min(1.0, self.lock_zoom_rate * dt)

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
