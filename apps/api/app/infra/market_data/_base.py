"""Shared lifecycle and in-memory state for all market-data adapters.

Subclasses implement exactly two hooks:
  _setup(session)              — called once during bootstrap (auth, initial fetch …)
  _tick(session, timestamp)    — produce/poll one round of bars; return broadcast payload

The base handles: instrument-id resolution, deque maintenance, run/stop loop,
market-hours gating, and event-hub broadcasting.  Neither subclass needs to
touch asyncio tasks, deques, or the DB instrument table directly.
"""
from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections import defaultdict, deque
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.events import EventHub
from app.core.market_hours import is_market_open, ist_now
from app.models.instrument import Instrument

logger = logging.getLogger(__name__)


class MarketDataBase(ABC):
    """Abstract base satisfying MarketDataPort.

    Subclass contract:
      - Set class attribute `is_live_feed: bool`
      - Set class attribute `_gate_to_market_hours: bool`
        (True  → run() skips ticks outside 09:15–15:30 IST Mon–Fri)
        (False → runs 24 / 7, used by the sim adapter)
      - Implement `_setup` and `_tick`
    """

    is_live_feed: bool = False
    _gate_to_market_hours: bool = False

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        event_hub: EventHub,
        symbols: list[str],
        interval_seconds: float,
        deque_maxlen: int = 256,
    ) -> None:
        self._session_factory = session_factory
        self._event_hub = event_hub
        self._symbols = [s.upper() for s in symbols]
        self._interval = interval_seconds
        self._latest_prices: dict[str, float] = {}
        self._recent_closes: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=deque_maxlen)
        )
        self._instrument_ids: dict[str, int] = {}
        self._running = False

    # ── MarketDataPort public API ──────────────────────────────────────────

    def get_latest_price(self, symbol: str) -> float | None:
        return self._latest_prices.get(symbol.upper())

    def get_recent_closes(self, symbol: str, lookback: int = 30) -> list[float]:
        dq = self._recent_closes[symbol.upper()]
        values = list(dq)
        return values[-lookback:] if lookback < len(values) else values

    def snapshot_prices(self) -> dict[str, float]:
        return dict(self._latest_prices)

    async def bootstrap(self) -> None:
        async with self._session_factory() as session:
            await self._resolve_instruments(session)
            await self._setup(session)
            await session.commit()

    async def run(self) -> None:
        self._running = True
        try:
            while self._running:
                if self._gate_to_market_hours and not is_market_open(ist_now()):
                    await asyncio.sleep(self._interval)
                    continue
                await self._cycle()
                await asyncio.sleep(self._interval)
        finally:
            self._running = False

    async def stop(self) -> None:
        self._running = False

    # ── Subclass hooks ─────────────────────────────────────────────────────

    @abstractmethod
    async def _setup(self, session: AsyncSession) -> None:
        """One-shot adapter-specific init inside the bootstrap transaction."""

    @abstractmethod
    async def _tick(
        self, session: AsyncSession, timestamp: datetime
    ) -> list[dict]:
        """Persist one bar per symbol; return the list of dicts to broadcast."""

    # ── Internal helpers ───────────────────────────────────────────────────

    async def _resolve_instruments(self, session: AsyncSession) -> None:
        for symbol in self._symbols:
            row = await session.execute(
                select(Instrument).where(
                    Instrument.symbol == symbol,
                    Instrument.exchange == "NSE",
                )
            )
            instrument = row.scalar_one_or_none()
            if instrument is None:
                instrument = Instrument(
                    symbol=symbol, exchange="NSE", tick_size=0.05, lot_size=1
                )
                session.add(instrument)
                await session.flush()
            self._instrument_ids[symbol] = instrument.id

    def _record_close(self, symbol: str, price: float) -> None:
        self._latest_prices[symbol] = price
        self._recent_closes[symbol].append(price)

    async def _cycle(self) -> None:
        timestamp = datetime.now(timezone.utc)
        try:
            async with self._session_factory() as session:
                bars = await self._tick(session, timestamp)
                await session.commit()
        except Exception:
            logger.exception("market-data tick failed — skipping cycle")
            return
        if bars:
            await self._event_hub.broadcast("market.bars", {"bars": bars})
