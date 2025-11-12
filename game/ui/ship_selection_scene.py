"""Ship selection scene displayed before launching the sandbox."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Tuple

import pygame
from pygame.math import Vector2

from game.assets.content import ContentManager
from game.engine.scene import Scene
from game.ships.data import ShipFrame
from game.ui.ship_info import MODEL_LAYOUTS

BACKGROUND_COLOR = (6, 10, 16)
PANEL_COLOR = (18, 26, 36)
ACCENT_COLOR = (86, 150, 220)
TEXT_COLOR = (210, 228, 246)
SUBDUED_TEXT_COLOR = (140, 162, 188)
TAB_IDLE = (32, 48, 66)
TAB_ACTIVE = (70, 110, 150)
BUTTON_IDLE = (30, 44, 58)
BUTTON_HOVER = (70, 110, 150)
BUTTON_ACTIVE = (110, 180, 240)
MODEL_LINE_COLOR = (140, 210, 255)
MODEL_FILL_COLOR = (24, 36, 52)
SCROLLBAR_TRACK = (32, 46, 62)
SCROLLBAR_GRIP = (86, 140, 190)


@dataclass
class InfoLine:
    surface: pygame.Surface
    indent: int = 0
    spacing: int = 4


class ShipSelectionScene(Scene):
    """Allow the player to pick a starting hull before entering the sandbox."""

    TABS: Tuple[str, ...] = ("Strike", "Escort", "Line")

    def __init__(self, manager) -> None:
        super().__init__(manager)
        self.content: ContentManager | None = None
        self.font_large: pygame.font.Font | None = None
        self.font_medium: pygame.font.Font | None = None
        self.font_small: pygame.font.Font | None = None
        self.font_tiny: pygame.font.Font | None = None
        self.tab_index: int = 0
        self.ships_by_tab: Dict[str, List[ShipFrame]] = {}
        self.selected_ship_id: str | None = None
        self.rotation: float = 0.0
        self.info_scroll: float = 0.0
        self.info_lines: List[InfoLine] = []
        self.info_total_height: int = 0
        self._last_surface_size: Tuple[int, int] = (0, 0)
        self._tab_rects: List[pygame.Rect] = []
        self._ship_button_rects: List[Tuple[pygame.Rect, ShipFrame]] = []
        self._start_rect: pygame.Rect | None = None
        self._info_view_height: int = 0
        self._hover_button: str | None = None

    # ------------------------------------------------------------------
    def on_enter(self, **kwargs) -> None:
        self.content = kwargs["content"]
        self.font_large = pygame.font.SysFont("consolas", 42)
        self.font_medium = pygame.font.SysFont("consolas", 26)
        self.font_small = pygame.font.SysFont("consolas", 18)
        self.font_tiny = pygame.font.SysFont("consolas", 14)
        self.rotation = 0.0
        self.info_scroll = 0.0
        self._build_ship_catalog()
        self._ensure_selection()
        self._refresh_info_lines()

    # ------------------------------------------------------------------
    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.QUIT:
            pygame.event.post(event)
            return
        if event.type == pygame.KEYDOWN:
            if event.key in (pygame.K_ESCAPE, pygame.K_BACKSPACE):
                self.manager.activate("title")
                return
            if event.key in (pygame.K_RETURN, pygame.K_SPACE):
                self._confirm_selection()
                return
            if event.key == pygame.K_LEFT:
                self._switch_tab(self.tab_index - 1)
                return
            if event.key == pygame.K_RIGHT:
                self._switch_tab(self.tab_index + 1)
                return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            pos = event.pos
            for index, rect in enumerate(self._tab_rects):
                if rect.collidepoint(pos):
                    self._switch_tab(index)
                    return
            for rect, frame in self._ship_button_rects:
                if rect.collidepoint(pos):
                    self._select_ship(frame.id)
                    return
            if self._start_rect and self._start_rect.collidepoint(pos):
                self._confirm_selection()
                return
        if event.type == pygame.MOUSEMOTION:
            pos = event.pos
            self._hover_button = None
            for rect, frame in self._ship_button_rects:
                if rect.collidepoint(pos):
                    self._hover_button = frame.id
                    break
            if self._start_rect and self._start_rect.collidepoint(pos):
                self._hover_button = "start"
        if event.type == pygame.MOUSEWHEEL:
            mouse_pos = pygame.mouse.get_pos()
            info_rect = self._info_panel_rect(self._last_surface_size)
            if info_rect.collidepoint(mouse_pos):
                self._scroll_info(-event.y * 32, info_rect.height - 24)

    def update(self, dt: float) -> None:
        self.rotation = (self.rotation + dt * math.radians(12.0)) % (math.pi * 2.0)

    def render(self, surface: pygame.Surface, alpha: float) -> None:  # noqa: ARG002
        surface.fill(BACKGROUND_COLOR)
        width, height = surface.get_size()
        self._last_surface_size = (width, height)
        title_rect = pygame.Rect(0, 24, width, 48)
        self._draw_title(surface, title_rect)
        tab_rect = pygame.Rect(0, title_rect.bottom + 12, width, 48)
        self._draw_tabs(surface, tab_rect)

        info_rect = self._info_panel_rect((width, height))
        self._draw_info_panel(surface, info_rect)

        selection_area = pygame.Rect(
            info_rect.right + 24,
            tab_rect.bottom + 8,
            width - info_rect.width - 48,
            height - tab_rect.bottom - 40,
        )
        model_rect, picker_rect = self._split_selection_area(selection_area)
        self._draw_model(surface, model_rect)
        self._draw_picker(surface, picker_rect)
        self._draw_start_button(surface, picker_rect)

    # ------------------------------------------------------------------
    def _build_ship_catalog(self) -> None:
        self.ships_by_tab = {tab: [] for tab in self.TABS}
        if not self.content:
            return
        for frame in self.content.ships.frames.values():
            tab = frame.size.capitalize()
            if tab in self.ships_by_tab:
                self.ships_by_tab[tab].append(frame)
        for tab in self.TABS:
            self.ships_by_tab[tab].sort(key=lambda frame: (frame.level_requirement, frame.name))

    def _ensure_selection(self) -> None:
        tab = self.TABS[self.tab_index]
        candidates = self.ships_by_tab.get(tab, [])
        if self.selected_ship_id and any(frame.id == self.selected_ship_id for frame in candidates):
            return
        for label in self.TABS:
            tab_ships = self.ships_by_tab.get(label, [])
            if tab_ships:
                self.tab_index = self.TABS.index(label)
                self.selected_ship_id = tab_ships[0].id
                return
        self.selected_ship_id = None

    def _switch_tab(self, index: int) -> None:
        if not self.TABS:
            return
        self.tab_index = index % len(self.TABS)
        tab = self.TABS[self.tab_index]
        ships = self.ships_by_tab.get(tab, [])
        if ships:
            if not any(frame.id == self.selected_ship_id for frame in ships):
                self.selected_ship_id = ships[0].id
        else:
            self.selected_ship_id = None
        self.info_scroll = 0.0
        self._refresh_info_lines()

    def _select_ship(self, frame_id: str) -> None:
        if self.selected_ship_id == frame_id:
            return
        self.selected_ship_id = frame_id
        self.info_scroll = 0.0
        self._refresh_info_lines()

    def _confirm_selection(self) -> None:
        if not self.selected_ship_id:
            return
        self.manager.set_context(selected_ship_id=self.selected_ship_id)
        self.manager.activate("sandbox", selected_ship_id=self.selected_ship_id)

    # ------------------------------------------------------------------
    def _draw_title(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
        if not self.font_large:
            return
        title = self.font_large.render("Select Your Starting Ship", True, TEXT_COLOR)
        surface.blit(title, (rect.centerx - title.get_width() // 2, rect.y))

    def _draw_tabs(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
        if not self.font_small:
            return
        tab_width = 160
        spacing = 18
        total_width = len(self.TABS) * tab_width + (len(self.TABS) - 1) * spacing
        start_x = rect.centerx - total_width // 2
        self._tab_rects = []
        for index, tab in enumerate(self.TABS):
            button_rect = pygame.Rect(start_x + index * (tab_width + spacing), rect.y, tab_width, rect.height)
            active = index == self.tab_index
            color = TAB_ACTIVE if active else TAB_IDLE
            pygame.draw.rect(surface, color, button_rect, border_radius=10)
            pygame.draw.rect(surface, ACCENT_COLOR, button_rect, 2, border_radius=10)
            label = self.font_small.render(tab, True, TEXT_COLOR if active else SUBDUED_TEXT_COLOR)
            surface.blit(
                label,
                (
                    button_rect.centerx - label.get_width() // 2,
                    button_rect.centery - label.get_height() // 2,
                ),
            )
            self._tab_rects.append(button_rect)

    def _info_panel_rect(self, size: Tuple[int, int]) -> pygame.Rect:
        width, height = size
        panel_width = max(320, int(width * 0.23))
        top = 120
        panel_height = height - top - 48
        return pygame.Rect(32, top, panel_width, panel_height)

    def _draw_info_panel(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
        pygame.draw.rect(surface, PANEL_COLOR, rect, border_radius=12)
        pygame.draw.rect(surface, ACCENT_COLOR, rect, 2, border_radius=12)
        view_height = max(0, rect.height - 24)
        self._info_view_height = view_height
        clip_surface = pygame.Surface((rect.width - 24, view_height), pygame.SRCALPHA)
        clip_surface.fill((0, 0, 0, 0))
        y = -self.info_scroll
        for line in self.info_lines:
            if y + line.surface.get_height() < 0:
                y += line.surface.get_height() + line.spacing
                continue
            if y > view_height:
                break
            clip_surface.blit(line.surface, (12 + line.indent, y))
            y += line.surface.get_height() + line.spacing
        surface.blit(clip_surface, (rect.x + 12, rect.y + 12))
        self._scroll_info(0.0)
        self._draw_scrollbar(surface, rect)

    def _draw_scrollbar(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
        view_height = self._info_view_height
        if self.info_total_height <= view_height or view_height <= 0:
            return
        track = pygame.Rect(rect.right - 16, rect.y + 12, 6, view_height)
        pygame.draw.rect(surface, SCROLLBAR_TRACK, track, border_radius=3)
        view_ratio = view_height / self.info_total_height
        grip_height = max(24, int(track.height * view_ratio))
        max_scroll = self.info_total_height - view_height
        scroll_ratio = self.info_scroll / max_scroll if max_scroll > 0 else 0
        grip_y = track.y + int((track.height - grip_height) * scroll_ratio)
        grip = pygame.Rect(track.x, grip_y, track.width, grip_height)
        pygame.draw.rect(surface, SCROLLBAR_GRIP, grip, border_radius=3)

    def _split_selection_area(self, rect: pygame.Rect) -> Tuple[pygame.Rect, pygame.Rect]:
        picker_height = max(160, int(rect.height * 0.28))
        model_rect = pygame.Rect(rect.x, rect.y, rect.width, rect.height - picker_height - 12)
        picker_rect = pygame.Rect(rect.x, model_rect.bottom + 12, rect.width, picker_height)
        return model_rect, picker_rect

    def _draw_model(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
        pygame.draw.rect(surface, PANEL_COLOR, rect, border_radius=16)
        pygame.draw.rect(surface, ACCENT_COLOR, rect, 2, border_radius=16)
        if not self.selected_ship_id:
            return
        frame = self._current_frame()
        if not frame or not self.font_medium:
            return
        points = self._model_points(frame)
        if not points:
            return
        max_extent_x = max(abs(point.x) for point in points)
        max_extent_y = max(abs(point.y) for point in points)
        if max_extent_x <= 0 or max_extent_y <= 0:
            return
        padding_x = rect.width * 0.08
        padding_y = rect.height * 0.12
        scale_x = (rect.width / 2 - padding_x) / max_extent_x
        scale_y = (rect.height / 2 - padding_y) / max_extent_y
        scale = max(4.0, min(scale_x, scale_y))
        center = Vector2(rect.centerx, rect.centery + 16)
        angle = self.rotation
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)
        rotated = [
            Vector2(
                center.x + (point.x * cos_a - point.y * sin_a) * scale,
                center.y + (point.x * sin_a + point.y * cos_a) * scale,
            )
            for point in points
        ]
        pygame.draw.polygon(surface, MODEL_FILL_COLOR, rotated)
        pygame.draw.lines(surface, MODEL_LINE_COLOR, True, rotated, 2)
        name_surface = self.font_medium.render(frame.name, True, TEXT_COLOR)
        surface.blit(
            name_surface,
            (
                rect.centerx - name_surface.get_width() // 2,
                rect.y + 16,
            ),
        )

    def _draw_picker(self, surface: pygame.Surface, rect: pygame.Rect) -> None:
        pygame.draw.rect(surface, PANEL_COLOR, rect, border_radius=16)
        pygame.draw.rect(surface, ACCENT_COLOR, rect, 2, border_radius=16)
        tab = self.TABS[self.tab_index]
        ships = self.ships_by_tab.get(tab, [])
        if not ships or not self.font_small:
            self._ship_button_rects = []
            return
        padding_x = 24
        padding_y = 20
        button_area_height = max(0, rect.height - padding_y - 68)
        max_columns = max(1, (rect.width - padding_x * 2) // 200)
        columns = max(1, min(len(ships), max_columns))
        rows = max(1, math.ceil(len(ships) / columns))
        spacing_x = 18
        spacing_y = 14
        usable_width = rect.width - padding_x * 2
        usable_height = button_area_height
        if columns > 1:
            button_width = int((usable_width - spacing_x * (columns - 1)) / columns)
        else:
            button_width = int(usable_width)
        if usable_height <= 0:
            button_height = 60
        else:
            if rows > 1:
                button_height = int((usable_height - spacing_y * (rows - 1)) / rows)
            else:
                button_height = int(usable_height)
            button_height = max(48, min(button_height, usable_height))
        total_width = columns * button_width + (columns - 1) * spacing_x
        start_x = rect.x + padding_x + max(0, (usable_width - total_width) // 2)
        start_y = rect.y + padding_y
        self._ship_button_rects = []
        for index, frame in enumerate(ships):
            row = index // columns
            col = index % columns
            x = start_x + col * (button_width + spacing_x)
            y = start_y + row * (button_height + spacing_y)
            button_rect = pygame.Rect(x, y, button_width, button_height)
            active = frame.id == self.selected_ship_id
            hover = self._hover_button == frame.id
            color = BUTTON_ACTIVE if active else BUTTON_HOVER if hover else BUTTON_IDLE
            pygame.draw.rect(surface, color, button_rect, border_radius=12)
            pygame.draw.rect(surface, ACCENT_COLOR, button_rect, 2, border_radius=12)
            label = self.font_small.render(frame.name, True, TEXT_COLOR)
            surface.blit(
                label,
                (
                    button_rect.centerx - label.get_width() // 2,
                    button_rect.y + 18,
                ),
            )
            role = self.font_tiny.render(frame.role, True, SUBDUED_TEXT_COLOR)
            surface.blit(
                role,
                (
                    button_rect.centerx - role.get_width() // 2,
                    button_rect.y + 48,
                ),
            )
            self._ship_button_rects.append((button_rect, frame))

    def _draw_start_button(self, surface: pygame.Surface, picker_rect: pygame.Rect) -> None:
        if not self.font_medium:
            return
        button_height = 48
        button_rect = pygame.Rect(
            picker_rect.centerx - 140,
            picker_rect.bottom - button_height - 20,
            280,
            button_height,
        )
        hover = self._hover_button == "start"
        color = BUTTON_ACTIVE if hover else BUTTON_HOVER
        pygame.draw.rect(surface, color, button_rect, border_radius=12)
        pygame.draw.rect(surface, ACCENT_COLOR, button_rect, 2, border_radius=12)
        label = self.font_medium.render("Launch", True, TEXT_COLOR)
        surface.blit(
            label,
            (
                button_rect.centerx - label.get_width() // 2,
                button_rect.centery - label.get_height() // 2,
            ),
        )
        self._start_rect = button_rect

    # ------------------------------------------------------------------
    def _current_frame(self) -> ShipFrame | None:
        if not self.selected_ship_id or not self.content:
            return None
        return self.content.ships.frames.get(self.selected_ship_id)

    def _model_points(self, frame: ShipFrame) -> List[Vector2]:
        layout = MODEL_LAYOUTS.get(frame.size, MODEL_LAYOUTS["Strike"])
        shape = layout.get("shape")
        if not shape:
            return [Vector2(0, 0)]
        return [Vector2(point[0], point[1]) for point in shape]

    def _scroll_info(self, amount: float, view_height: int | None = None) -> None:
        view = view_height if view_height is not None else self._info_view_height
        if view <= 0:
            self.info_scroll = 0.0
            return
        max_scroll = max(0.0, float(self.info_total_height - view))
        if max_scroll <= 0:
            self.info_scroll = 0.0
            return
        self.info_scroll = max(0.0, min(self.info_scroll + amount, max_scroll))

    def _refresh_info_lines(self) -> None:
        frame = self._current_frame()
        if not frame or not self.content or not self.font_medium or not self.font_small or not self.font_tiny:
            self.info_lines = []
            self.info_total_height = 0
            return
        lines: List[InfoLine] = []
        panel_width = max(320, int(self._last_surface_size[0] * 0.23)) - 48

        def add_line(text: str, font: pygame.font.Font, *, indent: int = 0, spacing: int = 6) -> None:
            if not text:
                return
            surface = font.render(text, True, TEXT_COLOR)
            lines.append(InfoLine(surface=surface, indent=indent, spacing=spacing))

        def add_wrapped(text: str, font: pygame.font.Font, *, indent: int = 0, spacing: int = 6) -> None:
            if not text:
                return
            for segment in self._wrap_text(text, font, panel_width - indent - 12):
                surface = font.render(segment, True, SUBDUED_TEXT_COLOR)
                lines.append(InfoLine(surface=surface, indent=indent, spacing=spacing))

        def add_spacer(height: int = 8) -> None:
            spacer = pygame.Surface((1, max(1, height)), pygame.SRCALPHA)
            spacer.fill((0, 0, 0, 0))
            lines.append(InfoLine(surface=spacer, spacing=0))

        add_line(frame.name, self.font_medium, spacing=10)
        add_line(f"Class: {frame.size}", self.font_small)
        add_line(f"Role: {frame.role}", self.font_small, spacing=8)
        if frame.notes:
            add_line("Overview", self.font_small, spacing=6)
            add_wrapped(frame.notes, self.font_tiny, indent=8, spacing=4)
            add_spacer(10)
        else:
            add_spacer(12)
        add_line("Starting Equipment", self.font_small, spacing=6)
        weapon_lines = self._starting_weapons(frame)
        if weapon_lines:
            for weapon in weapon_lines:
                add_wrapped(f"• {weapon}", self.font_tiny, indent=12, spacing=4)
        else:
            add_wrapped("• No default weapons", self.font_tiny, indent=12, spacing=4)
        module_lines = self._starting_modules(frame)
        if module_lines:
            for module in module_lines:
                add_wrapped(f"• {module}", self.font_tiny, indent=12, spacing=4)
        else:
            add_wrapped("• No default modules", self.font_tiny, indent=12, spacing=4)
        self.info_lines = lines
        self.info_total_height = sum(line.surface.get_height() + line.spacing for line in lines)
        self._scroll_info(0.0)

    def _wrap_text(self, text: str, font: pygame.font.Font, max_width: int) -> List[str]:
        words = text.split()
        if not words:
            return []
        lines: List[str] = []
        current = words[0]
        for word in words[1:]:
            test = f"{current} {word}"
            if font.size(test)[0] <= max_width:
                current = test
            else:
                lines.append(current)
                current = word
        lines.append(current)
        return lines

    def _starting_weapons(self, frame: ShipFrame) -> List[str]:
        if not self.content:
            return []
        weapons: List[str] = []
        for slot, weapon_id in frame.default_weapons.items():
            name = weapon_id
            if weapon_id in self.content.weapons.weapons:
                name = self.content.weapons.get(weapon_id).name
            weapons.append(f"{slot.capitalize()}: {name}")
        return weapons

    def _starting_modules(self, frame: ShipFrame) -> List[str]:
        if not self.content:
            return []
        modules: List[str] = []
        for slot, items in frame.default_modules.items():
            for item_id in items:
                name = item_id
                if item_id in self.content.items.items:
                    name = self.content.items.get(item_id).name
                modules.append(f"{slot.capitalize()}: {name}")
        return modules


__all__ = ["ShipSelectionScene"]
