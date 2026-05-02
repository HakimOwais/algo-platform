import asyncio
import random
from collections import defaultdict, deque
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.events import EventHub
from app.models.bar import Bar
from app.models.instrument import Instrument


class MarketDataService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        event_hub: EventHub,
        symbols: list[str],
        interval_seconds: float = 2.0,
    ) -> None:
        self._session_factory = session_factory
        self._event_hub = event_hub
        self._symbols = symbols
        self._interval_seconds = interval_seconds

        self._latest_prices: dict[str, float] = {}
        self._recent_closes: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=256))
        self._instrument_ids: dict[str, int] = {}
        self._running = False

    async def bootstrap(self) -> None:
        async with self._session_factory() as session:
            for symbol in self._symbols:
                result = await session.execute(
                    select(Instrument).where(Instrument.symbol == symbol, Instrument.exchange == "NSE")
                )
                instrument = result.scalar_one_or_none()
                if instrument is None:
                    instrument = Instrument(symbol=symbol, exchange="NSE", tick_size=0.05, lot_size=1)
                    session.add(instrument)
                    await session.flush()
                self._instrument_ids[symbol] = instrument.id

                seed_price = round(random.uniform(250.0, 3500.0), 2)
                self._latest_prices[symbol] = seed_price
                self._recent_closes[symbol].append(seed_price)
            await session.commit()

    def get_latest_price(self, symbol: str) -> float | None:
        return self._latest_prices.get(symbol.upper())

    def get_recent_closes(self, symbol: str, lookback: int = 30) -> list[float]:
        values = list(self._recent_closes[symbol.upper()])
        return values[-lookback:]

    def snapshot_prices(self) -> dict[str, float]:
        return dict(self._latest_prices)

    async def run(self) -> None:
        self._running = True
        while self._running:
            await self.generate_once()
            await asyncio.sleep(self._interval_seconds)

    async def stop(self) -> None:
        self._running = False

    async def generate_once(self) -> None:
        timestamp = datetime.now(timezone.utc)
        bars_payload = []

        async with self._session_factory() as session:
            for symbol in self._symbols:
                previous = self._latest_prices[symbol]
                drift = random.gauss(0, 0.0003)
                shock = random.gauss(0, 0.006)
                close_price = max(1.0, previous * (1 + drift + shock))
                high_price = max(previous, close_price) * (1 + abs(random.gauss(0, 0.0015)))
                low_price = min(previous, close_price) * (1 - abs(random.gauss(0, 0.0015)))
                volume = float(random.randint(20_000, 250_000))

                bar = Bar(
                    instrument_id=self._instrument_ids[symbol],
                    timestamp=timestamp,
                    interval="1m-sim",
                    open=round(previous, 2),
                    high=round(high_price, 2),
                    low=round(low_price, 2),
                    close=round(close_price, 2),
                    volume=volume,
                )
                session.add(bar)

                rounded_close = round(close_price, 2)
                self._latest_prices[symbol] = rounded_close
                self._recent_closes[symbol].append(rounded_close)
                bars_payload.append(
                    {
                        "symbol": symbol,
                        "open": bar.open,
                        "high": bar.high,
                        "low": bar.low,
                        "close": bar.close,
                        "volume": bar.volume,
                        "timestamp": timestamp.isoformat(),
                    }
                )
            await session.commit()

        await self._event_hub.broadcast("market.bars", {"bars": bars_payload})

