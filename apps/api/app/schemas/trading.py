from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.enums import OrderStatus, OrderType, Side
from app.schemas.common import ORMModel


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class OrderCreateRequest(BaseModel):
    strategy_name: str = Field(default="manual")
    symbol: str
    side: Side
    quantity: int = Field(gt=0)
    order_type: OrderType = OrderType.MARKET
    limit_price: float | None = None
    idempotency_key: str | None = None


class OrderRead(ORMModel):
    id: str
    strategy_name: str
    symbol: str
    side: Side
    quantity: int
    order_type: OrderType
    limit_price: float | None
    status: OrderStatus
    broker_order_id: str | None
    rejection_reason: str | None
    idempotency_key: str
    is_paper: bool
    requested_at: datetime
    updated_at: datetime


class FillRead(ORMModel):
    id: str
    order_id: str
    symbol: str
    quantity: int
    price: float
    fee: float
    filled_at: datetime


class PositionRead(ORMModel):
    id: int
    symbol: str
    quantity: int
    avg_price: float
    realized_pnl: float
    updated_at: datetime


class StrategyRead(ORMModel):
    id: int
    name: str
    version: str
    is_active: bool
    mode: str
    parameters: dict[str, Any]
    updated_at: datetime


class DecisionLogRead(ORMModel):
    id: int
    strategy_name: str
    symbol: str
    signal: str
    confidence: float
    reason: str
    payload: dict[str, Any]
    created_at: datetime


class StrategyUpdateRequest(BaseModel):
    parameters: dict[str, Any] = Field(default_factory=dict)
    version: str | None = None
    is_active: bool | None = None


class RiskToggleRequest(BaseModel):
    engaged: bool
    message: str = "Manual operator action"


class HealthResponse(BaseModel):
    status: str
    environment: str
    broker: str
    market_simulation: bool


class DashboardResponse(BaseModel):
    nav_estimate: float
    realized_pnl: float
    open_positions: int
    open_orders: int
    latest_prices: dict[str, float]
    kill_switch: bool
