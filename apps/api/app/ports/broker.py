"""BrokerPort — the only type OrderManager programs against."""
from __future__ import annotations

from typing import Protocol

from app.models.enums import Side
from app.services.broker_types import BrokerOrderResponse


class BrokerPort(Protocol):
    async def place_order(
        self, symbol: str, side: Side, quantity: int
    ) -> BrokerOrderResponse:
        ...
