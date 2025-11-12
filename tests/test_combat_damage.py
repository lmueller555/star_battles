from pathlib import Path

import pytest
from pygame.math import Vector3

from game.assets.content import ContentManager
from game.engine.logger import DEFAULT_CHANNELS, GameLogger, LoggerConfig
from game.ships.ship import Ship
from game.world.space import SpaceWorld


def _load_content() -> ContentManager:
    root = Path(__file__).resolve().parents[1]
    content = ContentManager(root / "game" / "assets")
    content.load()
    return content


def _quiet_logger() -> GameLogger:
    channels = {name: False for name in DEFAULT_CHANNELS}
    return GameLogger(LoggerConfig(level=logging.CRITICAL, channels=channels))


def test_enemy_hits_reduce_player_hull_without_draining_power() -> None:
    content = _load_content()
    logger = _quiet_logger()
    world = SpaceWorld(content.weapons, content.sector, content.stations, content.mining, logger)

    enemy_frame = content.ships.get("viper_mk_vii")
    player_frame = content.ships.get("viper_mk_vii")

    enemy = Ship(enemy_frame, team="enemy")
    enemy.apply_default_loadout(content)
    player = Ship(player_frame, team="player")
    player.apply_default_loadout(content)

    enemy.kinematics.position = Vector3(0.0, 0.0, -400.0)
    enemy.kinematics.rotation = Vector3(0.0, 0.0, 0.0)
    player.kinematics.position = Vector3(0.0, 0.0, 0.0)

    world.add_ship(player)
    world.add_ship(enemy)

    enemy.power = 500.0
    player.power = 150.0

    initial_hull = player.hull
    initial_power = player.power

    mount = next(m for m in enemy.mounts if m.weapon_id)

    result = world.fire_mount(enemy, mount, player)

    assert result is not None and result.hit
    assert result.damage > 0.0
    assert player.hull == pytest.approx(initial_hull - result.damage)
    assert player.power == pytest.approx(initial_power)
