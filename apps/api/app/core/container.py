from dataclasses import dataclass

from app.core.config import Settings
from app.core.events import EventHub
from app.services.market_data_service import MarketDataService
from app.services.order_manager import OrderManager
from app.services.orchestrator import TradingOrchestrator
from app.services.portfolio_service import PortfolioService
from app.services.risk_engine import RiskEngine
from app.services.strategy_engine import StrategyEngine


@dataclass
class ServiceContainer:
    settings: Settings
    event_hub: EventHub
    market_data_service: MarketDataService
    portfolio_service: PortfolioService
    risk_engine: RiskEngine
    order_manager: OrderManager
    strategy_engine: StrategyEngine
    orchestrator: TradingOrchestrator

