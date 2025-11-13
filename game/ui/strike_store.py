"""Strike-class equipment storefront and fitting helpers."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

from game.ships.ship import Ship
from game.ui.equipment_data import EQUIPMENT_ITEMS


_WEAPON_SLOT_NAMES = {"gun", "guns", "cannon", "launcher", "defensive", "special"}


def _weapon_capacity(ship: Ship) -> int:
    """Count weapon mounts that can accept store-listed weapons."""

    return sum(1 for mount in ship.mounts if mount.hardpoint.slot.lower() in _WEAPON_SLOT_NAMES)
@dataclass(frozen=True)
class StoreItem:
    """Immutable metadata describing a store inventory entry."""

    id: str
    name: str
    slot_family: str
    ship_class: str
    level: int
    durability_max: int
    durability: int
    price: int
    stats: Dict[str, float]
    upgrades: Tuple[str, ...]
    description: str
    tags: Tuple[str, ...] = ()

    def impact_score(self) -> float:
        """Return a relative score for sorting by impact."""

        if self.slot_family == "weapon":
            damage = self.stats.get("damage_max", 0.0) + self.stats.get("damage_min", 0.0)
            optimal = self.stats.get("optimal_range", 0.0)
            crit = self.stats.get("critical_offense", 0.0)
            reload = self.stats.get("reload", 1.0)
            # Higher damage, optimal range, and crit are better; shorter reload is stronger.
            return (damage * 0.5 + optimal * 0.02 + crit * 0.02) / max(reload, 0.01)
        magnitude = 0.0
        for key, value in self.stats.items():
            magnitude += abs(value)
        return magnitude


@dataclass
class StoreFilters:
    slot_families: Tuple[str, ...] = ("weapon", "hull", "engine")
    sort_by: str = "price"
    descending: bool = False


@dataclass
class ItemCardData:
    item: StoreItem
    affordable: bool
    selected: bool
    impact: float


@dataclass
class InventoryState:
    """Track owned items and the modules equipped for preview."""

    owned: Dict[str, int] = field(default_factory=dict)
    equipped: Dict[str, List[str]] = field(default_factory=lambda: {"hull": [], "engine": [], "weapon": []})

    def add(self, item: StoreItem) -> None:
        self.owned[item.id] = self.owned.get(item.id, 0) + 1

    def has(self, item_id: str) -> bool:
        return self.owned.get(item_id, 0) > 0

    def equip(self, item: StoreItem, capacity: int) -> bool:
        slot = item.slot_family
        slots = self.equipped.setdefault(slot, [])
        if len(slots) >= capacity:
            return False
        equipped_count = slots.count(item.id)
        if equipped_count >= self.owned.get(item.id, 0):
            return False
        slots.append(item.id)
        return True

    def unequipped_ids(self, slot_family: str) -> List[str]:
        equipped = set(self.equipped.get(slot_family, []))
        return [item_id for item_id, qty in self.owned.items() for _ in range(qty) if item_id not in equipped]


def _generate_catalog() -> Dict[str, StoreItem]:
    items: List[StoreItem] = []
    for data in EQUIPMENT_ITEMS:
        items.append(
            StoreItem(
                id=str(data["id"]),
                name=str(data["name"]),
                slot_family=str(data["slot_family"]),
                ship_class=str(data["ship_class"]),
                level=int(data.get("level", 1)),
                durability_max=int(data.get("durability_max", data.get("durability", 0))),
                durability=int(data.get("durability", data.get("durability_max", 0))),
                price=int(data.get("price", 0)),
                stats=dict(data.get("stats", {})),
                upgrades=tuple(data.get("upgrades", ())),
                description=str(data.get("description", "")),
                tags=tuple(data.get("tags", ())),
            )
        )
    return {item.id: item for item in items}


CATALOG: Dict[str, StoreItem] = _generate_catalog()


class _StoreContext:
    def __init__(self) -> None:
        self.ship: Optional[Ship] = None
        self.inventory = InventoryState()
        self.selected_item: Optional[str] = None

    def bind_ship(self, ship: Ship) -> None:
        if self.ship is not ship:
            self.ship = ship
            self.selected_item = None
        self.sync_inventory()

    def sync_inventory(self) -> None:
        self.inventory = InventoryState()
        ship = self.ship
        if not ship:
            return
        for item_id, quantity in ship.hold_items.items():
            if quantity <= 0:
                continue
            self.inventory.owned[item_id] = quantity
        for slot_type, modules in ship.modules_by_slot.items():
            for module in modules:
                item_id = module.id
                if not item_id:
                    continue
                self.inventory.owned[item_id] = self.inventory.owned.get(item_id, 0) + 1
                self.inventory.equipped.setdefault(slot_type, []).append(item_id)

    def available_currency(self) -> float:
        if not self.ship:
            return 0.0
        return float(self.ship.resources.cubits)


class StoreService:
    """Back-end operations for the store tab."""

    def __init__(self, context: _StoreContext) -> None:
        self._context = context

    def bind_ship(self, ship: Ship) -> None:
        self._context.bind_ship(ship)

    def list_items(self, filters: StoreFilters) -> List[ItemCardData]:
        ship = self._context.ship
        currency = self._context.available_currency()
        selected = self._context.selected_item
        families = set(filters.slot_families)
        ship_class = None
        if ship and ship.frame:
            ship_class = ship.frame.size.lower()

        def _eligible(item: StoreItem) -> bool:
            if item.slot_family not in families:
                return False
            if not ship_class:
                return True
            allowed = item.ship_class.lower()
            return allowed == ship_class or allowed in {"any", "all", "universal"}

        items = [item for item in CATALOG.values() if _eligible(item)]
        sort_key = filters.sort_by.lower()
        reverse = filters.descending

        def key(item: StoreItem) -> Tuple:
            if sort_key == "price":
                return (item.price, item.name)
            if sort_key == "name":
                return (item.name,)
            if sort_key == "slot":
                return (item.slot_family, item.price, item.name)
            if sort_key == "impact":
                return (item.impact_score(), item.price)
            return (item.price, item.name)

        items.sort(key=key, reverse=reverse)
        card_data: List[ItemCardData] = []
        for item in items:
            affordable = currency >= item.price
            card = ItemCardData(
                item=item,
                affordable=affordable,
                selected=item.id == selected,
                impact=item.impact_score(),
            )
            card_data.append(card)
        return card_data

    def buy(self, item_id: str) -> Dict[str, object]:
        ship = self._context.ship
        if not ship:
            return {"success": False, "error": "No ship bound."}
        try:
            item = CATALOG[item_id]
        except KeyError:
            return {"success": False, "error": "Item not found."}
        if ship.resources.cubits < item.price:
            return {"success": False, "error": "Insufficient funds."}
        if not ship.can_store_in_hold():
            return {"success": False, "error": "Hold is full."}
        ship.resources.cubits -= item.price
        stored = ship.add_hold_item(item.id)
        if not stored:
            ship.resources.cubits += item.price
            return {"success": False, "error": "Hold is full."}
        self._context.inventory.add(item)
        self._context.sync_inventory()
        capacity = 0
        if item.slot_family == "hull":
            capacity = int(ship.frame.slots.hull)
        elif item.slot_family == "engine":
            capacity = int(ship.frame.slots.engine)
        elif item.slot_family == "weapon":
            capacity = _weapon_capacity(ship)
        if capacity > 0:
            self._context.inventory.equip(item, capacity)
        self._context.selected_item = item_id
        return {"success": True, "currency": float(ship.resources.cubits)}

    def select(self, item_id: Optional[str]) -> None:
        self._context.selected_item = item_id

    def selected_item(self) -> Optional[StoreItem]:
        if not self._context.selected_item:
            return None
        return CATALOG.get(self._context.selected_item)


class FittingService:
    """Preview and apply module effects for the current ship."""

    def __init__(self, context: _StoreContext) -> None:
        self._context = context

    def _current_ship(self) -> Ship:
        if not self._context.ship:
            raise RuntimeError("No ship bound for fitting preview")
        return self._context.ship

    def preview_with(self, item_id: str) -> Dict[str, Dict[str, float]]:
        item = CATALOG[item_id]
        ship = self._current_ship()
        base = ship.stats
        inventory = self._context.inventory
        existing = inventory.equipped.get(item.slot_family, [])
        current_stats = self._apply_modules(base, [CATALOG[i] for i in existing])
        preview_stats = self._apply_modules(base, [CATALOG[i] for i in existing] + [item])
        deltas = {
            key: preview_stats.get(key, 0.0) - current_stats.get(key, 0.0)
            for key in preview_stats.keys()
            if key in current_stats
        }
        return {"deltas_by_stat": deltas, "preview": preview_stats, "current": current_stats}

    def apply(self, item_id: str) -> bool:
        ship = self._current_ship()
        item = CATALOG[item_id]
        inventory = self._context.inventory
        if not inventory.has(item_id):
            return False
        capacity = 0
        if item.slot_family == "hull":
            capacity = int(ship.frame.slots.hull)
        elif item.slot_family == "engine":
            capacity = int(ship.frame.slots.engine)
        elif item.slot_family == "weapon":
            capacity = _weapon_capacity(ship)
        if capacity <= 0:
            return False
        return inventory.equip(item, capacity)

    def _apply_modules(self, base: object, modules: Sequence[StoreItem]) -> Dict[str, float]:
        stats = {
            "hull_hp": float(getattr(base, "hull_hp", 0.0)),
            "armor": float(getattr(base, "armor", 0.0)),
            "critical_defense": float(getattr(base, "critical_defense", 0.0)),
            "hull_recovery": float(getattr(base, "hull_recovery", 0.0)),
            "acceleration": float(getattr(base, "acceleration", 0.0)),
            "turn_accel": float(getattr(base, "turn_accel", 0.0)),
            "turn_rate": float(getattr(base, "turn_rate", 0.0)),
            "max_speed": float(getattr(base, "max_speed", 0.0)),
            "boost_speed": float(getattr(base, "boost_speed", 0.0)),
            "strafe_speed": float(getattr(base, "strafe_speed", 0.0)),
            "boost_cost": float(getattr(base, "boost_cost", 0.0)),
            "avoidance_rating": float(getattr(base, "avoidance_rating", 0.0)),
        }
        stats["avoidance"] = float(getattr(base, "avoidance", 0.0))
        percent_mods = {
            "max_speed": 0.0,
            "boost_speed": 0.0,
            "acceleration": 0.0,
            "turn_rate": 0.0,
            "turn_accel": 0.0,
            "avoidance_rating": 0.0,
            "strafe_speed": 0.0,
            "boost_cost": 0.0,
        }
        for module in modules:
            if module.slot_family == "hull":
                stats["hull_hp"] += module.stats.get("hull_hp", 0.0)
                stats["armor"] += module.stats.get("armor", 0.0)
                stats["critical_defense"] += module.stats.get("critical_defense", 0.0)
                stats["hull_recovery"] += module.stats.get("hull_recovery", 0.0)
                stats["acceleration"] += module.stats.get("acceleration", 0.0)
                stats["turn_accel"] += module.stats.get("turn_accel", 0.0)
                if "avoidance_rating" in module.stats:
                    stats["avoidance_rating"] += module.stats["avoidance_rating"]
            elif module.slot_family == "engine":
                stats["max_speed"] += module.stats.get("max_speed", 0.0)
                stats["boost_speed"] += module.stats.get("boost_speed", 0.0)
                stats["acceleration"] += module.stats.get("acceleration", 0.0)
                stats["turn_rate"] += module.stats.get("turn_rate", 0.0)
                stats["turn_accel"] += module.stats.get("turn_accel", 0.0)
                stats["strafe_speed"] += module.stats.get("strafe_speed", 0.0)
                stats["boost_cost"] += module.stats.get("boost_cost", 0.0)
                if "avoidance_rating" in module.stats:
                    stats["avoidance_rating"] += module.stats["avoidance_rating"]
                percent_mods["max_speed"] += module.stats.get("max_speed_percent", 0.0)
                percent_mods["boost_speed"] += module.stats.get("boost_speed_percent", 0.0)
                percent_mods["acceleration"] += module.stats.get("acceleration_percent", 0.0)
                percent_mods["turn_rate"] += module.stats.get("turn_rate_percent", 0.0)
                percent_mods["turn_accel"] += module.stats.get("turn_accel_percent", 0.0)
                percent_mods["strafe_speed"] += module.stats.get("strafe_speed_percent", 0.0)
                percent_mods["boost_cost"] += module.stats.get("boost_cost_percent", 0.0)
                percent_mods["avoidance_rating"] += module.stats.get("avoidance_percent", 0.0)
            elif module.slot_family == "weapon":
                # Weapons do not impact ship stats in this preview.
                continue
        for key, percent in percent_mods.items():
            if abs(percent) < 1e-6:
                continue
            base_value = float(getattr(base, key, stats.get(key, 0.0)))
            stats[key] = stats.get(key, base_value) + base_value * (percent / 100.0)
        if stats["avoidance_rating"] > 1.0:
            stats["avoidance"] = stats["avoidance_rating"] / 1000.0
        else:
            stats["avoidance"] = stats["avoidance_rating"]
        return stats


_CONTEXT = _StoreContext()
store = StoreService(_CONTEXT)
fitting = FittingService(_CONTEXT)


__all__ = [
    "StoreItem",
    "StoreFilters",
    "InventoryState",
    "ItemCardData",
    "store",
    "fitting",
    "CATALOG",
]

