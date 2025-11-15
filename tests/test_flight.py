from __future__ import annotations

import sys
from pathlib import Path

from pygame.math import Vector3

sys.path.append(str(Path(__file__).resolve().parents[1]))

from game.ships.data import ShipFrame
from game.assets.content import ItemData
from game.ships.flight import (
    THRUSTER_SPEED_MULTIPLIER,
    effective_thruster_speed,
    update_ship_flight,
)
from game.ships.ship import Ship
from game.ships.stats import ShipSlotLayout, ShipStats


def _make_test_ship(
    max_speed: float, boost_speed: float, frame_id: str = "test_frame", **overrides
) -> Ship:
    stats = ShipStats(
        hull_points=1000.0,
        hull_recovery_per_sec=5.0,
        durability=200.0,
        armor_value=100.0,
        critical_defense=0.05,
        avoidance=0.05,
        avoidance_rating=50.0,
        avoidance_fading=0.75,
        speed=max_speed,
        boost_speed=boost_speed,
        acceleration=60.0,
        boost_acceleration=60.0,
        strafe_speed=25.0,
        strafe_acceleration=40.0,
        turn_rate=180.0,
        turn_accel=300.0,
        pitch_speed=180.0,
        yaw_speed=180.0,
        roll_speed=180.0,
        pitch_acceleration=300.0,
        yaw_acceleration=300.0,
        roll_acceleration=300.0,
        inertial_compensation=0.8,
        boost_cost=15.0,
        boost_consumes_power=False,
        power_points=150.0,
        power_recovery_per_sec=40.0,
        firewall_rating=120.0,
        emitter_rating=120.0,
        dradis_range_base=3000.0,
        dradis_range_max=3000.0,
        visual_range=800.0,
        ftl_range=10.0,
        ftl_charge_time=15.0,
        ftl_cooldown=25.0,
        ftl_cost=20.0,
        transponder_power_cost=0.0,
        durability_bonus=0.0,
        max_radiation_level=0.0,
        radioactive_decay=0.0,
        radioresistance=0.0,
    )
    for key, value in overrides.items():
        setattr(stats, key, value)
    slots = ShipSlotLayout(weapon_families={}, hull=0, engine=0, computer=0)
    frame = ShipFrame(
        id=frame_id,
        name="Test Frame",
        role="Interceptor",
        size="Strike",
        stats=stats,
        slots=slots,
        hardpoints=[],
    )
    ship = Ship(frame)
    ship.control.look_delta = Vector3()
    ship.control.strafe = Vector3()
    ship.control.roll_input = 0.0
    ship.control.brake = False
    ship.control.boost = False
    ship.kinematics.velocity = Vector3()
    return ship


def _advance(ship: Ship, dt: float, steps: int) -> None:
    for _ in range(steps):
        update_ship_flight(ship, dt)


def _forward_speed(ship: Ship) -> float:
    forward = ship.kinematics.basis.forward
    return ship.kinematics.velocity.dot(forward)


def _apply_yaw_turn(ship: Ship, dt: float = 0.1) -> float:
    ship.control.look_delta = Vector3(1.0, 0.0, 0.0)
    forward_before = ship.kinematics.forward()
    right_before = ship.kinematics.right()
    update_ship_flight(ship, dt)
    forward_after = ship.kinematics.forward()
    return forward_after.dot(right_before)


def test_thruster_speed_respects_lower_stat_limit() -> None:
    ship = _make_test_ship(max_speed=80.0, boost_speed=100.0)
    ship.control.throttle = 1.0
    _advance(ship, dt=0.1, steps=200)
    cruise_speed = _forward_speed(ship)

    ship.control.boost = True
    _advance(ship, dt=0.1, steps=400)
    boosted_speed = _forward_speed(ship)

    fallback_speed = ship.stats.speed * THRUSTER_SPEED_MULTIPLIER

    assert boosted_speed > cruise_speed
    assert boosted_speed <= ship.stats.boost_speed + 5.0
    assert boosted_speed < fallback_speed - 5.0


def test_thruster_speed_scales_with_higher_stat() -> None:
    ship = _make_test_ship(max_speed=80.0, boost_speed=170.0)
    ship.control.throttle = 1.0
    _advance(ship, dt=0.1, steps=200)

    ship.control.boost = True
    _advance(ship, dt=0.1, steps=700)
    boosted_speed = _forward_speed(ship)
    fallback_speed = ship.stats.speed * THRUSTER_SPEED_MULTIPLIER

    assert boosted_speed > fallback_speed + 5.0
    assert boosted_speed >= ship.stats.boost_speed * 0.8


def test_yaw_input_consistent_when_inverted() -> None:
    upright = _make_test_ship(max_speed=80.0, boost_speed=100.0)
    upright.auto_level_enabled = False
    upright_turn = _apply_yaw_turn(upright)
    assert upright_turn > 0.0

    inverted_roll = _make_test_ship(max_speed=80.0, boost_speed=100.0)
    inverted_roll.auto_level_enabled = False
    inverted_roll.kinematics.rotation = Vector3(0.0, 0.0, 180.0)
    roll_turn = _apply_yaw_turn(inverted_roll)
    assert roll_turn > 0.0

    inverted_pitch = _make_test_ship(max_speed=80.0, boost_speed=100.0)
    inverted_pitch.auto_level_enabled = False
    inverted_pitch.kinematics.rotation = Vector3(180.0, 0.0, 0.0)
    pitch_turn = _apply_yaw_turn(inverted_pitch)
    assert pitch_turn > 0.0


def test_thorim_boost_requires_engines() -> None:
    ship = _make_test_ship(
        max_speed=20.0,
        boost_speed=0.0,
        frame_id="thorim_siege",
        boost_speed_is_delta=True,
        boost_consumes_power=True,
        boost_cost=0.0,
    )
    base_tylium = ship.resources.tylium
    ship.control.throttle = 1.0
    ship.control.boost = True
    _advance(ship, dt=0.1, steps=100)
    flank_speed = ship.stats.speed * ship.stats.flank_speed_ratio
    assert _forward_speed(ship) <= flank_speed + 0.5
    assert ship.resources.tylium == base_tylium

    ship.frame.slots.engine = 3
    module = ItemData(
        id="thorim_siege_thrusters",
        slot_type="engine",
        name="Test Thorim Thruster",
        tags=["exclusive:thorim_siege"],
        stats={"boost_speed": 12.5, "boost_cost": 10.0, "boost_consumes_power": 1.0},
    )
    assert ship.equip_module(module)
    thruster_speed = effective_thruster_speed(ship.stats)
    assert abs(thruster_speed - (flank_speed + 12.5)) < 1e-6

    base_power = ship.power
    ship.control.boost = True
    ship.control.throttle = 1.0
    update_ship_flight(ship, dt=1.0)
    assert ship.power < base_power
    assert ship.resources.tylium == base_tylium
