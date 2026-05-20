"""TradingOrchestrator — drives the market-data loop and strategy cycle.

Owns two asyncio tasks:
  - market-data-loop  : delegates entirely to the market-data adapter
  - strategy-loop     : wakes on market.bars events, never on a wall-clock timer

The strategy fires exactly once per bar batch.  A 5-second timeout heartbeat
re-checks the running flag so stop() is never delayed more than 5 seconds.
"""
from __future__ import annotations

import asyncio
import logging

from app.core.events import EventHub
from app.ports.market_data import MarketDataPort
from app.services.strategy.pipeline import StrategyPipeline

logger = logging.getLogger(__name__)


class TradingOrchestrator:
    def __init__(
        self,
        market_data: MarketDataPort,
        strategy_pipeline: StrategyPipeline,
        event_hub: EventHub,
    ) -> None:
        self._market_data = market_data
        self._pipeline = strategy_pipeline
        self._event_hub = event_hub
        self._tasks: list[asyncio.Task] = []
        self._bar_queue: asyncio.Queue | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._bar_queue = self._event_hub.subscribe("market.bars")
        await self._market_data.bootstrap()
        self._tasks = [
            asyncio.create_task(self._market_data.run(), name="market-data-loop"),
            asyncio.create_task(self._strategy_loop(), name="strategy-loop"),
        ]

    async def stop(self) -> None:
        self._running = False
        if self._bar_queue is not None:
            self._event_hub.unsubscribe("market.bars", self._bar_queue)
            self._bar_queue = None
        await self._market_data.stop()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()

    async def _strategy_loop(self) -> None:
        while self._running:
            try:
                # Block until a bar arrives; timeout lets us re-check _running.
                await asyncio.wait_for(self._bar_queue.get(), timeout=5.0)
            except asyncio.TimeoutError:
                continue
            try:
                await self._pipeline.run_once()
            except Exception:
                logger.exception("strategy pipeline cycle failed")
