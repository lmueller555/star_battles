import asyncio
import json

import pytest

from game.server import GameServer, MultiPlayerSession


async def _read_message(reader: asyncio.StreamReader, timeout: float = 1.0) -> dict:
    raw = await asyncio.wait_for(reader.readline(), timeout)
    if not raw:
        raise AssertionError("Connection closed before receiving data")
    return json.loads(raw.decode("utf-8"))


async def _send_message(writer: asyncio.StreamWriter, payload: dict) -> None:
    writer.write(json.dumps(payload).encode("utf-8") + b"\n")
    await writer.drain()


async def _wait_for(reader: asyncio.StreamReader, msg_type: str, timeout: float = 1.0) -> dict:
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise AssertionError(f"Timed out waiting for message type {msg_type}")
        msg = await _read_message(reader, remaining)
        if msg.get("type") == msg_type:
            return msg


def test_join_flow_registers_players_and_broadcasts_snapshot():
    async def _run() -> None:
        session = MultiPlayerSession()
        server = GameServer()
        server.attach_session(session)
        await server.start()
        host, port = server.address

        reader, writer = await asyncio.open_connection(host, port)
        await _send_message(writer, {"type": "join", "name": "Ace"})

        welcome = await _wait_for(reader, "welcome")
        assert welcome["id"] == 1

        players = await _wait_for(reader, "players")
        assert players["players"] == [{"id": 1, "name": "Ace", "ready": False}]

        writer.close()
        await writer.wait_closed()
        await server.stop()

    asyncio.run(_run())


def test_ready_updates_are_broadcast_to_all_clients():
    async def _run() -> None:
        session = MultiPlayerSession()
        server = GameServer()
        server.attach_session(session)
        await server.start()
        host, port = server.address

        reader_a, writer_a = await asyncio.open_connection(host, port)
        reader_b, writer_b = await asyncio.open_connection(host, port)

        await _send_message(writer_a, {"type": "join", "name": "Alpha"})
        # Drain join broadcasts for both clients
        await _wait_for(reader_a, "welcome")
        await _wait_for(reader_a, "players")
        await _wait_for(reader_b, "players")

        await _send_message(writer_b, {"type": "join", "name": "Beta"})
        await _wait_for(reader_b, "welcome")
        await _wait_for(reader_b, "players")
        await _wait_for(reader_a, "players")

        await _send_message(writer_a, {"type": "ready", "ready": True})
        ready_notice = await _wait_for(reader_b, "player_ready")
        assert ready_notice == {"type": "player_ready", "id": 1, "ready": True}

        snapshot = await _wait_for(reader_b, "players")
        players = {player["id"]: player for player in snapshot["players"]}
        assert players[1]["ready"] is True
        assert players[2]["ready"] is False

        writer_a.close(); await writer_a.wait_closed()
        writer_b.close(); await writer_b.wait_closed()
        await server.stop()

    asyncio.run(_run())
