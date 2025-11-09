"""Game logging utilities with channel toggles."""
from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Optional

DEFAULT_CHANNELS = {
    "physics": True,
    "weapons": True,
    "ai": False,
    "ftl": True,
    "mining": True,
}


@dataclass
class LoggerConfig:
    """Configuration for runtime logging."""

    level: int = logging.INFO
    channels: Dict[str, bool] = None

    @classmethod
    def from_settings(cls, settings_path: Path) -> "LoggerConfig":
        if not settings_path.exists():
            return cls(level=logging.INFO, channels=DEFAULT_CHANNELS.copy())
        try:
            data = json.loads(settings_path.read_text())
        except json.JSONDecodeError:
            return cls(level=logging.INFO, channels=DEFAULT_CHANNELS.copy())
        level_name = data.get("logLevel", "INFO").upper()
        level = getattr(logging, level_name, logging.INFO)
        channels = DEFAULT_CHANNELS.copy()
        channels.update(data.get("logChannels", {}))
        return cls(level=level, channels=channels)


class ChannelLogger:
    """Wrapper that only emits records when the channel is enabled."""

    def __init__(self, name: str, logger: logging.Logger, enabled: bool) -> None:
        self._logger = logger
        self._enabled = enabled
        self._name = name

    @property
    def enabled(self) -> bool:
        return self._enabled

    @enabled.setter
    def enabled(self, value: bool) -> None:
        self._enabled = value

    def debug(self, msg: str, *args, **kwargs) -> None:
        if self._enabled:
            self._logger.debug(msg, *args, **kwargs)

    def info(self, msg: str, *args, **kwargs) -> None:
        if self._enabled:
            self._logger.info(msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs) -> None:
        if self._enabled:
            self._logger.warning(msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs) -> None:
        if self._enabled:
            self._logger.error(msg, *args, **kwargs)


class GameLogger:
    """Central logging registry for the project."""

    def __init__(self, config: LoggerConfig) -> None:
        logging.basicConfig(
            level=config.level,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            stream=sys.stdout,
        )
        self._root = logging.getLogger("game")
        self._channels: Dict[str, ChannelLogger] = {}
        for name, enabled in config.channels.items():
            self._channels[name] = ChannelLogger(
                name,
                logging.getLogger(f"game.{name}"),
                enabled,
            )

    def channel(self, name: str) -> ChannelLogger:
        if name not in self._channels:
            # Unknown channels start disabled until explicitly enabled.
            self._channels[name] = ChannelLogger(
                name,
                logging.getLogger(f"game.{name}"),
                False,
            )
        return self._channels[name]

    def set_enabled(self, name: str, enabled: bool) -> None:
        self.channel(name).enabled = enabled

    def channels(self) -> Iterable[str]:
        return self._channels.keys()


def init_logger(settings_path: Optional[Path] = None) -> GameLogger:
    """Initialise a logger from settings.json."""

    settings_path = settings_path or Path("settings.json")
    config = LoggerConfig.from_settings(settings_path)
    return GameLogger(config)


__all__ = ["GameLogger", "LoggerConfig", "ChannelLogger", "init_logger"]
