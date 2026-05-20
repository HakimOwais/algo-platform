"""Simulated market-data adapter — generates synthetic GBM prices.

Satisfies MarketDataPort.  Runs 24 / 7 with no market-hours gate.
All bar-persistence, deque management, and event broadcasting are
handled by MarketDataBase; this class only implements the two hooks.
"""
from __future__ import annotations

import random
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.events import EventHub
from app.infra.market_data._base import MarketDataBase
from app.models.bar import Bar


class SimMarketData(MarketDataBase):
    is_live_feed = False
    _gate_to_market_hours = False

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        event_hub: EventHub,
        symbols: list[str],
        interval_seconds: float = 2.0,
    ) -> None:
        super().__init__(
            session_factory=session_factory,
            event_hub=event_hub,
            symbols=symbols,
            interval_seconds=interval_seconds,
        )

    async def _setup(self, session: AsyncSession) -> None:
        for symbol in self._symbols:
            seed = round(random.uniform(250.0, 3500.0), 2)
            self._record_close(symbol, seed)

    async def _tick(self, session: AsyncSession, timestamp: datetime) -> list[dict]:
        payload: list[dict] = []
        for symbol in self._symbols:
            prev = self._latest_prices[symbol]
            drift = random.gauss(0, 0.0003)
            shock = random.gauss(0, 0.006)
            close = round(max(1.0, prev * (1 + drift + shock)), 2)
            high = round(max(prev, close) * (1 + abs(random.gauss(0, 0.0015))), 2)
            low = round(min(prev, close) * (1 - abs(random.gauss(0, 0.0015))), 2)
            volume = float(random.randint(20_000, 250_000))

            session.add(Bar(
                instrument_id=self._instrument_ids[symbol],
                timestamp=timestamp,
                interval="1m-sim",
                open=round(prev, 2),
                high=high,
                low=low,
                close=close,
                volume=volume,
            ))
            self._record_close(symbol, close)
            payload.append({
                "symbol": symbol,
                "open": round(prev, 2),
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
                "timestamp": timestamp.isoformat(),
            })
        return payload
