import json
import sys
from pathlib import Path

from pygame.math import Vector3

sys.path.append(str(Path(__file__).resolve().parents[1]))

from game.assets.content import ItemData
from game.combat.weapons import Projectile, WeaponData, WeaponDatabase
from game.engine.logger import GameLogger, LoggerConfig
from game.ships.data import Hardpoint, ShipFrame
from game.ships.ship import Ship
from game.ships.stats import ShipSlotLayout, ShipStats
from game.world.mining import MiningDatabase
from game.world.sector import SectorMap
from game.world.space import SpaceWorld
from game.world.station import StationDatabase


def make_logger() -> GameLogger:
    return GameLogger(LoggerConfig(level=0, channels={}))


def test_activate_countermeasure_intercepts_and_breaks_lock(tmp_path):
    sector_path = tmp_path / "sector.json"
    sector_path.write_text(json.dumps([
        {"id": "alpha", "position": [0.0, 0.0], "threat": False}
    ]))
    sector = SectorMap()
    sector.load(sector_path)
    stations = StationDatabase()
    mining = MiningDatabase()
    weapons = WeaponDatabase()
    logger = make_logger()
    world = SpaceWorld(weapons, sector, stations, mining, logger)

    stats = ShipStats.from_dict({
        "power_cap": 100,
        "power_regen": 10,
        "dradis_range": 3000,
    })
    slots = ShipSlotLayout.from_dict({"computer": 1})
    hardpoint = Hardpoint("hp", "cannon", Vector3(), 20.0, 180.0)
    frame = ShipFrame("test", "Test", "Interceptor", "Strike", stats, slots, [hardpoint])
    ship = Ship(frame)
    module = ItemData(
        id="flare_launcher_mk1",
        slot_type="computer",
        name="Flare Launcher",
        tags=["COUNTERMEASURE"],
        stats={
            "cm_radius": 600,
            "cm_lock_break": 1.0,
            "cm_power": 5,
            "cm_cooldown": 4,
        },
    )
    ship.equip_module(module)
    ship.lock_progress = 0.9
    ship.power = 50
    world.add_ship(ship)

    missile = WeaponData.from_dict({
        "id": "test_missile",
        "slotType": "launcher",
        "class": "missile",
        "damageMin": 100,
        "damageMax": 100,
        "accuracy": 1.0,
        "crit": 0.0,
        "critMult": 1.0,
        "rof": 1.0,
        "power": 0,
        "optimal": 800,
        "maxRange": 1200,
        "projectileSpeed": 200,
        "gimbal": 30,
        "ammo": 1,
        "reload": 1.0,
    })
    projectile = Projectile(
        weapon=missile,
        position=Vector3(0.0, 0.0, 300.0),
        velocity=Vector3(0.0, 0.0, -50.0),
        target_id=id(ship),
        ttl=5.0,
        team="enemy",
        damage=missile.damage_max,
    )
    world.projectiles.append(projectile)

    success, message = world.activate_countermeasure(ship)
    assert success is True
    assert "intercepted" in message
    assert len(world.projectiles) == 0
    assert ship.lock_progress < 0.9
    assert ship.countermeasure_cooldown > 0.0
    assert ship.power == 45

    success_again, message_again = world.activate_countermeasure(ship)
    assert success_again is False
    assert "recharging" in message_again


def test_hardpoint_group_defaults_primary():
    data = {
        "id": "test",
        "name": "Test Hull",
        "role": "Interceptor",
        "size": "Strike",
        "stats": {},
        "slots": {"cannon": 1},
        "hardpoints": [
            {"id": "hp1", "slot": "cannon", "position": [0.0, 0.0, 0.0]}
        ],
    }
    frame = ShipFrame.from_dict(data)
    assert frame.hardpoints[0].group == "primary"
