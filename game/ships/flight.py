"""Space-flight model."""
from __future__ import annotations

from math import radians
from typing import Optional

from pygame.math import Vector3

from .ship import Ship


LOOK_SENSITIVITY = 0.12
PASSIVE_DRAG = 0.12
STRAFE_DAMPING = 4.0
AUTO_LEVEL_RATE = 90.0
AUTO_INPUT_DEADZONE = 0.05


def _approach(current: float, target: float, rate: float) -> float:
    if current < target:
        current = min(target, current + rate)
    elif current > target:
        current = max(target, current - rate)
    return current


def update_ship_flight(ship: Ship, dt: float, logger=None) -> None:
    stats = ship.stats
    kin = ship.kinematics
    ctrl = ship.control

    # Update power regeneration and boost drain.
    if ctrl.boost and ship.power > 0.0:
        boost_target = stats.boost_speed
        ship.power = max(0.0, ship.power - stats.boost_drain * dt)
    else:
        boost_target = None
        ship.power = min(stats.power_cap, ship.power + stats.power_regen * dt)

    forward = kin.forward()
    right = kin.right()
    up = forward.cross(right)

    current_speed = kin.velocity.dot(forward)
    manual_input = ctrl.throttle
    if ship.auto_throttle_enabled and abs(manual_input) <= AUTO_INPUT_DEADZONE and not ctrl.brake:
        throttle_ratio = max(0.0, min(1.0, ship.auto_throttle_ratio))
    else:
        throttle_ratio = max(0.0, min(1.0, 0.5 + 0.5 * manual_input))
        if ship.auto_throttle_enabled:
            ship.auto_throttle_ratio = throttle_ratio
    if ctrl.brake and ship.auto_throttle_enabled:
        ship.disable_auto_throttle()
    target_speed = stats.max_speed * throttle_ratio
    if boost_target is not None:
        target_speed = boost_target
    if ctrl.brake:
        target_speed = 0.0

    speed_error = target_speed - current_speed
    accel = stats.acceleration if speed_error >= 0 else stats.acceleration * 0.5
    accel_step = max(-stats.acceleration, min(stats.acceleration, speed_error))
    kin.velocity += forward * accel_step * dt

    # Strafe control.
    desired_strafe = Vector3(
        ctrl.strafe.x * stats.strafe_cap,
        ctrl.strafe.y * stats.strafe_cap,
        0.0,
    )
    current_strafe = Vector3(
        kin.velocity.dot(right),
        kin.velocity.dot(up),
        0.0,
    )
    strafe_delta = desired_strafe - current_strafe
    kin.velocity += right * strafe_delta.x * min(1.0, stats.strafe_accel * dt)
    kin.velocity += up * strafe_delta.y * min(1.0, stats.strafe_accel * dt)
    kin.velocity -= (right * current_strafe.x + up * current_strafe.y) * min(1.0, STRAFE_DAMPING * dt)

    # Inertia compensation to align velocity with forward vector.
    vel_parallel = forward * kin.velocity.dot(forward)
    residual = kin.velocity - vel_parallel
    kin.velocity -= residual * min(1.0, stats.inertia_comp * dt)

    # Passive drag to keep speeds in check.
    kin.velocity -= kin.velocity * min(1.0, PASSIVE_DRAG * dt)

    # Update position.
    kin.position += kin.velocity * dt

    # Orientation updates from mouse deltas.
    desired_yaw_rate = ctrl.look_delta.x * LOOK_SENSITIVITY * stats.turn_rate
    desired_pitch_rate = -ctrl.look_delta.y * LOOK_SENSITIVITY * stats.turn_rate
    desired_roll_rate = ctrl.roll_input * stats.turn_rate * 0.5

    kin.angular_velocity.x = _approach(kin.angular_velocity.x, desired_pitch_rate, stats.turn_accel * dt)
    kin.angular_velocity.y = _approach(kin.angular_velocity.y, desired_yaw_rate, stats.turn_accel * dt)
    kin.angular_velocity.z = _approach(kin.angular_velocity.z, desired_roll_rate, stats.turn_accel * dt)

    kin.rotation.x = max(-85.0, min(85.0, kin.rotation.x + kin.angular_velocity.x * dt))
    kin.rotation.y = (kin.rotation.y + kin.angular_velocity.y * dt) % 360.0
    kin.rotation.z = (kin.rotation.z + kin.angular_velocity.z * dt) % 360.0

    if ship.auto_level_enabled and abs(ctrl.roll_input) <= AUTO_INPUT_DEADZONE:
        roll = ((kin.rotation.z + 180.0) % 360.0) - 180.0
        correction = max(-AUTO_LEVEL_RATE * dt, min(AUTO_LEVEL_RATE * dt, -roll))
        roll += correction
        kin.rotation.z = (roll + 360.0) % 360.0
        kin.angular_velocity.z = _approach(kin.angular_velocity.z, 0.0, stats.turn_accel * dt)

    ship.tick_cooldowns(dt)
    if ship.hull_regen_cooldown > 0.0:
        ship.hull_regen_cooldown = max(0.0, ship.hull_regen_cooldown - dt)
    else:
        ship.hull = min(ship.stats.hull_hp, ship.hull + ship.stats.hull_regen * dt)
    ship.boost_meter = ship.power


__all__ = ["update_ship_flight"]
