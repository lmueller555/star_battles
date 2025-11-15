"""Space-flight model."""
from __future__ import annotations

from math import radians
from typing import Optional

from pygame.math import Vector3

from .ship import Ship
from .stats import ShipStats


LOOK_SENSITIVITY = 0.12
PASSIVE_DRAG = 0.12
STRAFE_DAMPING = 4.0
AUTO_LEVEL_RATE = 90.0
AUTO_INPUT_DEADZONE = 0.05
THRUSTER_SPEED_MULTIPLIER = 1.5
THRUSTER_TYLIUM_DRAIN = 0.35
WORLD_UP = Vector3(0.0, 1.0, 0.0)


def _approach(current: float, target: float, rate: float) -> float:
    if current < target:
        current = min(target, current + rate)
    elif current > target:
        current = max(target, current - rate)
    return current


def effective_thruster_speed(stats: ShipStats) -> float:
    """Return the top speed achievable while boost thrusters are active."""

    base_speed = getattr(stats, "speed", 0.0)
    flank_ratio = getattr(stats, "flank_speed_ratio", 0.6)
    if getattr(stats, "boost_speed_is_delta", False):
        boost_bonus = max(0.0, getattr(stats, "boost_speed", 0.0))
        return base_speed * flank_ratio + boost_bonus
    boost_speed = getattr(stats, "boost_speed", 0.0)
    if boost_speed <= 0.0:
        boost_speed = base_speed * THRUSTER_SPEED_MULTIPLIER
    boost_speed = max(boost_speed, base_speed)
    return boost_speed


def update_ship_flight(ship: Ship, dt: float, logger=None) -> None:
    stats = ship.stats
    kin = ship.kinematics
    ctrl = ship.control

    # Regenerate ship power for other systems.
    ship.power = min(stats.power_points, ship.power + stats.power_recovery_per_sec * dt)

    # Thruster engagement and resource drain.
    thrusters_requested = bool(ctrl.boost)
    thrusters_active = False
    uses_power_thrusters = getattr(stats, "boost_consumes_power", False)
    boost_cost_rate = max(0.0, stats.boost_cost)
    if thrusters_requested:
        if uses_power_thrusters:
            drain = boost_cost_rate * dt
            if drain <= 0.0 or ship.power >= drain:
                if drain > 0.0:
                    ship.power = max(0.0, ship.power - drain)
                thrusters_active = True
        elif ship.resources.tylium > 0.0:
            tylium_drain_rate = boost_cost_rate if boost_cost_rate > 0.0 else THRUSTER_TYLIUM_DRAIN
            drain = tylium_drain_rate * dt
            if ship.resources.tylium >= drain:
                ship.resources.tylium -= drain
                thrusters_active = True
            else:
                ship.resources.tylium = 0.0
                thrusters_active = False
    if not thrusters_active:
        ctrl.boost = False

    forward = kin.forward()
    right = kin.right()
    up = kin.up()

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

    flank_ratio = max(0.0, min(1.0, ship.flank_speed_ratio))
    flank_speed = stats.speed * flank_ratio
    current_max_speed = flank_speed
    accel_value = stats.acceleration
    if thrusters_active:
        current_max_speed = effective_thruster_speed(stats)
        cruise_reference = max(1.0, stats.speed)
        accel_multiplier = current_max_speed / cruise_reference if cruise_reference > 0.0 else THRUSTER_SPEED_MULTIPLIER
        accel_value *= max(1.0, accel_multiplier)
    target_speed = current_max_speed * throttle_ratio
    if thrusters_active:
        target_speed = current_max_speed
    if ctrl.brake:
        target_speed = 0.0

    speed_error = target_speed - current_speed
    accel = accel_value if speed_error >= 0 else accel_value * 0.5
    accel_step = max(-accel_value, min(accel_value, speed_error))
    kin.velocity += forward * accel_step * dt

    # Strafe control.
    desired_strafe = Vector3(
        ctrl.strafe.x * stats.strafe_speed,
        ctrl.strafe.y * stats.strafe_speed,
        0.0,
    )
    current_strafe = Vector3(
        kin.velocity.dot(right),
        kin.velocity.dot(up),
        0.0,
    )
    strafe_delta = desired_strafe - current_strafe
    kin.velocity += right * strafe_delta.x * min(1.0, stats.strafe_acceleration * dt)
    kin.velocity += up * strafe_delta.y * min(1.0, stats.strafe_acceleration * dt)
    kin.velocity -= (right * current_strafe.x + up * current_strafe.y) * min(1.0, STRAFE_DAMPING * dt)

    # Inertia compensation to align velocity with forward vector.
    vel_parallel = forward * kin.velocity.dot(forward)
    residual = kin.velocity - vel_parallel
    kin.velocity -= residual * min(1.0, stats.inertial_compensation * dt)

    # Passive drag to keep speeds in check.
    kin.velocity -= kin.velocity * min(1.0, PASSIVE_DRAG * dt)

    # Update position.
    kin.position += kin.velocity * dt

    # Orientation updates from mouse deltas.
    desired_yaw_rate = ctrl.look_delta.x * LOOK_SENSITIVITY * stats.yaw_speed
    if up.dot(WORLD_UP) < 0.0:
        desired_yaw_rate = -desired_yaw_rate
    desired_pitch_rate = -ctrl.look_delta.y * LOOK_SENSITIVITY * stats.pitch_speed
    desired_roll_rate = ctrl.roll_input * stats.roll_speed * 0.5

    kin.angular_velocity.x = _approach(
        kin.angular_velocity.x, desired_pitch_rate, stats.pitch_acceleration * dt
    )
    kin.angular_velocity.y = _approach(
        kin.angular_velocity.y, desired_yaw_rate, stats.yaw_acceleration * dt
    )
    kin.angular_velocity.z = _approach(
        kin.angular_velocity.z, desired_roll_rate, stats.roll_acceleration * dt
    )

    kin.rotation.x = (kin.rotation.x + kin.angular_velocity.x * dt) % 360.0
    kin.rotation.y = (kin.rotation.y + kin.angular_velocity.y * dt) % 360.0
    kin.rotation.z = (kin.rotation.z + kin.angular_velocity.z * dt) % 360.0

    if ship.auto_level_enabled and abs(ctrl.roll_input) <= AUTO_INPUT_DEADZONE:
        roll = ((kin.rotation.z + 180.0) % 360.0) - 180.0
        correction = max(-AUTO_LEVEL_RATE * dt, min(AUTO_LEVEL_RATE * dt, -roll))
        roll += correction
        kin.rotation.z = (roll + 360.0) % 360.0
        kin.angular_velocity.z = _approach(
            kin.angular_velocity.z, 0.0, stats.roll_acceleration * dt
        )

    ship.thrusters_active = thrusters_active
    ship.tick_cooldowns(dt)
    if ship.hull_regen_cooldown > 0.0:
        ship.hull_regen_cooldown = max(0.0, ship.hull_regen_cooldown - dt)
    else:
        ship.hull = min(
            ship.stats.hull_points, ship.hull + ship.stats.hull_recovery_per_sec * dt
        )
    ship.boost_meter = ship.power if uses_power_thrusters else ship.resources.tylium


__all__ = ["effective_thruster_speed", "update_ship_flight"]
