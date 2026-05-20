"""NSE transaction-cost model — single source of truth.

Replaces two identical implementations in:
  - services/paper_broker.py  (_nse_cost)
  - services/backtester.py    (nse_cost)

Constants reflect the Zerodha / Upstox flat-fee structure as of 2024.
Pass a custom NseCostSchedule for different brokers or future rate changes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SideStr = Literal["BUY", "SELL"]


@dataclass(frozen=True)
class NseCostSchedule:
    brokerage_pct: float = 0.0003       # 0.03%
    brokerage_cap_inr: float = 20.0     # ₹20 per order (flat-fee broker cap)
    stt_sell_pct: float = 0.001         # 0.1% STT, sell-side only (delivery)
    exchange_fee_pct: float = 0.0000335 # NSE transaction charge (both sides)
    sebi_fee_pct: float = 0.000001      # SEBI turnover fee (both sides)
    stamp_buy_pct: float = 0.00015      # Stamp duty, buy-side only
    gst_rate: float = 0.18              # GST on brokerage + exchange fees


DEFAULT_SCHEDULE = NseCostSchedule()


def nse_cost(
    price: float,
    quantity: int,
    side: SideStr,
    schedule: NseCostSchedule = DEFAULT_SCHEDULE,
) -> float:
    """Return total transaction cost in ₹ for one NSE order."""
    notional = price * quantity
    brokerage = min(notional * schedule.brokerage_pct, schedule.brokerage_cap_inr)
    stt = notional * schedule.stt_sell_pct if side == "SELL" else 0.0
    exchange_fee = notional * schedule.exchange_fee_pct
    sebi_fee = notional * schedule.sebi_fee_pct
    gst = (brokerage + exchange_fee) * schedule.gst_rate
    stamp = notional * schedule.stamp_buy_pct if side == "BUY" else 0.0
    return brokerage + stt + exchange_fee + sebi_fee + gst + stamp
