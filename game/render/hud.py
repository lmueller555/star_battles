"""Heads-up display drawing."""
from __future__ import annotations

from math import radians, tan
from typing import Optional, Sequence

from dataclasses import dataclass

import pygame
from pygame.math import Vector2

from game.engine.telemetry import PerformanceSnapshot
from game.math.ballistics import compute_lead
from game.sensors.dradis import DradisSystem
from game.ui.sector_map import map_display_rect
from game.world.mining import MiningHUDState
from game.ships.ship import Ship
from game.ships.flight import effective_thruster_speed
from game.render.renderer import WIREFRAMES


FLANK_SLIDER_WIDTH = 18
FLANK_SLIDER_SPACING = 24
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
    slot_type: str
    weapon_class: str
    facing: str
    relative_position: tuple[float, float]
    mount_position: tuple[float, float, float] | None = None


class HUD:
    def __init__(self) -> None:
        self.surface: pygame.Surface | None = None
        self.font = pygame.font.SysFont("consolas", 16)
        self.large_font = pygame.font.SysFont("consolas", 24)
        self.overlay_enabled = False
        self._flank_slider_rect = pygame.Rect(0, 0, 0, 0)
        self._flank_slider_hit_rect = pygame.Rect(0, 0, 0, 0)
        self._ship_info_button_rect = pygame.Rect(0, 0, 0, 0)
        self._top_left_info_bottom = 0

    def set_surface(self, surface: pygame.Surface) -> None:
        self.surface = surface

    @property
    def surface_size(self) -> tuple[int, int]:
        if self.surface:
            return self.surface.get_size()
        display = pygame.display.get_surface()
        if display:
            return display.get_size()
        return 0, 0

    def _active_surface(self) -> pygame.Surface | None:
        if not self.surface:
            display = pygame.display.get_surface()
            if display:
                self.surface = display
        return self.surface

    def toggle_overlay(self) -> None:
        self.overlay_enabled = not self.overlay_enabled

    def draw_gimbal_arcs(self, camera, player: Ship, center: Vector2) -> None:
        surface = self._active_surface()
        if not player or not camera or not surface:
            return
        surface_size = surface.get_size()
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
                surface,
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
                        surface,
                        color,
                        (int(center.x), int(center.y)),
                        int(inner_radius),
                        1,
                    )
            if index >= 2:
                # Avoid overcrowding the reticle if many auxiliary groups exist.
                break

    def draw_ship_wireframe(self, player: Ship, slots: Sequence[WeaponSlotHUDState]) -> None:
        if not player or not slots:
            return
        if not self._active_surface():
            return
        display_slots = list(slots)
        if not display_slots:
            return

        surface_width, surface_height = self.surface.get_size()
        panel_size = 180
        bottom_margin = 180
        x = max(20, surface_width - panel_size - 20)
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

        frame = getattr(player, "frame", None)
        if frame is not None:
            segments_3d = (
                WIREFRAMES.get(frame.id)
                or WIREFRAMES.get(frame.size)
                or WIREFRAMES.get("Strike", [])
            )
        else:
            segments_3d = WIREFRAMES.get("Strike", [])

        xs: list[float] = []
        zs: list[float] = []
        for start, end in segments_3d:
            xs.extend((float(start.x), float(end.x)))
            zs.extend((float(start.z), float(end.z)))
        for slot in display_slots:
            if slot.mount_position:
                x_pos, _, z_pos = slot.mount_position
                xs.append(float(x_pos))
                zs.append(float(z_pos))

        if not xs or not zs:
            xs = [-1.0, 1.0]
            zs = [-1.0, 1.0]

        min_x = min(xs)
        max_x = max(xs)
        min_z = min(zs)
        max_z = max(zs)
        center_x = (min_x + max_x) * 0.5
        center_z = (min_z + max_z) * 0.5
        ship_width = max(1e-3, max_x - min_x)
        ship_depth = max(1e-3, max_z - min_z)

        content_rect = pygame.Rect(
            rect.left + 12,
            rect.top + 24,
            rect.width - 24,
            rect.height - 36,
        )
        if content_rect.width <= 0 or content_rect.height <= 0:
            content_rect = rect
        model_center = Vector2(content_rect.centerx, content_rect.centery)
        scale = min(
            content_rect.width / ship_width,
            content_rect.height / ship_depth,
        )
        if scale <= 0.0:
            scale = 1.0
        scale *= 0.85

        def _project(x: float, z: float) -> Vector2:
            px = (x - center_x) * scale + model_center.x
            py = model_center.y - (z - center_z) * scale
            return Vector2(px, py)

        hull_color = (90, 140, 180)
        for start, end in segments_3d:
            start_2d = _project(float(start.x), float(start.z))
            end_2d = _project(float(end.x), float(end.z))
            pygame.draw.line(
                self.surface,
                hull_color,
                (int(start_2d.x), int(start_2d.y)),
                (int(end_2d.x), int(end_2d.y)),
                2,
            )

        circle_radius = 11
        active_fill = (255, 210, 120)
        inactive_fill = (26, 36, 52)
        active_border = (255, 220, 160)
        ready_border = (150, 210, 240)
        cooldown_border = (110, 120, 140)
        icon_palette = {
            "hitscan": (220, 230, 250),
            "projectile": (255, 210, 150),
            "missile": (170, 240, 220),
            "beam": (210, 190, 255),
        }
        facing_vectors = {
            "forward": Vector2(0.0, -1.0),
            "front": Vector2(0.0, -1.0),
            "rear": Vector2(0.0, 1.0),
            "back": Vector2(0.0, 1.0),
            "left": Vector2(-1.0, 0.0),
            "right": Vector2(1.0, 0.0),
        }

        def _scale_color(color: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
            return tuple(max(0, min(255, int(channel * factor))) for channel in color)

        def _draw_icon(center: tuple[int, int], slot: WeaponSlotHUDState) -> None:
            base_color = icon_palette.get(slot.weapon_class, (210, 220, 235))
            if slot.active:
                icon_color = tuple(min(255, int(c * 1.1 + 20)) for c in base_color)
            elif not slot.ready:
                icon_color = _scale_color(base_color, 0.6)
            else:
                icon_color = base_color
            accent = _scale_color(icon_color, 0.55)
            r = circle_radius - 3
            if r <= 1:
                return
            cx, cy = center
            if slot.weapon_class == "missile" or slot.slot_type in {"launcher", "missile"}:
                top = (cx, cy - r + 2)
                left = (cx - r + 3, cy + r - 2)
                right = (cx + r - 3, cy + r - 2)
                pygame.draw.polygon(self.surface, icon_color, [top, left, right])
                pygame.draw.polygon(self.surface, accent, [top, left, right], 2)
                fin_left = (cx - r + 4, cy + r - 6)
                fin_right = (cx + r - 4, cy + r - 6)
                pygame.draw.line(self.surface, accent, fin_left, (fin_left[0], fin_left[1] + 4), 2)
                pygame.draw.line(self.surface, accent, fin_right, (fin_right[0], fin_right[1] + 4), 2)
            elif slot.weapon_class == "beam":
                start = (cx, cy - r)
                end = (cx, cy + r)
                pygame.draw.line(self.surface, icon_color, start, end, 4)
                pygame.draw.line(self.surface, accent, (cx - 4, cy), (cx + 4, cy), 2)
            elif slot.weapon_class == "projectile":
                pygame.draw.circle(self.surface, icon_color, (cx, cy), r)
                pygame.draw.circle(self.surface, accent, (cx, cy), r, 2)
            else:
                for offset in (-4, 0, 4):
                    start = (cx + offset, cy - r)
                    end = (cx + offset, cy + r)
                    pygame.draw.line(self.surface, icon_color, start, end, 2)
                muzzle = (cx, cy + r)
                pygame.draw.circle(self.surface, accent, muzzle, 2)

        clamp_left = rect.left + circle_radius + 2
        clamp_right = rect.right - circle_radius - 2
        clamp_top = rect.top + circle_radius + 2
        clamp_bottom = rect.bottom - circle_radius - 2
        min_spacing = circle_radius * 2 + 4
        base_offset = circle_radius + 8

        def _clamp_point(point: Vector2) -> Vector2:
            point.x = max(clamp_left, min(clamp_right, point.x))
            point.y = max(clamp_top, min(clamp_bottom, point.y))
            return point

        def _resolve_position(anchor: Vector2, direction: Vector2, existing: Sequence[Vector2]) -> Vector2:
            if direction.length_squared() <= 1e-4:
                direction = Vector2(0.0, -1.0)
            else:
                direction = direction.normalize()
            distance = base_offset
            candidate = _clamp_point(anchor + direction * distance)
            attempt = 0
            while attempt < 12:
                if all(candidate.distance_to(other) >= min_spacing for other in existing):
                    return candidate
                distance += circle_radius * 0.9
                candidate = _clamp_point(anchor + direction * distance)
                attempt += 1
            # Fallback: try rotating the direction to fan indicators apart
            for step in range(1, 9):
                angle = 30 * step
                rotated = direction.rotate(angle if step % 2 else -angle)
                distance = base_offset
                for _ in range(6):
                    candidate = _clamp_point(anchor + rotated * distance)
                    if all(candidate.distance_to(other) >= min_spacing for other in existing):
                        return candidate
                    distance += circle_radius * 0.9
            return candidate

        indicator_data: list[tuple[WeaponSlotHUDState, Vector2]] = []
        centers: list[Vector2] = []

        for slot in display_slots:
            if slot.mount_position:
                mount_x, _, mount_z = slot.mount_position
            else:
                offset_x, offset_z = slot.relative_position
                mount_x = center_x + offset_x * (ship_width * 0.5)
                mount_z = center_z + offset_z * (ship_depth * 0.5)
            anchor = _project(mount_x, mount_z)
            direction = anchor - model_center
            facing = facing_vectors.get(slot.facing)
            if facing is not None:
                direction += facing * 0.4
            indicator_pos = _resolve_position(anchor, direction, centers)
            centers.append(Vector2(indicator_pos))
            indicator_data.append((slot, anchor))

        def _separate_indicators() -> None:
            if len(centers) <= 1:
                return
            max_iterations = 18
            for _ in range(max_iterations):
                adjusted = False
                for i in range(len(centers)):
                    for j in range(i + 1, len(centers)):
                        delta = centers[j] - centers[i]
                        dist = delta.length()
                        if dist < min_spacing - 0.5:
                            if dist <= 1e-4:
                                delta = Vector2(1.0, 0.0)
                                dist = 1.0
                            push = (min_spacing - dist) * 0.5
                            offset = delta.normalize() * push
                            centers[i] = _clamp_point(centers[i] - offset)
                            centers[j] = _clamp_point(centers[j] + offset)
                            adjusted = True
                if not adjusted:
                    break

        _separate_indicators()

        for index, (slot, anchor) in enumerate(indicator_data):
            indicator_pos = centers[index]
            pygame.draw.circle(
                self.surface,
                (60, 110, 150),
                (int(anchor.x), int(anchor.y)),
                3,
                1,
            )
            center = (int(indicator_pos.x), int(indicator_pos.y))

            if slot.active:
                pygame.draw.circle(self.surface, active_fill, center, circle_radius)
                pygame.draw.circle(self.surface, active_border, center, circle_radius, 2)
            else:
                pygame.draw.circle(self.surface, inactive_fill, center, circle_radius)
                border_color = ready_border if slot.ready else cooldown_border
                pygame.draw.circle(self.surface, border_color, center, circle_radius, 2)
            _draw_icon(center, slot)

            if slot.active:
                label_color = (255, 225, 170)
            elif slot.ready:
                label_color = (190, 220, 255)
            else:
                label_color = (140, 160, 180)
            label = self.font.render(slot.label, True, label_color)
            label_rect = label.get_rect()
            direction_vec = centers[index] - anchor
            if direction_vec.length_squared() <= 1e-4:
                direction_vec = Vector2(0.0, -1.0)
            else:
                try:
                    direction_vec = direction_vec.normalize()
                except ValueError:
                    direction_vec = Vector2(0.0, -1.0)
            dx = direction_vec.x
            dy = direction_vec.y
            if abs(dy) >= abs(dx):
                if dy < 0.0:
                    label_rect.midtop = (center[0], center[1] + circle_radius + 6)
                else:
                    label_rect.midbottom = (center[0], center[1] - circle_radius - 6)
            else:
                if dx < 0.0:
                    label_rect.midleft = (center[0] + circle_radius + 6, center[1])
                else:
                    label_rect.midright = (center[0] - circle_radius - 6, center[1])
            self.surface.blit(label, label_rect)

    def draw_cursor_indicator(self, position: Vector2 | tuple[float, float], visible: bool) -> None:
        if not visible:
            return
        surface = self._active_surface()
        if not surface:
            return
        x, y = int(position[0]), int(position[1])
        pygame.draw.circle(surface, (255, 255, 255), (x, y), 4, 1)
        pygame.draw.circle(surface, (255, 255, 255), (x, y), 1)

    def draw_lead(self, camera, player: Ship, target: Optional[Ship], projectile_speed: float) -> None:
        if not target or projectile_speed <= 0.0:
            return
        surface = self._active_surface()
        if not surface:
            return
        origin = player.kinematics.position
        lead_point = compute_lead(origin, target.kinematics.position, target.kinematics.velocity, projectile_speed)
        screen, visible = camera.project(lead_point, surface.get_size())
        if visible:
            pygame.draw.circle(surface, (255, 220, 120), (int(screen.x), int(screen.y)), 8, 1)

    def draw_target_panel(self, camera, player: Ship, target: Optional[Ship]) -> None:
        surface = self._active_surface()
        if not surface:
            return
        if not target:
            text = self.font.render("NO TARGET", True, (200, 200, 200))
            position = (20, 20)
            surface.blit(text, position)
            self._top_left_info_bottom = position[1] + text.get_height()
            return
        distance = player.kinematics.position.distance_to(target.kinematics.position)
        rel_speed = (target.kinematics.velocity - player.kinematics.velocity).length()
        lines = [
            f"Target: {target.frame.name}",
            f"Range: {format_distance(distance)}",
            f"Relative: {rel_speed:.1f} m/s",
            f"Hull: {target.hull:.0f}/{target.stats.hull_hp:.0f}",
        ]
        top = 20
        bottom = top
        for i, line in enumerate(lines):
            text = self.font.render(line, True, (200, 220, 255))
            y = top + i * 18
            surface.blit(text, (20, y))
            bottom = max(bottom, y + text.get_height())
        self._top_left_info_bottom = bottom

    def draw_target_overlay(self, overlay: TargetOverlay | None) -> None:
        if not overlay:
            return
        surface = self._active_surface()
        if not surface:
            return

        rect = overlay.rect
        if rect.width <= 0 or rect.height <= 0:
            return

        color = overlay.color
        pygame.draw.rect(surface, color, rect, 1)

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
        if not self._active_surface():
            return
        width = 220
        bar_height = 10
        x = 20
        line_gap = 24

        min_info_bottom = 20 + self.font.get_height() * 4
        info_bottom = max(self._top_left_info_bottom, min_info_bottom)
        current_y = int(info_bottom + 12)

        def draw_bar(label: str, value: float, maximum: float, color: tuple[int, int, int], y: int) -> int:
            ratio = 0.0 if maximum <= 0 else max(0.0, min(1.0, value / maximum))
            text = self.font.render(f"{label}: {value:.0f}/{maximum:.0f}", True, color)
            text_pos = (x, y - text.get_height() - 4)
            self.surface.blit(text, text_pos)
            bar_rect = pygame.Rect(x, y, width, bar_height)
            pygame.draw.rect(self.surface, (40, 60, 80), bar_rect, 1)
            if ratio > 0.0:
                fill_width = int(bar_rect.width * ratio)
                if fill_width > 0:
                    fill_rect = pygame.Rect(bar_rect.x, bar_rect.y, fill_width, bar_rect.height)
                    pygame.draw.rect(self.surface, color, fill_rect)
            return y + bar_height + line_gap

        current_y = draw_bar("Hull", player.hull, player.stats.hull_hp, (255, 140, 150), current_y)
        current_y = draw_bar("Energy", player.power, player.stats.power_cap, (120, 200, 255), current_y)

        resources = [
            f"Tylium: {player.resources.tylium:.0f}",
            f"Titanium: {player.resources.titanium:.0f}",
            f"Water: {player.resources.water:.0f}",
            f"Cubits: {player.resources.cubits:.0f}",
        ]
        base_y = self.surface.get_height() - 80 + 48
        for i, text in enumerate(resources):
            label = self.font.render(text, True, (170, 220, 180))
            self.surface.blit(label, (x, base_y + i * 18))

    def draw_lock_ring(self, camera, player: Ship, target: Optional[Ship]) -> None:
        if not target or player.lock_progress <= 0.0:
            return
        if not self._active_surface():
            return
        screen, visible = camera.project(target.kinematics.position, self.surface.get_size())
        if not visible:
            return
        radius = 25 + player.lock_progress * 30
        pygame.draw.circle(self.surface, (255, 200, 60), (int(screen.x), int(screen.y)), int(radius), 1)
        progress_text = self.font.render(f"LOCK {player.lock_progress*100:.0f}%", True, (255, 200, 60))
        self.surface.blit(progress_text, (screen.x - 30, screen.y + radius + 4))

    def draw_dradis(self, dradis: DradisSystem) -> None:
        if not self._active_surface():
            return
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

    def draw_overlay(
        self,
        sim_dt: float,
        fps: float,
        player: Ship,
        target: Optional[Ship],
        performance: PerformanceSnapshot | None = None,
    ) -> None:
        if not self._active_surface():
            return
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
        if performance and performance.basis:
            basis = performance.basis
            total_basis = basis.hits + basis.misses
            if total_basis <= 0:
                lines.append("Basis cache: no samples")
            else:
                hit_rate = performance.basis_hit_rate() * 100.0
                lines.append(
                    f"Basis cache: {basis.hits}/{total_basis} hits ({hit_rate:.1f}%) dup={basis.duplicates}"
                )
        if performance and performance.collisions:
            collisions = performance.collisions
            candidates = collisions.candidates
            lines.append(
                "Collisions: cand={} culled={} tested={} time={:.2f}ms".format(
                    candidates,
                    collisions.culled,
                    collisions.tested,
                    collisions.duration_ms,
                )
            )
        if performance and performance.ai:
            counts = performance.ai.counts
            updates = performance.ai.updates

            def _fmt(bucket: str) -> str:
                total = counts.get(bucket, 0)
                updated = updates.get(bucket, 0)
                return f"{updated}/{total}"

            lines.append(
                "AI updates N/M/F/S: {} {} {} {}".format(
                    _fmt("near"),
                    _fmt("mid"),
                    _fmt("far"),
                    _fmt("sentry"),
                )
            )

        for i, line in enumerate(lines):
            text = self.font.render(line, True, (200, 220, 255))
            self.surface.blit(text, (20, 140 + i * 18))

    def draw(
        self,
        surface: pygame.Surface,
        camera,
        player: Ship,
        target: Optional[Ship],
        dradis: DradisSystem,
        projectile_speed: float,
        sim_dt: float,
        fps: float,
        performance: PerformanceSnapshot | None = None,
        docking_prompt: tuple[str, float, float] | None = None,
        mining_state: MiningHUDState | None = None,
        *,
        ship_info_open: bool = False,
        ship_button_hovered: bool = False,
        target_overlay: TargetOverlay | None = None,
        weapon_slots: Sequence[WeaponSlotHUDState] | None = None,
    ) -> None:
        self.set_surface(surface)
        self.draw_lead(camera, player, target, projectile_speed)
        self.draw_target_panel(camera, player, target)
        self.draw_target_overlay(target_overlay)
        if weapon_slots:
            self.draw_ship_wireframe(player, weapon_slots)
        self.draw_meters(player)
        self.draw_lock_ring(camera, player, target)
        self.draw_dradis(dradis)
        self.draw_ship_info_button(player, ship_info_open, ship_button_hovered)
        self.draw_flank_speed_slider(player)
        self.draw_overlay(sim_dt, fps, player, target, performance)
        if docking_prompt:
            name, distance, radius = docking_prompt
            self.draw_docking_prompt(name, distance, radius)
        if mining_state:
            self.draw_mining(mining_state)

    def draw_docking_prompt(self, name: str, distance: float, radius: float) -> None:
        if not self._active_surface():
            return
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
        if not self._active_surface():
            return
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
        if not self._active_surface():
            return
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
        thruster_speed = effective_thruster_speed(player.stats)
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

        current_speed_text = self.font.render(
            f"{player.kinematics.velocity.length():.0f} m/s",
            True,
            (200, 220, 255),
        )
        desired_speed_x = rect.right + 12
        max_speed_x = self.surface.get_width() - current_speed_text.get_width() - 8
        current_speed_x = desired_speed_x if desired_speed_x <= max_speed_x else max_speed_x
        current_speed_x = max(8, current_speed_x)
        current_speed_y = rect.centery - current_speed_text.get_height() // 2
        current_speed_y = max(8, current_speed_y)
        current_speed_y = min(self.surface.get_height() - current_speed_text.get_height() - 8, current_speed_y)
        self.surface.blit(
            current_speed_text,
            (current_speed_x, current_speed_y),
        )

    def draw_ship_info_button(self, player: Ship, open_state: bool, hovered: bool) -> None:
        if not self._active_surface():
            return
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
