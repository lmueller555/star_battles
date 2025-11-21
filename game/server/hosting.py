"""Asyncio-powered TCP server for lightweight multiplayer hosting."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, Optional

MessageHandler = Callable[["GameServer", int, dict], Awaitable[None]]
DisconnectHandler = Callable[["GameServer", int], Awaitable[None]]


@dataclass
class ClientInfo:
    """Metadata for a connected client."""

    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    address: tuple[str, int]
    name: Optional[str] = None

    async def send(self, payload: dict) -> None:
        data = json.dumps(payload).encode("utf-8") + b"\n"
        self.writer.write(data)
        await self.writer.drain()

    async def close(self) -> None:
        try:
            self.writer.close()
            await self.writer.wait_closed()
        except ConnectionError:
            # Connection already closed by peer.
            pass


class GameServer:
    """Small TCP server that relays JSON messages to connected clients."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 0,
        *,
        on_message: Optional[MessageHandler] = None,
        on_disconnect: Optional[DisconnectHandler] = None,
    ) -> None:
        self.host = host
        self.port = port
        self._server: asyncio.AbstractServer | None = None
        self._clients: Dict[int, ClientInfo] = {}
        self._next_id = 1
        self._on_message = on_message
        self._on_disconnect = on_disconnect
        self._lock = asyncio.Lock()
        self._session = None

    @property
    def clients(self) -> Dict[int, ClientInfo]:
        return self._clients

    @property
    def address(self) -> tuple[str, int]:
        if self._server is None:
            return self.host, self.port
        sock = next(iter(self._server.sockets), None)
        if sock is None:
            return self.host, self.port
        return sock.getsockname()[0], sock.getsockname()[1]

    def attach_session(self, session: object) -> None:
        """Attach a session helper that implements multiplayer state.

        The session should expose ``handle_message(server, client_id, message)``
        and ``handle_disconnect(server, client_id)`` coroutines. This keeps the
        networking layer generic while letting higher-level code manage lobby
        semantics.
        """

        self._session = session

    async def start(self) -> None:
        if self._server is not None:
            return
        self._server = await asyncio.start_server(self._handle_client, self.host, self.port)

    async def stop(self) -> None:
        for client_id in list(self._clients):
            await self._drop_client(client_id)

        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def broadcast(self, payload: dict) -> None:
        async with self._lock:
            for client in list(self._clients.values()):
                await client.send(payload)

    async def send_to(self, client_id: int, payload: dict) -> None:
        async with self._lock:
            client = self._clients.get(client_id)
            if client:
                await client.send(payload)

    async def _drop_client(self, client_id: int) -> None:
        async with self._lock:
            client = self._clients.pop(client_id, None)
        if client:
            await client.close()
            if self._on_disconnect:
                await self._on_disconnect(self, client_id)
            if self._session and hasattr(self._session, "handle_disconnect"):
                await self._session.handle_disconnect(self, client_id)

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        address = writer.get_extra_info("peername") or ("unknown", 0)
        async with self._lock:
            client_id = self._next_id
            self._next_id += 1
            self._clients[client_id] = ClientInfo(reader, writer, address)

        try:
            while not reader.at_eof():
                raw = await reader.readline()
                if not raw:
                    break
                try:
                    message = json.loads(raw.decode("utf-8"))
                    if not isinstance(message, dict):
                        continue
                except json.JSONDecodeError:
                    continue

                if self._on_message:
                    await self._on_message(self, client_id, message)
                elif self._session and hasattr(self._session, "handle_message"):
                    await self._session.handle_message(self, client_id, message)
        finally:
            await self._drop_client(client_id)

