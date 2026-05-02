import asyncio
from datetime import datetime, timezone

from fastapi import WebSocket


class EventHub:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._connections.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            if websocket in self._connections:
                self._connections.remove(websocket)

    async def broadcast(self, event: str, data: dict) -> None:
        payload = {
            "event": event,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        async with self._lock:
            peers = list(self._connections)
        for peer in peers:
            try:
                await peer.send_json(payload)
            except Exception:
                await self.disconnect(peer)

