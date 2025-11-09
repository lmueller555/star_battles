import json

from pygame.math import Vector3

from game.world.mining import MiningDatabase, MiningManager
from game.ships.ship import ShipResources


class DummyShip:
    def __init__(self) -> None:
        self.kinematics = type("Kin", (), {"position": Vector3(0.0, 0.0, 0.0)})()
        self.resources = ShipResources()

    def module_stat_total(self, key: str) -> float:
        return 0.0


def test_mining_scan_and_yield(tmp_path):
    data = [
        {
            "id": "test_node",
            "name": "Test Node",
            "system": "alpha",
            "resource": "tylium",
            "grade": 1.0,
            "baseYield": 5.0,
            "position": [0.0, 0.0, 0.0],
            "scanTime": 1.0,
            "stabilityDecay": 0.1,
        }
    ]
    path = tmp_path / "mining.json"
    path.write_text(json.dumps(data))
    database = MiningDatabase()
    database.load(path)
    manager = MiningManager(database)
    manager.enter_system("alpha")
    ship = DummyShip()
    manager.scan_step(ship, dt=1.2)
    node = manager.nodes[0]
    assert node.discovered
    success, _ = manager.start_mining(ship)
    assert success
    state = manager.step(ship, dt=1.0, stabilizing=False, scanning_active=False, logger=None)
    assert state.last_yield > 0.0
    assert ship.resources.tylium > 0.0
