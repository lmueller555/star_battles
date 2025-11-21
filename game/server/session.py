"""Lobby/session helpers for coordinating multiplayer clients."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Dict, List

from .hosting import GameServer


@dataclass
class PlayerState:
    """Track the state of a connected player."""

    player_id: int
    name: str
    ready: bool = False

    def as_dict(self) -> dict:
        return {"id": self.player_id, "name": self.name, "ready": self.ready}


class MultiPlayerSession:
    """Minimal lobby/session state that reacts to server messages."""

    def __init__(self) -> None:
        self.players: Dict[int, PlayerState] = {}
        self._lock = asyncio.Lock()

    async def handle_message(self, server: GameServer, client_id: int, message: dict) -> None:
        message_type = message.get("type")
        if message_type == "join":
            await self._handle_join(server, client_id, message)
        elif message_type == "ready":
            await self._handle_ready(server, client_id, message)
        elif message_type == "state_request":
            await server.send_to(client_id, self._snapshot_payload())
        else:
            await server.send_to(client_id, {"type": "error", "message": "Unknown message type"})

    async def handle_disconnect(self, server: GameServer, client_id: int) -> None:
        async with self._lock:
            removed = self.players.pop(client_id, None)
        if removed:
            await server.broadcast({"type": "player_left", "id": removed.player_id})
            await server.broadcast(self._snapshot_payload())

    async def _handle_join(self, server: GameServer, client_id: int, message: dict) -> None:
        name = str(message.get("name") or f"Player {client_id}")
        async with self._lock:
            state = self.players.get(client_id) or PlayerState(client_id, name)
            state.name = name
            self.players[client_id] = state
        await server.send_to(client_id, {"type": "welcome", "id": client_id})
        await server.broadcast(self._snapshot_payload())

    async def _handle_ready(self, server: GameServer, client_id: int, message: dict) -> None:
        ready = bool(message.get("ready", False))
        async with self._lock:
            state = self.players.get(client_id)
            if state is None:
                state = PlayerState(client_id, f"Player {client_id}")
                self.players[client_id] = state
            state.ready = ready
        await server.broadcast({"type": "player_ready", "id": client_id, "ready": ready})
        await server.broadcast(self._snapshot_payload())

    def _snapshot_payload(self) -> dict:
        return {"type": "players", "players": self._players_list()}

    def _players_list(self) -> List[dict]:
        return [player.as_dict() for player in self.players.values()]

