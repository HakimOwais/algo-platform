from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from starlette.middleware.cors import CORSMiddleware

from app.api import api_router
from app.core.config import get_settings
from app.core.container import ServiceContainer
from app.core.database import get_session_factory, init_db
from app.core.events import EventHub
from app.infra.market_data.angel_one import AngelOneMarketData
from app.infra.market_data.sim import SimMarketData
from app.infra.persistence.repositories import (
    SqlaDecisionRepo,
    SqlaFillRepo,
    SqlaOrderRepo,
    SqlaPositionRepo,
    SqlaStrategyRepo,
)
from app.services.broker_factory import build_broker
from app.services.order_manager import OrderManager
from app.services.orchestrator import TradingOrchestrator
from app.services.risk_engine import RiskEngine
from app.services.seed import seed_defaults
from app.services.strategy.pipeline import StrategyPipeline


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    await init_db()
    sf = get_session_factory()

    event_hub = EventHub()

    # ── Market data adapter ────────────────────────────────────────────────
    _use_live = bool(
        settings.angel_one_api_key
        and settings.angel_one_totp_secret
        and settings.angel_one_tokens
    )
    if _use_live:
        market_data = AngelOneMarketData(
            settings=settings,
            session_factory=sf,
            event_hub=event_hub,
            symbols=settings.symbols,
            symbol_tokens=settings.angel_one_tokens,
            poll_interval_seconds=settings.angel_one_poll_interval,
        )
    else:
        market_data = SimMarketData(
            session_factory=sf,
            event_hub=event_hub,
            symbols=settings.symbols,
        )

    # ── Repositories (no logic — pure data access) ─────────────────────────
    order_repo    = SqlaOrderRepo(sf)
    fill_repo     = SqlaFillRepo(sf)
    position_repo = SqlaPositionRepo(sf)
    decision_repo = SqlaDecisionRepo(sf)
    strategy_repo = SqlaStrategyRepo(sf)

    # ── Core services ──────────────────────────────────────────────────────
    risk_engine = RiskEngine(
        settings=settings,
        price_history_lookup=market_data.get_recent_closes,
    )
    broker = build_broker(
        settings=settings,
        price_lookup=market_data.get_latest_price,
    )
    order_manager = OrderManager(
        session_factory=sf,
        broker=broker,
        risk_engine=risk_engine,
        position_repo=position_repo,
        event_hub=event_hub,
        price_lookup=market_data.get_latest_price,
    )
    strategy_pipeline = StrategyPipeline(
        market_data=market_data,
        order_manager=order_manager,
        position_repo=position_repo,
        decision_repo=decision_repo,
        strategy_repo=strategy_repo,
        event_hub=event_hub,
        symbols=settings.symbols,
    )
    orchestrator = TradingOrchestrator(
        market_data=market_data,
        strategy_pipeline=strategy_pipeline,
        event_hub=event_hub,
    )

    app.state.container = ServiceContainer(
        settings=settings,
        event_hub=event_hub,
        market_data=market_data,
        risk_engine=risk_engine,
        order_manager=order_manager,
        strategy_pipeline=strategy_pipeline,
        orchestrator=orchestrator,
        orders=order_repo,
        fills=fill_repo,
        positions=position_repo,
        decisions=decision_repo,
        strategies=strategy_repo,
    )

    async with sf() as session:
        await seed_defaults(session)

    await orchestrator.start()
    try:
        yield
    finally:
        await orchestrator.stop()


app = FastAPI(
    title="Algo Trading Platform API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://0.0.0.0:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.websocket("/ws/stream")
async def websocket_stream(websocket: WebSocket):
    container: ServiceContainer = websocket.app.state.container
    await container.event_hub.connect(websocket)
    await websocket.send_json(
        {
            "event": "system.ready",
            "data": {
                "broker": container.settings.default_broker,
                "symbols": container.settings.symbols,
            },
        }
    )
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        await container.event_hub.disconnect(websocket)
