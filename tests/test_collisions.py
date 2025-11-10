import logging
from pathlib import Path

from pygame.math import Vector3

from game.assets.content import ContentManager
from game.engine.logger import DEFAULT_CHANNELS, GameLogger, LoggerConfig
from game.world.space import SpaceWorld
from game.ships.ship import Ship


def _load_content() -> ContentManager:
    root = Path(__file__).resolve().parents[1]
    content = ContentManager(root / "game" / "assets")
    content.load()
    return content


def _quiet_logger() -> GameLogger:
    channels = {name: False for name in DEFAULT_CHANNELS}
    return GameLogger(LoggerConfig(level=logging.CRITICAL, channels=channels))


def test_ship_collisions_reduce_durability_and_trigger_recoil() -> None:
    content = _load_content()
    logger = _quiet_logger()
    world = SpaceWorld(content.weapons, content.sector, content.stations, content.mining, logger)

    frame = content.ships.get("interceptor_mk1")
    ship_a = Ship(frame, team="player")
    ship_b = Ship(frame, team="enemy")

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
