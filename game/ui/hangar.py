"""Docking hangar overlay for Outposts."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

import pygame
from pygame.math import Vector2

from game.assets.content import ContentManager
from game.ships.ship import Ship, WeaponMount
from game.world.station import DockingStation
from game.ui.ship_info import DEFAULT_ANCHORS, MODEL_LAYOUTS
from game.ui.strike_store import ItemCardData, StoreFilters, StoreItem, fitting, store


@dataclass
class _SlotDisplay:
    label: str
    detail: str
    rect: pygame.Rect
    filled: bool
    category: str
    slot_type: str


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


@dataclass
class _HoldRow:
    item: _HoldItem
    rect: pygame.Rect
    button_rect: Optional[pygame.Rect]


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

    def set_surface(self, surface: pygame.Surface) -> None:
        """Update the target surface when the display size changes."""

        self.surface = surface

    def handle_event(self, event: pygame.event.Event) -> bool:
        """Allow ribbon selection via mouse input."""

        if self._sell_dialog and self._handle_sell_dialog_event(event):
            return True
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            pos = getattr(event, "pos", None)
            if not pos:
                return False
            if self.active_option == "Store" and self._handle_store_click(pos):
                return True
            if self.active_option == "Hold":
                for row in self._hold_rows:
                    if (
                        row.button_rect
                        and row.item.can_sell
                        and row.item.amount > 0.0
                        and row.button_rect.collidepoint(pos)
                    ):
                        self._open_sell_dialog(row.item)
                        return True
            for option, rect in self._ribbon_rects.items():
                if rect.collidepoint(pos):
                    self.active_option = option
                    return True
        return False

    def update(self, dt: float) -> None:
        """Advance hangar background animations."""

        self._interior.update(dt)

    def draw(self, surface: pygame.Surface, ship: Ship, station: DockingStation, distance: float) -> None:
        self._current_ship = ship
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
        info_lines = [
            "Hold SHIFT for max preview",
            "(Strike upgrades not captured)",
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
        columns = 1 if grid_rect.width < 420 else 2
        card_width = (grid_rect.width - padding * (columns + 1)) // columns
        card_height = 240
        mouse_pos = pygame.mouse.get_pos()
        self._store_cards = store.list_items(self._store_filters)
        self._store_card_rects = {}
        self._store_buy_rects = {}
        self._store_hover_item = None
        for index, card in enumerate(self._store_cards):
            col = index % columns
            row = index // columns
            card_rect = pygame.Rect(
                grid_rect.x + padding + col * (card_width + padding),
                grid_rect.y + padding + row * (card_height + padding),
                card_width,
                card_height,
            )
            self._draw_store_card(surface, card_rect, card, mouse_pos)
            self._store_card_rects[card.item.id] = card_rect
        if not self._store_cards:
            empty_text = self.small_font.render("No items match the current filters.", True, (170, 196, 214))
            surface.blit(empty_text, (grid_rect.x + 18, grid_rect.y + 24))

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
        slot_label = f"{card.item.slot_family.title()} • Strike only"
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
            damage = f"Damage {stats['damage_min']:.0f}–{stats['damage_max']:.0f}"
            if "critical_offense" in data.upgrades:
                special = f"Critical Offense {stats['critical_offense']:.0f}"
            else:
                special = f"Optimal Range {stats['optimal_range']:.0f} m"
            return [
                damage,
                special,
                f"Reload {stats['reload']:.2f} s",
                f"AP {stats['armor_piercing']:.0f}",
                f"Accuracy {stats['accuracy']:.0f}",
                f"Firing Arc {stats['firing_arc']:.0f}°",
                f"Power {stats['power']:.0f}",
            ]
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
            message = self.small_font.render("Select a Strike item to preview", True, (176, 204, 222))
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
                    ("Crit Offense", stats.get("critical_offense", 0.0), stats.get("critical_offense", 0.0)),
                ]
            )
        return lines

    def _draw_hold_panel(self, surface: pygame.Surface, rect: pygame.Rect, ship: Ship) -> None:
        items = self._gather_hold_items(ship)
        self._hold_rows = []
        row_height = 76
        spacing = 10
        y = rect.y + 12
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
            if item.can_sell and item.sell_rate and item.sell_currency and item.price_icon_key:
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

            self._hold_rows.append(_HoldRow(item=item, rect=row_rect, button_rect=button_rect))
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
        return items

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

    def _draw_ship_panel(self, surface: pygame.Surface, rect: pygame.Rect, ship: Ship) -> None:
        self._blit_panel(surface, rect, (18, 28, 40, 210), (70, 110, 150))
        header = self.font.render("Ship Overview", True, (210, 236, 255))
        surface.blit(header, (rect.x + 24, rect.y + 16))

        layout_rect = pygame.Rect(rect.x + 24, rect.y + 52, rect.width - 48, rect.height - 88)
        layout_rect.height = int(layout_rect.height * 0.9)

        shape, widgets = self._build_ship_layout(ship, layout_rect)
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
            if widget.rect.collidepoint(mouse_pos):
                hovered_widget = widget
                pygame.draw.rect(surface, (210, 236, 255), widget.rect, 2)

        if hovered_widget:
            self._draw_tooltip(surface, hovered_widget, mouse_pos)

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

    def _draw_tooltip(self, surface: pygame.Surface, widget: _SlotDisplay, mouse_pos: tuple[int, int]) -> None:
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
        text_surfaces = [font.render(line, True, (220, 236, 250)) for line in text_lines]
        text_width = max((surf.get_width() for surf in text_surfaces), default=0)
        width = max(120, text_width + padding * 2)
        height = padding * 2 + sum(surf.get_height() for surf in text_surfaces)
        height += spacing * (len(text_surfaces) - 1 if text_surfaces else 0)
        height += button_padding_top + button_height

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

        button_rect = pygame.Rect(
            tooltip_rect.x + padding,
            cursor_y + button_padding_top,
            tooltip_rect.width - padding * 2,
            button_height,
        )
        self._blit_panel(surface, button_rect, (28, 52, 70, 240), (130, 180, 220))
        button_label = self.mini_font.render("Upgrade", True, (220, 236, 250))
        surface.blit(
            button_label,
            (
                button_rect.centerx - button_label.get_width() // 2,
                button_rect.centery - button_label.get_height() // 2,
            ),
        )


__all__ = ["HangarView"]
