import asyncio


class TradingOrchestrator:
    def __init__(self, market_data_service, strategy_engine) -> None:
        self._market_data_service = market_data_service
        self._strategy_engine = strategy_engine
        self._market_task: asyncio.Task | None = None
        self._strategy_task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        await self._market_data_service.bootstrap()
        self._market_task = asyncio.create_task(self._market_data_service.run(), name="market-data-loop")
        self._strategy_task = asyncio.create_task(self._strategy_loop(), name="strategy-loop")

    async def stop(self) -> None:
        self._running = False
        await self._market_data_service.stop()
        tasks = [task for task in [self._market_task, self._strategy_task] if task is not None]
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _strategy_loop(self) -> None:
        while self._running:
            await self._strategy_engine.run_once()
            await asyncio.sleep(2.0)

