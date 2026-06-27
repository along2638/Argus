"""WebSocket alarm broadcaster — push alarm events to connected clients."""

import asyncio
import json
from typing import Dict, Set

from starlette.websockets import WebSocket, WebSocketState

from app.utils.logger import get_logger

logger = get_logger(__name__)


class AlarmBroadcaster:
    """Manages WebSocket connections and broadcasts alarm events."""

    def __init__(self):
        self._connections: Set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections.add(ws)
        logger.info("ws_client_connected", total=len(self._connections))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._connections.discard(ws)
        logger.info("ws_client_disconnected", total=len(self._connections))

    async def broadcast(self, event: dict) -> None:
        """Broadcast an event to all connected WebSocket clients."""
        if not self._connections:
            return

        message = json.dumps(event, ensure_ascii=False, default=str)
        dead: list[WebSocket] = []

        async with self._lock:
            targets = list(self._connections)

        for ws in targets:
            try:
                if ws.client_state == WebSocketState.CONNECTED:
                    await ws.send_text(message)
                else:
                    dead.append(ws)
            except Exception:
                dead.append(ws)

        if dead:
            async with self._lock:
                for ws in dead:
                    self._connections.discard(ws)
            logger.info("ws_dead_connections_cleaned", count=len(dead))

    @property
    def connection_count(self) -> int:
        return len(self._connections)


# Singleton
alarm_broadcaster = AlarmBroadcaster()
