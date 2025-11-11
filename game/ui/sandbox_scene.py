"""Sandbox combat scene."""
from __future__ import annotations

from dataclasses import dataclass

import pygame
from pygame.math import Vector2, Vector3

from game.assets.content import ContentManager
from game.combat.targeting import pick_nearest_target
from game.engine.input import InputMapper
from game.engine.logger import GameLogger
from game.engine.scene import Scene
from game.render.camera import ChaseCamera
from game.render.hud import HUD, TargetOverlay, WeaponSlotHUDState
from game.render.renderer import VectorRenderer
from game.sensors.dradis import DradisSystem
from game.ships.ship import Ship, ShipControlState, WeaponMount
from game.world.ai import create_ai_for_ship
from game.world.asteroids import Asteroid, AsteroidField
from game.world.space import COLLISION_RADII, SpaceWorld
from game.world.mining import MiningHUDState
from game.world.station import DockingStation
from game.ui.sector_map import SectorMapView
from game.ui.hangar import HangarView
from game.ui.ship_info import ShipInfoPanel


KEY_LOOK_SCALE = 6.0
SECTOR_SCALE = 5.0
FORMATION_SPACING = 1200.0 * SECTOR_SCALE
SHIP_FORMATION_OFFSETS = (
    Vector3(-FORMATION_SPACING, 0.0, -FORMATION_SPACING),
    Vector3(0.0, 0.0, 0.0),
    Vector3(FORMATION_SPACING, 0.0, FORMATION_SPACING),
)


@dataclass
class WeaponSlotState:
    index: int
    action: str
    mount: WeaponMount
    active: bool = False

    @property
    def label(self) -> str:
        return str(self.index + 1)


class SandboxScene(Scene):
    def __init__(self, manager) -> None:
        super().__init__(manager)
        self.content: ContentManager | None = None
        self.input: InputMapper | None = None
        self.logger: GameLogger | None = None
        self.world: SpaceWorld | None = None
        self.player: Ship | None = None
        self.dummy: Ship | None = None
        self.dradis: DradisSystem | None = None
        self.camera: ChaseCamera | None = None
        self.renderer: VectorRenderer | None = None
        self.hud: HUD | None = None
        self.sim_dt = 1.0 / 60.0
        self.fps = 60.0
        self.map_view: SectorMapView | None = None
        self.map_open = False
        self.armed_system_id: str | None = None
        self.jump_feedback: str = ""
        self.jump_feedback_timer: float = 0.0
        self.freelook_active: bool = False
        self.freelook_delta: tuple[float, float] = (0.0, 0.0)
        self.mining_state: MiningHUDState | None = None
        self.mining_feedback: str = ""
        self.mining_feedback_timer: float = 0.0
        self.weapon_slots: list[WeaponSlotState] = []
        self._weapon_action_map: dict[str, WeaponSlotState] = {}
        self._tracked_weapon_mount_ids: set[int] = set()
        self.combat_feedback: str = ""
        self.combat_feedback_timer: float = 0.0
        self.flank_slider_ratio: float = 0.0
        self.flank_slider_dragging: bool = False
        self.cursor_pos = Vector2()
        self.cursor_indicator_visible = False
        self._last_mouse_pos: Vector2 | None = None
        self.ship_info_panel: ShipInfoPanel | None = None
        self.ship_info_open: bool = False
        self._ship_button_hovered: bool = False
        self.selected_object: Ship | Asteroid | None = None

    def on_enter(self, **kwargs) -> None:
        self.content = kwargs["content"]
        self.input = kwargs["input"]
        self.logger = kwargs["logger"]
        self.flank_slider_ratio = 0.0
        reused_world: SpaceWorld | None = kwargs.get("world")
        reused_player: Ship | None = kwargs.get("player")

        self.world = None
        self.player = None
        self.dummy = None

        if reused_world is not None and reused_player is not None:
            self.world = reused_world
            self.player = reused_player
        else:
            self.world = SpaceWorld(
                self.content.weapons,
                self.content.sector,
                self.content.stations,
                self.content.mining,
                self.logger,
            )
            player_frame = self.content.ships.get("viper_mk_vii")
            self.player = Ship(player_frame, team="player")
            if self.content:
                self.player.apply_default_loadout(self.content)
            self.player.kinematics.position = Vector3(0.0, 0.0, 0.0)
            self.player.set_flank_speed_ratio(self.flank_slider_ratio)
            self.world.add_ship(self.player)

            if self.content:
                primary_enemy_spawn = (
                    "enemy",
                    "vanir_command",
                    (0.0, 0.0, 820.0),
                    (0.0, 0.0, -8.0),
                )
                self.dummy = None
                last_enemy_spawn: Ship | None = None
                for index, offset in enumerate(SHIP_FORMATION_OFFSETS):
                    frame = self.content.ships.get(primary_enemy_spawn[1])
                    ship = Ship(frame, team=primary_enemy_spawn[0])
                    ship.apply_default_loadout(self.content)
                    ship.kinematics.position = Vector3(primary_enemy_spawn[2]) * SECTOR_SCALE + offset
                    ship.kinematics.velocity = Vector3(primary_enemy_spawn[3])
                    ai = create_ai_for_ship(ship)
                    self.world.add_ship(ship, ai=ai)
                    last_enemy_spawn = ship
                    if index == 1:
                        self.dummy = ship

                if self.dummy is None:
                    self.dummy = last_enemy_spawn

                additional_spawns: list[tuple[str, str, tuple[float, float, float], tuple[float, float, float]]] = [
                    ("player", "glaive_command", (-340.0, -32.0, -210.0), (0.0, 0.0, 0.0)),
                    ("player", "vanir_command", (280.0, -24.0, -300.0), (0.0, 0.0, 0.0)),
                    ("enemy", "viper_mk_vii", (420.0, 60.0, 700.0), (-6.0, 0.0, -20.0)),
                    ("enemy", "viper_mk_vii", (-460.0, 48.0, 780.0), (7.0, 0.0, -18.0)),
                    ("enemy", "glaive_command", (60.0, -36.0, 940.0), (0.0, 0.0, -14.0)),
                    ("enemy", "brimir_carrier", (0.0, -80.0, 1280.0), (0.0, 0.0, -6.0)),
                ]
                for offset in SHIP_FORMATION_OFFSETS:
                    for team, frame_id, position, velocity in additional_spawns:
                        frame = self.content.ships.get(frame_id)
                        ship = Ship(frame, team=team)
                        ship.kinematics.position = Vector3(position) * SECTOR_SCALE + offset
                        ship.kinematics.velocity = Vector3(velocity)
                        ship.apply_default_loadout(self.content)
                        ai = create_ai_for_ship(ship)
                        self.world.add_ship(ship, ai=ai)

                edge_distance = AsteroidField.FIELD_RADIUS * 0.95
                outpost_spawns: list[tuple[str, str, Vector3]] = [
                    ("player", "outpost_regular", Vector3(-edge_distance, 0.0, -edge_distance)),
                    ("enemy", "outpost_regular", Vector3(edge_distance, 0.0, edge_distance)),
                ]
                for team, frame_id, position in outpost_spawns:
                    frame = self.content.ships.get(frame_id)
                    outpost = Ship(frame, team=team)
                    outpost.kinematics.position = position
                    outpost.kinematics.velocity = Vector3(0.0, 0.0, 0.0)
                    outpost.apply_default_loadout(self.content)
                    self.world.add_ship(outpost)

                if self.player:
                    self.world.place_ship_near_outpost(self.player, zero_velocity=True)

        if not self.world or not self.player:
            raise RuntimeError("SandboxScene requires an active world and player ship")

        self.dradis = DradisSystem(self.player)
        surface = pygame.display.get_surface()
        aspect = surface.get_width() / surface.get_height()
        self.camera = ChaseCamera(70.0, aspect)
        self.renderer = VectorRenderer(surface)
        self.hud = HUD(surface)
        self.ship_info_panel = ShipInfoPanel(surface, self.content)
        self.ship_info_open = False
        self._ship_button_hovered = False
        self.map_view = SectorMapView(self.content.sector)
        self.map_open = False
        self.armed_system_id = None
        self.jump_feedback = ""
        self.jump_feedback_timer = 0.0
        self.freelook_active = False
        self.freelook_delta = (0.0, 0.0)
        self.station_contact: tuple[DockingStation, float] | None = None
        self.selected_object = None
        self.hangar_open = False
        self.hangar_view = HangarView(surface, self.content)
        self.mining_state = None
        self.mining_feedback = ""
        self.mining_feedback_timer = 0.0
        self._setup_weapon_slots()
        self.combat_feedback = ""
        self.combat_feedback_timer = 0.0
        if self.player:
            self.flank_slider_ratio = getattr(self.player, "flank_speed_ratio", 0.0)
        self._enter_game_cursor()
        self.player.set_flank_speed_ratio(self.flank_slider_ratio)

    def on_exit(self) -> None:
        self._enter_ui_cursor()
        self.weapon_slots.clear()
        self._weapon_action_map.clear()
        self._tracked_weapon_mount_ids.clear()
        if self.ship_info_panel:
            self.ship_info_panel.close()
        self.ship_info_open = False

    def handle_event(self, event: pygame.event.Event) -> None:
        if self.input:
            self.input.handle_event(event)
        if self.map_open or self.hangar_open or self.ship_info_open:
            self._ship_button_hovered = False
        ui_event = event
        mouse_pos: tuple[int, int] | None = None
        if hasattr(event, "pos"):
            converted = self._surface_mouse_pos(event.pos)
            mouse_pos = converted
            if converted != event.pos:
                payload_source = getattr(event, "dict", None)
                payload = payload_source.copy() if isinstance(payload_source, dict) else {}
                if not payload:
                    for key in ("pos", "rel", "buttons", "button", "touch", "window"):
                        if hasattr(event, key):
                            payload[key] = getattr(event, key)
                payload["pos"] = converted
                ui_event = pygame.event.Event(event.type, payload)
        if (
            event.type == pygame.MOUSEMOTION
            and self.cursor_indicator_visible
            and self.hud
        ):
            width, height = self.hud.surface.get_size()
            delta_x = 0.0
            delta_y = 0.0
            if mouse_pos is not None:
                current_pos = Vector2(mouse_pos)
                if self._last_mouse_pos is None:
                    self._last_mouse_pos = current_pos
                else:
                    delta = current_pos - self._last_mouse_pos
                    delta_x, delta_y = delta.x, delta.y
                    self._last_mouse_pos = current_pos
            else:
                rel = getattr(event, "rel", None)
                if rel:
                    delta_x, delta_y = float(rel[0]), float(rel[1])
            if delta_x != 0.0 or delta_y != 0.0:
                self.cursor_pos.x = max(0.0, min(width, self.cursor_pos.x + delta_x))
                self.cursor_pos.y = max(0.0, min(height, self.cursor_pos.y + delta_y))
        if self.ship_info_open and self.ship_info_panel:
            consumed = self.ship_info_panel.handle_event(ui_event)
            if consumed:
                return
            if (
                mouse_pos is not None
                and event.type == pygame.MOUSEBUTTONDOWN
                and event.button == 1
            ):
                if not self.ship_info_panel.panel_rect.collidepoint(mouse_pos):
                    self._close_ship_info_panel()
                    return
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                self._close_ship_info_panel()
                return
        if self.hangar_open and self.hangar_view:
            consumed = self.hangar_view.handle_event(ui_event)
            if consumed:
                return
        if self.hud:
            button_rect = self.hud.ship_info_button_rect
            if event.type == pygame.MOUSEMOTION and mouse_pos is not None:
                self._ship_button_hovered = (
                    button_rect.width > 0
                    and button_rect.height > 0
                    and button_rect.collidepoint(mouse_pos)
                    and not (self.map_open or self.hangar_open or self.ship_info_open)
                )
            elif (
                event.type == pygame.MOUSEBUTTONDOWN
                and event.button == 1
                and mouse_pos is not None
            ):
                if not (self.map_open or self.hangar_open):
                    if (
                        button_rect.width > 0
                        and button_rect.height > 0
                        and button_rect.collidepoint(mouse_pos)
                    ):
                        self._toggle_ship_info_panel()
                        return
        if self.player and self.hud and not (self.map_open or self.hangar_open or self.ship_info_open):
            if (
                event.type == pygame.MOUSEBUTTONDOWN
                and event.button == 1
                and mouse_pos is not None
            ):
                slider_rect = self.hud.flank_slider_hit_rect
                if slider_rect.width > 0 and slider_rect.height > 0:
                    if slider_rect.collidepoint(mouse_pos):
                        self.flank_slider_dragging = True
                        self._update_flank_slider_from_mouse(mouse_pos)
            elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                self.flank_slider_dragging = False
            elif (
                event.type == pygame.MOUSEMOTION
                and self.flank_slider_dragging
                and mouse_pos is not None
            ):
                self._update_flank_slider_from_mouse(mouse_pos)
            if (
                event.type == pygame.MOUSEBUTTONUP
                and event.button == 1
                and mouse_pos is not None
                and self.camera
            ):
                slider_rect = self.hud.flank_slider_hit_rect
                if (
                    slider_rect.width > 0
                    and slider_rect.height > 0
                    and slider_rect.collidepoint(mouse_pos)
                ):
                    pass
                else:
                    picked = self._pick_target_at(mouse_pos)
                    if picked:
                        self._set_selected_object(picked)
        if (
            event.type in (pygame.MOUSEBUTTONUP, pygame.MOUSEBUTTONDOWN)
            and not (self.player and self.hud)
        ):
            self.flank_slider_dragging = False
        if self.map_open and self.map_view and mouse_pos is not None:
            if event.type == pygame.MOUSEMOTION:
                hovered = self.map_view.pick_system(mouse_pos)
                self.map_view.selection.hovered_id = hovered
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                hovered = self.map_view.pick_system(mouse_pos)
                if hovered:
                    self.armed_system_id = hovered
                    self.map_view.selection.armed_id = hovered
                    if self.content:
                        system = self.content.sector.get(hovered)
                        self.jump_feedback = f"Jump armed: {system.name} (press J to commit)"
                        self.jump_feedback_timer = 4.0
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            if self.ship_info_open:
                self._close_ship_info_panel()
            elif self.map_open:
                self.map_open = False
                self._enter_game_cursor()
            elif self.hangar_open:
                self.hangar_open = False
                self._enter_game_cursor()
            else:
                self.manager.activate("title")

    def update(self, dt: float) -> None:
        self.sim_dt = dt
        if not self.input or not self.player or not self.world or not self.dradis:
            return
        self._refresh_weapon_slots_if_needed()
        self.input.update_axes()
        self.freelook_delta = (0.0, 0.0)
        scanning = False
        stabilizing = False
        self.player.set_flank_speed_ratio(self.flank_slider_ratio)
        if self.input.consume_action("open_map"):
            if self.ship_info_open:
                self._close_ship_info_panel()
            self.map_open = not self.map_open
            if self.map_open:
                self._enter_ui_cursor()
            else:
                self._enter_game_cursor()
            if self.map_open:
                self.hangar_open = False
                self.flank_slider_dragging = False
        if self.map_open:
            self.player.control.look_delta = Vector3()
            self.player.control.strafe = Vector3()
            self.player.control.throttle = 0.0
            self.player.control.boost = False
            self.player.control.brake = False
            self.player.control.roll_input = 0.0
            self.freelook_active = False
        elif self.hangar_open:
            self.player.control.look_delta = Vector3()
            self.player.control.strafe = Vector3()
            self.player.control.throttle = 0.0
            self.player.control.boost = False
            self.player.control.brake = False
            self.player.control.roll_input = 0.0
            self.freelook_active = False
            scanning = False
            stabilizing = False
        elif self.ship_info_open:
            self.player.control.look_delta = Vector3()
            self.player.control.strafe = Vector3()
            self.player.control.throttle = 0.0
            self.player.control.boost = False
            self.player.control.brake = False
            self.player.control.roll_input = 0.0
            self.freelook_active = False
            scanning = False
            stabilizing = False
        else:
            mouse_dx, mouse_dy = self.input.mouse()
            freelook_held = self.input.action("freelook")
            look_input = Vector3(
                self.input.axis_state.get("look_x", 0.0),
                self.input.axis_state.get("look_y", 0.0),
                0.0,
            )
            if look_input.length_squared() > 0.0:
                look_input = look_input.normalize() * KEY_LOOK_SCALE
            if freelook_held:
                self.freelook_active = True
                self.freelook_delta = (mouse_dx, mouse_dy)
                self.player.control.look_delta = Vector3()
            else:
                self.freelook_active = False
                self.player.control.look_delta = look_input
            self.player.control.strafe = Vector3(
                self.input.axis_state.get("strafe_x", 0.0),
                self.input.axis_state.get("strafe_y", 0.0),
                0.0,
            )
            self.player.control.throttle = self.input.axis_state.get("throttle", 0.0)
            self.player.control.boost = self.input.action("boost")
            self.player.control.brake = self.input.action("brake")
            roll_input = 0.0
            pressed = pygame.key.get_pressed()
            if pressed[pygame.K_z]:
                roll_input -= 1.0
            if pressed[pygame.K_c]:
                roll_input += 1.0
            self.player.control.roll_input = roll_input
            scanning = self.input.action("scan_mining")
            stabilizing = self.input.action("stabilize_mining")
            if self.input.consume_action("toggle_mining"):
                if self.world.mining_active():
                    self.world.stop_mining()
                    self._set_mining_feedback("Mining disengaged")
                else:
                    success, message = self.world.start_mining(self.player)
                    self._set_mining_feedback(message)
        if self.input.consume_action("toggle_overlay"):
            self.hud.toggle_overlay()
        if self.input.consume_action("toggle_auto_throttle") and self.player:
            enabled = self.player.toggle_auto_throttle()
            message = "Auto-throttle engaged" if enabled else "Auto-throttle disengaged"
            self._set_combat_feedback(message, duration=2.0)
        if self.input.consume_action("toggle_auto_level") and self.player:
            enabled = self.player.toggle_auto_level()
            message = "Auto-level on" if enabled else "Auto-level off"
            self._set_combat_feedback(message, duration=2.0)
        if self.input.consume_action("target_nearest"):
            target = pick_nearest_target(self.player, self.world.ships)
            if target:
                self.player.target_id = id(target)
                self.selected_object = target
        if self.input.consume_action("target_cycle"):
            enemies = [s for s in self.world.ships if s.team != self.player.team and s.is_alive()]
            if enemies:
                if self.player.target_id is None:
                    self.player.target_id = id(enemies[0])
                    self.selected_object = enemies[0]
                else:
                    idx = next((i for i, s in enumerate(enemies) if id(s) == self.player.target_id), -1)
                    next_enemy = enemies[(idx + 1) % len(enemies)]
                    self.player.target_id = id(next_enemy)
                    self.selected_object = next_enemy

        if self.input.consume_action("commit_jump") and self.armed_system_id and self.world and self.player:
            success, message = self.world.begin_jump(self.player, self.armed_system_id)
            self.jump_feedback = message
            self.jump_feedback_timer = 4.0
            if success:
                self.map_open = False
                self._enter_game_cursor()
                if self.map_view:
                    self.map_view.selection.armed_id = None
                self.armed_system_id = None

        target = next((s for s in self.world.ships if id(s) == self.player.target_id), None)
        if target:
            self.selected_object = target
        elif isinstance(self.selected_object, Ship):
            self.selected_object = None

        if (
            self.input.consume_action("activate_pd")
            and self.world
            and self.player
        ):
            success, message = self.world.activate_countermeasure(self.player)
            if message:
                self._set_combat_feedback(message, duration=2.5 if success else 2.0)

        preferred_target: Ship | Asteroid | None = None
        if isinstance(self.selected_object, (Ship, Asteroid)):
            preferred_target = self.selected_object
        else:
            preferred_target = target

        self._update_weapon_systems(preferred_target)

        station, distance = self.world.nearest_station(self.player)
        if station:
            self.station_contact = (station, distance)
            if distance > station.docking_radius + 50.0 and self.hangar_open:
                self.hangar_open = False
                self._enter_game_cursor()
        else:
            self.station_contact = None
            self.hangar_open = False
        if self.station_contact and self.input.consume_action("open_hangar"):
            station, distance = self.station_contact
            if distance <= station.docking_radius:
                if self.ship_info_open:
                    self._close_ship_info_panel()
                self.hangar_open = not self.hangar_open
                if self.hangar_open:
                    self._enter_ui_cursor()
                else:
                    self._enter_game_cursor()
                if self.hangar_open:
                    self.flank_slider_dragging = False
        if self.station_contact and self.input.consume_action("dock_explore"):
            station, distance = self.station_contact
            if distance <= station.docking_radius and self.world and self.player:
                if self.ship_info_open:
                    self._close_ship_info_panel()
                self.hangar_open = False
                self.player.control = ShipControlState()
                self.player.kinematics.velocity = Vector3()
                self.player.kinematics.angular_velocity = Vector3()
                self._enter_ui_cursor()
                self.world.remove_ship(self.player)
                self.manager.activate(
                    "outpost_interior",
                    content=self.content,
                    input=self.input,
                    logger=self.logger,
                    world=self.world,
                    player=self.player,
                    station=station,
                    distance=distance,
                )
                return
            self._set_combat_feedback("Dock & Explore is not available yet.", duration=2.5)
        if self.hangar_open:
            if self.hangar_view:
                self.hangar_view.update(dt)
            self.player.control.look_delta = Vector3()
            self.player.control.strafe = Vector3()
            self.player.control.throttle = 0.0
            self.player.control.boost = False
            self.player.control.brake = False
            self.player.control.roll_input = 0.0
            self.freelook_active = False
            scanning = False
            stabilizing = False
            self.flank_slider_dragging = False

        self.world.update(dt)
        if self.player and self.camera and self.player.collision_recoil > 0.0:
            strength = max(0.05, self.player.collision_recoil * 0.6)
            self.camera.apply_recoil(strength)
            self.player.collision_recoil = 0.0
        self.dradis.update(self.world.ships, dt)
        self.mining_state = self.world.step_mining(
            self.player,
            dt,
            scanning=scanning and not (self.map_open or self.hangar_open),
            stabilizing=stabilizing and not (self.map_open or self.hangar_open),
        )
        if self.mining_state and self.mining_state.status:
            self._set_mining_feedback(self.mining_state.status, duration=3.0)
        if target and not target.is_alive():
            if self.selected_object is target:
                self.selected_object = None
            self.player.target_id = None
        self.fps = 0.9 * self.fps + 0.1 * (1.0 / dt)
        if self.jump_feedback_timer > 0.0:
            self.jump_feedback_timer = max(0.0, self.jump_feedback_timer - dt)
        if self.mining_feedback_timer > 0.0:
            self.mining_feedback_timer = max(0.0, self.mining_feedback_timer - dt)
        if self.combat_feedback_timer > 0.0:
            self.combat_feedback_timer = max(0.0, self.combat_feedback_timer - dt)

    def render(self, surface: pygame.Surface, alpha: float) -> None:
        if not self.renderer or not self.camera or not self.player or not self.hud or not self.world:
            return
        self.renderer.surface = surface
        self.hud.surface = surface
        self.renderer.clear()
        self.renderer.draw_grid(self.camera, self.player.kinematics.position)
        asteroids = self.world.asteroids_in_current_system()
        self.renderer.draw_asteroids(
            self.camera,
            asteroids,
        )
        target = next(
            (
                s
                for s in self.world.ships
                if id(s) == self.player.target_id and s.is_alive()
            ),
            None,
        )
        lock_mode = bool(target and self.player.lock_progress >= 1.0)
        self.camera.update(
            self.player,
            self.sim_dt,
            freelook_active=self.freelook_active,
            freelook_delta=self.freelook_delta,
            target=target,
            lock_mode=lock_mode,
        )
        for ship in self.world.ships:
            if ship.is_alive():
                self.renderer.draw_ship(self.camera, ship)
        self.renderer.draw_projectiles(self.camera, self.world.projectiles)
        projectile_speed = 0.0
        if target and self.content:
            for mount in self.player.mounts:
                if mount.weapon_id:
                    weapon = self.content.weapons.get(mount.weapon_id)
                    if weapon.wclass != "hitscan":
                        projectile_speed = weapon.projectile_speed
        docking_prompt = None
        if self.station_contact:
            station, distance = self.station_contact
            docking_prompt = (station.name, distance, station.docking_radius)
        overlay_object = self.selected_object
        if isinstance(overlay_object, Ship) and not overlay_object.is_alive():
            overlay_object = None
        if isinstance(overlay_object, Asteroid) and overlay_object not in asteroids:
            overlay_object = None
        if overlay_object is None and target:
            overlay_object = target
        target_overlay = self._build_target_overlay(overlay_object)

        if self.dradis and not self.hangar_open:
            self.hud.draw(
                self.camera,
                self.player,
                target,
                self.dradis,
                projectile_speed,
                self.sim_dt,
                self.fps,
                docking_prompt=docking_prompt if not self.hangar_open else None,
                mining_state=self.mining_state,
                ship_info_open=self.ship_info_open,
                ship_button_hovered=self._ship_button_hovered,
                target_overlay=target_overlay,
                weapon_slots=self._weapon_slot_hud_states(),
            )
        if self.map_open and self.map_view:
            status = self.jump_feedback if self.jump_feedback_timer > 0.0 else None
            self.map_view.draw(surface, self.world, self.player, status)
        elif self.hangar_open and self.hangar_view and self.station_contact:
            station, distance = self.station_contact
            self.hangar_view.set_surface(surface)
            self.hangar_view.draw(surface, self.player, station, distance)
        if self.ship_info_open and self.ship_info_panel:
            self.ship_info_panel.draw()
        if self.jump_feedback_timer > 0.0:
            self._blit_feedback(surface, self.jump_feedback, offset=100)
        if self.mining_feedback_timer > 0.0:
            self._blit_feedback(surface, self.mining_feedback, offset=70)
        if self.combat_feedback_timer > 0.0:
            self._blit_feedback(surface, self.combat_feedback, offset=40)
        if self.hud:
            self.hud.draw_cursor_indicator(self.cursor_pos, self.cursor_indicator_visible)

    def _update_flank_slider_from_mouse(self, mouse_pos: tuple[int, int]) -> None:
        if not self.player or not self.hud:
            return
        rect = self.hud.flank_slider_rect
        if rect.height <= 0:
            return
        rel = (mouse_pos[1] - rect.top) / rect.height
        ratio = 1.0 - rel
        ratio = max(0.0, min(1.0, ratio))
        self.flank_slider_ratio = ratio
        self.player.set_flank_speed_ratio(ratio)

    def _surface_mouse_pos(self, pos: tuple[int, int]) -> tuple[int, int]:
        surface = pygame.display.get_surface()
        if not surface:
            return pos
        surface_width, surface_height = surface.get_size()
        if surface_width <= 0 or surface_height <= 0:
            return pos

        # Convert the window-relative mouse position back into logical surface
        # coordinates.  This accounts for the scaling and letterboxing that
        # pygame applies when the display surface is stretched to fit the
        # window (including when the SCALED flag is active).
        window_width, window_height = pygame.display.get_window_size()
        if window_width <= 0 or window_height <= 0:
            return pos
        scale = min(window_width / surface_width, window_height / surface_height)
        if scale <= 0.0:
            return pos
        display_width = surface_width * scale
        display_height = surface_height * scale
        offset_x = (window_width - display_width) / 2.0
        offset_y = (window_height - display_height) / 2.0
        x = (pos[0] - offset_x) / scale
        y = (pos[1] - offset_y) / scale
        clamped_x = max(0.0, min(float(surface_width), float(x)))
        clamped_y = max(0.0, min(float(surface_height), float(y)))
        return int(round(clamped_x)), int(round(clamped_y))

    def _project_target_rect(
        self, position: Vector3, radius: float
    ) -> tuple[pygame.Rect, float, pygame.Rect] | None:
        if not self.camera or not self.hud:
            return None
        if radius <= 0.0:
            return None
        screen_size = self.hud.surface.get_size()
        center, visible = self.camera.project(position, screen_size)
        if not visible:
            return None
        offsets = [
            self.camera.right * radius,
            -self.camera.right * radius,
            self.camera.up * radius,
            -self.camera.up * radius,
        ]
        xs = [center.x]
        ys = [center.y]
        for offset in offsets:
            point, vis = self.camera.project(position + offset, screen_size)
            if vis:
                xs.append(point.x)
                ys.append(point.y)
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        width = max(max_x - min_x, 18.0)
        height = max(max_y - min_y, 18.0)
        center_x = (min_x + max_x) * 0.5
        center_y = (min_y + max_y) * 0.5
        rect = pygame.Rect(0, 0, int(round(width)), int(round(height)))
        rect.center = (
            int(round(center_x)),
            int(round(center_y)),
        )
        rect = rect.inflate(16, 16)
        pick_rect = rect.copy()
        bounds = pygame.Rect(0, 0, screen_size[0], screen_size[1])
        rect.clamp_ip(bounds)
        return rect, center.z, pick_rect

    def _ship_pick_radius(self, ship: Ship) -> float:
        return COLLISION_RADII.get(ship.frame.size, 12.0)

    def _pick_target_at(self, mouse_pos: tuple[int, int]) -> Ship | Asteroid | None:
        if not (self.world and self.player and self.camera and self.hud):
            return None
        best: Ship | Asteroid | None = None
        best_depth = float("inf")
        surface_size = self.hud.surface.get_size()
        if surface_size[0] <= 0 or surface_size[1] <= 0:
            return None

        for ship in self.world.ships:
            if ship is self.player or not ship.is_alive():
                continue
            projected = self._project_target_rect(
                ship.kinematics.position, self._ship_pick_radius(ship)
            )
            if not projected:
                continue
            _, depth, pick_rect = projected
            if pick_rect.inflate(12, 12).collidepoint(mouse_pos) and depth < best_depth:
                best = ship
                best_depth = depth

        for asteroid in self.world.asteroids_in_current_system():
            projected = self._project_target_rect(
                asteroid.position, max(asteroid.radius, 6.0)
            )
            if not projected:
                continue
            _, depth, pick_rect = projected
            if pick_rect.inflate(8, 8).collidepoint(mouse_pos) and depth < best_depth:
                best = asteroid
                best_depth = depth

        return best

    def _set_selected_object(self, obj: Ship | Asteroid | None) -> None:
        if not self.player:
            return
        previous = self.selected_object
        self.selected_object = obj
        if isinstance(obj, Ship):
            self.player.target_id = id(obj)
        elif obj is None:
            if isinstance(previous, Ship):
                self.player.target_id = None
        else:
            self.player.target_id = None

    def _build_target_overlay(self, obj: Ship | Asteroid | None) -> TargetOverlay | None:
        if not obj or not self.player or not self.camera or not self.hud:
            return None
        if isinstance(obj, Ship):
            if not obj.is_alive():
                return None
            radius = self._ship_pick_radius(obj)
            position = obj.kinematics.position
            max_health = obj.stats.hull_hp
            name = obj.frame.name
            color = (255, 80, 100) if obj.team != self.player.team else (150, 220, 255)
            current_health = obj.hull
        elif isinstance(obj, Asteroid):
            radius = max(obj.radius, 6.0)
            position = obj.position
            max_health = obj.MAX_HEALTH
            name = f"{obj.resource.title()} Asteroid" if obj.resource else "Asteroid"
            color = (210, 190, 150)
            current_health = obj.health
        else:
            return None

        projected = self._project_target_rect(position, radius)
        if not projected:
            return None
        rect, _, _ = projected
        distance = position.distance_to(self.player.kinematics.position)
        return TargetOverlay(
            rect=rect,
            name=name,
            current_health=current_health,
            max_health=max_health,
            distance_m=distance,
            color=color,
        )

    def _set_mining_feedback(self, message: str, duration: float = 2.0) -> None:
        if not message:
            return
        self.mining_feedback = message
        self.mining_feedback_timer = duration

    def _set_combat_feedback(self, message: str, duration: float = 2.5) -> None:
        if not message:
            return
        self.combat_feedback = message
        self.combat_feedback_timer = duration

    def _setup_weapon_slots(self) -> None:
        previous_states = {id(slot.mount): slot.active for slot in self.weapon_slots}
        self.weapon_slots.clear()
        self._weapon_action_map.clear()
        self._tracked_weapon_mount_ids.clear()
        if not self.player:
            return
        actions = [
            "toggle_weapon_slot_1",
            "toggle_weapon_slot_2",
            "toggle_weapon_slot_3",
            "toggle_weapon_slot_4",
            "toggle_weapon_slot_5",
            "toggle_weapon_slot_6",
        ]
        mounts = [mount for mount in self.player.mounts if mount.weapon_id]
        for index, mount in enumerate(mounts[: len(actions)]):
            active = previous_states.get(id(mount), False)
            slot = WeaponSlotState(
                index=index,
                action=actions[index],
                mount=mount,
                active=active,
            )
            self.weapon_slots.append(slot)
            self._weapon_action_map[slot.action] = slot
            self._tracked_weapon_mount_ids.add(id(mount))

    def _refresh_weapon_slots_if_needed(self) -> None:
        if not self.player:
            return
        current = {id(mount) for mount in self.player.mounts if mount.weapon_id}
        if current != self._tracked_weapon_mount_ids:
            self._setup_weapon_slots()

    def _update_weapon_slot_toggles(self) -> None:
        if not self.input:
            return
        for slot in self.weapon_slots:
            if self.input.consume_action(slot.action):
                slot.active = not slot.active

    def _update_weapon_systems(self, target: Ship | Asteroid | None) -> None:
        if not self.input or not self.player or not self.world or not self.content:
            return
        self._refresh_weapon_slots_if_needed()
        self._update_weapon_slot_toggles()
        active_slots = [slot for slot in self.weapon_slots if slot.active]
        if not active_slots:
            return
        preferred: Ship | Asteroid | None = None
        if isinstance(target, Ship):
            if target.team != self.player.team and target.is_alive():
                preferred = target
        elif isinstance(target, Asteroid):
            if not target.is_destroyed():
                preferred = target
        enemies = [
            ship
            for ship in self.world.ships
            if ship.team != self.player.team and ship.is_alive()
        ]
        if not enemies and not preferred:
            return
        for slot in active_slots:
            self._auto_fire_slot(slot, preferred, enemies)

    def _auto_fire_slot(
        self,
        slot: WeaponSlotState,
        preferred_target: Ship | Asteroid | None,
        enemies: list[Ship],
    ) -> None:
        if not self.world or not self.player or not self.content:
            return
        mount = slot.mount
        if not mount.weapon_id:
            return
        try:
            weapon = self.content.weapons.get(mount.weapon_id)
        except KeyError:
            return
        if mount.cooldown > 0.0:
            return
        power_cost = weapon.power_cost
        if self.player.power < power_cost:
            return
        target = self._select_weapon_target(mount, weapon, preferred_target, enemies)
        if not target:
            return
        if (
            weapon.slot_type == "launcher"
            and self.player.lock_progress < 1.0
            and not isinstance(target, Asteroid)
        ):
            return
        result = self.world.fire_mount(self.player, mount, target)
        if weapon.slot_type == "launcher" and mount.cooldown > 0.0:
            self.player.lock_progress = 0.0
        if result and result.hit and self.camera:
            self.camera.apply_recoil(0.4)

    def _select_weapon_target(
        self,
        mount: WeaponMount,
        weapon,
        preferred: Ship | Asteroid | None,
        enemies: list[Ship],
    ) -> Ship | Asteroid | None:
        if not self.player:
            return None
        if preferred and self._target_within_weapon_limits(mount, weapon, preferred):
            return preferred
        best: Ship | None = None
        best_distance = float("inf")
        for enemy in enemies:
            if not self._target_within_weapon_limits(mount, weapon, enemy):
                continue
            distance = enemy.kinematics.position.distance_to(
                self.player.kinematics.position
            )
            if distance < best_distance:
                best = enemy
                best_distance = distance
        return best

    def _target_within_weapon_limits(
        self, mount: WeaponMount, weapon, target: Ship | Asteroid
    ) -> bool:
        if not self.player:
            return False
        if isinstance(target, Ship):
            if not target.is_alive():
                return False
            target_position = target.kinematics.position
        else:
            if target.is_destroyed():
                return False
            target_position = target.position
        to_target = target_position - self.player.kinematics.position
        distance = to_target.length()
        if weapon.max_range > 0.0 and distance > weapon.max_range:
            return False
        if to_target.length_squared() <= 0.0:
            return True
        forward = self.player.kinematics.forward()
        try:
            direction = to_target.normalize()
        except ValueError:
            return True
        angle = forward.angle_to(direction)
        gimbal_limit = min(float(mount.hardpoint.gimbal), float(weapon.gimbal))
        return angle <= gimbal_limit

    def _weapon_slot_hud_states(self) -> list[WeaponSlotHUDState]:
        if not self.player or not self.content or not self.input:
            return []
        self._refresh_weapon_slots_if_needed()
        states: list[WeaponSlotHUDState] = []
        for slot in self.weapon_slots:
            mount = slot.mount
            if not mount.weapon_id:
                continue
            try:
                weapon = self.content.weapons.get(mount.weapon_id)
            except KeyError:
                continue
            active = slot.active
            ready = mount.cooldown <= 0.0 and self.player.power >= weapon.power_cost
            states.append(
                WeaponSlotHUDState(
                    label=slot.label,
                    active=active,
                    ready=ready,
                )
            )
        return states

    def _blit_feedback(self, surface: pygame.Surface, message: str, offset: float) -> None:
        if not message:
            return
        text = self.hud.font.render(message, True, (255, 230, 120))
        surface.blit(
            text,
            (
                surface.get_width() / 2 - text.get_width() / 2,
                surface.get_height() - offset,
            ),
        )

    def _toggle_ship_info_panel(self) -> None:
        if not self.player or not self.ship_info_panel:
            return
        if self.ship_info_open:
            self._close_ship_info_panel()
            return
        self.ship_info_panel.open_for(self.player)
        self.ship_info_open = True
        self.flank_slider_dragging = False
        self._ship_button_hovered = False
        self._enter_ui_cursor()

    def _close_ship_info_panel(self) -> None:
        if not self.ship_info_open:
            return
        if self.ship_info_panel:
            self.ship_info_panel.close()
        self.ship_info_open = False
        self._ship_button_hovered = False
        if not (self.map_open or self.hangar_open):
            self._enter_game_cursor()

    def _enter_game_cursor(self) -> None:
        pygame.mouse.set_visible(False)
        pygame.event.set_grab(True)
        self.cursor_indicator_visible = True
        self._reset_cursor_to_center()
        current_pos = pygame.mouse.get_pos()
        converted = self._surface_mouse_pos(current_pos)
        self._last_mouse_pos = Vector2(converted)

    def _enter_ui_cursor(self) -> None:
        pygame.mouse.set_visible(True)
        pygame.event.set_grab(False)
        self.cursor_indicator_visible = False
        self._last_mouse_pos = None

    def _reset_cursor_to_center(self) -> None:
        surface = pygame.display.get_surface()
        if not surface:
            return
        width, height = surface.get_size()
        self.cursor_pos.update(width / 2, height / 2)


__all__ = ["SandboxScene"]
