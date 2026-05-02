from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from starlette.middleware.cors import CORSMiddleware

from app.api import api_router
from app.core.config import get_settings
from app.core.container import ServiceContainer
from app.core.database import get_session_factory, init_db
from app.core.events import EventHub
from app.services.broker_factory import build_broker
from app.services.market_data_service import MarketDataService
from app.services.orchestrator import TradingOrchestrator
from app.services.order_manager import OrderManager
from app.services.portfolio_service import PortfolioService
from app.services.risk_engine import RiskEngine
from app.services.seed import seed_defaults
from app.services.strategy_engine import StrategyEngine


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    await init_db()
    session_factory = get_session_factory()

    event_hub = EventHub()
    market_data_service = MarketDataService(
        session_factory=session_factory,
        event_hub=event_hub,
        symbols=settings.symbols,
    )
    portfolio_service = PortfolioService()
    risk_engine = RiskEngine(
        settings=settings,
        portfolio_service=portfolio_service,
        price_history_lookup=market_data_service.get_recent_closes,
    )
    broker = build_broker(settings=settings, price_lookup=market_data_service.get_latest_price)
    order_manager = OrderManager(
        session_factory=session_factory,
        broker=broker,
        risk_engine=risk_engine,
        portfolio_service=portfolio_service,
        event_hub=event_hub,
        price_lookup=market_data_service.get_latest_price,
    )
    strategy_engine = StrategyEngine(
        session_factory=session_factory,
        market_data_service=market_data_service,
        order_manager=order_manager,
        portfolio_service=portfolio_service,
        event_hub=event_hub,
        symbols=settings.symbols,
    )
    orchestrator = TradingOrchestrator(
        market_data_service=market_data_service,
        strategy_engine=strategy_engine,
    )

    container = ServiceContainer(
        settings=settings,
        event_hub=event_hub,
        market_data_service=market_data_service,
        portfolio_service=portfolio_service,
        risk_engine=risk_engine,
        order_manager=order_manager,
        strategy_engine=strategy_engine,
        orchestrator=orchestrator,
    )
    app.state.container = container

    async with session_factory() as session:
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

# Configure CORS to allow frontend to communicate
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
