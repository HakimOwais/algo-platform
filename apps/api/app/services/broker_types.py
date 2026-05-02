from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class BrokerFillPayload:
    symbol: str
    quantity: int
    price: float
    fee: float
    filled_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class BrokerOrderResponse:
    accepted: bool
    broker_order_id: str
    status: str
    reason: str | None = None
    fills: list[BrokerFillPayload] = field(default_factory=list)

