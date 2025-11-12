from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import pygame
from pygame.math import Vector2

from game.assets.content import ContentManager
from game.ships.ship import Ship


@dataclass
class EquipmentWidget:
    identifier: Tuple[str, str, int]
    category: str
    slot_type: str
    index: int
    label: str
    detail: str
    rect: pygame.Rect
    filled: bool
    group: Optional[str] = None


MODEL_LAYOUTS: Dict[str, Dict[str, object]] = {
    "Strike": {
        "shape": [
            (0.0, -160.0),
            (72.0, -92.0),
            (96.0, -24.0),
            (88.0, 52.0),
            (24.0, 148.0),
            (-24.0, 148.0),
            (-88.0, 52.0),
            (-96.0, -24.0),
            (-72.0, -92.0),
        ],
        "anchors": {
            "cannon": {"mode": "sym", "y": -80.0, "spacing": 88.0},
            "launcher": {"mode": "sym", "y": -28.0, "spacing": 96.0},
            "hull": {"mode": "sym", "y": 16.0, "spacing": 88.0},
            "engine": {"mode": "sym", "y": 108.0, "spacing": 96.0},
            "computer": {"mode": "sym", "y": -118.0, "spacing": 84.0},
            "utility": {"mode": "sym", "y": 60.0, "spacing": 84.0},
        },
    },
    "Escort": {
        "shape": [
            (0.0, -188.0),
            (118.0, -124.0),
            (156.0, -28.0),
            (156.0, 68.0),
            (112.0, 146.0),
            (0.0, 186.0),
            (-112.0, 146.0),
            (-156.0, 68.0),
            (-156.0, -28.0),
            (-118.0, -124.0),
        ],
        "anchors": {
            "cannon": {"mode": "sym", "y": -76.0, "spacing": 112.0},
            "launcher": {"mode": "sym", "y": -16.0, "spacing": 132.0},
            "hull": {"mode": "sym", "y": 32.0, "spacing": 128.0},
            "engine": {"mode": "sym", "y": 128.0, "spacing": 136.0},
            "computer": {
                "mode": "grid",
                "y": -140.0,
                "spacing_x": 84.0,
                "spacing_y": 40.0,
                "columns": 3,
            },
            "utility": {"mode": "sym", "y": 70.0, "spacing": 110.0},
        },
    },
    "Line": {
        "shape": [
            (0.0, -212.0),
            (160.0, -152.0),
            (206.0, -52.0),
            (206.0, 44.0),
            (176.0, 128.0),
            (100.0, 208.0),
            (0.0, 232.0),
            (-100.0, 208.0),
            (-176.0, 128.0),
            (-206.0, 44.0),
            (-206.0, -52.0),
            (-160.0, -152.0),
        ],
        "anchors": {
            "cannon": {"mode": "sym", "y": -44.0, "spacing": 150.0},
            "launcher": {"mode": "sym", "y": 14.0, "spacing": 176.0},
            "hull": {"mode": "sym", "y": 84.0, "spacing": 168.0},
            "engine": {"mode": "sym", "y": 156.0, "spacing": 192.0},
            "computer": {
                "mode": "grid",
                "y": -156.0,
                "spacing_x": 120.0,
                "spacing_y": 46.0,
                "columns": 2,
            },
            "utility": {"mode": "sym", "y": 120.0, "spacing": 170.0},
        },
    },
    "Capital": {
        "shape": [
            (0.0, -238.0),
            (168.0, -176.0),
            (228.0, -72.0),
            (244.0, 48.0),
            (228.0, 138.0),
            (172.0, 204.0),
            (0.0, 244.0),
            (-172.0, 204.0),
            (-228.0, 138.0),
            (-244.0, 48.0),
            (-228.0, -72.0),
            (-168.0, -176.0),
        ],
        "anchors": {
            "guns": {"mode": "sym", "y": -92.0, "spacing": 188.0},
            "gun": {"mode": "sym", "y": -92.0, "spacing": 188.0},
            "launcher": {"mode": "sym", "y": -18.0, "spacing": 220.0},
            "defensive": {
                "mode": "grid",
                "y": -150.0,
                "spacing_x": 170.0,
                "spacing_y": 56.0,
                "columns": 2,
            },
            "hull": {"mode": "sym", "y": 68.0, "spacing": 204.0},
            "engine": {"mode": "sym", "y": 168.0, "spacing": 210.0},
            "computer": {
                "mode": "grid",
                "y": -188.0,
                "spacing_x": 122.0,
                "spacing_y": 46.0,
                "columns": 3,
            },
            "utility": {"mode": "sym", "y": 118.0, "spacing": 188.0},
        },
    },
    "Outpost": {
        "shape": [
            (-260.0, -220.0),
            (260.0, -220.0),
            (300.0, -120.0),
            (300.0, 120.0),
            (260.0, 220.0),
            (-260.0, 220.0),
            (-300.0, 120.0),
            (-300.0, -120.0),
        ],
        "anchors": {
            "guns": {"mode": "sym", "y": -140.0, "spacing": 260.0},
            "launcher": {"mode": "sym", "y": -40.0, "spacing": 280.0},
            "defensive": {
                "mode": "grid",
                "y": -200.0,
                "spacing_x": 240.0,
                "spacing_y": 70.0,
                "columns": 2,
            },
            "hull": {"mode": "sym", "y": 40.0, "spacing": 240.0},
            "engine": {"mode": "sym", "y": 200.0, "spacing": 260.0},
            "computer": {
                "mode": "grid",
                "y": -240.0,
                "spacing_x": 180.0,
                "spacing_y": 56.0,
                "columns": 3,
            },
            "utility": {"mode": "sym", "y": 120.0, "spacing": 240.0},
        },
    },
}

VANIR_LINE_SHAPE: List[Tuple[float, float]] = [
    (0.0, -212.0),
    (36.0, -204.0),
    (74.0, -190.0),
    (110.0, -172.0),
    (144.0, -148.0),
    (174.0, -118.0),
    (194.0, -84.0),
    (204.0, -48.0),
    (198.0, -16.0),
    (182.0, 10.0),
    (158.0, 36.0),
    (134.0, 58.0),
    (114.0, 78.0),
    (98.0, 102.0),
    (92.0, 130.0),
    (102.0, 154.0),
    (124.0, 178.0),
    (148.0, 202.0),
    (156.0, 222.0),
    (142.0, 232.0),
    (112.0, 228.0),
    (78.0, 212.0),
    (38.0, 196.0),
    (0.0, 232.0),
    (-38.0, 196.0),
    (-78.0, 212.0),
    (-112.0, 228.0),
    (-142.0, 232.0),
    (-156.0, 222.0),
    (-148.0, 202.0),
    (-124.0, 178.0),
    (-102.0, 154.0),
    (-92.0, 130.0),
    (-98.0, 102.0),
    (-114.0, 78.0),
    (-134.0, 58.0),
    (-158.0, 36.0),
    (-182.0, 10.0),
    (-198.0, -16.0),
    (-204.0, -48.0),
    (-194.0, -84.0),
    (-174.0, -118.0),
    (-144.0, -148.0),
    (-110.0, -172.0),
    (-74.0, -190.0),
    (-36.0, -204.0),
]

SHIP_LAYOUT_OVERRIDES: Dict[str, Dict[str, object]] = {
    "vanir_command": {"shape": VANIR_LINE_SHAPE},
    "advanced_vanir": {"shape": VANIR_LINE_SHAPE},
}


def get_model_layout(size: str, frame_id: str | None = None) -> Dict[str, object]:
    base_layout = MODEL_LAYOUTS.get(size, MODEL_LAYOUTS["Strike"])
    layout: Dict[str, object] = dict(base_layout)
    if "shape" in layout:
        layout["shape"] = list(layout["shape"])  # type: ignore[assignment]
    else:
        layout["shape"] = list(MODEL_LAYOUTS["Strike"]["shape"])
    if "anchors" in layout:
        layout["anchors"] = dict(layout["anchors"])  # type: ignore[assignment]
    override = SHIP_LAYOUT_OVERRIDES.get(frame_id or "")
    if override:
        if "shape" in override:
            layout["shape"] = list(override["shape"])  # type: ignore[assignment]
        if "anchors" in override:
            base_anchors = dict(layout.get("anchors", {}))
            base_anchors.update(override["anchors"])  # type: ignore[arg-type]
            layout["anchors"] = base_anchors
    return layout

DEFAULT_ANCHORS: Dict[str, Dict[str, float]] = {
    "default": {"mode": "sym", "y": 0.0, "spacing": 96.0},
    "cannon": {"mode": "sym", "y": -60.0, "spacing": 96.0},
    "launcher": {"mode": "sym", "y": -10.0, "spacing": 110.0},
    "hull": {"mode": "sym", "y": 20.0, "spacing": 110.0},
    "engine": {"mode": "sym", "y": 110.0, "spacing": 120.0},
    "computer": {"mode": "sym", "y": -120.0, "spacing": 90.0},
    "utility": {"mode": "sym", "y": 70.0, "spacing": 100.0},
    "guns": {"mode": "sym", "y": -80.0, "spacing": 180.0},
    "defensive": {"mode": "grid", "y": -140.0, "spacing_x": 150.0, "spacing_y": 60.0, "columns": 2},
}

WIDGET_SIZE = 40
WIDGET_COLORS = {
    "weapon": ((130, 210, 255), (28, 38, 46)),
    "module": ((255, 204, 144), (40, 32, 24)),
}
HIGHLIGHT_COLOR = (255, 220, 140)
BORDER_COLOR = (70, 110, 150)
PANEL_BACKGROUND = (14, 20, 28)
PANEL_OUTLINE = (120, 180, 220)


class ShipInfoPanel:
    def __init__(self, surface: pygame.Surface, content: ContentManager) -> None:
        self.surface = surface
        self.content = content
        self.font = pygame.font.SysFont("consolas", 20)
        self.small_font = pygame.font.SysFont("consolas", 14)
        self.mini_font = pygame.font.SysFont("consolas", 12)
        self.current_ship: Optional[Ship] = None
        self.open: bool = False
        self.panel_rect = pygame.Rect(0, 0, 0, 0)
        self.widgets: List[EquipmentWidget] = []
        self.hover_widget: Optional[EquipmentWidget] = None
        self.selected_widget: Optional[EquipmentWidget] = None
        self._selected_id: Optional[Tuple[str, str, int]] = None
        self._last_surface_size: Tuple[int, int] = (0, 0)
        self._scale: float = 1.0
        self._center = Vector2()
        self._scaled_shape: List[Tuple[int, int]] = []

    # ------------------------------------------------------------------
    def is_open(self) -> bool:
        return self.open and self.current_ship is not None

    def open_for(self, ship: Ship) -> None:
        self.current_ship = ship
        self.open = True
        self._selected_id = None
        self._rebuild_layout()

    def close(self) -> None:
        self.open = False
        self.widgets.clear()
        self.hover_widget = None
        self.selected_widget = None
        self._selected_id = None

    # ------------------------------------------------------------------
    def handle_event(self, event: pygame.event.Event) -> bool:
        if not self.is_open():
            return False
        consumed = False
        if event.type == pygame.MOUSEMOTION:
            self.hover_widget = self._widget_at(event.pos)
            consumed = self.panel_rect.collidepoint(event.pos)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if not self.panel_rect.collidepoint(event.pos):
                return False
            widget = self._widget_at(event.pos)
            if widget:
                self._selected_id = widget.identifier
                self.selected_widget = widget
            else:
                self._selected_id = None
                self.selected_widget = None
            consumed = True
        return consumed

    def draw(self) -> None:
        if not self.is_open():
            return
        surface_size = self.surface.get_size()
        if surface_size != self._last_surface_size:
            self._rebuild_layout()
        else:
            # Always rebuild to reflect loadout changes.
            self._rebuild_layout()
        pygame.draw.rect(self.surface, PANEL_BACKGROUND, self.panel_rect)
        pygame.draw.rect(self.surface, PANEL_OUTLINE, self.panel_rect, 2)
        self._draw_header()
        if self._scaled_shape:
            pygame.draw.polygon(self.surface, (32, 46, 60), self._scaled_shape, 0)
            pygame.draw.lines(self.surface, (160, 210, 240), True, self._scaled_shape, 2)
        for widget in self.widgets:
            self._draw_widget(widget)
        self._draw_sections()
        self._draw_tooltip()

    # ------------------------------------------------------------------
    def _compute_panel_rect(self) -> pygame.Rect:
        width, height = self.surface.get_size()
        panel_width = min(760, max(460, width - 160))
        panel_height = min(520, max(360, height - 180))
        x = max(40, (width - panel_width) // 2)
        y = max(40, (height - panel_height) // 2)
        return pygame.Rect(x, y, panel_width, panel_height)

    def _rebuild_layout(self) -> None:
        self._last_surface_size = self.surface.get_size()
        self.panel_rect = self._compute_panel_rect()
        self.widgets.clear()
        self.hover_widget = None
        self.selected_widget = None
        if not self.current_ship:
            self._scaled_shape = []
            return
        frame = self.current_ship.frame
        layout = get_model_layout(frame.size, frame.id)
        shape_data = layout.get("shape", MODEL_LAYOUTS["Strike"]["shape"])
        shape: List[Tuple[float, float]] = list(shape_data)
        slot_counts = self._slot_counts(self.current_ship)
        positions_by_slot: Dict[str, List[Tuple[float, float]]] = {}
        max_x = max((abs(point[0]) for point in shape), default=1.0)
        max_y = max((abs(point[1]) for point in shape), default=1.0)
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
        self._center = Vector2(
            self.panel_rect.x + self.panel_rect.width * 0.36,
            self.panel_rect.centery,
        )
        self._scale = self._compute_scale(max_x, max_y)
        self._scaled_shape = [
            self._model_to_screen(Vector2(point[0], point[1]))
            for point in shape
        ]
        widgets = self._build_widgets(self.current_ship, positions_by_slot)
        self.widgets = widgets
        if self._selected_id:
            for widget in self.widgets:
                if widget.identifier == self._selected_id:
                    self.selected_widget = widget
                    break

    def _compute_scale(self, max_x: float, max_y: float) -> float:
        available_width = self.panel_rect.width * 0.58
        available_height = self.panel_rect.height - 160.0
        denom_x = max(max_x * 2.0 + 80.0, 1.0)
        denom_y = max(max_y * 2.0 + 80.0, 1.0)
        scale_x = available_width / denom_x if available_width > 0 else 1.0
        scale_y = available_height / denom_y if available_height > 0 else 1.0
        return max(0.3, min(scale_x, scale_y))

    def _model_to_screen(self, point: Vector2) -> Tuple[int, int]:
        converted = Vector2(
            self._center.x + point.x * self._scale,
            self._center.y + point.y * self._scale,
        )
        return int(converted.x), int(converted.y)

    def _slot_counts(self, ship: Ship) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for slot_type, capacity in ship.frame.slots.weapon_families.items():
            counts[slot_type.lower()] = int(capacity)
        counts["hull"] = ship.frame.slots.hull
        counts["engine"] = ship.frame.slots.engine
        counts["computer"] = ship.frame.slots.computer
        counts["utility"] = ship.frame.slots.utility
        return counts

    def _generate_positions(
        self,
        slot_type: str,
        count: int,
        layout: Dict[str, object],
    ) -> List[Tuple[float, float]]:
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

    def _build_widgets(
        self,
        ship: Ship,
        positions_by_slot: Dict[str, List[Tuple[float, float]]],
    ) -> List[EquipmentWidget]:
        widgets: List[EquipmentWidget] = []
        # Weapons
        for slot_type, capacity in ship.frame.slots.weapon_families.items():
            normalized = slot_type.lower()
            positions = positions_by_slot.get(normalized, [])
            mounts = [
                mount
                for mount in ship.mounts
                if self._slot_matches(mount.hardpoint.slot, normalized)
            ]
            for index in range(int(capacity)):
                pos = self._position_for_index(positions, index)
                rect = pygame.Rect(0, 0, WIDGET_SIZE, WIDGET_SIZE)
                rect.center = self._model_to_screen(Vector2(pos[0], pos[1]))
                detail = "Empty"
                filled = False
                group = None
                if index < len(mounts):
                    mount = mounts[index]
                    group = getattr(mount.hardpoint, "group", None)
                    if mount.weapon_id:
                        filled = True
                        detail = self._weapon_name(mount.weapon_id)
                label = f"{self._slot_display_name(slot_type)} {index + 1}"
                identifier = ("weapon", normalized, index)
                widgets.append(
                    EquipmentWidget(
                        identifier=identifier,
                        category="weapon",
                        slot_type=slot_type,
                        index=index,
                        label=label,
                        detail=detail,
                        rect=rect,
                        filled=filled,
                        group=group,
                    )
                )
        # Modules
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
                pos = self._position_for_index(positions, index)
                rect = pygame.Rect(0, 0, WIDGET_SIZE, WIDGET_SIZE)
                rect.center = self._model_to_screen(Vector2(pos[0], pos[1]))
                module = modules[index] if index < len(modules) else None
                detail = module.name if module else "Empty"
                label = f"{self._slot_display_name(slot_type)} {index + 1}"
                identifier = ("module", normalized, index)
                widgets.append(
                    EquipmentWidget(
                        identifier=identifier,
                        category="module",
                        slot_type=slot_type,
                        index=index,
                        label=label,
                        detail=detail,
                        rect=rect,
                        filled=module is not None,
                    )
                )
        return widgets

    def _slot_matches(self, slot_name: str, target: str) -> bool:
        slot = slot_name.lower()
        if slot == target:
            return True
        if target in {"guns", "gun"}:
            return slot in {"guns", "gun"}
        return False

    def _position_for_index(self, positions: List[Tuple[float, float]], index: int) -> Tuple[float, float]:
        if not positions:
            return (0.0, 0.0)
        if index < len(positions):
            return positions[index]
        return positions[-1]

    def _weapon_name(self, weapon_id: str) -> str:
        try:
            weapon = self.content.weapons.get(weapon_id)
            return weapon.name
        except KeyError:
            return weapon_id

    def _slot_display_name(self, slot_type: str) -> str:
        mapping = {
            "cannon": "Cannon",
            "launcher": "Launcher",
            "guns": "Gun",
            "gun": "Gun",
            "defensive": "Defensive",
            "hull": "Hull",
            "engine": "Engine",
            "computer": "Computer",
            "utility": "Utility",
        }
        normalized = slot_type.lower()
        base = mapping.get(normalized, normalized.replace("_", " ").title())
        if base.endswith("s"):
            return base
        return base

    def _widget_at(self, pos: Tuple[int, int]) -> Optional[EquipmentWidget]:
        for widget in self.widgets:
            if widget.rect.collidepoint(pos):
                return widget
        return None

    def _draw_widget(self, widget: EquipmentWidget) -> None:
        center = widget.rect.center
        background, inactive = WIDGET_COLORS.get(widget.category, ((200, 200, 200), (32, 32, 32)))
        fill_color = background if widget.filled else inactive
        pygame.draw.circle(self.surface, fill_color, center, WIDGET_SIZE // 2)
        pygame.draw.circle(self.surface, BORDER_COLOR, center, WIDGET_SIZE // 2, 2)
        if widget == self.hover_widget or widget == self.selected_widget:
            pygame.draw.circle(self.surface, HIGHLIGHT_COLOR, center, WIDGET_SIZE // 2 + 2, 2)
        label = self.mini_font.render(str(widget.index + 1), True, (20, 28, 36))
        label_rect = label.get_rect(center=(center[0], center[1] - 10))
        self.surface.blit(label, label_rect)
        abbrev = self.mini_font.render(widget.slot_type[0].upper(), True, (24, 30, 34))
        abbrev_rect = abbrev.get_rect(center=(center[0], center[1] + 8))
        self.surface.blit(abbrev, abbrev_rect)

    def _draw_header(self) -> None:
        assert self.current_ship is not None
        frame = self.current_ship.frame
        title = self.font.render(frame.name, True, (230, 240, 255))
        subtitle_text = f"{frame.size} Class • {frame.role} • Level {frame.level_requirement}"
        subtitle = self.small_font.render(subtitle_text, True, (180, 210, 230))
        faction_line = frame.faction
        if frame.counterpart:
            faction_line += f" • Counterpart: {frame.counterpart}"
        faction = self.small_font.render(faction_line, True, (170, 200, 220))
        self.surface.blit(title, (self.panel_rect.x + 24, self.panel_rect.y + 20))
        self.surface.blit(subtitle, (self.panel_rect.x + 24, self.panel_rect.y + 48))
        self.surface.blit(faction, (self.panel_rect.x + 24, self.panel_rect.y + 68))

    def _draw_sections(self) -> None:
        assert self.current_ship is not None
        frame = self.current_ship.frame
        stats = self.current_ship.stats
        info_x = int(self.panel_rect.x + self.panel_rect.width * 0.68)
        info_y = self.panel_rect.y + 96
        sections = [
            (
                "Hull Systems",
                [
                    f"Hull: {stats.hull_hp:.0f} HP",
                    f"Regen: {stats.hull_regen:.1f}/s",
                    f"Armor: {stats.armor:.0f}",
                    f"Durability: {stats.durability:.0f}",
                    f"Crit Def: {stats.crit_defense:.0f}",
                ],
            ),
            (
                "Engine Systems",
                [
                    f"Avoidance: {stats.avoidance_rating:.0f}",
                    f"Turn: {stats.turn_rate:.1f}°/s",
                    f"Turn Accel: {stats.turn_accel:.1f}°/s²",
                    f"Accel: {stats.acceleration:.1f} m/s²",
                    f"Cruise: {stats.max_speed:.1f} m/s",
                    f"Boost: {stats.boost_speed:.1f} m/s",
                    f"Boost Cost: {stats.boost_drain:.2f} Tyl/s",
                ],
            ),
            (
                "FTL Systems",
                [
                    f"Range: {stats.ftl_range:.2f} LY",
                    f"Charge: {stats.ftl_charge:.1f} s",
                    f"Threat Charge: {stats.ftl_threat_charge:.1f} s",
                    f"Cost: {stats.ftl_cost_per_ly:.0f} Tyl/LY",
                ],
            ),
            (
                "Computer Systems",
                [
                    f"Power: {stats.power_cap:.0f}",
                    f"Recharge: {stats.power_regen:.1f}/s",
                    f"Firewall: {stats.firewall:.0f}",
                    f"Emitter: {stats.emitter:.0f}",
                    f"DRADIS: {stats.dradis_range:.0f} m",
                    f"Visual: {stats.visual_range:.0f} m",
                ],
            ),
        ]
        if frame.purchase_cost:
            costs = ", ".join(f"{key.title()}: {value:.0f}" for key, value in frame.purchase_cost.items())
            sections.append(("Purchase", [costs]))
        if frame.operating_costs:
            lines = [f"{key.title()}: {value}" for key, value in frame.operating_costs.items()]
            sections.append(("Operating", lines))
        if frame.role_bonuses:
            sections.append(("Role Bonuses", frame.role_bonuses))
        if frame.traits:
            sections.append(("Traits", frame.traits))
        if frame.notes:
            sections.append(("Notes", [frame.notes]))
        for title, lines in sections:
            header = self.small_font.render(title, True, (210, 235, 250))
            self.surface.blit(header, (info_x, info_y))
            info_y += 20
            for line in lines:
                text = self.mini_font.render(line, True, (180, 205, 220))
                self.surface.blit(text, (info_x, info_y))
                info_y += 16
            info_y += 8

    def _draw_tooltip(self) -> None:
        widget = self.hover_widget or self.selected_widget
        if not widget:
            return
        lines = [widget.label, widget.detail if widget.detail else "Empty"]
        if widget.category == "weapon" and widget.group:
            lines.append(f"Group: {widget.group}")
        tooltip_width = max(self.small_font.size(line)[0] for line in lines) + 24
        tooltip_height = len(lines) * 18 + 12
        x = self.panel_rect.x + 24
        y = self.panel_rect.bottom - tooltip_height - 24
        rect = pygame.Rect(x, y, tooltip_width, tooltip_height)
        pygame.draw.rect(self.surface, (20, 30, 40), rect)
        pygame.draw.rect(self.surface, HIGHLIGHT_COLOR, rect, 1)
        for idx, line in enumerate(lines):
            text = self.small_font.render(line, True, (220, 235, 250))
            self.surface.blit(text, (x + 12, y + 6 + idx * 18))


__all__ = ["ShipInfoPanel"]
