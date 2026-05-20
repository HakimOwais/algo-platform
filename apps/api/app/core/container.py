"""ServiceContainer — single source of all live service references.

Services depend on Protocol interfaces (ports/), not on each other's concrete
classes.  Routes access services through this container and never open DB
sessions themselves — they call repo methods instead.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.config import Settings
from app.core.events import EventHub
from app.ports.market_data import MarketDataPort
from app.ports.repositories import (
    DecisionRepo,
    FillRepo,
    OrderRepo,
    PositionRepo,
    StrategyRepo,
)
from app.services.order_manager import OrderManager
from app.services.orchestrator import TradingOrchestrator
from app.services.risk_engine import RiskEngine
from app.services.strategy.pipeline import StrategyPipeline


@dataclass
class ServiceContainer:
    settings: Settings
    event_hub: EventHub
    market_data: MarketDataPort
    risk_engine: RiskEngine
    order_manager: OrderManager
    strategy_pipeline: StrategyPipeline
    orchestrator: TradingOrchestrator
    # Repositories — routes use these directly instead of session_factory
    orders: OrderRepo
    fills: FillRepo
    positions: PositionRepo
    decisions: DecisionRepo
    strategies: StrategyRepo
