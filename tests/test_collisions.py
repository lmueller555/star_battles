import logging
from pathlib import Path

from pygame.math import Vector3

from game.assets.content import ContentManager
from game.engine.logger import DEFAULT_CHANNELS, GameLogger, LoggerConfig
from game.world.space import COLLISION_RADII, SpaceWorld
from game.ships.outpost_hull import OUTPOST_HULL_PROFILE, outpost_half_extents
from game.ships.ship import Ship


def _load_content() -> ContentManager:
    root = Path(__file__).resolve().parents[1]
    content = ContentManager(root / "game" / "assets")
    content.load()
    return content


def _quiet_logger() -> GameLogger:
    channels = {name: False for name in DEFAULT_CHANNELS}
    return GameLogger(LoggerConfig(level=logging.CRITICAL, channels=channels))


def _to_local(reference: Ship, position: Vector3) -> Vector3:
    basis = reference.kinematics.basis
    rel = position - reference.kinematics.position
    return Vector3(rel.dot(basis.right), rel.dot(basis.up), rel.dot(basis.forward))


def test_ship_collisions_reduce_durability_and_trigger_recoil() -> None:
    content = _load_content()
    logger = _quiet_logger()
    world = SpaceWorld(content.weapons, content.sector, content.stations, content.mining, logger)

    frame = content.ships.get("viper_mk_vii")
    ship_a = Ship(frame, team="player")
    ship_b = Ship(frame, team="enemy")
    ship_a.stats.inertia_comp = 0.0
    ship_b.stats.inertia_comp = 0.0

    ship_a.kinematics.position = Vector3(0.0, 0.0, 0.0)
    ship_b.kinematics.position = Vector3(10.0, 0.0, 0.0)
    ship_a.kinematics.velocity = Vector3(12.0, 0.0, 0.0)
    ship_b.kinematics.velocity = Vector3(-12.0, 0.0, 0.0)

    world.add_ship(ship_a)
    world.add_ship(ship_b)

    dur_a_before = ship_a.durability
    world.update(1 / 60)

    distance_after = ship_a.kinematics.position.distance_to(ship_b.kinematics.position)
    assert distance_after > 10.0
    assert ship_a.durability < dur_a_before
    assert ship_a.collision_recoil > 0.0


def test_outpost_skin_repels_lateral_intrusion() -> None:
    content = _load_content()
    logger = _quiet_logger()
    world = SpaceWorld(content.weapons, content.sector, content.stations, content.mining, logger)

    outpost_frame = content.ships.get("outpost_regular")
    interceptor_frame = content.ships.get("viper_mk_vii")
    outpost = Ship(outpost_frame, team="player")
    intruder = Ship(interceptor_frame, team="enemy")

    outpost.kinematics.position = Vector3(0.0, 0.0, 0.0)
    intruder.kinematics.velocity = Vector3(0.0, 0.0, 0.0)

    width_at_center, _ = outpost_half_extents(0.0)
    intruder_radius = COLLISION_RADII[interceptor_frame.size]
    local_start = Vector3(width_at_center * 0.6, 0.0, 0.0)
    intruder.kinematics.position = outpost.kinematics.position + outpost.kinematics.basis.right * local_start.x

    world.add_ship(outpost)
    world.add_ship(intruder)

    world.update(1 / 30)

    local_after = _to_local(outpost, intruder.kinematics.position)
    assert local_after.x >= width_at_center + intruder_radius - 1.5
    assert abs(local_after.y) < intruder_radius
    assert abs(local_after.z) < OUTPOST_HULL_PROFILE[-1].z * 0.25


def test_outpost_skin_repels_front_approach() -> None:
    content = _load_content()
    logger = _quiet_logger()
    world = SpaceWorld(content.weapons, content.sector, content.stations, content.mining, logger)

    outpost_frame = content.ships.get("outpost_regular")
    escort_frame = content.ships.get("viper_mk_vii")
    outpost = Ship(outpost_frame, team="player")
    escort = Ship(escort_frame, team="player")

    outpost.kinematics.position = Vector3(0.0, 0.0, 0.0)

    nose_z = OUTPOST_HULL_PROFILE[-1].z
    escort_radius = COLLISION_RADII[escort_frame.size]
    escort.kinematics.position = outpost.kinematics.position + outpost.kinematics.basis.forward * (nose_z + escort_radius * 0.5)

    world.add_ship(outpost)
    world.add_ship(escort)

    world.update(1 / 30)

    local_after = _to_local(outpost, escort.kinematics.position)
    assert local_after.z >= nose_z + escort_radius - 1e-3
    assert abs(local_after.x) < escort_radius * 0.5
    assert abs(local_after.y) < escort_radius * 0.5
