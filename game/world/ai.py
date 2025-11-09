"""Simple AI behaviours for sandbox ships."""
from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from pygame.math import Vector3

from game.combat.targeting import is_within_gimbal, pick_nearest_target
from game.ships.ship import Ship

if TYPE_CHECKING:
    from game.world.space import SpaceWorld

class ShipAI:
    """Base AI controller that manages throttle and weapon firing."""

    def __init__(self, ship: Ship) -> None:
        self.ship = ship
        self.target: Optional[Ship] = None
        self._preferred_range: Optional[float] = None

    # ------------------------------------------------------------------
    # Public hooks

    def update(self, world: "SpaceWorld", dt: float) -> None:
        if not self.ship.is_alive():
            return
        self._ensure_ranges(world)
        self.target = self._select_target(world)
        self._reset_controls()
        if self.target and self.target.is_alive():
            self.ship.target_id = id(self.target)
        else:
            self.ship.target_id = None
        self._update_behavior(world, dt)

    def post_update(self, world: "SpaceWorld", dt: float) -> None:
        if not self.ship.is_alive() or not self.target or not self.target.is_alive():
            return
        self._handle_weapons(world)

    # ------------------------------------------------------------------
    # Behaviour template methods

    def _update_behavior(self, world: "SpaceWorld", dt: float) -> None:
        if not self.target or not self.target.is_alive():
            self.ship.control.throttle = 0.2
            return
        # Default behaviour simply faces the target and approaches within range.
        to_target = self.target.kinematics.position - self.ship.kinematics.position
        if to_target.length_squared() == 0:
            return
        self._set_look_direction(to_target)
        preferred = self._preferred_range or 900.0
        distance = to_target.length()
        if distance > preferred * 1.1:
            self.ship.control.throttle = 1.0
            self.ship.control.boost = distance > preferred * 1.6
        else:
            self.ship.control.throttle = 0.4

    def _handle_weapons(self, world: "SpaceWorld") -> None:
        assert self.target is not None
        target = self.target
        if not target.is_alive():
            return
        distance = self.ship.kinematics.position.distance_to(target.kinematics.position)
        for mount in self.ship.mounts:
            if not mount.weapon_id:
                continue
            weapon = world.weapons.get(mount.weapon_id)
            if weapon.slot_type == "launcher":
                if (
                    self.ship.lock_progress >= 1.0
                    and distance <= weapon.max_range * 1.05
                    and self._allow_missile_shot(distance)
                ):
                    world.fire_mount(self.ship, mount, target)
                    self.ship.lock_progress = 0.0
            else:
                if (
                    distance <= weapon.max_range * 1.05
                    and is_within_gimbal(mount, self.ship, target)
                ):
                    world.fire_mount(self.ship, mount, target)

    # ------------------------------------------------------------------
    # Helpers

    def _ensure_ranges(self, world: "SpaceWorld") -> None:
        if self._preferred_range is not None:
            return
        optimal: list[float] = []
        for mount in self.ship.mounts:
            if not mount.weapon_id:
                continue
            weapon = world.weapons.get(mount.weapon_id)
            if weapon.slot_type == "cannon":
                optimal.append(weapon.optimal_range)
        if optimal:
            self._preferred_range = sum(optimal) / len(optimal)
        else:
            self._preferred_range = 900.0

    def _select_target(self, world: "SpaceWorld") -> Optional[Ship]:
        return pick_nearest_target(self.ship, world.ships)

    def _reset_controls(self) -> None:
        self.ship.control.throttle = 0.0
        self.ship.control.boost = False
        self.ship.control.brake = False
        self.ship.control.strafe = Vector3()
        self.ship.control.roll_input = 0.0
        self.ship.control.look_delta = Vector3()

    def _set_look_direction(self, direction: Vector3, strength: float = 1.0) -> None:
        if direction.length_squared() == 0:
            return
        desired = direction.normalize()
        forward = self.ship.kinematics.forward()
        right = self.ship.kinematics.right()
        up = self.ship.kinematics.up()
        local_x = desired.dot(right)
        local_y = desired.dot(up)
        look = Vector3(-local_y, local_x, 0.0) * strength
        if look.length() > 1.0:
            look.scale_to_length(1.0)
        self.ship.control.look_delta = look

    def _allow_missile_shot(self, distance: float) -> bool:
        return True

    @property
    def preferred_range(self) -> float:
        return self._preferred_range if self._preferred_range is not None else 900.0


class InterceptorAI(ShipAI):
    """Fast hit-and-run passes with disengage logic."""

    def __init__(self, ship: Ship) -> None:
        super().__init__(ship)
        self.break_timer: float = 0.0
        self.slash_timer: float = 0.0
        self.slash_direction: float = 1.0

    def _update_behavior(self, world: "SpaceWorld", dt: float) -> None:
        if not self.target or not self.target.is_alive():
            self.ship.control.throttle = 0.4
            return
        ship = self.ship
        to_target = self.target.kinematics.position - ship.kinematics.position
        distance = to_target.length()
        if distance == 0:
            return

        # Decide whether to break off.
        if ship.hull <= ship.stats.hull_hp * 0.45:
            self.break_timer = max(self.break_timer, 4.0)
        if self.break_timer > 0.0:
            self.break_timer = max(0.0, self.break_timer - dt)
            self._set_look_direction(-to_target)
            ship.control.throttle = 1.0
            ship.control.boost = True
            ship.control.strafe = Vector3()
            if ship.hull >= ship.stats.hull_hp * 0.7 and self.break_timer == 0.0:
                self.slash_timer = 0.0
            return

        preferred = self.preferred_range
        self._set_look_direction(to_target)
        ship.control.throttle = 1.0
        ship.control.boost = distance > preferred * 1.35
        ship.control.strafe = Vector3()
        if distance < preferred * 0.9:
            self.slash_timer -= dt
            if self.slash_timer <= 0.0:
                self.slash_direction *= -1.0
                self.slash_timer = 1.4
            ship.control.strafe = Vector3(self.slash_direction * 0.6, 0.0, 0.0)
            ship.control.roll_input = -0.25 * self.slash_direction
        else:
            ship.control.roll_input = 0.0


class AssaultAI(ShipAI):
    """Heavy assault hulls close range and orbit their target."""

    def __init__(self, ship: Ship) -> None:
        super().__init__(ship)
        self.orbit_direction: float = 1.0
        self.orbit_timer: float = 0.0

    def _update_behavior(self, world: "SpaceWorld", dt: float) -> None:
        if not self.target or not self.target.is_alive():
            self.ship.control.throttle = 0.3
            return
        ship = self.ship
        to_target = self.target.kinematics.position - ship.kinematics.position
        distance = to_target.length()
        if distance == 0:
            return
        preferred = max(600.0, self.preferred_range)
        self._set_look_direction(to_target)

        if distance > preferred * 1.15:
            ship.control.throttle = 1.0
            ship.control.boost = distance > preferred * 1.6
            ship.control.strafe = Vector3()
            ship.control.roll_input = 0.0
        else:
            ship.control.throttle = 0.7
            ship.control.boost = False
            if distance < preferred * 0.75:
                self.orbit_timer -= dt
                if self.orbit_timer <= 0.0:
                    self.orbit_direction *= -1.0
                    self.orbit_timer = 2.2
            ship.control.strafe = Vector3(self.orbit_direction * 0.45, 0.0, 0.0)
            ship.control.roll_input = -0.2 * self.orbit_direction


class CommandAI(ShipAI):
    """Command ships stay near allies and avoid isolation."""

    def __init__(self, ship: Ship) -> None:
        super().__init__(ship)
        self.orbit_direction: float = 1.0
        self.realign_timer: float = 0.0

    def _update_behavior(self, world: "SpaceWorld", dt: float) -> None:
        ship = self.ship
        allies: list[Ship] = [
            ally
            for ally in world.ships
            if ally.team == ship.team and ally is not ship and ally.is_alive()
        ]

        ally_center = None
        ally_distance = 0.0
        if allies:
            center = Vector3()
            for ally in allies:
                center += ally.kinematics.position
            center /= len(allies)
            ally_center = center
            ally_distance = center.distance_to(ship.kinematics.position)

        if ally_center is not None and ally_distance > 600.0:
            direction = ally_center - ship.kinematics.position
            self._set_look_direction(direction)
            ship.control.throttle = 0.7
            ship.control.boost = ally_distance > 1000.0
            ship.control.strafe = Vector3()
            return

        if not self.target or not self.target.is_alive():
            ship.control.throttle = 0.25
            return

        to_target = self.target.kinematics.position - ship.kinematics.position
        distance = to_target.length()
        if distance == 0:
            return

        preferred = max(1000.0, self.preferred_range)

        isolated = not allies or ally_distance > 1400.0
        if isolated and distance < preferred:
            # Flee until we can regroup.
            self._set_look_direction(-to_target)
            ship.control.throttle = 1.0
            ship.control.boost = True
            ship.control.strafe = Vector3()
            return

        self._set_look_direction(to_target)
        if distance > preferred * 1.25:
            ship.control.throttle = 0.85
            ship.control.boost = distance > preferred * 1.6
            ship.control.strafe = Vector3()
            ship.control.roll_input = 0.0
        else:
            ship.control.throttle = 0.55
            ship.control.boost = False
            self.realign_timer -= dt
            if distance < preferred * 0.75 and self.realign_timer <= 0.0:
                self.orbit_direction *= -1.0
                self.realign_timer = 3.0
            ship.control.strafe = Vector3(self.orbit_direction * 0.35, 0.0, 0.0)
            ship.control.roll_input = -0.15 * self.orbit_direction

    def _allow_missile_shot(self, distance: float) -> bool:
        # Command hulls tend to save missiles for safer ranges.
        return distance >= self.preferred_range * 0.6


def create_ai_for_ship(ship: Ship) -> Optional[ShipAI]:
    role = ship.frame.role.lower()
    if role == "interceptor":
        return InterceptorAI(ship)
    if role == "assault":
        return AssaultAI(ship)
    if role == "command":
        return CommandAI(ship)
    if role == "multi-role":
        # Escort/multi-role hulls use the assault profile as a baseline.
        return AssaultAI(ship)
    return None


__all__ = [
    "ShipAI",
    "InterceptorAI",
    "AssaultAI",
    "CommandAI",
    "create_ai_for_ship",
]
