"""Heads-up display drawing."""
from __future__ import annotations

from math import radians, tan
from typing import Optional, Sequence

from dataclasses import dataclass

import pygame
from pygame.math import Vector2

from game.math.ballistics import compute_lead
from game.sensors.dradis import DradisSystem
from game.ui.sector_map import map_display_rect
from game.world.mining import MiningHUDState
from game.ships.ship import Ship


FLANK_SLIDER_WIDTH = 18
FLANK_SLIDER_SPACING = 24
THRUSTER_SPEED_MULTIPLIER = 1.5
SHIP_INFO_BUTTON_SIZE = 48
SHIP_INFO_BUTTON_SPACING = 18


def flank_slider_rect(surface_size: tuple[int, int]) -> pygame.Rect:
    map_rect = map_display_rect(surface_size)
    if map_rect.width <= 0 or map_rect.height <= 0:
        return pygame.Rect(0, 0, 0, 0)
    surface_width = surface_size[0]
    x = min(surface_width - FLANK_SLIDER_WIDTH - FLANK_SLIDER_SPACING, map_rect.right + FLANK_SLIDER_SPACING)
    x = max(map_rect.right + 4, x)
    y = map_rect.top
    return pygame.Rect(x, y, FLANK_SLIDER_WIDTH, map_rect.height)


def ship_info_button_rect(surface_size: tuple[int, int]) -> pygame.Rect:
    map_rect = map_display_rect(surface_size)
    size = SHIP_INFO_BUTTON_SIZE
    if map_rect.width <= 0 or map_rect.height <= 0:
        return pygame.Rect(0, 0, size, size)
    x = max(0, map_rect.left - SHIP_INFO_BUTTON_SPACING - size)
    y = max(0, map_rect.centery - size // 2)
    return pygame.Rect(x, y, size, size)


def _gimbal_radius(
    angle_deg: float,
    fov_deg: float,
    aspect: float,
    screen_size: tuple[int, int],
) -> float:
    """Return the radius in pixels for the edge of a gimbal cone."""

    if angle_deg <= 0.0 or fov_deg <= 0.0:
        return 0.0
    width, height = screen_size
    if width <= 0 or height <= 0:
        return 0.0
    half_vertical = max(1e-5, radians(fov_deg) / 2.0)
    tan_half_vertical = max(1e-5, tan(half_vertical))
    tan_half_horizontal = max(1e-5, tan_half_vertical * max(1e-5, aspect))
    tan_angle = tan(radians(angle_deg))
    radius_h = (width * 0.5) * tan_angle / tan_half_horizontal
    radius_v = (height * 0.5) * tan_angle / tan_half_vertical
    radius = min(radius_h, radius_v)
    if not radius or radius < 0.0:
        return 0.0
    return float(radius)


def format_distance(distance_m: float) -> str:
    if distance_m >= 1000.0:
        return f"{distance_m / 1000.0:.1f} km"
    return f"{distance_m:.0f} m"


@dataclass
class TargetOverlay:
    """Visual data required to render the focused target indicator."""

    rect: pygame.Rect
    name: str
    current_health: float
    max_health: float | None
    distance_m: float
    color: tuple[int, int, int]


@dataclass
class WeaponSlotHUDState:
    label: str
    active: bool
    ready: bool


class HUD:
    def __init__(self, surface: pygame.Surface) -> None:
        self.surface = surface
        self.font = pygame.font.SysFont("consolas", 16)
        self.large_font = pygame.font.SysFont("consolas", 24)
        self.overlay_enabled = False
        self._flank_slider_rect = pygame.Rect(0, 0, 0, 0)
        self._flank_slider_hit_rect = pygame.Rect(0, 0, 0, 0)
        self._ship_info_button_rect = pygame.Rect(0, 0, 0, 0)

    def toggle_overlay(self) -> None:
        self.overlay_enabled = not self.overlay_enabled

    def draw_gimbal_arcs(self, camera, player: Ship, center: Vector2) -> None:
        if not player or not camera:
            return
        surface_size = self.surface.get_size()
        gimbals: dict[str, list[float]] = {}
        for mount in getattr(player, "mounts", []):
            if not getattr(mount, "weapon_id", None):
                continue
            group = getattr(mount.hardpoint, "group", "primary")
            gimbals.setdefault(group, []).append(float(mount.hardpoint.gimbal))
        if not gimbals:
            return
        palette = {
            "primary": (120, 200, 255),
            "aux": (255, 190, 140),
        }
        fallback = (200, 210, 220)
        for index, group in enumerate(sorted(gimbals.keys())):
            angles = gimbals[group]
            max_angle = max(angles)
            radius = _gimbal_radius(max_angle, camera.fov, camera.aspect, surface_size)
            if radius <= 0.0:
                continue
            color = palette.get(group, fallback)
            pygame.draw.circle(
                self.surface,
                color,
                (int(center.x), int(center.y)),
                int(radius),
                1,
            )
            min_angle = min(angles)
            if min_angle < max_angle - 1.5:
                inner_radius = _gimbal_radius(min_angle, camera.fov, camera.aspect, surface_size)
                if inner_radius > 4.0:
                    pygame.draw.circle(
                        self.surface,
                        color,
                        (int(center.x), int(center.y)),
                        int(inner_radius),
                        1,
                    )
            if index >= 2:
                # Avoid overcrowding the reticle if many auxiliary groups exist.
                break

    def draw_ship_wireframe(self, slots: Sequence[WeaponSlotHUDState]) -> None:
        if not slots:
            return
        display_slots = list(slots)[:6]
        if not display_slots:
            return
        _, surface_height = self.surface.get_size()
        panel_size = 140
        bottom_margin = 180
        x = 20
        y = max(12, surface_height - panel_size - bottom_margin)
        rect = pygame.Rect(x, y, panel_size, panel_size)
        pygame.draw.rect(self.surface, (12, 20, 28), rect)
        pygame.draw.rect(self.surface, (70, 110, 150), rect, 1)

        title = self.font.render("Weapons", True, (170, 210, 240))
        title_pos = (
            rect.left,
            max(4, rect.top - title.get_height() - 4),
        )
        self.surface.blit(title, title_pos)

        nose = (rect.centerx, rect.top + 10)
        left_wing = (rect.left + 16, rect.top + rect.height * 0.48)
        right_wing = (rect.right - 16, rect.top + rect.height * 0.48)
        tail_left = (rect.left + rect.width * 0.32, rect.bottom - 18)
        tail_right = (rect.right - rect.width * 0.32, rect.bottom - 18)
        tail = (rect.centerx, rect.bottom - 6)
        outline = [nose, left_wing, tail_left, tail, tail_right, right_wing, nose]
        pygame.draw.lines(self.surface, (100, 150, 190), False, outline, 2)
        pygame.draw.line(
            self.surface,
            (80, 120, 160),
            (rect.centerx, rect.top + 14),
            (rect.centerx, rect.bottom - 18),
            1,
        )

        def layout(count: int) -> list[tuple[float, float]]:
            offsets: list[tuple[float, float]] = []
            if count <= 0:
                return offsets
            front_y = 0.18
            row_spacing = 0.2
            remaining = count
            if count % 2 == 1:
                offsets.append((0.0, front_y))
                remaining -= 1
            row_index = 0
            while remaining > 0:
                y_offset = front_y + row_index * row_spacing
                x_offset = 0.3 + 0.06 * row_index
                offsets.append((-x_offset, y_offset))
                if len(offsets) >= count:
                    break
                offsets.append((x_offset, y_offset))
                remaining -= 2
                row_index += 1
            return offsets[:count]

        offsets = layout(len(display_slots))
        usable_height = rect.height - 64
        base_y = rect.top + 28
        max_radius = rect.width * 0.32
        circle_radius = 9
        active_fill = (255, 210, 120)
        inactive_fill = (26, 36, 52)
        active_border = (255, 220, 160)
        ready_border = (150, 210, 240)
        cooldown_border = (110, 120, 140)

        for slot, (offset_x, offset_y) in zip(display_slots, offsets):
            px = rect.centerx + offset_x * max_radius
            py = base_y + offset_y * usable_height
            center = (int(px), int(py))
            if slot.active:
                pygame.draw.circle(self.surface, active_fill, center, circle_radius)
                pygame.draw.circle(self.surface, active_border, center, circle_radius, 2)
            else:
                pygame.draw.circle(self.surface, inactive_fill, center, circle_radius)
                border_color = ready_border if slot.ready else cooldown_border
                pygame.draw.circle(self.surface, border_color, center, circle_radius, 2)
            if slot.active:
                label_color = (255, 225, 170)
            elif slot.ready:
                label_color = (190, 220, 255)
            else:
                label_color = (140, 160, 180)
            label = self.font.render(slot.label, True, label_color)
            label_rect = label.get_rect()
            label_rect.center = (center[0], center[1] + circle_radius + 12)
            self.surface.blit(label, label_rect)

    def draw_cursor_indicator(self, position: Vector2 | tuple[float, float], visible: bool) -> None:
        if not visible:
            return
        x, y = int(position[0]), int(position[1])
        pygame.draw.circle(self.surface, (255, 255, 255), (x, y), 4, 1)
        pygame.draw.circle(self.surface, (255, 255, 255), (x, y), 1)

    def draw_lead(self, camera, player: Ship, target: Optional[Ship], projectile_speed: float) -> None:
        if not target or projectile_speed <= 0.0:
            return
        origin = player.kinematics.position
        lead_point = compute_lead(origin, target.kinematics.position, target.kinematics.velocity, projectile_speed)
        screen, visible = camera.project(lead_point, self.surface.get_size())
        if visible:
            pygame.draw.circle(self.surface, (255, 220, 120), (int(screen.x), int(screen.y)), 8, 1)

    def draw_target_panel(self, camera, player: Ship, target: Optional[Ship]) -> None:
        if not target:
            text = self.font.render("NO TARGET", True, (200, 200, 200))
            self.surface.blit(text, (20, 20))
            return
        distance = player.kinematics.position.distance_to(target.kinematics.position)
        rel_speed = (target.kinematics.velocity - player.kinematics.velocity).length()
        lines = [
            f"Target: {target.frame.name}",
            f"Range: {format_distance(distance)}",
            f"Relative: {rel_speed:.1f} m/s",
            f"Hull: {target.hull:.0f}/{target.stats.hull_hp:.0f}",
        ]
        for i, line in enumerate(lines):
            text = self.font.render(line, True, (200, 220, 255))
            self.surface.blit(text, (20, 20 + i * 18))

    def draw_target_overlay(self, overlay: TargetOverlay | None) -> None:
        if not overlay:
            return

        rect = overlay.rect
        if rect.width <= 0 or rect.height <= 0:
            return

        color = overlay.color
        pygame.draw.rect(self.surface, color, rect, 1)

        health_text = f"{overlay.current_health:.0f}"
        if overlay.max_health is not None and overlay.max_health > 0.0:
            health_text = f"{overlay.current_health:.0f}/{overlay.max_health:.0f}"
        label = f"{overlay.name} - {health_text}"
        text = self.font.render(label, True, color)
        text_pos = (
            rect.left,
            max(0, rect.top - text.get_height() - 6),
        )
        self.surface.blit(text, text_pos)

        distance_text = self.font.render(f"{overlay.distance_m:.0f} m", True, color)
        distance_pos = (
            rect.left,
            min(self.surface.get_height() - distance_text.get_height(), rect.bottom + 4),
        )
        self.surface.blit(distance_text, distance_pos)

    def draw_meters(self, player: Ship) -> None:
        width = 220
        bar_height = 10
        x = 20
        base_y = self.surface.get_height() - 80
        def draw_bar(label: str, value: float, maximum: float, color: tuple[int, int, int], offset: int) -> None:
            ratio = 0.0 if maximum <= 0 else max(0.0, min(1.0, value / maximum))
            pygame.draw.rect(self.surface, (40, 60, 80), (x, base_y + offset, width, bar_height), 1)
            pygame.draw.rect(self.surface, color, (x, base_y + offset, width * ratio, bar_height))
            text = self.font.render(f"{label}: {value:.0f}/{maximum:.0f}", True, color)
            self.surface.blit(text, (x, base_y + offset - 16))

        draw_bar("Power", player.power, player.stats.power_cap, (120, 200, 255), 0)
        draw_bar("Tylium Reserve", player.resources.tylium, player.tylium_capacity, (255, 190, 120), 24)
        resources = [
            f"Tylium: {player.resources.tylium:.0f}",
            f"Titanium: {player.resources.titanium:.0f}",
            f"Water: {player.resources.water:.0f}",
        ]
        for i, text in enumerate(resources):
            label = self.font.render(text, True, (170, 220, 180))
            self.surface.blit(label, (x, base_y + 48 + i * 18))

    def draw_lock_ring(self, camera, player: Ship, target: Optional[Ship]) -> None:
        if not target or player.lock_progress <= 0.0:
            return
        screen, visible = camera.project(target.kinematics.position, self.surface.get_size())
        if not visible:
            return
        radius = 25 + player.lock_progress * 30
        pygame.draw.circle(self.surface, (255, 200, 60), (int(screen.x), int(screen.y)), int(radius), 1)
        progress_text = self.font.render(f"LOCK {player.lock_progress*100:.0f}%", True, (255, 200, 60))
        self.surface.blit(progress_text, (screen.x - 30, screen.y + radius + 4))

    def draw_dradis(self, dradis: DradisSystem) -> None:
        surface_size = self.surface.get_size()
        map_rect = map_display_rect(surface_size)
        center = Vector2(self.surface.get_width() - 140, self.surface.get_height() - 140)
        radius = 110
        if map_rect.width > 0 and map_rect.height > 0:
            center = Vector2(map_rect.centerx, map_rect.centery)
            max_radius = min(map_rect.width, map_rect.height) / 2.0 - 12.0
            if max_radius > 0.0:
                radius = min(radius, int(max_radius))
        if radius <= 0:
            return
        pygame.draw.circle(self.surface, (60, 90, 110), center, radius, 1)
        for tick in (0.25, 0.5, 0.75, 1.0):
            pygame.draw.circle(self.surface, (40, 70, 90), center, radius * tick, 1)
            label = format_distance(dradis.owner.stats.dradis_range * tick)
            text = self.font.render(label, True, (150, 180, 200))
            self.surface.blit(text, (center.x - 60, center.y - radius * tick - 10))
        for contact in dradis.contacts.values():
            if not contact.detected and contact.time_since_seen > 1.0:
                continue
            rel_pos = contact.ship.kinematics.position - dradis.owner.kinematics.position
            rel_flat = Vector2(rel_pos.x, rel_pos.z)
            if rel_flat.length_squared() == 0:
                continue
            direction = rel_flat.normalize()
            projected = center + direction * radius * min(1.0, contact.distance / dradis.owner.stats.dradis_range)
            base_color = (150, 255, 180) if contact.ship.team == dradis.owner.team else (255, 120, 140)
            intensity = max(0.3, min(1.0, contact.progress if contact.detected else contact.progress * 0.6))
            color = tuple(int(c * intensity) for c in base_color)
            size = 5 if contact.detected else 3
            pygame.draw.circle(self.surface, color, (int(projected.x), int(projected.y)), size, 1)

    def draw_overlay(self, sim_dt: float, fps: float, player: Ship, target: Optional[Ship]) -> None:
        if not self.overlay_enabled:
            return
        lines = [
            f"FPS: {fps:.1f}",
            f"Sim dt: {sim_dt*1000:.2f} ms",
            f"Speed: {player.kinematics.velocity.length():.1f} m/s",
        ]
        if target:
            distance = player.kinematics.position.distance_to(target.kinematics.position)
            lines.append(f"Target dist: {format_distance(distance)}")
            lines.append(f"Lock: {player.lock_progress*100:.0f}%")
        for i, line in enumerate(lines):
            text = self.font.render(line, True, (200, 220, 255))
            self.surface.blit(text, (20, 140 + i * 18))

    def draw(
        self,
        camera,
        player: Ship,
        target: Optional[Ship],
        dradis: DradisSystem,
        projectile_speed: float,
        sim_dt: float,
        fps: float,
        docking_prompt: tuple[str, float, float] | None = None,
        mining_state: MiningHUDState | None = None,
        *,
        ship_info_open: bool = False,
        ship_button_hovered: bool = False,
        target_overlay: TargetOverlay | None = None,
        weapon_slots: Sequence[WeaponSlotHUDState] | None = None,
    ) -> None:
        self.draw_lead(camera, player, target, projectile_speed)
        self.draw_target_panel(camera, player, target)
        self.draw_target_overlay(target_overlay)
        if weapon_slots:
            self.draw_ship_wireframe(weapon_slots)
        self.draw_meters(player)
        self.draw_lock_ring(camera, player, target)
        self.draw_dradis(dradis)
        self.draw_ship_info_button(player, ship_info_open, ship_button_hovered)
        self.draw_flank_speed_slider(player)
        self.draw_overlay(sim_dt, fps, player, target)
        if docking_prompt:
            name, distance, radius = docking_prompt
            self.draw_docking_prompt(name, distance, radius)
        if mining_state:
            self.draw_mining(mining_state)

    def draw_docking_prompt(self, name: str, distance: float, radius: float) -> None:
        header = self.large_font.render(f"Docking available: {name}", True, (255, 232, 150))
        x = self.surface.get_width() / 2 - header.get_width() / 2
        y = 54
        self.surface.blit(header, (x, y))

        distance_text = self.font.render(
            f"Range {distance:.0f} m / {radius:.0f} m", True, (220, 236, 250)
        )
        self.surface.blit(
            distance_text,
            (
                self.surface.get_width() / 2 - distance_text.get_width() / 2,
                y + header.get_height() + 6,
            ),
        )

        options_text = self.font.render(
            "[H] Dock at Hangar   |   [O] Dock & Explore",
            True,
            (255, 230, 160),
        )
        self.surface.blit(
            options_text,
            (
                self.surface.get_width() / 2 - options_text.get_width() / 2,
                y + header.get_height() + distance_text.get_height() + 18,
            ),
        )

    def draw_mining(self, state: MiningHUDState) -> None:
        panel_width = 240
        panel_height = 140
        x = self.surface.get_width() - panel_width - 40
        y = 40
        panel_rect = pygame.Rect(x, y, panel_width, panel_height)
        pygame.draw.rect(self.surface, (18, 32, 42), panel_rect)
        pygame.draw.rect(self.surface, (80, 150, 180), panel_rect, 1)
        title = self.font.render("Mining", True, (210, 240, 255))
        self.surface.blit(title, (x + 12, y + 8))
        if state.active_node:
            node = state.active_node
            resource = node.resource.title()
            lines = [
                f"{node.name}",
                f"{resource} Grade {node.grade:.1f}",
                f"Range: {node.distance:.0f} m",
            ]
            for i, line in enumerate(lines):
                text = self.font.render(line, True, (200, 220, 255))
                self.surface.blit(text, (x + 12, y + 32 + i * 18))

            bar_rect = pygame.Rect(x + 12, y + 90, panel_width - 24, 12)
            pygame.draw.rect(self.surface, (50, 70, 90), bar_rect, 1)
            pygame.draw.rect(
                self.surface,
                (255, 200, 120),
                (bar_rect.x, bar_rect.y, bar_rect.width * max(0.0, min(1.0, state.stability)), bar_rect.height),
            )
            stability_text = self.font.render(f"Stability {state.stability * 100:.0f}%", True, (255, 220, 140))
            self.surface.blit(stability_text, (x + 12, y + 110))
            if state.yield_rate > 0.0:
                yield_text = self.font.render(f"Yield {state.yield_rate:.1f}/s", True, (180, 230, 180))
                self.surface.blit(yield_text, (x + 12, y + 128))
            else:
                idle_text = self.font.render("Stabilise beam", True, (255, 180, 160))
                self.surface.blit(idle_text, (x + 12, y + 128))
        else:
            text = self.font.render("No active beam", True, (180, 200, 220))
            self.surface.blit(text, (x + 12, y + 40))
            if state.scanning_active:
                scanning_text = self.font.render("Scanning...", True, (200, 220, 255))
                self.surface.blit(scanning_text, (x + 12, y + 62))
        if state.status:
            status_text = self.font.render(state.status, True, (255, 230, 160))
            self.surface.blit(status_text, (x + 12, y + panel_height + 8))
        if state.scanning_nodes:
            list_y = y + panel_height + 28
            for node in state.scanning_nodes[:3]:
                progress = node.scan_progress * 100
                label = f"{node.name}: {node.distance:.0f} m"
                text = self.font.render(label, True, (160, 200, 220))
                self.surface.blit(text, (x + 12, list_y))
                status = "ID" if node.discovered else f"Scan {progress:.0f}%"
                status_text = self.font.render(status, True, (140, 190, 210))
                self.surface.blit(status_text, (x + panel_width - status_text.get_width() - 12, list_y))
                list_y += 18

    def draw_flank_speed_slider(self, player: Ship) -> None:
        rect = flank_slider_rect(self.surface.get_size())
        self._flank_slider_rect = rect.copy()
        if rect.width <= 0 or rect.height <= 0:
            self._flank_slider_hit_rect = pygame.Rect(0, 0, 0, 0)
            return
        expanded = rect.inflate(12, 12)
        self._flank_slider_hit_rect = expanded.copy()
        pygame.draw.rect(self.surface, (10, 18, 26), expanded)
        pygame.draw.rect(self.surface, (60, 90, 120), expanded, 1)

        ratio = max(0.0, min(1.0, player.flank_speed_ratio))
        fill_height = int(rect.height * ratio)
        if fill_height > 0:
            fill_rect = pygame.Rect(
                rect.left,
                rect.bottom - fill_height,
                rect.width,
                fill_height,
            )
            fill_color = (255, 200, 120) if player.thrusters_active else (120, 200, 255)
            pygame.draw.rect(self.surface, fill_color, fill_rect)
        pygame.draw.rect(self.surface, (35, 60, 85), rect, 2)

        handle_center_y = rect.bottom - fill_height
        handle_rect = pygame.Rect(
            rect.left - 6,
            int(handle_center_y) - 6,
            rect.width + 12,
            12,
        )
        handle_color = (255, 230, 160) if player.thrusters_active else (200, 220, 240)
        pygame.draw.rect(self.surface, handle_color, handle_rect)
        pygame.draw.rect(self.surface, (70, 110, 150), handle_rect, 1)

        label = self.font.render("Flank Speed", True, (200, 220, 255))
        label_x = max(8, min(self.surface.get_width() - label.get_width() - 8, rect.centerx - label.get_width() // 2))
        label_pos = (
            label_x,
            rect.top - 28,
        )
        self.surface.blit(label, label_pos)

        flank_speed = player.stats.max_speed * ratio
        thruster_speed = flank_speed * THRUSTER_SPEED_MULTIPLIER
        speed_text = self.font.render(
            f"{flank_speed:.0f} m/s | {thruster_speed:.0f} m/s",
            True,
            (160, 210, 230),
        )
        speed_x = max(
            8,
            min(self.surface.get_width() - speed_text.get_width() - 8, rect.centerx - speed_text.get_width() // 2),
        )
        self.surface.blit(
            speed_text,
            (speed_x, rect.bottom + 8),
        )

    def draw_ship_info_button(self, player: Ship, open_state: bool, hovered: bool) -> None:
        rect = ship_info_button_rect(self.surface.get_size())
        self._ship_info_button_rect = rect.copy()
        background = (12, 20, 28)
        border = (70, 110, 150)
        if hovered:
            background = (20, 32, 44)
            border = (120, 180, 220)
        if open_state:
            background = (40, 60, 80)
            border = (255, 200, 140)
        pygame.draw.rect(self.surface, background, rect)
        pygame.draw.rect(self.surface, border, rect, 2)
        nose = (rect.centerx, rect.top + 8)
        port = (rect.left + 10, rect.bottom - 12)
        stern = (rect.centerx, rect.bottom - 4)
        starboard = (rect.right - 10, rect.bottom - 12)
        color = (180, 220, 255) if not open_state else (255, 210, 160)
        pygame.draw.polygon(self.surface, color, [nose, port, stern, starboard], 2)
        engine_bar = pygame.Rect(rect.centerx - 8, rect.bottom - 18, 16, 4)
        pygame.draw.rect(self.surface, color, engine_bar)

        status = "Thrusters ACTIVE" if player.thrusters_active else "Thrusters STANDBY"
        status_color = (255, 200, 140) if player.thrusters_active else (150, 190, 220)
        status_text = self.font.render(status, True, status_color)
        status_x = max(8, rect.centerx - status_text.get_width() // 2)
        self.surface.blit(
            status_text,
            (status_x, rect.bottom + 26),
        )

    @property
    def flank_slider_rect(self) -> pygame.Rect:
        return self._flank_slider_rect.copy()

    @property
    def flank_slider_hit_rect(self) -> pygame.Rect:
        return self._flank_slider_hit_rect.copy()

    @property
    def ship_info_button_rect(self) -> pygame.Rect:
        return self._ship_info_button_rect.copy()


__all__ = [
    "HUD",
    "TargetOverlay",
    "WeaponSlotHUDState",
    "format_distance",
]
