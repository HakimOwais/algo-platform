"""
Paper broker — simulates realistic fills using the real NSE transaction cost model.

Costs include: brokerage (₹20 cap), STT (0.1% sell-side), NSE exchange fee,
SEBI turnover fee, GST, and stamp duty — matching actual Zerodha / Upstox costs.
"""
from __future__ import annotations

import asyncio
import random
import uuid

from app.models.enums import Side
from app.services.broker_types import BrokerFillPayload, BrokerOrderResponse

# ── Real NSE cost constants ───────────────────────────────────────────────────
_BROKERAGE_PCT = 0.0003     # 0.03%
_BROKERAGE_CAP = 20.0       # ₹20 per order (Zerodha/Upstox flat-fee model)
_STT_SELL      = 0.001      # 0.1% STT charged on the sell side only (delivery)
_EXCHANGE_FEE  = 0.0000335  # NSE transaction charge (both sides)
_SEBI_FEE      = 0.000001   # SEBI turnover fee (both sides)
_STAMP_BUY     = 0.00015    # Stamp duty on buy side only
_GST_RATE      = 0.18       # GST on brokerage + exchange fees


def _nse_cost(fill_price: float, quantity: int, side: Side) -> float:
    """Return total transaction cost in ₹ for one paper fill."""
    notional = fill_price * quantity
    brokerage    = min(notional * _BROKERAGE_PCT, _BROKERAGE_CAP)
    stt          = notional * _STT_SELL if side == Side.SELL else 0.0
    exchange_fee = notional * _EXCHANGE_FEE
    sebi_fee     = notional * _SEBI_FEE
    gst          = (brokerage + exchange_fee) * _GST_RATE
    stamp        = notional * _STAMP_BUY if side == Side.BUY else 0.0
    return brokerage + stt + exchange_fee + sebi_fee + gst + stamp


class PaperBroker:
    """Simulates order fills with realistic NSE costs and random latency."""

    def __init__(self, price_lookup) -> None:
        self._price_lookup = price_lookup

    async def place_order(self, symbol: str, side: Side, quantity: int) -> BrokerOrderResponse:
        # Simulate network latency (50–250 ms)
        await asyncio.sleep(random.uniform(0.05, 0.25))

        market_price = self._price_lookup(symbol)
        if market_price is None:
            return BrokerOrderResponse(
                accepted=False,
                broker_order_id=str(uuid.uuid4()),
                status="REJECTED",
                reason=f"No market price available for {symbol}",
            )

        # Market impact slippage: 2–15 bps (wider for larger orders / illiquid times)
        slippage = random.uniform(0.0002, 0.0015)
        fill_price = (
            market_price * (1.0 + slippage)
            if side == Side.BUY
            else market_price * (1.0 - slippage)
        )
        fill_price = round(fill_price, 2)

        fee = round(_nse_cost(fill_price, quantity, side), 2)
        fill = BrokerFillPayload(symbol=symbol, quantity=quantity, price=fill_price, fee=fee)

        return BrokerOrderResponse(
            accepted=True,
            broker_order_id=str(uuid.uuid4()),
            status="FILLED",
            fills=[fill],
        )
