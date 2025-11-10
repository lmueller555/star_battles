"""Input mapping and rebind support."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

import pygame

DEFAULT_BINDINGS = {
    "throttle_up": ["K_w"],
    "throttle_down": ["K_s"],
    "strafe_left": ["K_a"],
    "strafe_right": ["K_d"],
    "strafe_up": ["K_q"],
    "strafe_down": ["K_e"],
    "roll_left": ["K_z"],
    "roll_right": ["K_c"],
    "boost": ["K_SPACE"],
    "brake": ["K_LCTRL"],
    "freelook": ["K_f"],
    "fire_primary": ["BUTTON_LEFT"],
    "fire_secondary": ["BUTTON_RIGHT"],
    "fire_group_alpha": ["K_1"],
    "fire_group_beta": ["K_2"],
    "fire_group_gamma": ["K_3"],
    "target_nearest": ["K_t"],
    "target_cycle": ["K_r"],
    "toggle_overlay": ["K_F3"],
    "toggle_auto_throttle": ["K_x"],
    "toggle_auto_level": ["K_l"],
    "open_map": ["K_m"],
    "commit_jump": ["K_j"],
    "activate_pd": ["K_g"],
    "open_hangar": ["K_h"],
    "scan_mining": ["K_v"],
    "toggle_mining": ["K_b"],
    "stabilize_mining": ["K_LSHIFT"],
}

MOUSE_BUTTONS = {
    "BUTTON_LEFT": 0,
    "BUTTON_MIDDLE": 1,
    "BUTTON_RIGHT": 2,
}


@dataclass
class InputBindings:
    """Runtime structure representing current bindings."""

    actions: Dict[str, list[str]] = field(default_factory=lambda: DEFAULT_BINDINGS.copy())

    @classmethod
    def load(cls, path: Path) -> "InputBindings":
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            return cls()
        actions = DEFAULT_BINDINGS.copy()
        actions.update({k: list(v) for k, v in data.get("bindings", {}).items()})
        return cls(actions=actions)

    def save(self, path: Path) -> None:
        path.write_text(json.dumps({"bindings": self.actions}, indent=2))


class InputMapper:
    """Handles button state queries for the simulation."""

    def __init__(self, bindings: Optional[InputBindings] = None) -> None:
        self.bindings = bindings or InputBindings()
        self.axis_state: Dict[str, float] = {
            "strafe_x": 0.0,
            "strafe_y": 0.0,
            "strafe_z": 0.0,
            "throttle": 0.0,
            "look_x": 0.0,
            "look_y": 0.0,
        }
        self.action_state: Dict[str, bool] = {action: False for action in self.bindings.actions}
        self.mouse_delta = (0.0, 0.0)

    def begin_frame(self) -> None:
        self.mouse_delta = (0.0, 0.0)

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.MOUSEMOTION:
            self.mouse_delta = (self.mouse_delta[0] + event.rel[0], self.mouse_delta[1] + event.rel[1])
            return
        if event.type in (pygame.KEYDOWN, pygame.KEYUP):
            key_name = pygame.key.name(event.key).upper()
            for action, keys in self.bindings.actions.items():
                if f"K_{key_name}" in keys:
                    self.action_state[action] = event.type == pygame.KEYDOWN
        if event.type in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
            button_key = None
            for name, idx in MOUSE_BUTTONS.items():
                if idx == event.button - 1:
                    button_key = name
                    break
            if button_key:
                for action, keys in self.bindings.actions.items():
                    if button_key in keys:
                        self.action_state[action] = event.type == pygame.MOUSEBUTTONDOWN

    def update_axes(self) -> None:
        pressed = pygame.key.get_pressed()
        self.axis_state["strafe_x"] = 0.0
        self.axis_state["strafe_y"] = 0.0
        self.axis_state["strafe_z"] = 0.0
        self.axis_state["throttle"] = 0.0
        self.axis_state["look_x"] = 0.0
        self.axis_state["look_y"] = 0.0
        if pressed[pygame.K_a]:
            self.axis_state["strafe_x"] -= 1.0
        if pressed[pygame.K_d]:
            self.axis_state["strafe_x"] += 1.0
        if pressed[pygame.K_q]:
            self.axis_state["strafe_y"] += 1.0
        if pressed[pygame.K_e]:
            self.axis_state["strafe_y"] -= 1.0
        if pressed[pygame.K_w]:
            self.axis_state["throttle"] += 1.0
        if pressed[pygame.K_s]:
            self.axis_state["throttle"] -= 1.0
        if pressed[pygame.K_LEFT]:
            self.axis_state["look_x"] += 1.0
        if pressed[pygame.K_RIGHT]:
            self.axis_state["look_x"] -= 1.0
        if pressed[pygame.K_UP]:
            self.axis_state["look_y"] -= 1.0
        if pressed[pygame.K_DOWN]:
            self.axis_state["look_y"] += 1.0

    def action(self, name: str) -> bool:
        return self.action_state.get(name, False)

    def consume_action(self, name: str) -> bool:
        value = self.action(name)
        self.action_state[name] = False
        return value

    def mouse(self) -> tuple[float, float]:
        return self.mouse_delta


__all__ = ["InputMapper", "InputBindings", "DEFAULT_BINDINGS"]
