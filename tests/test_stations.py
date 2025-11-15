import json

from pygame.math import Vector3

from game.combat.weapons import WeaponData, WeaponDatabase
from game.engine.logger import GameLogger, LoggerConfig
from game.ships.data import Hardpoint, ShipFrame
from game.ships.ship import Ship
from game.ships.stats import ShipSlotLayout, ShipStats
from game.world.sector import SectorMap
from game.world.space import SpaceWorld
from game.world.mining import MiningDatabase
from game.world.station import StationDatabase


def make_logger() -> GameLogger:
    return GameLogger(LoggerConfig(level=0, channels={}))


def make_frame(frame_id: str, *, role: str = "Interceptor", size: str = "Strike") -> ShipFrame:
    stats = ShipStats.from_dict({})
    slots = ShipSlotLayout.from_dict({})
    return ShipFrame(
        id=frame_id,
        name=frame_id.title(),
        role=role,
        size=size,
        stats=stats,
        slots=slots,
        hardpoints=[],
    )


def test_station_database_nearest(tmp_path):
    data = [
        {"id": "a", "system": "alpha", "position": [0, 0, 0], "dockingRadius": 900},
        {"id": "b", "system": "alpha", "position": [200, 0, 0], "dockingRadius": 900},
        {"id": "c", "system": "beta", "position": [0, 0, 0], "dockingRadius": 900},
    ]
    path = tmp_path / "stations.json"
    path.write_text(json.dumps(data))
    db = StationDatabase()
    db.load(path)
    station, distance = db.nearest_in_system("alpha", (10.0, 0.0, 0.0))
    assert station is not None
    assert station.id == "a"
    assert distance == 10.0


def test_space_world_nearest_station(tmp_path):
    sector_path = tmp_path / "sector.json"
    sector_path.write_text(json.dumps([
        {"id": "alpha", "position": [0, 0], "threat": False},
        {"id": "beta", "position": [1, 1], "threat": False},
    ]))
    stations_path = tmp_path / "stations.json"
    stations_path.write_text(json.dumps([
        {"id": "dock", "system": "alpha", "position": [0, 0, 500], "dockingRadius": 950},
    ]))

    sector = SectorMap()
    sector.load(sector_path)
    stations = StationDatabase()
    stations.load(stations_path)

    weapons = WeaponDatabase()
    logger = make_logger()
    world = SpaceWorld(
        weapons=weapons,
        sector=sector,
        stations=stations,
        mining=MiningDatabase(),
        logger=logger,
    )

    player_ship = Ship(make_frame("player_ship"), team="player")
    player_ship.kinematics.position = Vector3(0.0, 0.0, 520.0)
    station_ship = Ship(make_frame("station_ship", role="Station", size="Outpost"), team="player")
    station_ship.kinematics.position = Vector3(0.0, 0.0, 500.0)

    world.add_ship(player_ship)
    world.add_ship(station_ship)

    station, distance = world.nearest_station(player_ship)
    assert station is not None
    assert station.id == "dock"
    assert distance == 20.0


def test_space_world_ignores_unanchored_station_data(tmp_path):
    sector_path = tmp_path / "sector.json"
    sector_path.write_text(json.dumps([
        {"id": "alpha", "position": [0, 0], "threat": False},
    ]))
    stations_path = tmp_path / "stations.json"
    stations_path.write_text(json.dumps([
        {"id": "ghost", "system": "alpha", "position": [200, 0, 0], "dockingRadius": 800},
    ]))

    sector = SectorMap()
    sector.load(sector_path)
    stations = StationDatabase()
    stations.load(stations_path)

    world = SpaceWorld(
        weapons=WeaponDatabase(),
        sector=sector,
        stations=stations,
        mining=MiningDatabase(),
        logger=make_logger(),
    )

    player_ship = Ship(make_frame("player_ship"), team="player")
    player_ship.kinematics.position = Vector3(0.0, 0.0, 0.0)
    world.add_ship(player_ship)

    station, distance = world.nearest_station(player_ship)
    assert station is None
    assert distance == float("inf")


def test_space_world_places_player_near_outpost(tmp_path):
    sector_path = tmp_path / "sector.json"
    sector_path.write_text(json.dumps([
        {"id": "alpha", "position": [0, 0], "threat": False},
    ]))
    stations_path = tmp_path / "stations.json"
    stations_path.write_text(json.dumps([
        {"id": "gamma_outpost", "system": "alpha", "position": [0, 0, 0], "dockingRadius": 950},
    ]))

    sector = SectorMap()
    sector.load(sector_path)
    stations = StationDatabase()
    stations.load(stations_path)

    world = SpaceWorld(
        weapons=WeaponDatabase(),
        sector=sector,
        stations=stations,
        mining=MiningDatabase(),
        logger=make_logger(),
    )

    player_ship = Ship(make_frame("player_ship"), team="player")
    outpost_ship = Ship(make_frame("player_outpost", role="Outpost", size="Outpost"), team="player")
    outpost_ship.kinematics.position = Vector3(100.0, 0.0, 200.0)

    world.add_ship(outpost_ship)
    world.add_ship(player_ship)

    placed = world.place_ship_near_outpost(player_ship, zero_velocity=True)
    assert placed
    distance = player_ship.kinematics.position.distance_to(outpost_ship.kinematics.position)
    assert 800.0 <= distance <= 1000.0


def test_outpost_weapons_auto_fire_on_enemies():
    weapons = WeaponDatabase()
    pd_weapon = WeaponData.from_dict(
        {
            "id": "pd_x30p",
            "slotType": "cannon",
            "class": "hitscan",
            "damage": 120.0,
            "accuracy": 1.0,
            "crit": 0.0,
            "critMult": 1.0,
            "rof": 2.0,
            "power": 0.0,
            "optimal": 400.0,
            "maxRange": 600.0,
            "gimbal": 90.0,
        }
    )
    weapons.weapons[pd_weapon.id] = pd_weapon

    logger = make_logger()
    world = SpaceWorld(
        weapons=weapons,
        sector=SectorMap(),
        stations=StationDatabase(),
        mining=MiningDatabase(),
        logger=logger,
    )

    hardpoint = Hardpoint(
        id="hp_outpost_test",
        slot="gun",
        position=Vector3(0.0, 0.0, 40.0),
        gimbal=90.0,
        tracking_speed=180.0,
    )
    outpost_frame = ShipFrame(
        id="test_outpost",
        name="Test Outpost",
        role="Outpost",
        size="Outpost",
        stats=ShipStats.from_dict({"power_points": 500.0, "power_recovery_per_sec": 50.0}),
        slots=ShipSlotLayout.from_dict({"weapons": {"guns": 1}}),
        hardpoints=[hardpoint],
    )
    outpost = Ship(outpost_frame, team="player")
    outpost.mounts[0].weapon_id = pd_weapon.id

    enemy = Ship(make_frame("enemy_ship"), team="cylon")

    outpost.kinematics.position = Vector3(0.0, 0.0, 0.0)
    enemy.kinematics.position = Vector3(0.0, 0.0, 400.0)

    world.add_ship(outpost)
    world.add_ship(enemy)

    initial_hull = enemy.hull

    world.update(0.1)

    mount = outpost.mounts[0]
    assert enemy.hull < initial_hull
    assert mount.cooldown > 0.0
    assert mount.effect_type == "point_defense"
    assert mount.effect_timer > 0.0


def test_outpost_weapon_facings_match_orientation():
    frame_data = {
        "id": "outpost_facing_test",
        "name": "Facing Test Outpost",
        "role": "Outpost",
        "size": "Outpost",
        "stats": {},
        "slots": {},
        "hardpoints": [
            {
                "id": "hp_outpost_launcher_port",
                "slot": "launcher",
                "position": [-235.0, -50.0, -260.0],
                "gimbal": 180,
                "tracking_speed": 24,
            },
            {
                "id": "hp_outpost_launcher_starboard",
                "slot": "launcher",
                "position": [235.0, -50.0, -260.0],
                "gimbal": 180,
                "tracking_speed": 24,
            },
            {
                "id": "hp_outpost_west",
                "slot": "launcher",
                "position": [-248.0, 42.0, -40.0],
                "gimbal": 42,
                "tracking_speed": 32,
            },
            {
                "id": "hp_outpost_pd_west",
                "slot": "defensive",
                "position": [-205.0, 38.0, 200.0],
                "gimbal": 180,
                "tracking_speed": 180,
            },
            {
                "id": "hp_outpost_north",
                "slot": "launcher",
                "position": [-70.0, 32.0, 600.0],
                "gimbal": 35,
                "tracking_speed": 36,
            },
            {
                "id": "hp_outpost_pd_south",
                "slot": "launcher",
                "position": [-220.0, -42.0, 60.0],
                "gimbal": 180,
                "tracking_speed": 180,
            },
            {
                "id": "hp_outpost_east",
                "slot": "launcher",
                "position": [248.0, 42.0, -40.0],
                "gimbal": 42,
                "tracking_speed": 32,
            },
            {
                "id": "hp_outpost_pd_east",
                "slot": "defensive",
                "position": [205.0, 38.0, 200.0],
                "gimbal": 180,
                "tracking_speed": 180,
            },
            {
                "id": "hp_outpost_south",
                "slot": "launcher",
                "position": [70.0, 32.0, 600.0],
                "gimbal": 35,
                "tracking_speed": 36,
            },
            {
                "id": "hp_outpost_pd_north",
                "slot": "launcher",
                "position": [220.0, -42.0, 60.0],
                "gimbal": 180,
                "tracking_speed": 180,
            },
        ],
    }

    frame = ShipFrame.from_dict(frame_data)
    facing_map = {hardpoint.id: hardpoint.facing for hardpoint in frame.hardpoints}

    front_ids = {
        "hp_outpost_launcher_port",
        "hp_outpost_launcher_starboard",
    }
    left_ids = {
        "hp_outpost_west",
        "hp_outpost_pd_west",
        "hp_outpost_north",
        "hp_outpost_pd_south",
    }
    right_ids = {
        "hp_outpost_east",
        "hp_outpost_pd_east",
        "hp_outpost_south",
        "hp_outpost_pd_north",
    }

    for hp_id in front_ids:
        assert facing_map[hp_id] == "forward"
    for hp_id in left_ids:
        assert facing_map[hp_id] == "left"
    for hp_id in right_ids:
        assert facing_map[hp_id] == "right"


def test_outpost_zero_orientation_is_treated_as_unset():
    frame_data = {
        "id": "outpost_zero_orientation",
        "name": "Zero Orientation Outpost",
        "role": "Outpost",
        "size": "Outpost",
        "stats": {},
        "slots": {},
        "hardpoints": [
            {
                "id": "hp_outpost_west",
                "slot": "launcher",
                "position": [-248.0, 42.0, -40.0],
                "gimbal": 42,
                "tracking_speed": 32,
                "orientation": [0.0, 0.0, 0.0],
            },
            {
                "id": "hp_outpost_east",
                "slot": "launcher",
                "position": [248.0, 42.0, -40.0],
                "gimbal": 42,
                "tracking_speed": 32,
                "orientation": [0.0, 0.0, 0.0],
            },
        ],
    }

    frame = ShipFrame.from_dict(frame_data)
    facing_map = {hardpoint.id: hardpoint.facing for hardpoint in frame.hardpoints}

    assert facing_map["hp_outpost_west"] == "left"
    assert facing_map["hp_outpost_east"] == "right"
