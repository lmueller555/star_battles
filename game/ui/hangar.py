"""Docking hangar overlay for Outposts."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple

import pygame
from pygame.math import Vector2

from game.assets.content import ContentManager
from game.ships.ship import Ship, WeaponMount
from game.world.station import DockingStation
from game.ui.ship_info import DEFAULT_ANCHORS, MODEL_LAYOUTS


@dataclass
class _SlotDisplay:
    label: str
    detail: str
    rect: pygame.Rect
    filled: bool
    category: str
    slot_type: str


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

    def set_surface(self, surface: pygame.Surface) -> None:
        """Update the target surface when the display size changes."""

        self.surface = surface

    def handle_event(self, event: pygame.event.Event) -> bool:
        """Allow ribbon selection via mouse input."""

        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            pos = getattr(event, "pos", None)
            if not pos:
                return False
            for option, rect in self._ribbon_rects.items():
                if rect.collidepoint(pos):
                    self.active_option = option
                    return True
        return False

    def update(self, dt: float) -> None:
        """Advance hangar background animations."""

        self._interior.update(dt)

    def draw(self, surface: pygame.Surface, ship: Ship, station: DockingStation, distance: float) -> None:
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

        left_width = int(inner_rect.width * (1.0 / 3.0))
        left_rect = pygame.Rect(inner_rect.x, inner_rect.y, left_width, inner_rect.height)
        right_rect = pygame.Rect(left_rect.right + 16, inner_rect.y, inner_rect.width - left_width - 16, inner_rect.height)

        self._draw_left_panel(surface, left_rect)
        self._draw_ship_panel(surface, right_rect, ship)

        footer = self.small_font.render("Press H to undock", True, (170, 210, 240))
        surface.blit(footer, (panel_rect.x + panel_rect.width - footer.get_width() - 28, panel_rect.y + panel_rect.height - 32))

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

    def _draw_left_panel(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
        self._blit_panel(surface, rect, (14, 24, 32, 210), (60, 98, 134))
        title = self.font.render(self.active_option, True, (210, 230, 250))
        surface.blit(title, (rect.x + 20, rect.y + 16))

        content_rect = rect.inflate(-40, -72)
        content_rect.y = rect.y + 54
        self._blit_panel(surface, content_rect, (10, 18, 26, 200), (50, 88, 120))

        lines = self._panel_lines_for_option(self.active_option)
        for idx, line in enumerate(lines):
            text = self.small_font.render(line, True, (180, 208, 228))
            surface.blit(text, (content_rect.x + 16, content_rect.y + 18 + idx * 20))

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
