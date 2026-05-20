import asyncio
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import WebSocket


class EventHub:
    """In-process event bus.

    Two fan-out targets per broadcast():
      - Internal subscribers: asyncio.Queue objects registered via subscribe().
        Used by services that need to react to events (e.g., orchestrator on market.bars).
      - External WebSocket clients: connected browser / frontend sessions.

    Internal queues are bounded (maxsize=64 by default).  A slow subscriber that
    falls behind receives dropped events rather than applying backpressure to the
    market-data loop.
    """

    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()
        self._subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self._ws_lock = asyncio.Lock()

    # ── WebSocket clients ──────────────────────────────────────────────────────

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._ws_lock:
            self._connections.add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._ws_lock:
            self._connections.discard(websocket)

    # ── Internal pub/sub ───────────────────────────────────────────────────────

    def subscribe(self, event: str, maxsize: int = 64) -> asyncio.Queue:
        """Return a queue that will receive every future broadcast for *event*."""
        q: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._subscribers[event].append(q)
        return q

    def unsubscribe(self, event: str, queue: asyncio.Queue) -> None:
        try:
            self._subscribers[event].remove(queue)
        except ValueError:
            pass

    # ── Broadcast ─────────────────────────────────────────────────────────────

    async def broadcast(self, event: str, data: dict) -> None:
        payload = {
            "event": event,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # Internal queues — non-blocking; drop on overflow rather than stall.
        for q in list(self._subscribers.get(event, [])):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass

        # WebSocket clients — IO, so done under a snapshot of the connection set.
        async with self._ws_lock:
            peers = list(self._connections)
        for peer in peers:
            try:
                await peer.send_json(payload)
            except Exception:
                await self.disconnect(peer)
