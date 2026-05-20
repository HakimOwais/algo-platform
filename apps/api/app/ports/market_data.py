"""MarketDataPort — the only type the rest of the app depends on.

Both SimMarketData and AngelOneMarketData satisfy this Protocol.
The orchestrator, strategy engine, and risk engine program against this
interface, never against the concrete adapters.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class MarketDataPort(Protocol):
    """Read-only price access + lifecycle control."""

    is_live_feed: bool

    async def bootstrap(self) -> None:
        """One-shot startup: authenticate, resolve instruments, warm up deques."""
        ...

    async def run(self) -> None:
        """Start the polling / streaming loop.  Runs until stop() is called."""
        ...

    async def stop(self) -> None:
        """Signal the loop to exit gracefully."""
        ...

    def get_latest_price(self, symbol: str) -> float | None:
        """Return the most recent close price, or None if not yet seen."""
        ...

    def get_recent_closes(self, symbol: str, lookback: int = 30) -> list[float]:
        """Return up to `lookback` most-recent close prices, oldest first."""
        ...

    def snapshot_prices(self) -> dict[str, float]:
        """Return a shallow copy of {symbol: latest_price} for all tracked symbols."""
        ...
