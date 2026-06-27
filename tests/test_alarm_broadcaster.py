"""Tests for alarm WebSocket broadcaster."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.websockets import WebSocketState

from app.core.alarm_broadcaster import AlarmBroadcaster


class TestAlarmBroadcaster:
    """Test AlarmBroadcaster class."""

    @pytest.mark.asyncio
    async def test_connect(self):
        """Test WebSocket connection is accepted and tracked."""
        broadcaster = AlarmBroadcaster()
        ws = AsyncMock()
        ws.accept = AsyncMock()

        await broadcaster.connect(ws)

        ws.accept.assert_called_once()
        assert broadcaster.connection_count == 1

    @pytest.mark.asyncio
    async def test_disconnect(self):
        """Test WebSocket disconnection removes from tracking."""
        broadcaster = AlarmBroadcaster()
        ws = AsyncMock()
        broadcaster._connections.add(ws)

        await broadcaster.disconnect(ws)

        assert broadcaster.connection_count == 0

    @pytest.mark.asyncio
    async def test_broadcast_to_connected(self):
        """Test broadcast sends message to all connected clients."""
        broadcaster = AlarmBroadcaster()
        ws1 = AsyncMock()
        ws1.client_state = WebSocketState.CONNECTED
        ws2 = AsyncMock()
        ws2.client_state = WebSocketState.CONNECTED
        broadcaster._connections = {ws1, ws2}

        await broadcaster.broadcast({"type": "alarm", "stream_id": "cam-1"})

        ws1.send_text.assert_called_once()
        ws2.send_text.assert_called_once()
        # Verify JSON content
        import json
        sent = json.loads(ws1.send_text.call_args[0][0])
        assert sent["type"] == "alarm"
        assert sent["stream_id"] == "cam-1"

    @pytest.mark.asyncio
    async def test_broadcast_empty(self):
        """Test broadcast with no connections does nothing."""
        broadcaster = AlarmBroadcaster()
        # Should not raise
        await broadcaster.broadcast({"type": "alarm"})

    @pytest.mark.asyncio
    async def test_broadcast_removes_dead_connections(self):
        """Test that dead connections are cleaned up after broadcast."""
        broadcaster = AlarmBroadcaster()
        ws_alive = AsyncMock()
        ws_alive.client_state = WebSocketState.CONNECTED
        ws_dead = AsyncMock()
        ws_dead.client_state = WebSocketState.DISCONNECTED
        broadcaster._connections = {ws_alive, ws_dead}

        await broadcaster.broadcast({"type": "alarm"})

        ws_alive.send_text.assert_called_once()
        ws_dead.send_text.assert_not_called()
        assert ws_alive in broadcaster._connections
        assert ws_dead not in broadcaster._connections

    @pytest.mark.asyncio
    async def test_broadcast_handles_send_error(self):
        """Test that send errors don't crash the broadcast."""
        broadcaster = AlarmBroadcaster()
        ws_ok = AsyncMock()
        ws_ok.client_state = WebSocketState.CONNECTED
        ws_err = AsyncMock()
        ws_err.client_state = WebSocketState.CONNECTED
        ws_err.send_text = AsyncMock(side_effect=Exception("connection lost"))
        broadcaster._connections = {ws_ok, ws_err}

        # Should not raise
        await broadcaster.broadcast({"type": "alarm"})

        ws_ok.send_text.assert_called_once()
        assert ws_err not in broadcaster._connections
