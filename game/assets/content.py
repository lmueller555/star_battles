"""Asset loading entry point."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from game.combat.weapons import WeaponDatabase
from game.ships.data import ShipDatabase


@dataclass
class ItemData:
    id: str
    slot_type: str
    name: str
    tags: list[str]
    stats: Dict[str, float]

    @classmethod
    def from_dict(cls, data: Dict) -> "ItemData":
        return cls(
            id=data["id"],
            slot_type=data.get("slotType", "utility"),
            name=data.get("name", data["id"]),
            tags=list(data.get("tags", [])),
            stats=data.get("stats", {}),
        )


class ItemDatabase:
    def __init__(self) -> None:
        self.items: Dict[str, ItemData] = {}

    def load_directory(self, directory: Path) -> None:
        if not directory.exists():
            return
        for path in directory.glob("*.json"):
            try:
                data = json.loads(path.read_text())
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                data = [data]
            for entry in data:
                item = ItemData.from_dict(entry)
                self.items[item.id] = item

    def get(self, item_id: str) -> ItemData:
        return self.items[item_id]


class ContentManager:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.ships = ShipDatabase()
        self.weapons = WeaponDatabase()
        self.items = ItemDatabase()

    def load(self) -> None:
        self.ships.load_directory(self.root / "data" / "ships")
        self.weapons.load_directory(self.root / "data" / "weapons")
        self.items.load_directory(self.root / "data" / "items")


__all__ = ["ContentManager", "ItemDatabase", "ItemData"]
