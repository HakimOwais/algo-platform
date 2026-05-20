"""Paper broker — simulates realistic fills using the real NSE transaction cost model."""
from __future__ import annotations

import asyncio
import random
import uuid

from app.models.enums import Side
from app.quant.costs import nse_cost
from app.services.broker_types import BrokerFillPayload, BrokerOrderResponse


class PaperBroker:
    """Simulates order fills with realistic NSE costs and random latency."""

    def __init__(self, price_lookup) -> None:
        self._price_lookup = price_lookup

    async def place_order(self, symbol: str, side: Side, quantity: int) -> BrokerOrderResponse:
        await asyncio.sleep(random.uniform(0.05, 0.25))  # simulate network latency

        market_price = self._price_lookup(symbol)
        if market_price is None:
            return BrokerOrderResponse(
                accepted=False,
                broker_order_id=str(uuid.uuid4()),
                status="REJECTED",
                reason=f"No market price available for {symbol}",
            )

        slippage = random.uniform(0.0002, 0.0015)
        fill_price = (
            market_price * (1.0 + slippage)
            if side == Side.BUY
            else market_price * (1.0 - slippage)
        )
        fill_price = round(fill_price, 2)
        side_str = "BUY" if side == Side.BUY else "SELL"
        fee = round(nse_cost(fill_price, quantity, side_str), 2)

        return BrokerOrderResponse(
            accepted=True,
            broker_order_id=str(uuid.uuid4()),
            status="FILLED",
            fills=[BrokerFillPayload(symbol=symbol, quantity=quantity, price=fill_price, fee=fee)],
        )
