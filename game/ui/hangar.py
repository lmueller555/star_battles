"""Docking hangar overlay for Outposts."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

import pygame
from pygame.math import Vector2

from game.assets.content import ContentManager, ItemData
from game.ships.ship import Ship, WeaponMount
from game.world.station import DockingStation
from game.ui.ship_info import DEFAULT_ANCHORS, MODEL_LAYOUTS
from game.ui.strike_store import CATALOG, ItemCardData, StoreFilters, StoreItem, fitting, store
from game.ui.equipment_upgrade import EQUIPMENT_UPGRADE_SPECS, EquipmentUpgradeModel


@dataclass
class _SlotDisplay:
    label: str
    detail: str
    rect: pygame.Rect
    filled: bool
    category: str
    slot_type: str
    index: int = 0


@dataclass
class _HoldItem:
    key: str
    name: str
    amount: float
    icon_key: str
    can_sell: bool = False
    sell_rate: float | None = None
    sell_currency: Optional[str] = None
    price_icon_key: Optional[str] = None
    description: Optional[str] = None
    equippable: bool = False
    slot_family: Optional[str] = None
    store_item: Optional[StoreItem] = None
    item_id: Optional[str] = None
    instance_index: Optional[int] = None
    slot_index: Optional[int] = None
    location: str = "hold"
    mount_index: Optional[int] = None


@dataclass
class _HoldRow:
    item: _HoldItem
    rect: pygame.Rect
    button_rect: Optional[pygame.Rect]
    action: Optional[str] = None
    enabled: bool = False
    upgrade_rect: Optional[pygame.Rect] = None
    upgrade_enabled: bool = False


@dataclass
class _TooltipButton:
    rect: pygame.Rect
    enabled: bool
    action: str
    slot: _SlotDisplay


@dataclass
class _SellDialog:
    item_key: str
    item_name: str
    sell_currency: str
    sell_rate: float
    price_icon_key: str
    input_value: str = "1"
    rect: pygame.Rect = field(default_factory=lambda: pygame.Rect(0, 0, 0, 0))
    confirm_rect: pygame.Rect = field(default_factory=lambda: pygame.Rect(0, 0, 0, 0))
    cancel_rect: pygame.Rect = field(default_factory=lambda: pygame.Rect(0, 0, 0, 0))
    available: float = 0.0


@dataclass(frozen=True)
class _StatRowDef:
    label: str
    keys: Tuple[str, ...]
    units: str
    precision: int
    axis: Optional[str] = None
    tooltip: str = ""


@dataclass
class _UpgradeDialog:
    item: _HoldItem
    store_item: StoreItem
    spec: EquipmentUpgradeSpec
    model: EquipmentUpgradeModel
    rect: pygame.Rect = field(default_factory=lambda: pygame.Rect(0, 0, 0, 0))
    pip_rects: List[Tuple[int, pygame.Rect]] = field(default_factory=list)
    left_chevron: Optional[pygame.Rect] = None
    right_chevron: Optional[pygame.Rect] = None
    confirm_rect: Optional[pygame.Rect] = None
    cancel_rect: Optional[pygame.Rect] = None
    max_rect: Optional[pygame.Rect] = None
    guarantee_rect: Optional[pygame.Rect] = None
    message: Optional[str] = None
    flash_timer: float = 0.0
    flash_axes: Tuple[str, ...] = ()
    row_rects: List[Tuple[pygame.Rect, _StatRowDef]] = field(default_factory=list)


STAT_TOOLTIPS: Dict[str, str] = {
    "damage": "Average damage range delivered per shot.",
    "armor_piercing": "Reduces target armor before damage mitigation.",
    "range": "Minimum and maximum firing distance envelope.",
    "optimal_range": "Range where the weapon maintains peak accuracy and DPS.",
    "accuracy": "Directly improves hit chance against evasive targets.",
    "critical_offense": "Raises critical hit chance against enemy defenses.",
    "reload": "Seconds between shots or bursts.",
    "power": "Energy drawn from the ship per shot.",
    "firing_arc": "Degrees of traverse the weapon can cover.",
    "durability": "Item health before it becomes inoperable.",
    "armor": "Adds to the ship's damage reduction value.",
    "hull_hp": "Flat hull hit points added to the ship.",
    "acceleration": "Change to linear acceleration.",
    "turn_accel": "Change to rotational acceleration.",
    "turn_rate": "Change to rotational speed.",
    "max_speed": "Increase to sustained cruise speed.",
    "boost_speed": "Increase to boosted top speed.",
    "avoidance": "Improves chance to avoid incoming fire.",
}


AXIS_KEYS: Dict[str, Tuple[str, ...]] = {
    "damage": ("damage_min", "damage_max"),
    "critical_offense": ("critical_offense",),
    "optimal_range": ("optimal_range",),
    "armor": ("armor",),
    "hull_hp": ("hull_hp",),
    "acceleration": ("acceleration",),
    "turn_accel": ("turn_accel",),
    "turn_rate": ("turn_rate",),
    "max_speed": ("max_speed",),
    "boost_speed": ("boost_speed",),
    "avoidance": ("avoidance_rating",),
}


WEAPON_ROWS: Tuple[_StatRowDef, ...] = (
    _StatRowDef("Damage", ("damage_min", "damage_max"), "points", 2, axis="damage", tooltip=STAT_TOOLTIPS["damage"]),
    _StatRowDef(
        "Armor Piercing",
        ("armor_piercing",),
        "points",
        0,
        tooltip=STAT_TOOLTIPS["armor_piercing"],
    ),
    _StatRowDef("Range", ("range_min", "range_max"), "m", 0, tooltip=STAT_TOOLTIPS["range"]),
    _StatRowDef(
        "Optimal Range",
        ("optimal_range",),
        "m",
        0,
        axis="optimal_range",
        tooltip=STAT_TOOLTIPS["optimal_range"],
    ),
    _StatRowDef("Accuracy", ("accuracy",), "points", 0, tooltip=STAT_TOOLTIPS["accuracy"]),
    _StatRowDef(
        "Critical Offense",
        ("critical_offense",),
        "points",
        0,
        axis="critical_offense",
        tooltip=STAT_TOOLTIPS["critical_offense"],
    ),
    _StatRowDef("Reload", ("reload",), "s", 2, tooltip=STAT_TOOLTIPS["reload"]),
    _StatRowDef("Power Cost", ("power",), "points", 2, tooltip=STAT_TOOLTIPS["power"]),
    _StatRowDef("Firing Arc", ("firing_arc",), "°", 0, tooltip=STAT_TOOLTIPS["firing_arc"]),
    _StatRowDef("Durability", ("durability",), "points", 0, tooltip=STAT_TOOLTIPS["durability"]),
)


HULL_ROWS: Tuple[_StatRowDef, ...] = (
    _StatRowDef("Armor Value", ("armor",), "points", 2, axis="armor", tooltip=STAT_TOOLTIPS["armor"]),
    _StatRowDef("Hull Points", ("hull_hp",), "points", 1, axis="hull_hp", tooltip=STAT_TOOLTIPS["hull_hp"]),
    _StatRowDef("Acceleration", ("acceleration",), "m/s²", 2, tooltip=STAT_TOOLTIPS["acceleration"]),
    _StatRowDef("Turn Accel", ("turn_accel",), "deg/s²", 2, tooltip=STAT_TOOLTIPS["turn_accel"]),
    _StatRowDef("Durability", ("durability",), "points", 0, tooltip=STAT_TOOLTIPS["durability"]),
)


ENGINE_ROWS: Tuple[_StatRowDef, ...] = (
    _StatRowDef("Speed", ("max_speed",), "m/s", 2, axis="max_speed", tooltip=STAT_TOOLTIPS["max_speed"]),
    _StatRowDef("Boost Speed", ("boost_speed",), "m/s", 2, axis="boost_speed", tooltip=STAT_TOOLTIPS["boost_speed"]),
    _StatRowDef("Acceleration", ("acceleration",), "m/s²", 2, axis="acceleration", tooltip=STAT_TOOLTIPS["acceleration"]),
    _StatRowDef("Turn Speed", ("turn_rate",), "deg/s", 2, axis="turn_rate", tooltip=STAT_TOOLTIPS["turn_rate"]),
    _StatRowDef("Turn Accel", ("turn_accel",), "deg/s²", 2, axis="turn_accel", tooltip=STAT_TOOLTIPS["turn_accel"]),
    _StatRowDef("Avoidance", ("avoidance_rating",), "points", 1, axis="avoidance", tooltip=STAT_TOOLTIPS["avoidance"]),
    _StatRowDef("Durability", ("durability",), "points", 0, tooltip=STAT_TOOLTIPS["durability"]),
)

class _HangarInteriorAnimator:
    """Render a stylised hangar interior with light animation."""

    def __init__(self) -> None:
        self.time: float = 0.0
        self._arm_offsets: Tuple[float, float, float] = (0.0, 1.6, 3.2)

    def update(self, dt: float) -> None:
        self.time += dt

    def draw(self, surface: pygame.Surface) -> None:
        width, height = surface.get_size()
        deck_y = int(height * 0.62)

        surface.fill((8, 12, 18))
        upper_rect = pygame.Rect(0, 0, width, deck_y)
        lower_rect = pygame.Rect(0, deck_y, width, height - deck_y)
        pygame.draw.rect(surface, (18, 26, 36), upper_rect)
        pygame.draw.rect(surface, (26, 34, 46), lower_rect)

        door_rect = pygame.Rect(int(width * 0.16), int(height * 0.12), int(width * 0.68), int(height * 0.4))
        pygame.draw.rect(surface, (12, 18, 26), door_rect)
        pygame.draw.rect(surface, (60, 96, 134), door_rect, 4)

        ceiling_beam = pygame.Rect(0, int(height * 0.18) - 10, width, 20)
        pygame.draw.rect(surface, (32, 44, 58), ceiling_beam)

        for offset in (0.22, 0.5, 0.78):
            strut = pygame.Rect(
                int(width * offset) - int(width * 0.01),
                int(height * 0.18),
                int(width * 0.02),
                int(height * 0.34),
            )
            pygame.draw.rect(surface, (38, 52, 66), strut)
            pygame.draw.rect(surface, (70, 110, 148), strut, 2)

        platform = [
            (int(width * 0.06), deck_y),
            (int(width * 0.94), deck_y),
            (width, height),
            (0, height),
        ]
        pygame.draw.polygon(surface, (28, 36, 46), platform)
        pygame.draw.line(surface, (70, 110, 150), platform[0], platform[1], 3)

        for idx in range(9):
            stripe_x = int(width * 0.08 + idx * width * 0.1)
            stripe = pygame.Rect(stripe_x, deck_y + int(height * 0.05), int(width * 0.035), 6)
            pygame.draw.rect(surface, (48, 66, 78), stripe)

        ship_points = [
            (int(width * 0.41), deck_y - int(height * 0.08)),
            (int(width * 0.59), deck_y - int(height * 0.08)),
            (int(width * 0.64), deck_y - int(height * 0.05)),
            (int(width * 0.36), deck_y - int(height * 0.05)),
        ]
        pygame.draw.polygon(surface, (30, 42, 58), ship_points)
        pygame.draw.lines(surface, (120, 170, 210), True, ship_points, 2)

        glow_surface = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
        glow_strength = 60 + int(40 * (0.5 + 0.5 * math.sin(self.time * 1.8)))
        glow_rect = pygame.Rect(
            int(width * 0.25),
            deck_y - int(height * 0.18),
            int(width * 0.5),
            int(height * 0.26),
        )
        pygame.draw.ellipse(glow_surface, (120, 190, 255, glow_strength), glow_rect)
        surface.blit(glow_surface, (0, 0), special_flags=pygame.BLEND_ADD)

        self._draw_arms(surface, width, deck_y)

    def _draw_arms(self, surface: pygame.Surface, width: int, deck_y: int) -> None:
        arm_color = (80, 128, 164)
        joint_color = (160, 210, 240)
        base_y = deck_y - int(surface.get_height() * 0.04)

        for index, offset in enumerate(self._arm_offsets):
            base_x = int(width * (0.3 + index * 0.2))
            base = Vector2(base_x, base_y)
            length_primary = surface.get_height() * 0.18
            length_secondary = surface.get_height() * 0.11
            sway = math.sin(self.time * 1.15 + offset) * 0.55
            elbow_angle = -0.9 + sway
            wrist_angle = 0.5 + math.sin(self.time * 1.7 + offset * 0.8) * 0.45
            elbow = base + Vector2(
                math.sin(elbow_angle) * length_primary,
                -math.cos(elbow_angle) * length_primary,
            )
            tip = elbow + Vector2(
                math.sin(elbow_angle + wrist_angle) * length_secondary,
                -math.cos(elbow_angle + wrist_angle) * length_secondary,
            )
            jaw_left = tip + Vector2(-14.0, 16.0)
            jaw_right = tip + Vector2(14.0, 16.0)
            points = [
                (int(base.x), int(base.y)),
                (int(elbow.x), int(elbow.y)),
                (int(tip.x), int(tip.y)),
            ]
            pygame.draw.lines(surface, arm_color, False, points, 7)
            pygame.draw.circle(surface, (34, 48, 62), (int(base.x), int(base.y)), 14)
            pygame.draw.circle(surface, arm_color, (int(elbow.x), int(elbow.y)), 10)
            pygame.draw.circle(surface, joint_color, (int(tip.x), int(tip.y)), 6)
            pygame.draw.line(surface, joint_color, (int(jaw_left.x), int(jaw_left.y)), (int(tip.x), int(tip.y)), 3)
            pygame.draw.line(surface, joint_color, (int(jaw_right.x), int(jaw_right.y)), (int(tip.x), int(tip.y)), 3)

            glow_radius = 22
            glow_surface = pygame.Surface((glow_radius * 2, glow_radius * 2), pygame.SRCALPHA)
            glow_value = min(255, 140 + int(80 * (0.5 + 0.5 * math.sin(self.time * 3.0 + offset))))
            pygame.draw.circle(glow_surface, (120, 210, 255, glow_value), (glow_radius, glow_radius), glow_radius)
            surface.blit(glow_surface, (int(tip.x) - glow_radius, int(tip.y) - glow_radius), special_flags=pygame.BLEND_ADD)


class HangarView:
    """Render the station hangar management interface."""

    def __init__(self, surface: pygame.Surface, content: ContentManager | None = None) -> None:
        self.surface = surface
        self.content = content
        self.font = pygame.font.SysFont("consolas", 18)
        self.small_font = pygame.font.SysFont("consolas", 14)
        self.mini_font = pygame.font.SysFont("consolas", 12)
        self.ribbon_options: Tuple[str, ...] = ("Store", "Hold", "Locker")
        self.active_option: str = "Hold"
        self._ribbon_rects: Dict[str, pygame.Rect] = {}
        self._interior = _HangarInteriorAnimator()
        self._slot_icons = self._create_slot_icons()
        self._hold_icons = self._create_hold_icons()
        self._price_icons = self._create_price_icons()
        self._hold_rows: List[_HoldRow] = []
        self._sell_dialog: Optional[_SellDialog] = None
        self._upgrade_dialog: Optional[_UpgradeDialog] = None
        self._current_ship: Optional[Ship] = None
        self._store_filters = StoreFilters()
        self._store_toggle_states: Dict[str, bool] = {"weapon": True, "hull": True, "engine": True}
        self._store_sort_options: List[tuple[str, str, bool]] = [
            ("price", "Price", False),
            ("name", "Name", False),
            ("slot", "Slot", False),
            ("impact", "Most Impact", True),
        ]
        self._store_sort_selection: str = "price"
        self._store_sort_desc: bool = False
        self._store_card_rects: Dict[str, pygame.Rect] = {}
        self._store_buy_rects: Dict[str, pygame.Rect] = {}
        self._store_toggle_rects: Dict[str, pygame.Rect] = {}
        self._store_sort_rects: Dict[str, pygame.Rect] = {}
        self._store_hover_item: Optional[str] = None
        self._store_preview_data: Optional[Dict[str, Dict[str, float]]] = None
        self._store_cards: List[ItemCardData] = []
        self._store_inventory_view = pygame.Rect(0, 0, 0, 0)
        self._store_scroll_offset: float = 0.0
        self._store_content_height: float = 0.0
        self._store_view_height: float = 0.0
        self._store_scrollbar_rect: Optional[pygame.Rect] = None
        self._store_scrollbar_thumb_rect: Optional[pygame.Rect] = None
        self._store_scrollbar_dragging: bool = False
        self._store_scroll_drag_offset: float = 0.0
        self._ship_widgets: List[_SlotDisplay] = []
        self._active_slot_label: Optional[str] = None
        self._active_slot_mouse_pos: Optional[Tuple[int, int]] = None
        self._tooltip_buttons: List[_TooltipButton] = []
        self._player_skills: Dict[str, int] = {"Gunnery": 3, "Engineering": 3, "Propulsion": 3}

    def set_surface(self, surface: pygame.Surface) -> None:
        """Update the target surface when the display size changes."""

        self.surface = surface

    def handle_event(self, event: pygame.event.Event) -> bool:
        """Allow ribbon selection via mouse input."""

        if self._upgrade_dialog and self._handle_upgrade_dialog_event(event):
            return True
        if self._sell_dialog and self._handle_sell_dialog_event(event):
            return True
        if self.active_option == "Store":
            if event.type == pygame.MOUSEWHEEL:
                if self._store_inventory_view.collidepoint(pygame.mouse.get_pos()):
                    self._scroll_store_by(-event.y * 60.0)
                    return True
            if event.type == pygame.MOUSEBUTTONDOWN:
                if event.button in (4, 5):
                    pos = getattr(event, "pos", pygame.mouse.get_pos())
                    if self._store_inventory_view.collidepoint(pos):
                        delta = -60.0 if event.button == 4 else 60.0
                        self._scroll_store_by(delta)
                        return True
                if event.button == 1:
                    pos = getattr(event, "pos", None)
                    if pos and self._handle_store_scrollbar_press(pos):
                        return True
            if event.type == pygame.MOUSEMOTION and self._store_scrollbar_dragging:
                pos = getattr(event, "pos", None)
                if pos:
                    self._drag_store_scrollbar(pos[1])
                    return True
            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                self._store_scrollbar_dragging = False
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            pos = getattr(event, "pos", None)
            if not pos:
                return False
            for button in self._tooltip_buttons:
                if button.rect.collidepoint(pos):
                    if button.action == "unequip":
                        if button.enabled and button.slot.filled:
                            if self._unequip_slot(button.slot):
                                self._play_confirm_sound()
                    elif button.action == "upgrade":
                        if button.enabled and button.slot.filled:
                            self._open_upgrade_dialog_for_slot(button.slot)
                    self._clear_active_slot()
                    return True
            slot = self._slot_at_position(pos)
            if slot:
                if self._active_slot_label == slot.label:
                    self._clear_active_slot()
                else:
                    self._active_slot_label = slot.label
                    self._active_slot_mouse_pos = pos
                return True
            if self.active_option == "Store" and self._handle_store_click(pos):
                self._clear_active_slot()
                return True
            if self.active_option == "Hold":
                for row in self._hold_rows:
                    if row.button_rect and row.button_rect.collidepoint(pos):
                        if row.action == "sell" and row.item.can_sell and row.item.amount > 0.0:
                            self._open_sell_dialog(row.item)
                            self._clear_active_slot()
                        elif row.action == "equip" and row.enabled:
                            if self._equip_hold_item(row.item):
                                self._play_confirm_sound()
                                self._clear_active_slot()
                        return True
                    if row.upgrade_rect and row.upgrade_rect.collidepoint(pos):
                        if row.upgrade_enabled:
                            self._open_upgrade_dialog(row.item)
                            self._clear_active_slot()
                        return True
            for option, rect in self._ribbon_rects.items():
                if rect.collidepoint(pos):
                    self.active_option = option
                    self._clear_active_slot()
                    return True
            if self._active_slot_label:
                self._clear_active_slot()
                return True
        return False

    def update(self, dt: float) -> None:
        """Advance hangar background animations."""

        self._interior.update(dt)
        if self._upgrade_dialog and self._upgrade_dialog.flash_timer > 0.0:
            self._upgrade_dialog.flash_timer = max(0.0, self._upgrade_dialog.flash_timer - dt)

    def draw(self, surface: pygame.Surface, ship: Ship, station: DockingStation, distance: float) -> None:
        self._current_ship = ship
        self._tooltip_buttons = []
        width, height = surface.get_size()
        self._interior.draw(surface)
        panel_width = int(width * 0.78)
        panel_height = int(height * 0.72)
        panel_rect = pygame.Rect((width - panel_width) // 2, (height - panel_height) // 2, panel_width, panel_height)
        self._blit_panel(surface, panel_rect, (12, 18, 26, 210), (82, 132, 168), 2)

        title = self.font.render(f"Docked at {station.name}", True, (220, 240, 255))
        surface.blit(title, (panel_rect.x + 28, panel_rect.y + 18))
        if distance <= 5.0:
            range_message = "Docked inside hangar"
        else:
            range_message = f"Distance: {distance:.0f} m (dock radius {station.docking_radius:.0f} m)"
        range_text = self.small_font.render(range_message, True, (178, 206, 228))
        surface.blit(range_text, (panel_rect.x + 28, panel_rect.y + 44))

        ribbon_height = 46
        ribbon_rect = pygame.Rect(panel_rect.x + 24, panel_rect.y + 72, panel_rect.width - 48, ribbon_height)
        self._draw_ribbon(surface, ribbon_rect)

        inner_rect = panel_rect.inflate(-48, -ribbon_height - 96)
        inner_rect.y = ribbon_rect.bottom + 16
        inner_rect.height = panel_rect.bottom - inner_rect.y - 24

        if self.active_option == "Store":
            left_width = int(inner_rect.width * 0.26)
            preview_width = int(inner_rect.width * 0.28)
            center_width = inner_rect.width - left_width - preview_width - 24
            left_rect = pygame.Rect(inner_rect.x, inner_rect.y, left_width, inner_rect.height)
            center_rect = pygame.Rect(left_rect.right + 12, inner_rect.y, center_width, inner_rect.height)
            preview_rect = pygame.Rect(center_rect.right + 12, inner_rect.y, preview_width, inner_rect.height)
            store.bind_ship(ship)
            self._update_store_filters()
            self._draw_store_filters(surface, left_rect, ship)
            self._draw_store_grid(surface, center_rect, ship)
            self._draw_store_preview(surface, preview_rect, ship)
            self._ship_widgets = []
        else:
            left_width = int(inner_rect.width * (1.0 / 3.0))
            left_rect = pygame.Rect(inner_rect.x, inner_rect.y, left_width, inner_rect.height)
            right_rect = pygame.Rect(left_rect.right + 16, inner_rect.y, inner_rect.width - left_width - 16, inner_rect.height)
            self._draw_left_panel(surface, left_rect, ship)
            self._draw_ship_panel(surface, right_rect, ship)

        footer = self.small_font.render("Press H to undock", True, (170, 210, 240))
        surface.blit(footer, (panel_rect.x + panel_rect.width - footer.get_width() - 28, panel_rect.y + panel_rect.height - 32))

        if self._sell_dialog:
            self._draw_sell_dialog(surface)
        if self._upgrade_dialog:
            self._draw_upgrade_dialog(surface)

    # ------------------------------------------------------------------
    def _draw_ribbon(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
        self._blit_panel(surface, rect, (16, 28, 38, 200), (70, 110, 150))
        option_width = rect.width // len(self.ribbon_options)
        self._ribbon_rects = {}
        for index, option in enumerate(self.ribbon_options):
            option_rect = pygame.Rect(rect.x + index * option_width, rect.y, option_width, rect.height)
            is_active = option == self.active_option
            color = (36, 60, 82, 220) if is_active else (20, 32, 44, 200)
            border_color = (150, 220, 255) if is_active else (70, 110, 150)
            button_rect = option_rect.inflate(-4, -6)
            self._blit_panel(surface, button_rect, color, border_color, 2)
            label = self.font.render(option, True, (220, 236, 250))
            surface.blit(
                label,
                (
                    option_rect.centerx - label.get_width() // 2,
                    option_rect.centery - label.get_height() // 2,
                ),
            )
            self._ribbon_rects[option] = button_rect

    def _draw_left_panel(self, surface: pygame.Surface, rect: pygame.Rect, ship: Ship) -> None:
        self._blit_panel(surface, rect, (14, 24, 32, 210), (60, 98, 134))
        title = self.font.render(self.active_option, True, (210, 230, 250))
        surface.blit(title, (rect.x + 20, rect.y + 16))

        content_rect = rect.inflate(-40, -72)
        content_rect.y = rect.y + 54
        self._blit_panel(surface, content_rect, (10, 18, 26, 200), (50, 88, 120))
        if self.active_option == "Hold":
            self._draw_hold_panel(surface, content_rect, ship)
        else:
            self._hold_rows = []
            lines = self._panel_lines_for_option(self.active_option)
            for idx, line in enumerate(lines):
                text = self.small_font.render(line, True, (180, 208, 228))
                surface.blit(text, (content_rect.x + 16, content_rect.y + 18 + idx * 20))

    def _update_store_filters(self) -> None:
        active = [slot for slot, enabled in self._store_toggle_states.items() if enabled]
        if not active:
            active = list(self._store_toggle_states.keys())
            for slot in active:
                self._store_toggle_states[slot] = True
        self._store_filters = StoreFilters(
            slot_families=tuple(sorted(active)),
            sort_by=self._store_sort_selection,
            descending=self._store_sort_desc,
        )

    def _toggle_store_family(self, family: str) -> None:
        current = self._store_toggle_states.get(family, True)
        self._store_toggle_states[family] = not current
        if not any(self._store_toggle_states.values()):
            for key in self._store_toggle_states.keys():
                self._store_toggle_states[key] = True
        self._update_store_filters()

    def _select_store_sort(self, sort_key: str) -> None:
        if sort_key == self._store_sort_selection:
            # Toggle descending flag on repeated clicks.
            self._store_sort_desc = not self._store_sort_desc
        else:
            self._store_sort_selection = sort_key
            for key, _, default_desc in self._store_sort_options:
                if key == sort_key:
                    self._store_sort_desc = default_desc
                    break
        self._update_store_filters()

    def _scroll_store_by(self, delta: float) -> None:
        if self._store_view_height <= 0.0 or self._store_content_height <= self._store_view_height:
            self._store_scroll_offset = 0.0
            return
        max_offset = max(0.0, self._store_content_height - self._store_view_height)
        self._store_scroll_offset = min(max(self._store_scroll_offset + delta, 0.0), max_offset)

    def _scroll_store_to_fraction(self, fraction: float) -> None:
        if self._store_view_height <= 0.0 or self._store_content_height <= self._store_view_height:
            self._store_scroll_offset = 0.0
            return
        max_offset = max(0.0, self._store_content_height - self._store_view_height)
        fraction = max(0.0, min(1.0, fraction))
        self._store_scroll_offset = max_offset * fraction

    def _handle_store_scrollbar_press(self, pos: Tuple[int, int]) -> bool:
        if (
            not self._store_scrollbar_rect
            or self._store_content_height <= self._store_view_height
            or not self._store_scrollbar_rect.collidepoint(pos)
        ):
            return False
        if self._store_scrollbar_thumb_rect and self._store_scrollbar_thumb_rect.collidepoint(pos):
            self._store_scrollbar_dragging = True
            self._store_scroll_drag_offset = pos[1] - self._store_scrollbar_thumb_rect.y
            return True
        if self._store_scrollbar_thumb_rect:
            self._jump_store_scrollbar(pos[1])
            self._store_scrollbar_dragging = True
            return True
        return False

    def _jump_store_scrollbar(self, mouse_y: float) -> None:
        if not (self._store_scrollbar_rect and self._store_scrollbar_thumb_rect):
            return
        track_top = self._store_scrollbar_rect.y
        track_span = self._store_scrollbar_rect.height - self._store_scrollbar_thumb_rect.height
        if track_span <= 0:
            self._store_scroll_drag_offset = 0.0
            return
        thumb_height = self._store_scrollbar_thumb_rect.height
        new_top = mouse_y - thumb_height / 2
        new_top = max(track_top, min(track_top + track_span, new_top))
        self._store_scroll_drag_offset = mouse_y - new_top
        fraction = (new_top - track_top) / track_span
        self._scroll_store_to_fraction(fraction)

    def _drag_store_scrollbar(self, mouse_y: float) -> None:
        if not (self._store_scrollbar_rect and self._store_scrollbar_thumb_rect):
            return
        track_top = self._store_scrollbar_rect.y
        track_span = self._store_scrollbar_rect.height - self._store_scrollbar_thumb_rect.height
        if track_span <= 0:
            return
        new_top = mouse_y - self._store_scroll_drag_offset
        new_top = max(track_top, min(track_top + track_span, new_top))
        fraction = (new_top - track_top) / track_span
        self._scroll_store_to_fraction(fraction)

    def _handle_store_click(self, pos: Tuple[int, int]) -> bool:
        ship = self._current_ship
        if ship:
            store.bind_ship(ship)
        if not self._store_cards:
            self._store_cards = store.list_items(self._store_filters)
        for item_id, rect in self._store_buy_rects.items():
            if rect.collidepoint(pos):
                card = next((card for card in self._store_cards if card.item.id == item_id), None)
                if not card or not card.affordable:
                    return True
                result = store.buy(item_id)
                if result.get("success"):
                    self._play_confirm_sound()
                    self._refresh_store_preview(item_id)
                    self._store_cards = store.list_items(self._store_filters)
                return True
        for family, rect in self._store_toggle_rects.items():
            if rect.collidepoint(pos):
                self._toggle_store_family(family)
                return True
        for sort_key, rect in self._store_sort_rects.items():
            if rect.collidepoint(pos):
                self._select_store_sort(sort_key)
                return True
        for item_id, rect in self._store_card_rects.items():
            if rect.collidepoint(pos):
                store.select(item_id)
                self._refresh_store_preview(item_id)
                return True
        return False

    def _play_confirm_sound(self) -> None:
        try:
            if pygame.mixer.get_init():
                tone = pygame.mixer.Sound(buffer=b"\x00\x00" * 12)
                tone.set_volume(0.35)
                tone.play()
        except pygame.error:
            return

    def _refresh_store_preview(self, item_id: Optional[str] = None) -> None:
        if item_id:
            store.select(item_id)
        selected = store.selected_item()
        if not selected:
            self._store_preview_data = None
            return
        try:
            self._store_preview_data = fitting.preview_with(selected.id)
        except RuntimeError:
            self._store_preview_data = None

    def _draw_store_filters(self, surface: pygame.Surface, rect: pygame.Rect, ship: Ship) -> None:
        self._blit_panel(surface, rect, (14, 24, 32, 210), (70, 108, 148))
        title = self.font.render("Filters", True, (214, 236, 255))
        surface.blit(title, (rect.x + 20, rect.y + 16))
        inner = rect.inflate(-36, -64)
        inner.y = rect.y + 54
        self._blit_panel(surface, inner, (10, 18, 26, 210), (56, 90, 126))
        y = inner.y + 16
        toggle_height = 36
        self._store_toggle_rects = {}
        for idx, (family, label) in enumerate([
            ("weapon", "Weapons"),
            ("hull", "Hull"),
            ("engine", "Engine"),
        ]):
            rect_toggle = pygame.Rect(inner.x + 12, y + idx * (toggle_height + 8), inner.width - 24, toggle_height)
            enabled = self._store_toggle_states.get(family, True)
            fill = (32, 56, 74, 230) if enabled else (22, 32, 44, 190)
            border = (120, 200, 255) if enabled else (60, 90, 118)
            self._blit_panel(surface, rect_toggle, fill, border, 1)
            text = self.small_font.render(label, True, (220, 236, 255) if enabled else (150, 176, 200))
            surface.blit(text, (rect_toggle.x + 16, rect_toggle.y + 8))
            self._store_toggle_rects[family] = rect_toggle
        y += 3 * (toggle_height + 8) + 12
        sort_label = self.small_font.render("Sort By", True, (208, 228, 248))
        surface.blit(sort_label, (inner.x + 12, y))
        y += 28
        self._store_sort_rects = {}
        for idx, (key, label, _default_desc) in enumerate(self._store_sort_options):
            option_rect = pygame.Rect(inner.x + 12, y + idx * (toggle_height - 4), inner.width - 24, toggle_height - 6)
            is_selected = key == self._store_sort_selection
            fill = (40, 66, 92, 230) if is_selected else (20, 32, 44, 200)
            border = (140, 210, 255) if is_selected else (58, 90, 120)
            self._blit_panel(surface, option_rect, fill, border, 1)
            label_text = self.mini_font.render(label, True, (214, 234, 252) if is_selected else (164, 190, 210))
            surface.blit(label_text, (option_rect.x + 14, option_rect.y + 6))
            order = "▼" if (is_selected and self._store_sort_desc) else "▲"
            order_surface = self.mini_font.render(order, True, (214, 234, 252))
            surface.blit(order_surface, (option_rect.right - 24, option_rect.y + 6))
            self._store_sort_rects[key] = option_rect
        y += len(self._store_sort_options) * (toggle_height - 4) + 8
        currency = self.small_font.render("Cubits", True, (200, 220, 242))
        surface.blit(currency, (inner.x + 12, y))
        amount = self.font.render(f"{ship.resources.cubits:,.0f}", True, (220, 238, 255))
        surface.blit(amount, (inner.x + 12, y + 22))
        ship_class = ship.frame.size if ship else "Ship"
        info_lines = [
            "Hold SHIFT for max preview",
            f"({ship_class} upgrades not captured)",
        ]
        for idx, line in enumerate(info_lines):
            text = self.mini_font.render(line, True, (150, 178, 200))
            surface.blit(text, (inner.x + 12, inner.bottom - 40 + idx * 16))

    def _draw_store_grid(self, surface: pygame.Surface, rect: pygame.Rect, ship: Ship) -> None:
        self._blit_panel(surface, rect, (18, 30, 42, 210), (70, 108, 148))
        header = self.font.render("Inventory", True, (214, 236, 255))
        surface.blit(header, (rect.x + 24, rect.y + 18))
        grid_rect = rect.inflate(-36, -72)
        grid_rect.y = rect.y + 56
        self._blit_panel(surface, grid_rect, (12, 20, 30, 210), (60, 96, 134))
        padding = 16
        scrollbar_width = 12
        track_gap = 6
        card_area_width = max(0, grid_rect.width - scrollbar_width - track_gap)
        columns = 1 if card_area_width < 420 else 2
        columns = max(1, columns)
        available_width = card_area_width - padding * (columns + 1)
        if available_width <= 0:
            card_width = max(1, card_area_width - 2 * padding)
        else:
            card_width = available_width // columns
        card_height = 240
        mouse_pos = pygame.mouse.get_pos()
        self._store_cards = store.list_items(self._store_filters)
        self._store_card_rects = {}
        self._store_buy_rects = {}
        self._store_hover_item = None
        view_width = max(0, card_area_width - 2 * padding)
        view_height = max(0, grid_rect.height - 2 * padding)
        self._store_inventory_view = pygame.Rect(
            grid_rect.x + padding,
            grid_rect.y + padding,
            view_width,
            view_height,
        )
        total_rows = (len(self._store_cards) + columns - 1) // columns if self._store_cards else 0
        if total_rows > 0:
            content_height = padding + total_rows * (card_height + padding)
        else:
            content_height = view_height
        self._store_view_height = float(view_height)
        self._store_content_height = float(max(content_height, view_height))
        max_offset = max(0.0, self._store_content_height - self._store_view_height)
        if max_offset <= 0.0:
            self._store_scroll_offset = 0.0
            self._store_scrollbar_dragging = False
        else:
            self._store_scroll_offset = min(self._store_scroll_offset, max_offset)
        if self._store_inventory_view.width > 0 and self._store_inventory_view.height > 0:
            surface.set_clip(self._store_inventory_view)
        origin_x = grid_rect.x + padding
        origin_y = grid_rect.y + padding
        for index, card in enumerate(self._store_cards):
            col = index % columns
            row = index // columns
            card_rect = pygame.Rect(
                origin_x + col * (card_width + padding),
                origin_y + row * (card_height + padding) - int(self._store_scroll_offset),
                card_width,
                card_height,
            )
            if card_rect.bottom < self._store_inventory_view.top or card_rect.top > self._store_inventory_view.bottom:
                continue
            self._draw_store_card(surface, card_rect, card, mouse_pos)
            self._store_card_rects[card.item.id] = card_rect
        surface.set_clip(None)
        if not self._store_cards:
            empty_text = self.small_font.render("No items match the current filters.", True, (170, 196, 214))
            surface.blit(empty_text, (grid_rect.x + 18, grid_rect.y + 24))
        scrollbar_rect = pygame.Rect(
            grid_rect.x + card_area_width + track_gap,
            grid_rect.y + padding,
            scrollbar_width,
            view_height,
        )
        self._store_scrollbar_rect = scrollbar_rect
        self._store_scrollbar_thumb_rect = None
        if scrollbar_rect.width > 0 and scrollbar_rect.height > 0:
            self._blit_panel(surface, scrollbar_rect, (20, 32, 44, 200), (58, 90, 120))
            if max_offset > 0.0:
                thumb_ratio = self._store_view_height / self._store_content_height if self._store_content_height else 1.0
                thumb_height = max(36, int(scrollbar_rect.height * thumb_ratio))
                thumb_height = min(scrollbar_rect.height, thumb_height)
                track_span = scrollbar_rect.height - thumb_height
                if track_span <= 0:
                    thumb_top = scrollbar_rect.y
                else:
                    fraction = self._store_scroll_offset / max_offset if max_offset else 0.0
                    thumb_top = scrollbar_rect.y + int(track_span * fraction)
                thumb_rect = pygame.Rect(scrollbar_rect.x, thumb_top, scrollbar_rect.width, thumb_height)
                self._store_scrollbar_thumb_rect = thumb_rect
                self._blit_panel(surface, thumb_rect, (52, 86, 116, 220), (142, 202, 248))

    def _draw_store_card(
        self,
        surface: pygame.Surface,
        rect: pygame.Rect,
        card: ItemCardData,
        mouse_pos: Tuple[int, int],
    ) -> None:
        selected = card.selected
        hovered = rect.collidepoint(mouse_pos)
        fill = (34, 52, 70, 230) if selected or hovered else (22, 34, 46, 210)
        border = (140, 210, 255) if selected else (72, 110, 148)
        self._blit_panel(surface, rect, fill, border, 1)
        icon = self._slot_icons.get(card.item.slot_family)
        name_color = (220, 240, 255)
        title = self.small_font.render(card.item.name, True, name_color)
        surface.blit(title, (rect.x + 16, rect.y + 12))
        slot_label = f"{card.item.slot_family.title()} • {card.item.ship_class} only"
        subtitle = self.mini_font.render(slot_label, True, (172, 198, 220))
        surface.blit(subtitle, (rect.x + 16, rect.y + 32))
        if icon:
            icon_rect = icon.get_rect()
            icon_rect.topright = (rect.right - 16, rect.y + 12)
            surface.blit(icon, icon_rect.topleft)
        stats_y = rect.y + 58
        highlight_lines = self._store_highlight_lines(card.item)
        for idx, line in enumerate(highlight_lines):
            text = self.mini_font.render(line, True, (204, 226, 248))
            surface.blit(text, (rect.x + 16, stats_y + idx * 16))
        cursor_y = stats_y + len(highlight_lines) * 16 + 8
        bottom_limit = rect.y + rect.height - 110
        cursor_y = min(cursor_y, bottom_limit)
        upgrades = ", ".join(axis.replace("_", " ").title() for axis in card.item.upgrades)
        if upgrades:
            upgrade_text = self.mini_font.render(f"Upgrades: {upgrades}", True, (186, 208, 230))
            surface.blit(upgrade_text, (rect.x + 16, cursor_y))
            cursor_y = min(cursor_y + 18, rect.y + rect.height - 96)
        tags_text = ", ".join(card.item.tags)
        if tags_text:
            cursor_y = min(cursor_y, rect.y + rect.height - 82)
            tags = self.mini_font.render(tags_text.upper(), True, (150, 182, 210))
            surface.blit(tags, (rect.x + 16, cursor_y))
            cursor_y += 18
        price_text = self.small_font.render(f"Price: {card.item.price:,.0f}", True, (214, 232, 252))
        surface.blit(price_text, (rect.x + 16, rect.y + rect.height - 54))
        dura_text = self.mini_font.render(
            f"Durability: {card.item.durability:,.0f} / {card.item.durability_max:,.0f}",
            True,
            (168, 194, 214),
        )
        surface.blit(dura_text, (rect.x + 16, rect.y + rect.height - 38))
        buy_rect = pygame.Rect(rect.right - 96, rect.y + rect.height - 46, 80, 32)
        can_buy = card.affordable
        buy_fill = (58, 112, 150, 230) if can_buy else (32, 46, 58, 180)
        buy_border = (160, 220, 255) if can_buy else (68, 96, 122)
        self._blit_panel(surface, buy_rect, buy_fill, buy_border, 1)
        label = self.small_font.render("Buy", True, (220, 240, 255) if can_buy else (136, 160, 182))
        surface.blit(
            label,
            (
                buy_rect.centerx - label.get_width() // 2,
                buy_rect.centery - label.get_height() // 2,
            ),
        )
        if not can_buy:
            tooltip = self.mini_font.render("Insufficient funds", True, (180, 102, 102))
            surface.blit(tooltip, (rect.x + 16, rect.y + rect.height - 20))
        self._store_buy_rects[card.item.id] = buy_rect
        if hovered:
            self._store_hover_item = card.item.id
        if pygame.key.get_mods() & pygame.KMOD_SHIFT:
            badge = self.mini_font.render("Higher levels: data not captured", True, (214, 232, 252))
            surface.blit(badge, (rect.x + 16, rect.y + rect.height - 88))

    def _store_highlight_lines(self, item: ItemCardData | StoreItem) -> List[str]:
        data = item.item if isinstance(item, ItemCardData) else item
        stats = data.stats
        if data.slot_family == "weapon":
            lines: List[str] = []
            if "burst_count" in stats:
                lines.append(f"Damage {stats['damage_min']:.0f} ×{int(stats['burst_count'])}")
            elif stats.get("damage_min") != stats.get("damage_max"):
                lines.append(f"Damage {stats['damage_min']:.0f}–{stats['damage_max']:.0f}")
            else:
                lines.append(f"Damage {stats.get('damage_max', 0.0):.0f}")
            lines.append(f"AP {stats.get('armor_piercing', 0.0):.0f}")
            lines.append(f"Optimal {stats.get('optimal_range', 0.0):.0f} m")
            if "range_min" in stats and "range_max" in stats:
                lines.append(
                    f"Range {stats['range_min']:.0f}–{stats['range_max']:.0f} m"
                )
            lines.append(f"Reload {stats.get('reload', 0.0):.2f} s")
            lines.append(f"Power {stats.get('power', 0.0):.0f}")
            lines.append(f"Accuracy {stats.get('accuracy', 0.0):.0f}")
            lines.append(f"Crit Offense {stats.get('critical_offense', 0.0):.0f}")
            lines.append(f"Firing Arc {stats.get('firing_arc', 0.0):.0f}°")
            if "turn_speed" in stats:
                lines.append(f"Turn {stats['turn_speed']:.0f}°/s")
            if "projectile_speed" in stats:
                lines.append(f"Speed {stats['projectile_speed']:.0f} m/s")
            if "damage_per_second" in stats:
                lines.append(f"DPS {stats['damage_per_second']:.1f}")
            return lines
        if data.slot_family == "hull":
            lines = []
            if "armor" in stats:
                lines.append(f"Armor +{stats['armor']:.2f}")
            if "hull_hp" in stats:
                lines.append(f"Hull +{stats['hull_hp']:.1f}")
            if "acceleration" in stats:
                lines.append(f"Accel {stats['acceleration']:+.1f}")
            if "turn_accel" in stats:
                lines.append(f"Turn Accel {stats['turn_accel']:+.2f}")
            if "avoidance_rating" in stats:
                lines.append(f"Avoidance +{stats['avoidance_rating']:.0f}")
            return lines
        if data.slot_family == "engine":
            lines = []
            if "max_speed" in stats:
                lines.append(f"Speed +{stats['max_speed']:.2f} m/s")
            if "boost_speed" in stats:
                lines.append(f"Boost +{stats['boost_speed']:.2f} m/s")
            if "acceleration" in stats:
                lines.append(f"Accel {stats['acceleration']:+.2f}")
            if "turn_rate" in stats:
                lines.append(f"Turn {stats['turn_rate']:+.2f}°/s")
            if "turn_accel" in stats:
                lines.append(f"Turn Accel {stats['turn_accel']:+.2f}°/s²")
            if "avoidance_rating" in stats:
                lines.append(f"Avoidance +{stats['avoidance_rating']:.0f}")
            return lines
        return []

    def _draw_store_preview(self, surface: pygame.Surface, rect: pygame.Rect, ship: Ship) -> None:
        self._blit_panel(surface, rect, (18, 32, 44, 210), (70, 110, 150))
        header = self.font.render("Preview", True, (214, 236, 255))
        surface.blit(header, (rect.x + 22, rect.y + 18))
        inner = rect.inflate(-32, -72)
        inner.y = rect.y + 56
        self._blit_panel(surface, inner, (12, 20, 28, 210), (60, 92, 130))
        selected = store.selected_item()
        if not selected:
            ship_class = ship.frame.size if ship else "Ship"
            message = self.small_font.render(
                f"Select a {ship_class} item to preview",
                True,
                (176, 204, 222),
            )
            surface.blit(message, (inner.x + 12, inner.y + 12))
            return
        if not self._store_preview_data:
            self._refresh_store_preview(selected.id)
        preview_data = self._store_preview_data or {"deltas_by_stat": {}, "current": {}, "preview": {}}
        y = inner.y + 12
        title = self.small_font.render(selected.name, True, (220, 240, 255))
        surface.blit(title, (inner.x + 12, y))
        y += 26
        lines = self._preview_lines_for_item(selected, preview_data)
        for label, current_value, preview_value in lines:
            delta = preview_value - current_value
            base_text = self.mini_font.render(f"{label}: {current_value:.2f}", True, (176, 202, 222))
            surface.blit(base_text, (inner.x + 12, y))
            delta_color = (120, 210, 150) if delta >= 0 else (210, 110, 110)
            delta_text = self.mini_font.render(f"{delta:+.2f}", True, delta_color)
            surface.blit(delta_text, (inner.x + inner.width - delta_text.get_width() - 12, y))
            y += 20
        if pygame.key.get_mods() & pygame.KMOD_SHIFT:
            badge = self.mini_font.render("Higher levels: data not captured", True, (214, 234, 252))
            surface.blit(badge, (inner.x + 12, inner.bottom - 24))

    def _preview_lines_for_item(
        self, item: StoreItem, preview_data: Dict[str, Dict[str, float]]
    ) -> List[Tuple[str, float, float]]:
        deltas = preview_data.get("deltas_by_stat", {})
        current = preview_data.get("current", {})
        preview_stats = preview_data.get("preview", {})
        lines: List[Tuple[str, float, float]] = []
        if item.slot_family == "hull":
            for key, label in (
                ("hull_hp", "Hull"),
                ("armor", "Armor"),
                ("acceleration", "Acceleration"),
                ("turn_accel", "Turn Accel"),
            ):
                if key in deltas:
                    lines.append((label, current.get(key, 0.0), preview_stats.get(key, 0.0)))
        elif item.slot_family == "engine":
            for key, label in (
                ("max_speed", "Speed"),
                ("boost_speed", "Boost"),
                ("acceleration", "Acceleration"),
                ("turn_rate", "Turn"),
                ("turn_accel", "Turn Accel"),
                ("avoidance_rating", "Avoidance"),
            ):
                if key in deltas:
                    lines.append((label, current.get(key, 0.0), preview_stats.get(key, 0.0)))
        else:
            # Weapons preview: show damage values directly.
            stats = item.stats
            lines.extend(
                [
                    ("Damage Min", stats.get("damage_min", 0.0), stats.get("damage_min", 0.0)),
                    ("Damage Max", stats.get("damage_max", 0.0), stats.get("damage_max", 0.0)),
                    ("Optimal Range", stats.get("optimal_range", 0.0), stats.get("optimal_range", 0.0)),
                    ("Range Min", stats.get("range_min", 0.0), stats.get("range_min", 0.0)),
                    ("Range Max", stats.get("range_max", 0.0), stats.get("range_max", 0.0)),
                    ("Crit Offense", stats.get("critical_offense", 0.0), stats.get("critical_offense", 0.0)),
                    ("Armor Piercing", stats.get("armor_piercing", 0.0), stats.get("armor_piercing", 0.0)),
                    ("Reload", stats.get("reload", 0.0), stats.get("reload", 0.0)),
                    ("Power", stats.get("power", 0.0), stats.get("power", 0.0)),
                ]
            )
            if "turn_speed" in stats:
                lines.append(("Turn Speed", stats["turn_speed"], stats["turn_speed"]))
            if "projectile_speed" in stats:
                lines.append(("Projectile Speed", stats["projectile_speed"], stats["projectile_speed"]))
            if "damage_per_second" in stats:
                lines.append(("Damage / s", stats["damage_per_second"], stats["damage_per_second"]))
        return lines

    def _draw_hold_panel(self, surface: pygame.Surface, rect: pygame.Rect, ship: Ship) -> None:
        items = self._gather_hold_items(ship)
        self._hold_rows = []
        row_height = 76
        spacing = 10
        capacity_text = self.mini_font.render(
            f"Capacity: {ship.hold_item_count():.0f}/{ship.hold_capacity}",
            True,
            (214, 232, 255) if ship.hold_item_count() < ship.hold_capacity else (220, 160, 150),
        )
        surface.blit(capacity_text, (rect.x + 16, rect.y + 12))
        y = rect.y + 36
        for item in items:
            row_rect = pygame.Rect(rect.x + 12, y, rect.width - 24, row_height)
            fill = (18, 30, 44, 220) if item.can_sell else (14, 24, 34, 200)
            border = (90, 150, 210) if item.can_sell else (58, 86, 112)
            self._blit_panel(surface, row_rect, fill, border, 1)

            icon = self._hold_icons.get(item.icon_key)
            if icon:
                icon_rect = icon.get_rect()
                icon_rect.x = row_rect.x + 16
                icon_rect.centery = row_rect.centery
                surface.blit(icon, icon_rect.topleft)
            text_x = row_rect.x + 72
            name_text = self.small_font.render(item.name, True, (214, 232, 255))
            surface.blit(name_text, (text_x, row_rect.y + 12))

            amount_display = self._format_amount_display(item.amount)
            amount_text = self.mini_font.render(f"Amount: {amount_display}", True, (182, 210, 228))
            surface.blit(amount_text, (text_x, row_rect.y + 36))

            if item.description:
                desc_text = self.mini_font.render(item.description, True, (148, 178, 200))
                surface.blit(desc_text, (text_x, row_rect.y + 54))

            button_rect: Optional[pygame.Rect] = None
            action: Optional[str] = None
            enabled = False
            if item.equippable and item.store_item:
                button_rect = pygame.Rect(row_rect.right - 110, row_rect.centery - 18, 98, 36)
                enabled = item.amount > 0.0 and self._can_equip_store_item(ship, item.store_item)
                action = "equip"
                fill_color = (60, 110, 150, 230) if enabled else (34, 46, 60, 200)
                border_color = (150, 220, 255) if enabled else (72, 96, 120)
                self._blit_panel(surface, button_rect, fill_color, border_color, 1)
                label = self.small_font.render("Equip", True, (220, 238, 255) if enabled else (150, 170, 188))
                surface.blit(
                    label,
                    (
                        button_rect.centerx - label.get_width() // 2,
                        button_rect.centery - label.get_height() // 2,
                    ),
                )
                upgrade_rect = pygame.Rect(button_rect.x - 108, button_rect.y, 98, 36)
                upgrade_spec = (
                    EQUIPMENT_UPGRADE_SPECS.get(item.store_item.id)
                    if item.store_item
                    else None
                )
                upgrade_enabled = bool(upgrade_spec and item.amount > 0.0)
                upgrade_fill = (70, 130, 180, 230) if upgrade_enabled else (32, 44, 58, 200)
                upgrade_border = (170, 230, 255) if upgrade_enabled else (70, 96, 120)
                self._blit_panel(surface, upgrade_rect, upgrade_fill, upgrade_border, 1)
                upgrade_label = self.small_font.render(
                    "Upgrade", True, (220, 240, 255) if upgrade_enabled else (150, 170, 188)
                )
                surface.blit(
                    upgrade_label,
                    (
                        upgrade_rect.centerx - upgrade_label.get_width() // 2,
                        upgrade_rect.centery - upgrade_label.get_height() // 2,
                    ),
                )
                if not enabled:
                    status = "No free slot" if item.amount > 0.0 else "None owned"
                    note_text = self.mini_font.render(status, True, (150, 170, 188))
                    surface.blit(note_text, (row_rect.x + 16, row_rect.bottom - note_text.get_height() - 12))
            elif item.can_sell and item.sell_rate and item.sell_currency and item.price_icon_key:
                price_icon = self._price_icons.get(item.price_icon_key)
                currency_name = self._format_currency_name(item.sell_currency)
                price_value = self._format_amount_display(item.sell_rate or 0.0)
                price_text = self.mini_font.render(f"{price_value} {currency_name}", True, (220, 230, 200))
                if price_icon:
                    combo_width = price_icon.get_width() + 6 + price_text.get_width()
                    start_x = row_rect.centerx - combo_width // 2
                    icon_rect = price_icon.get_rect()
                    icon_rect.x = start_x
                    icon_rect.bottom = row_rect.bottom - 10
                    text_pos = (icon_rect.right + 6, row_rect.bottom - price_text.get_height() - 12)
                    surface.blit(price_icon, icon_rect.topleft)
                    surface.blit(price_text, text_pos)
                else:
                    text_pos = (
                        row_rect.centerx - price_text.get_width() // 2,
                        row_rect.bottom - price_text.get_height() - 12,
                    )
                    surface.blit(price_text, text_pos)

                button_rect = pygame.Rect(row_rect.right - 96, row_rect.centery - 18, 84, 36)
                button_color = (46, 88, 126) if item.amount > 0.0 else (32, 44, 56)
                border_color = (150, 220, 255) if item.amount > 0.0 else (68, 96, 120)
                self._blit_panel(surface, button_rect, (*button_color, 220), border_color, 1)
                label_color = (214, 236, 255) if item.amount > 0.0 else (130, 160, 180)
                label = self.small_font.render("Sell", True, label_color)
                surface.blit(
                    label,
                    (
                        button_rect.centerx - label.get_width() // 2,
                        button_rect.centery - label.get_height() // 2,
                    ),
                )
                action = "sell"
                enabled = item.amount > 0.0
            else:
                note = "Not for sale"
                if item.key == "cubits":
                    note = "Station currency balance"
                elif item.key == "tylium":
                    note = "Fuel and trade reserve"
                status_text = self.mini_font.render(note, True, (132, 158, 182))
                surface.blit(
                    status_text,
                    (
                        row_rect.centerx - status_text.get_width() // 2,
                        row_rect.bottom - status_text.get_height() - 12,
                    ),
                )

            self._hold_rows.append(
                _HoldRow(
                    item=item,
                    rect=row_rect,
                    button_rect=button_rect,
                    action=action,
                    enabled=enabled,
                    upgrade_rect=upgrade_rect if item.equippable and item.store_item else None,
                    upgrade_enabled=upgrade_enabled if item.equippable and item.store_item else False,
                )
            )
            y += row_height + spacing

    def _gather_hold_items(self, ship: Ship) -> List[_HoldItem]:
        resources = ship.resources
        items: List[_HoldItem] = [
            _HoldItem(
                key="tylium",
                name="Tylium",
                amount=float(resources.tylium),
                icon_key="tylium",
                description="Primary fuel and trade stock.",
            ),
            _HoldItem(
                key="water",
                name="Water",
                amount=float(resources.water),
                icon_key="water",
                can_sell=True,
                sell_rate=0.2,
                sell_currency="cubits",
                price_icon_key="gem",
                description="Fresh reserves collected from mining.",
            ),
            _HoldItem(
                key="titanium",
                name="Titanium",
                amount=float(resources.titanium),
                icon_key="titanium",
                can_sell=True,
                sell_rate=0.5,
                sell_currency="tylium",
                price_icon_key="coin",
                description="Structural alloy cargo.",
            ),
            _HoldItem(
                key="cubits",
                name="Cubits",
                amount=float(resources.cubits),
                icon_key="cubits",
                description="Station exchange currency.",
            ),
        ]
        for item_id in sorted(ship.hold_items.keys()):
            quantity = ship.hold_items[item_id]
            if quantity <= 0:
                continue
            store_item = CATALOG.get(item_id)
            if store_item:
                icon_key = store_item.slot_family
                items.append(
                    _HoldItem(
                        key=item_id,
                        name=store_item.name,
                        amount=float(quantity),
                        icon_key=icon_key if icon_key in self._hold_icons else "module",
                        description=store_item.description,
                        equippable=True,
                        slot_family=store_item.slot_family,
                        store_item=store_item,
                        item_id=item_id,
                        instance_index=0,
                        location="hold",
                    )
                )
            else:
                items.append(
                    _HoldItem(
                        key=item_id,
                        name=item_id.replace("_", " ").title(),
                        amount=float(quantity),
                        icon_key="module",
                        description="Stored equipment.",
                    )
                )
        return items

    def _item_current_level(self, ship: Ship, item: _HoldItem) -> int:
        if not item.store_item:
            return 1
        if item.location == "hold":
            index = item.instance_index or 0
            return ship.hold_item_level(item.store_item.id, index)
        if item.location == "module":
            slot_type = item.slot_family or item.store_item.slot_family
            if slot_type is None:
                return ship.item_level(item.store_item.id)
            index = item.slot_index or 0
            return ship.module_level(slot_type, index)
        if item.location == "weapon":
            if item.mount_index is None:
                return ship.item_level(item.store_item.id)
            return ship.weapon_level(item.mount_index)
        return ship.item_level(item.store_item.id)

    def _set_item_level(self, ship: Ship, item: _HoldItem, level: int) -> None:
        if not item.store_item:
            return
        if item.location == "hold":
            index = item.instance_index or 0
            ship.set_hold_item_level(item.store_item.id, index, level)
            return
        if item.location == "module":
            slot_type = item.slot_family or item.store_item.slot_family
            if slot_type is None:
                ship.set_item_level(item.store_item.id, level)
                return
            index = item.slot_index or 0
            ship.set_module_level(slot_type, index, level)
            return
        if item.location == "weapon":
            if item.mount_index is not None:
                ship.set_weapon_level(item.mount_index, level)
            return
        ship.set_item_level(item.store_item.id, level)

    def _can_equip_store_item(self, ship: Ship, item: StoreItem) -> bool:
        family = item.slot_family.lower()
        if family == "weapon":
            return any(not mount.weapon_id for mount in ship.mounts)
        if family in {"hull", "engine", "computer", "utility"}:
            capacity = getattr(ship.frame.slots, family, 0)
            return len(ship.modules_by_slot.get(family, [])) < capacity
        return False

    def _equip_hold_item(self, item: _HoldItem) -> bool:
        ship = self._current_ship
        if not ship or not item.store_item or item.amount <= 0.0:
            return False
        store_item = item.store_item
        if not self._can_equip_store_item(ship, store_item):
            return False
        removed_levels = ship.remove_hold_item(
            store_item.id, index=item.instance_index or 0
        )
        if not removed_levels:
            return False
        level = removed_levels[0]
        success = False
        family = store_item.slot_family.lower()
        if family in {"hull", "engine", "computer", "utility"}:
            module = ItemData(
                id=store_item.id,
                slot_type=store_item.slot_family,
                name=store_item.name,
                tags=list(store_item.tags),
                stats=dict(store_item.stats),
            )
            success = ship.equip_module(module, level=level)
        elif family == "weapon":
            mount_info = self._find_available_mount(ship, store_item.slot_family)
            if mount_info:
                mount_index, mount = mount_info
                mount.weapon_id = store_item.id
                mount.level = max(1, int(level))
                success = True
        if not success:
            ship.add_hold_item(store_item.id, level=level)
            return False
        store.bind_ship(ship)
        return True

    def _find_available_mount(
        self, ship: Ship, slot_family: str
    ) -> Optional[tuple[int, WeaponMount]]:
        normalized = slot_family.lower()
        for index, mount in enumerate(ship.mounts):
            if not mount.weapon_id and self._slot_matches(mount.hardpoint.slot, normalized):
                return index, mount
        for index, mount in enumerate(ship.mounts):
            if not mount.weapon_id:
                return index, mount
        return None

    def _weapon_mount_at_index(
        self, ship: Ship, slot_type: str, index: int
    ) -> Optional[tuple[int, WeaponMount]]:
        normalized = slot_type.lower()
        mounts = [
            mount
            for mount in ship.mounts
            if self._slot_matches(mount.hardpoint.slot, normalized)
        ]
        if 0 <= index < len(mounts):
            mount = mounts[index]
            return ship.mounts.index(mount), mount
        return None

    def _unequip_slot(self, widget: _SlotDisplay) -> bool:
        ship = self._current_ship
        if not ship or not widget.filled:
            return False
        if not ship.can_store_in_hold():
            return False
        if widget.category == "weapon":
            mount_info = self._weapon_mount_at_index(ship, widget.slot_type, widget.index)
            if not mount_info:
                return False
            mount_index, mount = mount_info
            if not mount.weapon_id:
                return False
            item_id = mount.weapon_id
            level = mount.level if hasattr(mount, "level") else 1
            if not ship.add_hold_item(item_id, level=level):
                return False
            mount.weapon_id = None
            mount.level = 1
            store.bind_ship(ship)
            return True
        result = ship.unequip_module(widget.slot_type, widget.index)
        if not result:
            return False
        module, level = result
        if not module.id:
            return False
        if not ship.add_hold_item(module.id, level=level):
            ship.equip_module(module, level=level, index=widget.index)
            modules = ship.modules_by_slot.get(widget.slot_type, [])
            if modules:
                modules.insert(widget.index, modules.pop())
            return False
        store.bind_ship(ship)
        return True

    def _open_upgrade_dialog_for_slot(self, widget: _SlotDisplay) -> None:
        if not self._current_ship or not widget.filled:
            return
        store_item = self._store_item_for_slot(widget)
        if not store_item:
            return
        icon_key = store_item.slot_family.lower()
        if icon_key not in self._hold_icons:
            icon_key = "module"
        location = "module"
        instance_index = 0
        slot_index = widget.index
        mount_index: Optional[int] = None
        if widget.category == "weapon":
            mount_info = self._weapon_mount_at_index(
                self._current_ship, widget.slot_type, widget.index
            )
            if not mount_info:
                return
            mount_index, mount = mount_info
            if not mount.weapon_id:
                return
            location = "weapon"
        item_id = store_item.id
        item = _HoldItem(
            key=store_item.id,
            name=store_item.name,
            amount=1.0,
            icon_key=icon_key,
            description=store_item.description,
            equippable=True,
            slot_family=store_item.slot_family,
            store_item=store_item,
            item_id=item_id,
            instance_index=instance_index,
            slot_index=slot_index,
            location=location,
            mount_index=mount_index,
        )
        self._open_upgrade_dialog(item)

    def _store_item_for_slot(self, widget: _SlotDisplay) -> Optional[StoreItem]:
        ship = self._current_ship
        if not ship or not widget.filled:
            return None
        if widget.category == "weapon":
            mount_info = self._weapon_mount_at_index(ship, widget.slot_type, widget.index)
            if mount_info:
                _, mount = mount_info
                if mount.weapon_id:
                    return CATALOG.get(mount.weapon_id)
            return None
        modules = ship.modules_by_slot.get(widget.slot_type, [])
        if 0 <= widget.index < len(modules):
            module = modules[widget.index]
            if module and module.id:
                return CATALOG.get(module.id)
        return None

    def _handle_sell_dialog_event(self, event: pygame.event.Event) -> bool:
        if not self._sell_dialog:
            return False
        dialog = self._sell_dialog
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self._sell_dialog = None
                return True
            if event.key == pygame.K_RETURN:
                self._confirm_sell()
                return True
            if event.key == pygame.K_BACKSPACE:
                dialog.input_value = dialog.input_value[:-1]
                if not dialog.input_value:
                    dialog.input_value = "0"
                return True
            char = event.unicode
            if char.isdigit():
                if dialog.input_value == "0":
                    dialog.input_value = char
                else:
                    dialog.input_value += char
                return True
            if char == "." and "." not in dialog.input_value:
                dialog.input_value = dialog.input_value + "." if dialog.input_value else "0."
                return True
            return False
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            pos = getattr(event, "pos", None)
            if not pos:
                return False
            if dialog.confirm_rect.collidepoint(pos):
                self._confirm_sell()
                return True
            if dialog.cancel_rect.collidepoint(pos):
                self._sell_dialog = None
                return True
            if not dialog.rect.collidepoint(pos):
                self._sell_dialog = None
                return True
        return False

    def _open_sell_dialog(self, item: _HoldItem) -> None:
        initial_amount = max(0.0, min(item.amount, 1.0 if item.amount >= 1.0 else item.amount))
        input_value = self._format_amount_string(initial_amount if initial_amount > 0.0 else 0.0)
        self._sell_dialog = _SellDialog(
            item_key=item.key,
            item_name=item.name,
            sell_currency=item.sell_currency or "tylium",
            sell_rate=item.sell_rate or 0.0,
            price_icon_key=item.price_icon_key or "coin",
            input_value=input_value,
            available=item.amount,
        )

    def _draw_sell_dialog(self, surface: pygame.Surface) -> None:
        if not self._sell_dialog:
            return
        dialog = self._sell_dialog
        width, height = surface.get_size()
        overlay = pygame.Surface((width, height), pygame.SRCALPHA)
        overlay.fill((6, 10, 16, 180))
        surface.blit(overlay, (0, 0))

        box_width = max(340, int(width * 0.3))
        box_height = max(260, int(height * 0.32))
        rect = pygame.Rect((width - box_width) // 2, (height - box_height) // 2, box_width, box_height)
        self._blit_panel(surface, rect, (18, 30, 44, 240), (120, 200, 255), 2)
        dialog.rect = rect

        available = self._resource_amount(dialog.item_key)
        dialog.available = available
        amount = self._sanitize_dialog_input(dialog, available)
        expected = amount * dialog.sell_rate
        currency_name = self._format_currency_name(dialog.sell_currency)

        title = self.font.render(f"Sell {dialog.item_name}", True, (220, 238, 255))
        surface.blit(title, (rect.x + 28, rect.y + 22))

        available_text = self.mini_font.render(
            f"In hold: {self._format_amount_display(available)}",
            True,
            (190, 214, 232),
        )
        surface.blit(available_text, (rect.x + 28, rect.y + 62))

        amount_label = self.small_font.render("Amount to sell", True, (210, 230, 248))
        surface.blit(amount_label, (rect.x + 28, rect.y + 92))

        input_rect = pygame.Rect(rect.x + 28, rect.y + 120, rect.width - 56, 44)
        self._blit_panel(surface, input_rect, (10, 20, 32, 230), (120, 200, 255), 1)
        value_display = dialog.input_value or "0"
        input_text = self.font.render(value_display, True, (220, 236, 255))
        surface.blit(
            input_text,
            (
                input_rect.centerx - input_text.get_width() // 2,
                input_rect.centery - input_text.get_height() // 2,
            ),
        )

        expected_text = self.small_font.render(
            f"Receive: {self._format_amount_display(expected)} {currency_name}",
            True,
            (230, 236, 210) if dialog.sell_currency == "tylium" else (214, 236, 255),
        )
        expected_y = input_rect.bottom + 30
        if dialog.price_icon_key in self._price_icons:
            icon = self._price_icons[dialog.price_icon_key]
            icon_rect = icon.get_rect()
            icon_rect.x = rect.x + 28
            icon_rect.centery = expected_y + expected_text.get_height() // 2
            surface.blit(icon, icon_rect.topleft)
            surface.blit(expected_text, (icon_rect.right + 8, expected_y))
        else:
            surface.blit(expected_text, (rect.x + 28, expected_y))

        button_y = rect.bottom - 58
        cancel_rect = pygame.Rect(rect.x + 32, button_y, 104, 40)
        confirm_rect = pygame.Rect(rect.right - 136, button_y, 104, 40)
        self._blit_panel(surface, cancel_rect, (26, 36, 48, 220), (100, 140, 180), 1)
        cancel_label = self.small_font.render("Cancel", True, (182, 208, 224))
        surface.blit(
            cancel_label,
            (
                cancel_rect.centerx - cancel_label.get_width() // 2,
                cancel_rect.centery - cancel_label.get_height() // 2,
            ),
        )

        confirm_fill = (46, 92, 132, 240) if amount > 0.0 else (24, 32, 44, 220)
        confirm_border = (150, 220, 255) if amount > 0.0 else (88, 120, 150)
        self._blit_panel(surface, confirm_rect, confirm_fill, confirm_border, 1)
        confirm_label = self.small_font.render("Confirm", True, (214, 236, 255) if amount > 0.0 else (144, 170, 188))
        surface.blit(
            confirm_label,
            (
                confirm_rect.centerx - confirm_label.get_width() // 2,
                confirm_rect.centery - confirm_label.get_height() // 2,
            ),
        )

        dialog.confirm_rect = confirm_rect
        dialog.cancel_rect = cancel_rect

    def _draw_upgrade_dialog(self, surface: pygame.Surface) -> None:
        if not self._upgrade_dialog or not self._current_ship:
            return
        dialog = self._upgrade_dialog
        ship = self._current_ship
        model = dialog.model
        model.player_resources = self._resource_snapshot(ship)

        width, height = surface.get_size()
        overlay = pygame.Surface((width, height), pygame.SRCALPHA)
        overlay.fill((6, 10, 16, 220))
        surface.blit(overlay, (0, 0))

        box_width = min(900, int(width * 0.72))
        box_height = min(680, int(height * 0.78))
        box_width = max(720, box_width)
        box_height = max(520, box_height)
        rect = pygame.Rect((width - box_width) // 2, (height - box_height) // 2, box_width, box_height)
        self._blit_panel(surface, rect, (18, 30, 44, 238), (120, 200, 255), 2)
        dialog.rect = rect

        header_rect = pygame.Rect(rect.x + 28, rect.y + 20, rect.width - 56, 90)
        icon = self._hold_icons.get(dialog.item.icon_key or dialog.store_item.slot_family)
        text_x = header_rect.x
        if icon:
            icon_rect = icon.get_rect()
            icon_rect.x = header_rect.x
            icon_rect.centery = header_rect.centery
            surface.blit(icon, icon_rect.topleft)
            text_x = icon_rect.right + 18

        name_text = self.font.render(dialog.store_item.name, True, (224, 240, 255))
        surface.blit(name_text, (text_x, header_rect.y + 4))

        level_label = self.small_font.render(
            f"Level {model.current_level} / {dialog.spec.level_cap}",
            True,
            (182, 208, 232),
        )
        surface.blit(level_label, (text_x, header_rect.y + 34))

        effect_rect = pygame.Rect(header_rect.right - 320, header_rect.y, 300, header_rect.height)
        self._draw_wrapped_text(
            surface,
            dialog.spec.effect,
            self.mini_font,
            (176, 206, 232),
            effect_rect,
        )

        pip_area = pygame.Rect(rect.x + 56, header_rect.bottom + 12, rect.width - 112, 60)
        self._draw_upgrade_pips(surface, pip_area, dialog)

        table_top = pip_area.bottom + 16
        table_rect = pygame.Rect(rect.x + 32, table_top, rect.width - 64, rect.bottom - table_top - 118)
        self._blit_panel(surface, table_rect, (12, 22, 32, 220), (80, 124, 168), 1)

        row_height = 34
        label_x = table_rect.x + 18
        current_x = table_rect.x + int(table_rect.width * 0.46)
        preview_x = table_rect.x + int(table_rect.width * 0.7)
        delta_x = table_rect.right - 20
        y = table_rect.y + 14
        dialog.row_rects = []
        tooltip_text: Optional[str] = None

        rows = self._stat_rows_for_slot(dialog.spec.slot)
        for row in rows:
            row_rect = pygame.Rect(table_rect.x + 8, y - 6, table_rect.width - 16, row_height)
            if dialog.flash_timer > 0.0 and row.axis and row.axis in dialog.flash_axes:
                highlight = pygame.Surface((row_rect.width, row_rect.height), pygame.SRCALPHA)
                intensity = int(120 * dialog.flash_timer)
                intensity = max(30, min(120, intensity))
                highlight.fill((70, 150, 200, intensity))
                surface.blit(highlight, row_rect.topleft)

            current_values: List[float] = []
            preview_values: List[float] = []
            preview_known = True
            for key in row.keys:
                current_value, _ = model.stat_value(key, model.current_level)
                preview_value, known = model.stat_value(key, model.preview_level)
                current_values.append(current_value)
                preview_values.append(preview_value)
                preview_known = preview_known and known
            differences = [pv - cv for pv, cv in zip(preview_values, current_values)]
            axis_active = bool(row.axis and row.axis in dialog.spec.upgrade_axes)
            current_text = self._format_stat_value(row, current_values)
            preview_text = self._format_stat_value(row, preview_values)
            delta_text, delta_color = self._format_delta_text(row, differences, preview_known, axis_active)
            if not preview_known and axis_active:
                preview_text += " ?"

            label_surface = self.small_font.render(row.label, True, (196, 220, 240))
            surface.blit(label_surface, (label_x, y))

            current_surface = self.small_font.render(current_text, True, (180, 204, 226))
            surface.blit(
                current_surface,
                (current_x - current_surface.get_width(), y),
            )

            preview_surface = self.small_font.render(preview_text, True, (226, 242, 255))
            surface.blit(
                preview_surface,
                (preview_x - preview_surface.get_width(), y),
            )

            delta_surface = self.small_font.render(delta_text, True, delta_color)
            surface.blit(
                delta_surface,
                (delta_x - delta_surface.get_width(), y),
            )

            dialog.row_rects.append((row_rect, row))
            if row_rect.collidepoint(pygame.mouse.get_pos()):
                tooltip_text = row.tooltip
            y += row_height

        footer_rect = pygame.Rect(rect.x + 32, rect.bottom - 104, rect.width - 64, 72)
        self._blit_panel(surface, footer_rect, (14, 24, 34, 230), (86, 132, 170), 1)

        skill_ok, requirement = model.meets_skill()
        if requirement:
            skill_text = f"Requires Skill: {requirement[0].skill} {requirement[0].rank}"
        else:
            skill_text = "Requires Skill: None"
        skill_color = (180, 214, 238) if skill_ok or not requirement else (220, 120, 120)
        skill_surface = self.small_font.render(skill_text, True, skill_color)
        surface.blit(skill_surface, (footer_rect.x + 16, footer_rect.y + 12))

        totals, unknown_cost = model.aggregate_cost()
        shortfalls = model.missing_resources()
        cost_parts: List[str] = []
        currency_names = {"tylium": "Tylium", "cubits": "Cubits", "merits": "Merits", "tuning_kits": "TKs"}
        order = ["tylium", "cubits", "merits", "tuning_kits"]
        for currency in order:
            amount = totals.get(currency, 0.0)
            if amount <= 0.0 and currency not in totals:
                continue
            label = currency_names.get(currency, currency.title())
            if currency == "tuning_kits":
                text_value = f"{amount:.0f}"
            else:
                text_value = f"{amount:,.0f}" if not unknown_cost else "—"
            if currency in shortfalls:
                text_value = f"[ {text_value} ]"
            cost_parts.append(f"{label} {text_value}")
        if unknown_cost and not cost_parts:
            cost_parts.append("Cost data incomplete")
        cost_text = " | ".join(cost_parts) if cost_parts else "No additional cost"
        cost_color = (204, 234, 254)
        cost_surface = self.small_font.render(cost_text, True, cost_color)
        cost_x = footer_rect.centerx - cost_surface.get_width() // 2
        surface.blit(cost_surface, (cost_x, footer_rect.y + 12))

        chance_text = self._chance_text(dialog)
        if chance_text:
            chance_surface = self.mini_font.render(chance_text, True, (180, 210, 238))
            surface.blit(
                chance_surface,
                (
                    footer_rect.centerx - chance_surface.get_width() // 2,
                    footer_rect.y + 36,
                ),
            )

        button_y = footer_rect.bottom - 52
        button_size = pygame.Rect(0, 0, 116, 44)
        cancel_rect = pygame.Rect(footer_rect.right - 120, button_y, button_size.width, button_size.height)
        confirm_rect = pygame.Rect(cancel_rect.left - 126, button_y, button_size.width, button_size.height)
        max_rect = pygame.Rect(confirm_rect.left - 126, button_y, button_size.width, button_size.height)

        can_upgrade, reason = model.can_upgrade()
        confirm_fill = (70, 140, 180, 236) if can_upgrade else (32, 46, 60, 200)
        confirm_border = (170, 230, 255) if can_upgrade else (80, 110, 140)
        self._blit_panel(surface, confirm_rect, confirm_fill, confirm_border, 1)
        confirm_text = self.small_font.render("Upgrade", True, (232, 244, 255) if can_upgrade else (150, 170, 190))
        surface.blit(
            confirm_text,
            (
                confirm_rect.centerx - confirm_text.get_width() // 2,
                confirm_rect.centery - confirm_text.get_height() // 2,
            ),
        )

        self._blit_panel(surface, cancel_rect, (34, 50, 64, 210), (90, 130, 168), 1)
        cancel_text = self.small_font.render("Cancel", True, (200, 220, 236))
        surface.blit(
            cancel_text,
            (
                cancel_rect.centerx - cancel_text.get_width() // 2,
                cancel_rect.centery - cancel_text.get_height() // 2,
            ),
        )

        max_level = model.max_affordable_level()
        max_enabled = max_level > model.current_level
        self._blit_panel(
            surface,
            max_rect,
            (34, 50, 64, 210) if max_enabled else (24, 34, 46, 200),
            (120, 170, 210) if max_enabled else (70, 96, 120),
            1,
        )
        max_text = self.small_font.render("Max", True, (214, 236, 255) if max_enabled else (150, 170, 188))
        surface.blit(
            max_text,
            (
                max_rect.centerx - max_text.get_width() // 2,
                max_rect.centery - max_text.get_height() // 2,
            ),
        )

        dialog.confirm_rect = confirm_rect
        dialog.cancel_rect = cancel_rect
        dialog.max_rect = max_rect

        steps = model.steps_in_range()
        has_tuning = any(step.tuning_kits for step in steps)
        if has_tuning:
            guarantee_rect = pygame.Rect(footer_rect.x + 16, button_y, 132, 44)
            guarantee_active = model.guarantee
            fill = (64, 120, 160, 228) if guarantee_active else (30, 44, 58, 200)
            border = (180, 230, 255) if guarantee_active else (80, 110, 140)
            self._blit_panel(surface, guarantee_rect, fill, border, 1)
            guarantee_text = "Guaranteed" if guarantee_active else "Guarantee"
            text_surface = self.small_font.render(guarantee_text, True, (224, 242, 255))
            surface.blit(
                text_surface,
                (
                    guarantee_rect.centerx - text_surface.get_width() // 2,
                    guarantee_rect.centery - text_surface.get_height() // 2,
                ),
            )
            dialog.guarantee_rect = guarantee_rect
        else:
            dialog.guarantee_rect = None

        status_text = dialog.message
        if not status_text and not can_upgrade and reason:
            status_text = reason
        if status_text:
            color = (120, 210, 150) if "Upgraded" in status_text else (220, 140, 140)
            status_surface = self.mini_font.render(status_text, True, color)
            surface.blit(status_surface, (rect.x + 32, footer_rect.y - 28))

        if tooltip_text:
            tooltip_surface = self.mini_font.render(tooltip_text, True, (196, 224, 248))
            surface.blit(
                tooltip_surface,
                (
                    rect.x + 32,
                    footer_rect.y - tooltip_surface.get_height() - 6,
                ),
            )

    def _draw_upgrade_pips(self, surface: pygame.Surface, area: pygame.Rect, dialog: _UpgradeDialog) -> None:
        model = dialog.model
        spec = dialog.spec
        pygame.draw.line(surface, (90, 130, 170), (area.x, area.centery), (area.right, area.centery), 2)
        count = spec.level_cap
        spacing = area.width / max(1, count - 1)
        radius = 11
        pip_rects: List[Tuple[int, pygame.Rect]] = []
        for index in range(count):
            level = index + 1
            center_x = int(area.x + index * spacing)
            center = (center_x, area.centery)
            tier_color = (92, 156, 214) if level <= 10 else (208, 96, 120)
            outline_color = (170, 230, 255) if model.current_level < level <= model.preview_level else tier_color
            fill_color = tier_color if level <= model.current_level else (26, 38, 52)
            pygame.draw.circle(surface, fill_color, center, radius)
            pygame.draw.circle(surface, outline_color, center, radius, 2)
            pip_rects.append((level, pygame.Rect(center_x - radius, area.centery - radius, radius * 2, radius * 2)))
        dialog.pip_rects = pip_rects

        left_rect = pygame.Rect(area.x - 42, area.centery - 20, 34, 40)
        right_rect = pygame.Rect(area.right + 8, area.centery - 20, 34, 40)
        pygame.draw.polygon(surface, (150, 210, 255), [(left_rect.right, left_rect.top), (left_rect.right, left_rect.bottom), (left_rect.x, left_rect.centery)], 0)
        pygame.draw.polygon(surface, (150, 210, 255), [(right_rect.x, right_rect.top), (right_rect.x, right_rect.bottom), (right_rect.right, right_rect.centery)], 0)
        dialog.left_chevron = left_rect
        dialog.right_chevron = right_rect

        preview_label = self.small_font.render(
            f"Preview Level {model.preview_level}",
            True,
            (186, 214, 240),
        )
        surface.blit(preview_label, (area.centerx - preview_label.get_width() // 2, area.bottom + 6))

    def _chance_text(self, dialog: _UpgradeDialog) -> str:
        model = dialog.model
        steps = model.steps_in_range()
        if not steps:
            return ""
        unique_chances = {step.success_chance for step in steps if step.success_chance and step.success_chance < 1.0}
        if not unique_chances:
            if model.guarantee and any(step.guarantee_kits for step in steps):
                return "Guaranteed"
            return ""
        if model.guarantee and any(step.guarantee_kits for step in steps):
            return "Chance: Guaranteed"
        if len(unique_chances) == 1:
            chance = next(iter(unique_chances)) * 100.0
            overall = model.aggregated_success()
            if overall is not None and len(steps) > 1:
                return f"Chance: {chance:.0f}% per step (Overall {overall * 100:.0f}%)"
            return f"Chance: {chance:.0f}% per step"
        return "Chance varies per step"

    def _format_stat_value(self, row: _StatRowDef, values: List[float]) -> str:
        if len(values) == 1:
            text = self._format_number(values[0], row.precision)
        else:
            formatted = [self._format_number(v, row.precision) for v in values]
            text = "–".join(formatted)
        return f"{text} {row.units}"

    def _format_delta_text(
        self,
        row: _StatRowDef,
        differences: List[float],
        preview_known: bool,
        axis_active: bool,
    ) -> Tuple[str, Tuple[int, int, int]]:
        if not axis_active:
            return "—", (120, 140, 160)
        if not preview_known:
            return "unknown", (170, 180, 210)
        if all(abs(delta) < 1e-4 for delta in differences):
            return "—", (120, 140, 160)
        formatted = [self._format_delta(delta, row.precision) for delta in differences]
        text = " / ".join(formatted)
        has_positive = any(delta > 1e-4 for delta in differences)
        has_negative = any(delta < -1e-4 for delta in differences)
        if has_positive and has_negative:
            color = (210, 210, 160)
        elif has_positive:
            color = (130, 210, 160)
        else:
            color = (220, 140, 140)
        return f"{text} {row.units}", color

    def _format_number(self, value: float, precision: int) -> str:
        fmt = f"{{:,.{precision}f}}"
        return fmt.format(value)

    def _format_delta(self, value: float, precision: int) -> str:
        fmt = f"{{:+,.{precision}f}}"
        return fmt.format(value)

    def _resource_snapshot(self, ship: Ship) -> Dict[str, float]:
        resources = vars(ship.resources).copy()
        return {key: float(value) for key, value in resources.items()}

    def _stat_rows_for_slot(self, slot: str) -> Tuple[_StatRowDef, ...]:
        if slot == "weapon":
            return WEAPON_ROWS
        if slot == "hull":
            return HULL_ROWS
        if slot == "engine":
            return ENGINE_ROWS
        return ()

    def _chance_axes_delta(self, dialog: _UpgradeDialog, previous: int, new_level: int) -> str:
        rows = self._stat_rows_for_slot(dialog.spec.slot)
        labels: List[str] = []
        for row in rows:
            if not row.axis or row.axis not in dialog.spec.upgrade_axes:
                continue
            keys = AXIS_KEYS.get(row.axis, row.keys)
            diffs: List[str] = []
            for key in keys:
                prev_value, prev_known = dialog.model.stat_value(key, previous)
                new_value, new_known = dialog.model.stat_value(key, new_level)
                if prev_known and new_known:
                    diffs.append(self._format_delta(new_value - prev_value, row.precision))
            if diffs:
                delta_text = diffs[0] if len(diffs) == 1 else " / ".join(diffs)
                labels.append(f"{row.label} {delta_text}")
        return ", ".join(labels)

    def _handle_upgrade_dialog_event(self, event: pygame.event.Event) -> bool:
        if not self._upgrade_dialog:
            return False
        dialog = self._upgrade_dialog
        model = dialog.model
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self._close_upgrade_dialog()
                return True
            if event.key in (pygame.K_LEFT, pygame.K_a):
                model.increment_preview(-1)
                dialog.message = None
                return True
            if event.key in (pygame.K_RIGHT, pygame.K_d):
                model.increment_preview(1)
                dialog.message = None
                return True
            if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                self._attempt_upgrade()
                return True
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            pos = getattr(event, "pos", pygame.mouse.get_pos())
            if dialog.confirm_rect and dialog.confirm_rect.collidepoint(pos):
                self._attempt_upgrade()
                return True
            if dialog.cancel_rect and dialog.cancel_rect.collidepoint(pos):
                self._close_upgrade_dialog()
                return True
            if dialog.max_rect and dialog.max_rect.collidepoint(pos):
                model.set_preview_level(model.max_affordable_level())
                dialog.message = None
                return True
            if dialog.guarantee_rect and dialog.guarantee_rect.collidepoint(pos):
                model.toggle_guarantee()
                dialog.message = None
                return True
            for level, pip_rect in dialog.pip_rects:
                if pip_rect.collidepoint(pos):
                    model.set_preview_level(level)
                    dialog.message = None
                    return True
            if dialog.left_chevron and dialog.left_chevron.collidepoint(pos):
                model.increment_preview(-1)
                dialog.message = None
                return True
            if dialog.right_chevron and dialog.right_chevron.collidepoint(pos):
                model.increment_preview(1)
                dialog.message = None
                return True
            if dialog.rect and not dialog.rect.collidepoint(pos):
                self._close_upgrade_dialog()
                return True
        return False

    def _attempt_upgrade(self) -> None:
        if not self._upgrade_dialog or not self._current_ship:
            return
        dialog = self._upgrade_dialog
        model = dialog.model
        can_upgrade, reason = model.can_upgrade()
        if not can_upgrade:
            dialog.message = reason or "Cannot upgrade"
            return
        steps = model.steps_in_range()
        if not steps:
            dialog.message = "Already at level cap"
            return

        ship = self._current_ship
        previous_level = model.current_level
        last_success_level = previous_level
        failure_level: Optional[int] = None
        for step in steps:
            for currency, amount in step.costs.items():
                if amount > 0.0:
                    ship.resources.spend(currency, amount)
            if step.tuning_kits:
                kits = float(step.tuning_kits)
                if model.guarantee and step.guarantee_kits:
                    kits = float(step.guarantee_kits)
                ship.resources.tuning_kits = max(0.0, ship.resources.tuning_kits - kits)
            chance = 1.0
            if step.success_chance is not None:
                if model.guarantee and step.guarantee_kits:
                    chance = 1.0
                else:
                    chance = step.success_chance
            success = True
            roll_value = 0.0
            if chance < 0.999:
                roll_value = random.random()
                success = roll_value <= chance
            if success:
                last_success_level = step.level
            else:
                failure_level = step.level
                break

        self._set_item_level(ship, dialog.item, last_success_level)
        model.current_level = last_success_level
        model.set_preview_level(min(model.spec.level_cap, last_success_level + 1))
        model.player_resources = self._resource_snapshot(ship)

        if last_success_level > previous_level:
            delta_summary = self._chance_axes_delta(dialog, previous_level, last_success_level)
            if delta_summary:
                dialog.message = f"Upgraded to Level {last_success_level} ({delta_summary})"
            else:
                dialog.message = f"Upgraded to Level {last_success_level}"
            dialog.flash_timer = 1.2
        elif failure_level:
            dialog.message = f"Upgrade failed at Level {failure_level} (stopped at {last_success_level})"
            dialog.flash_timer = 0.0
        else:
            dialog.message = "Upgrade made no progress"
            dialog.flash_timer = 0.0

    def _open_upgrade_dialog(self, item: _HoldItem) -> None:
        if not self._current_ship or not item.store_item:
            return
        spec = EQUIPMENT_UPGRADE_SPECS.get(item.store_item.id)
        if not spec:
            return
        ship = self._current_ship
        model = EquipmentUpgradeModel(
            spec,
            current_level=self._item_current_level(ship, item),
            player_resources=self._resource_snapshot(ship),
            player_skills=dict(self._player_skills),
        )
        dialog = _UpgradeDialog(
            item=item,
            store_item=item.store_item,
            spec=spec,
            model=model,
            flash_axes=spec.upgrade_axes,
        )
        self._upgrade_dialog = dialog
        self._sell_dialog = None

    def _close_upgrade_dialog(self) -> None:
        self._upgrade_dialog = None

    def _confirm_sell(self) -> None:
        if not self._sell_dialog or not self._current_ship:
            return
        dialog = self._sell_dialog
        ship = self._current_ship
        available = self._resource_amount(dialog.item_key)
        amount = self._sanitize_dialog_input(dialog, available)
        if amount <= 0.0:
            self._sell_dialog = None
            return
        if hasattr(ship.resources, dialog.item_key):
            current_value = getattr(ship.resources, dialog.item_key)
            setattr(ship.resources, dialog.item_key, max(0.0, current_value - amount))
        ship.resources.add(dialog.sell_currency, amount * dialog.sell_rate)
        self._sell_dialog = None

    def _sanitize_dialog_input(self, dialog: _SellDialog, available: float) -> float:
        amount = max(0.0, self._parse_amount(dialog.input_value))
        if available >= 0.0 and amount > available:
            formatted = self._format_amount_string(available)
            if dialog.input_value != formatted:
                dialog.input_value = formatted
            amount = available
        return amount

    def _parse_amount(self, value: str) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _resource_amount(self, resource: str) -> float:
        if not self._current_ship:
            return 0.0
        if hasattr(self._current_ship.resources, resource):
            return float(getattr(self._current_ship.resources, resource))
        return 0.0

    def _format_amount_display(self, value: float) -> str:
        return self._format_amount_string(value)

    def _format_amount_string(self, value: float) -> str:
        if math.isclose(value, round(value), abs_tol=1e-4):
            return str(int(round(value)))
        return f"{value:.2f}".rstrip("0").rstrip(".")

    def _format_currency_name(self, currency: str) -> str:
        if currency == "tylium":
            return "Tylium"
        if currency == "cubits":
            return "Cubits"
        return currency.title()

    def _draw_wrapped_text(
        self,
        surface: pygame.Surface,
        text: str,
        font: pygame.font.Font,
        color: Tuple[int, int, int],
        rect: pygame.Rect,
    ) -> None:
        words = text.split()
        if not words:
            return
        line = ""
        line_height = font.get_linesize()
        y = rect.y
        for word in words:
            candidate = f"{line} {word}".strip()
            if font.size(candidate)[0] <= rect.width:
                line = candidate
            else:
                if line:
                    surface.blit(font.render(line, True, color), (rect.x, y))
                    y += line_height
                line = word
        if line and y <= rect.bottom:
            surface.blit(font.render(line, True, color), (rect.x, y))

    def _draw_ship_panel(self, surface: pygame.Surface, rect: pygame.Rect, ship: Ship) -> None:
        self._blit_panel(surface, rect, (18, 28, 40, 210), (70, 110, 150))
        header = self.font.render("Ship Overview", True, (210, 236, 255))
        surface.blit(header, (rect.x + 24, rect.y + 16))

        layout_rect = pygame.Rect(rect.x + 24, rect.y + 52, rect.width - 48, rect.height - 88)
        layout_rect.height = int(layout_rect.height * 0.9)

        shape, widgets = self._build_ship_layout(ship, layout_rect)
        self._ship_widgets = widgets
        if shape:
            pygame.draw.polygon(surface, (30, 44, 58), shape, 0)
            pygame.draw.lines(surface, (160, 210, 240), True, shape, 2)
        hovered_widget: _SlotDisplay | None = None
        mouse_pos = pygame.mouse.get_pos()
        for widget in widgets:
            fill_color = (70, 118, 162) if widget.category == "weapon" else (170, 120, 72)
            empty_color = (40, 52, 62) if widget.category == "weapon" else (56, 44, 32)
            color = fill_color if widget.filled else empty_color
            pygame.draw.rect(surface, color, widget.rect)
            pygame.draw.rect(surface, (12, 18, 26), widget.rect, 2)
            icon = self._slot_icons.get(self._icon_key_for_slot(widget))
            if icon:
                icon_rect = icon.get_rect(center=widget.rect.center)
                surface.blit(icon, icon_rect.topleft)
            if self._active_slot_label == widget.label:
                pygame.draw.rect(surface, (210, 236, 255), widget.rect, 2)
            if widget.rect.collidepoint(mouse_pos):
                hovered_widget = widget
                pygame.draw.rect(surface, (210, 236, 255), widget.rect, 2)

        if hovered_widget:
            self._draw_tooltip(surface, hovered_widget, mouse_pos)
        elif self._active_slot_label:
            active_widget = self._find_widget_by_label(self._active_slot_label)
            if active_widget:
                anchor = self._active_slot_mouse_pos or active_widget.rect.center
                self._draw_tooltip(surface, active_widget, anchor)

    def _blit_panel(
        self,
        target: pygame.Surface,
        rect: pygame.Rect,
        fill_color: Tuple[int, ...],
        border_color: Tuple[int, int, int] | None = None,
        border_width: int = 1,
    ) -> None:
        overlay = pygame.Surface(rect.size, pygame.SRCALPHA)
        if len(fill_color) == 3:
            overlay.fill((*fill_color, 255))
        else:
            overlay.fill(fill_color)
        target.blit(overlay, rect.topleft)
        if border_color and border_width > 0:
            pygame.draw.rect(target, border_color, rect, border_width)

    # ------------------------------------------------------------------
    def _build_ship_layout(self, ship: Ship, rect: pygame.Rect) -> tuple[List[tuple[int, int]], List[_SlotDisplay]]:
        layout = MODEL_LAYOUTS.get(ship.frame.size, MODEL_LAYOUTS["Strike"])
        shape_points: Iterable[Tuple[float, float]] = layout.get("shape", MODEL_LAYOUTS["Strike"]["shape"])
        shape = [Vector2(point) for point in shape_points]
        slot_counts = self._slot_counts(ship)
        positions_by_slot: Dict[str, List[Tuple[float, float]]] = {}
        max_x = max((abs(point.x) for point in shape), default=1.0)
        max_y = max((abs(point.y) for point in shape), default=1.0)
        for slot_type, count in slot_counts.items():
            if count <= 0:
                continue
            positions = self._generate_positions(slot_type, count, layout)
            positions_by_slot[slot_type] = positions
            if positions:
                slot_max_x = max(abs(pos[0]) for pos in positions)
                slot_max_y = max(abs(pos[1]) for pos in positions)
                max_x = max(max_x, slot_max_x)
                max_y = max(max_y, slot_max_y)

        scale = self._compute_scale(rect, max_x, max_y)
        center = Vector2(rect.centerx, rect.centery)
        scaled_shape = [self._model_to_screen(point, center, scale) for point in shape]
        widgets: List[_SlotDisplay] = []

        for slot_type, capacity in ship.frame.slots.weapon_families.items():
            normalized = slot_type.lower()
            positions = positions_by_slot.get(normalized, [])
            mounts = [
                mount
                for mount in ship.mounts
                if self._slot_matches(mount.hardpoint.slot, normalized)
            ]
            for index in range(int(capacity)):
                position = self._position_for_index(positions, index)
                rect_center = self._model_to_screen(Vector2(position), center, scale)
                widget_rect = pygame.Rect(0, 0, 44, 44)
                widget_rect.center = rect_center
                detail = "Empty"
                filled = False
                if index < len(mounts):
                    detail = self._weapon_detail(mounts[index])
                    filled = bool(mounts[index].weapon_id)
                label = f"{self._slot_display_name(slot_type)} {index + 1}"
                widgets.append(
                    _SlotDisplay(
                        label=label,
                        detail=detail,
                        rect=widget_rect,
                        filled=filled,
                        category="weapon",
                        slot_type=normalized,
                        index=index,
                    )
                )

        module_slots = [
            ("hull", ship.frame.slots.hull),
            ("engine", ship.frame.slots.engine),
            ("computer", ship.frame.slots.computer),
            ("utility", ship.frame.slots.utility),
        ]
        for slot_type, capacity in module_slots:
            if capacity <= 0:
                continue
            normalized = slot_type.lower()
            positions = positions_by_slot.get(normalized, [])
            modules = ship.modules_by_slot.get(slot_type, [])
            for index in range(int(capacity)):
                position = self._position_for_index(positions, index)
                rect_center = self._model_to_screen(Vector2(position), center, scale)
                widget_rect = pygame.Rect(0, 0, 44, 44)
                widget_rect.center = rect_center
                module = modules[index] if index < len(modules) else None
                detail = module.name if module else "Empty"
                label = f"{self._slot_display_name(slot_type)} {index + 1}"
                widgets.append(
                    _SlotDisplay(
                        label=label,
                        detail=detail,
                        rect=widget_rect,
                        filled=module is not None,
                        category="module",
                        slot_type=normalized,
                        index=index,
                    )
                )

        return scaled_shape, widgets

    def _panel_lines_for_option(self, option: str) -> List[str]:
        if option == "Store":
            return [
                "Station storefront systems are offline.",
                "Future updates will enable purchasing.",
            ]
        if option == "Hold":
            return [
                "Ship hold inventory management coming soon.",
                "Hover over ship slots to inspect installed gear.",
            ]
        if option == "Locker":
            return [
                "Personal lockers are not yet accessible.",
                "Stow and retrieve equipment here in a later update.",
            ]
        return ["No data available."]

    def _slot_counts(self, ship: Ship) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for slot_type, capacity in ship.frame.slots.weapon_families.items():
            counts[slot_type.lower()] = int(capacity)
        counts["hull"] = ship.frame.slots.hull
        counts["engine"] = ship.frame.slots.engine
        counts["computer"] = ship.frame.slots.computer
        counts["utility"] = ship.frame.slots.utility
        return counts

    def _generate_positions(self, slot_type: str, count: int, layout: Dict[str, object]) -> List[Tuple[float, float]]:
        if count <= 0:
            return []
        spec = self._anchor_spec(slot_type, layout)
        mode = spec.get("mode", "sym")
        if mode == "grid":
            return self._grid_positions(count, spec)
        if mode == "line":
            return self._line_positions(count, spec)
        return self._sym_positions(count, spec)

    def _anchor_spec(self, slot_type: str, layout: Dict[str, object]) -> Dict[str, float]:
        anchors = layout.get("anchors", {})
        normalized = slot_type.lower()
        candidates = [normalized]
        if normalized == "gun":
            candidates.append("guns")
        elif normalized == "guns":
            candidates.append("gun")
        for candidate in candidates:
            if isinstance(anchors, dict) and candidate in anchors:
                return dict(anchors[candidate])
        return dict(DEFAULT_ANCHORS.get(normalized, DEFAULT_ANCHORS["default"]))

    def _sym_positions(self, count: int, spec: Dict[str, float]) -> List[Tuple[float, float]]:
        spacing = spec.get("spacing", 100.0)
        y = spec.get("y", 0.0)
        offset = spec.get("x_offset", 0.0)
        if count == 1:
            return [(offset, y)]
        mid = (count - 1) / 2.0
        return [((i - mid) * spacing + offset, y) for i in range(count)]

    def _grid_positions(self, count: int, spec: Dict[str, float]) -> List[Tuple[float, float]]:
        columns = max(1, int(spec.get("columns", 2)))
        spacing_x = spec.get("spacing_x", spec.get("spacing", 90.0))
        spacing_y = spec.get("spacing_y", 48.0)
        base_y = spec.get("y", 0.0)
        center_x = spec.get("center_x", True)
        offset_x = spec.get("x_offset", 0.0)
        positions: List[Tuple[float, float]] = []
        for index in range(count):
            row = index // columns
            col = index % columns
            if center_x:
                col_offset = (col - (columns - 1) / 2.0) * spacing_x
            else:
                col_offset = col * spacing_x
            x = offset_x + col_offset
            y = base_y + row * spacing_y
            positions.append((x, y))
        return positions

    def _line_positions(self, count: int, spec: Dict[str, float]) -> List[Tuple[float, float]]:
        start = spec.get("start", (-80.0, 0.0))
        end = spec.get("end", (80.0, 0.0))
        if count == 1:
            return [((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0)]
        return [
            (
                start[0] + (end[0] - start[0]) * (i / (count - 1)),
                start[1] + (end[1] - start[1]) * (i / (count - 1)),
            )
            for i in range(count)
        ]

    def _position_for_index(self, positions: List[Tuple[float, float]], index: int) -> Tuple[float, float]:
        if not positions:
            return (0.0, 0.0)
        if index < len(positions):
            return positions[index]
        return positions[-1]

    def _slot_matches(self, slot_name: str, target: str) -> bool:
        slot = slot_name.lower()
        if slot == target:
            return True
        if target in {"guns", "gun"}:
            return slot in {"guns", "gun"}
        return False

    def _weapon_detail(self, mount: WeaponMount) -> str:
        if not mount.weapon_id:
            return "Empty"
        if not self.content:
            return mount.weapon_id.replace("_", " ").title()
        weapon = self.content.weapons.get(mount.weapon_id)
        if weapon:
            return weapon.name
        return mount.weapon_id.replace("_", " ").title()

    def _slot_display_name(self, slot_type: str) -> str:
        normalized = slot_type.lower()
        mapping = {
            "cannon": "Cannon",
            "launcher": "Launcher",
            "guns": "Guns",
            "gun": "Gun",
            "defensive": "Defense",
        }
        return mapping.get(normalized, normalized.replace("_", " ").title())

    def _model_to_screen(self, point: Vector2, center: Vector2, scale: float) -> tuple[int, int]:
        converted = Vector2(center.x + point.x * scale, center.y + point.y * scale)
        return int(converted.x), int(converted.y)

    def _compute_scale(self, rect: pygame.Rect, max_x: float, max_y: float) -> float:
        available_width = rect.width
        available_height = rect.height
        denom_x = max(max_x * 2.0 + 120.0, 1.0)
        denom_y = max(max_y * 2.0 + 120.0, 1.0)
        scale_x = available_width / denom_x if available_width > 0 else 1.0
        scale_y = available_height / denom_y if available_height > 0 else 1.0
        return max(0.25, min(scale_x, scale_y))

    def _create_hold_icons(self) -> Dict[str, pygame.Surface]:
        icons: Dict[str, pygame.Surface] = {}

        def surface() -> pygame.Surface:
            return pygame.Surface((48, 48), pygame.SRCALPHA)

        tylium = surface()
        pygame.draw.rect(tylium, (220, 196, 112), pygame.Rect(10, 18, 28, 16))
        pygame.draw.rect(tylium, (140, 110, 48), pygame.Rect(10, 18, 28, 16), 2)
        pygame.draw.rect(tylium, (255, 232, 150), pygame.Rect(14, 20, 20, 8))
        pygame.draw.polygon(tylium, (186, 150, 60), [(12, 18), (18, 12), (30, 12), (36, 18)])
        icons["tylium"] = tylium

        water = surface()
        drop_points = [(24, 10), (34, 24), (28, 36), (20, 36), (14, 24)]
        pygame.draw.polygon(water, (100, 170, 255), drop_points)
        highlight = [(24, 12), (30, 22), (24, 28)]
        pygame.draw.polygon(water, (200, 230, 255), highlight)
        pygame.draw.polygon(water, (60, 100, 170), drop_points, 2)
        icons["water"] = water

        titanium = surface()
        pygame.draw.polygon(
            titanium,
            (170, 180, 190),
            [(10, 28), (18, 16), (38, 16), (30, 28)],
        )
        pygame.draw.polygon(
            titanium,
            (210, 220, 232),
            [(14, 26), (20, 18), (34, 18), (28, 26)],
        )
        pygame.draw.polygon(titanium, (110, 126, 138), [(10, 28), (18, 16), (38, 16), (30, 28)], 2)
        icons["titanium"] = titanium

        cubits = surface()
        gem_points = [(24, 10), (36, 22), (24, 38), (12, 22)]
        pygame.draw.polygon(cubits, (160, 120, 240), gem_points)
        pygame.draw.polygon(cubits, (210, 180, 255), [(24, 12), (32, 22), (24, 34), (16, 22)])
        pygame.draw.polygon(cubits, (90, 60, 150), gem_points, 2)
        icons["cubits"] = cubits

        module = surface()
        pygame.draw.polygon(module, (160, 210, 230), [(24, 8), (38, 24), (24, 40), (10, 24)])
        pygame.draw.polygon(module, (70, 110, 130), [(24, 12), (34, 24), (24, 36), (14, 24)], 2)
        icons["module"] = module

        hull = surface()
        pygame.draw.rect(hull, (140, 180, 210), pygame.Rect(10, 14, 28, 20))
        pygame.draw.rect(hull, (60, 90, 120), pygame.Rect(10, 14, 28, 20), 3)
        pygame.draw.line(hull, (200, 230, 255), (14, 20), (34, 28), 3)
        icons["hull"] = hull

        engine = surface()
        pygame.draw.polygon(engine, (120, 200, 255), [(16, 10), (32, 18), (28, 30), (12, 22)])
        pygame.draw.polygon(engine, (255, 200, 120), [(12, 22), (28, 30), (24, 38), (8, 30)])
        pygame.draw.polygon(engine, (70, 110, 160), [(16, 10), (32, 18), (28, 30), (12, 22)], 2)
        icons["engine"] = engine

        weapon = surface()
        pygame.draw.circle(weapon, (200, 210, 220), (24, 24), 14)
        pygame.draw.circle(weapon, (90, 110, 140), (24, 24), 14, 3)
        pygame.draw.line(weapon, (220, 90, 90), (12, 24), (36, 24), 3)
        pygame.draw.line(weapon, (220, 90, 90), (24, 12), (24, 36), 3)
        icons["weapon"] = weapon

        utility = surface()
        pygame.draw.circle(utility, (220, 180, 90), (20, 20), 6)
        pygame.draw.rect(utility, (80, 110, 150), pygame.Rect(18, 18, 16, 12))
        pygame.draw.line(utility, (240, 220, 150), (20, 10), (36, 12), 3)
        icons["utility"] = utility

        computer = surface()
        pygame.draw.rect(computer, (140, 200, 220), pygame.Rect(12, 14, 24, 18))
        pygame.draw.rect(computer, (60, 90, 110), pygame.Rect(12, 14, 24, 18), 2)
        pygame.draw.rect(computer, (70, 110, 150), pygame.Rect(16, 18, 6, 10))
        pygame.draw.rect(computer, (70, 110, 150), pygame.Rect(24, 18, 6, 10))
        icons["computer"] = computer

        return icons

    def _create_price_icons(self) -> Dict[str, pygame.Surface]:
        icons: Dict[str, pygame.Surface] = {}

        coin = pygame.Surface((20, 20), pygame.SRCALPHA)
        pygame.draw.circle(coin, (220, 186, 90), (10, 10), 9)
        pygame.draw.circle(coin, (255, 232, 160), (10, 10), 6)
        pygame.draw.circle(coin, (138, 98, 40), (10, 10), 9, 2)
        icons["coin"] = coin

        gem = pygame.Surface((20, 20), pygame.SRCALPHA)
        points = [(10, 2), (18, 10), (10, 18), (2, 10)]
        pygame.draw.polygon(gem, (150, 190, 255), points)
        pygame.draw.polygon(gem, (210, 236, 255), [(10, 4), (16, 10), (10, 16), (4, 10)])
        pygame.draw.polygon(gem, (90, 130, 200), points, 2)
        icons["gem"] = gem

        return icons

    def _create_slot_icons(self) -> Dict[str, pygame.Surface]:
        def base_surface() -> pygame.Surface:
            surf = pygame.Surface((32, 32), pygame.SRCALPHA)
            pygame.draw.rect(surf, (18, 28, 36, 220), pygame.Rect(0, 0, 32, 32))
            pygame.draw.rect(surf, (12, 18, 26), pygame.Rect(0, 0, 32, 32), 2)
            return surf

        icons: Dict[str, pygame.Surface] = {}

        weapon = base_surface()
        pygame.draw.circle(weapon, (220, 90, 90), (16, 16), 7)
        pygame.draw.circle(weapon, (60, 16, 16), (16, 16), 7, 2)
        pygame.draw.line(weapon, (220, 200, 200), (16, 4), (16, 28), 2)
        pygame.draw.line(weapon, (220, 200, 200), (4, 16), (28, 16), 2)
        icons["weapon"] = weapon

        hull = base_surface()
        pygame.draw.polygon(
            hull,
            (210, 190, 120),
            [(16, 4), (26, 10), (26, 22), (16, 28), (6, 22), (6, 10)],
        )
        pygame.draw.polygon(
            hull,
            (80, 70, 40),
            [(16, 6), (24, 11), (24, 21), (16, 26), (8, 21), (8, 11)],
            2,
        )
        icons["hull"] = hull

        engine = base_surface()
        pygame.draw.polygon(engine, (120, 200, 255), [(16, 4), (24, 20), (8, 20)])
        pygame.draw.rect(engine, (220, 140, 60), pygame.Rect(10, 20, 12, 6))
        pygame.draw.rect(engine, (255, 200, 120), pygame.Rect(10, 24, 12, 4))
        icons["engine"] = engine

        computer = base_surface()
        pygame.draw.rect(computer, (140, 200, 220), pygame.Rect(6, 8, 20, 16))
        pygame.draw.rect(computer, (40, 60, 70), pygame.Rect(6, 8, 20, 16), 2)
        for x in (6, 12, 18, 24):
            pygame.draw.line(computer, (80, 120, 160), (x, 26), (x, 30), 2)
        icons["computer"] = computer

        utility = base_surface()
        pygame.draw.circle(utility, (230, 180, 90), (12, 12), 5)
        pygame.draw.rect(utility, (120, 90, 40), pygame.Rect(15, 15, 12, 10))
        pygame.draw.line(utility, (240, 220, 150), (20, 4), (28, 12), 3)
        icons["utility"] = utility

        module = base_surface()
        pygame.draw.polygon(module, (150, 210, 230), [(16, 4), (28, 16), (16, 28), (4, 16)])
        pygame.draw.polygon(module, (70, 110, 130), [(16, 7), (25, 16), (16, 25), (7, 16)], 2)
        icons["module"] = module

        empty = pygame.Surface((32, 32), pygame.SRCALPHA)
        pygame.draw.rect(empty, (40, 52, 62, 180), pygame.Rect(0, 0, 32, 32))
        pattern_color = (18, 26, 34)
        for offset in range(0, 32, 4):
            pygame.draw.line(empty, pattern_color, (offset, 0), (0, offset), 1)
        pygame.draw.rect(empty, (90, 110, 126), pygame.Rect(2, 2, 28, 28), 2)
        icons["empty"] = empty

        return icons

    def _icon_key_for_slot(self, widget: _SlotDisplay) -> str:
        if not widget.filled:
            return "empty"
        normalized = widget.slot_type.lower()
        module_keys = {"hull", "engine", "computer", "utility"}
        if normalized in module_keys:
            return normalized
        if normalized in self._slot_icons:
            return normalized
        return "weapon" if widget.category == "weapon" else "module"

    def _find_widget_by_label(self, label: str) -> Optional[_SlotDisplay]:
        for widget in self._ship_widgets:
            if widget.label == label:
                return widget
        return None

    def _slot_at_position(self, pos: Tuple[int, int]) -> Optional[_SlotDisplay]:
        for widget in self._ship_widgets:
            if widget.rect.collidepoint(pos):
                return widget
        return None

    def _clear_active_slot(self) -> None:
        self._active_slot_label = None
        self._active_slot_mouse_pos = None
        self._tooltip_buttons = []

    def _draw_tooltip(self, surface: pygame.Surface, widget: _SlotDisplay, mouse_pos: tuple[int, int]) -> None:
        self._tooltip_buttons = []

        text_lines: List[str] = []
        header = widget.label
        if header:
            text_lines.append(header)
        if widget.filled and widget.detail:
            text_lines.append(widget.detail)
        else:
            text_lines.append("Empty")

        font = self.small_font
        padding = 12
        spacing = 6
        button_height = 28
        button_padding_top = 10
        button_spacing = 6
        text_surfaces = [font.render(line, True, (220, 236, 250)) for line in text_lines]
        text_width = max((surf.get_width() for surf in text_surfaces), default=0)
        width = max(120, text_width + padding * 2)

        buttons: List[tuple[str, bool, str]] = []
        upgrade_enabled = False
        if widget.filled:
            store_item = self._store_item_for_slot(widget)
            if store_item:
                upgrade_enabled = bool(EQUIPMENT_UPGRADE_SPECS.get(store_item.id))
            buttons.append(("Upgrade", upgrade_enabled, "upgrade"))
        can_unequip = bool(widget.filled and self._current_ship and self._current_ship.can_store_in_hold())
        buttons.append(("Unequip", can_unequip, "unequip"))

        height = padding * 2 + sum(surf.get_height() for surf in text_surfaces)
        height += spacing * (len(text_surfaces) - 1 if text_surfaces else 0)
        if buttons:
            height += button_padding_top + button_height * len(buttons)
            if len(buttons) > 1:
                height += button_spacing * (len(buttons) - 1)

        tooltip_rect = pygame.Rect(mouse_pos[0] + 16, mouse_pos[1] + 16, width, height)
        surface_rect = surface.get_rect()
        if tooltip_rect.right > surface_rect.right:
            tooltip_rect.x = mouse_pos[0] - width - 16
        if tooltip_rect.bottom > surface_rect.bottom:
            tooltip_rect.y = surface_rect.bottom - height - 16
        if tooltip_rect.x < surface_rect.left:
            tooltip_rect.x = surface_rect.left + 16
        if tooltip_rect.y < surface_rect.top:
            tooltip_rect.y = surface_rect.top + 16

        self._blit_panel(surface, tooltip_rect, (16, 24, 32, 230), (90, 140, 180))

        cursor_y = tooltip_rect.y + padding
        for surf in text_surfaces:
            surface.blit(surf, (tooltip_rect.x + padding, cursor_y))
            cursor_y += surf.get_height() + spacing
        cursor_y -= spacing

        last_button_rect: Optional[pygame.Rect] = None
        for index, (label, enabled, action) in enumerate(buttons):
            button_rect = pygame.Rect(
                tooltip_rect.x + padding,
                cursor_y + button_padding_top + index * (button_height + button_spacing),
                tooltip_rect.width - padding * 2,
                button_height,
            )
            if action == "upgrade":
                fill_color = (70, 130, 180, 240) if enabled else (32, 44, 58, 200)
                border_color = (170, 230, 255) if enabled else (70, 96, 120)
            else:
                fill_color = (40, 68, 92, 240) if enabled else (24, 36, 48, 200)
                border_color = (150, 210, 250) if enabled else (70, 96, 122)
            self._blit_panel(surface, button_rect, fill_color, border_color)
            label_color = (220, 236, 250) if enabled else (150, 170, 188)
            button_label = self.mini_font.render(label, True, label_color)
            surface.blit(
                button_label,
                (
                    button_rect.centerx - button_label.get_width() // 2,
                    button_rect.centery - button_label.get_height() // 2,
                ),
            )
            self._tooltip_buttons.append(
                _TooltipButton(rect=button_rect, enabled=enabled, action=action, slot=widget)
            )
            last_button_rect = button_rect

        if (
            buttons
            and not can_unequip
            and self._current_ship
            and self._current_ship.hold_item_count() >= self._current_ship.hold_capacity
        ):
            warning = self.mini_font.render("Hold full", True, (210, 140, 140))
            target_rect = last_button_rect or tooltip_rect
            surface.blit(warning, (target_rect.x, target_rect.bottom + 6))


__all__ = ["HangarView"]
