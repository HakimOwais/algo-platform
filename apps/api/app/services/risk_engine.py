"""Risk engine — pre-trade checks, drawdown-based position scaling, daily loss limits.

Depends on Settings and a price_history_lookup callable only.
Portfolio PnL is now queried through the PositionRepo passed into evaluate_order
so this class carries no persistent reference to PortfolioService.
"""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.enums import OrderStatus
from app.models.order import Order
from app.models.position import Position
from app.models.risk_event import RiskEvent
from app.quant.monte_carlo import monte_carlo_var_cvar_from_prices

_BASE_CAPITAL: float = 1_000_000.0  # ₹10 L default starting NAV


@dataclass
class RiskDecision:
    allowed: bool
    reason: str


@dataclass(frozen=True)
class DrawdownState:
    current_drawdown: float
    position_scalar: float
    label: str   # "NORMAL" | "CAUTION" | "STOP"


def compute_drawdown_scalar(
    peak_nav: float,
    current_nav: float,
    caution_threshold: float = 0.10,
    stop_threshold: float = 0.20,
) -> DrawdownState:
    if peak_nav <= 0:
        return DrawdownState(0.0, 1.0, "NORMAL")
    dd = max(0.0, (peak_nav - current_nav) / peak_nav)
    if dd >= stop_threshold:
        return DrawdownState(dd, 0.0, "STOP")
    if dd >= caution_threshold:
        return DrawdownState(dd, 0.5, "CAUTION")
    return DrawdownState(dd, 1.0, "NORMAL")


def fractional_kelly(
    expected_return: float,
    variance: float,
    fraction: float = 0.25,
    floor: float = 0.0,
    cap: float = 1.5,
) -> float:
    if variance <= 1e-12:
        return 0.0
    raw = (expected_return / variance) * fraction
    return max(floor, min(raw, cap))


class RiskEngine:
    def __init__(
        self,
        settings: Settings,
        price_history_lookup: Callable[[str, int], list[float]] | None = None,
    ) -> None:
        self._settings = settings
        self._price_history_lookup = price_history_lookup
        self._kill_switch = False
        self._current_day = date.today()
        self._peak_nav: float = settings.initial_capital_inr

    @property
    def kill_switch(self) -> bool:
        return self._kill_switch

    def update_peak_nav(self, current_nav: float) -> DrawdownState:
        if current_nav > self._peak_nav:
            self._peak_nav = current_nav
        return compute_drawdown_scalar(self._peak_nav, current_nav)

    def get_drawdown_state(self, current_nav: float) -> DrawdownState:
        return compute_drawdown_scalar(self._peak_nav, current_nav)

    async def set_kill_switch(
        self, session: AsyncSession, engaged: bool, message: str
    ) -> None:
        self._kill_switch = engaged
        session.add(RiskEvent(
            event_type="KILL_SWITCH_ON" if engaged else "KILL_SWITCH_OFF",
            severity="CRITICAL" if engaged else "INFO",
            message=message,
            context={"engaged": engaged},
        ))
        await session.commit()

    async def evaluate_order(
        self,
        session: AsyncSession,
        symbol: str,
        quantity: int,
        notional: float,
    ) -> RiskDecision:
        if self._kill_switch:
            return RiskDecision(False, "Kill switch is active")
        if quantity <= 0:
            return RiskDecision(False, "Order quantity must be positive")
        if quantity > self._settings.max_order_qty:
            return RiskDecision(
                False, f"Order quantity exceeds max ({self._settings.max_order_qty})"
            )
        if notional > self._settings.max_position_notional_inr:
            return RiskDecision(
                False,
                f"Order notional exceeds max ({self._settings.max_position_notional_inr:.0f})"
            )

        open_orders = await self._open_orders_count(session)
        if open_orders >= self._settings.max_open_orders:
            return RiskDecision(False, "Open order limit reached")

        mc_decision = await self._monte_carlo_guard(session, symbol, notional)
        if mc_decision is not None:
            return mc_decision

        realized = await self._total_realized_pnl(session)
        if realized <= -abs(self._settings.max_daily_loss_inr):
            session.add(RiskEvent(
                event_type="DAILY_LOSS_LIMIT",
                severity="CRITICAL",
                message="Daily loss threshold breached; activating kill switch",
                context={
                    "realized_pnl": realized,
                    "threshold": self._settings.max_daily_loss_inr,
                },
            ))
            await session.flush()
            self._kill_switch = True
            return RiskDecision(False, "Daily loss threshold breached")

        return RiskDecision(True, "OK")

    async def status(self, session: AsyncSession) -> dict:
        open_orders = await self._open_orders_count(session)
        realized = await self._total_realized_pnl(session)
        result = await session.execute(
            select(RiskEvent).order_by(RiskEvent.created_at.desc()).limit(10)
        )
        recent = [
            {
                "event_type": e.event_type,
                "severity": e.severity,
                "message": e.message,
                "created_at": e.created_at.isoformat(),
            }
            for e in result.scalars().all()
        ]
        current_nav = self._settings.initial_capital_inr + realized
        dd = self.get_drawdown_state(current_nav)
        return {
            "kill_switch": self._kill_switch,
            "peak_nav": self._peak_nav,
            "current_nav_estimate": current_nav,
            "drawdown": {
                "current": round(dd.current_drawdown, 4),
                "position_scalar": dd.position_scalar,
                "label": dd.label,
            },
            "max_daily_loss_inr": self._settings.max_daily_loss_inr,
            "max_position_notional_inr": self._settings.max_position_notional_inr,
            "max_open_orders": self._settings.max_open_orders,
            "enable_monte_carlo_risk": self._settings.enable_monte_carlo_risk,
            "mc_confidence": self._settings.mc_confidence,
            "mc_horizon_steps": self._settings.mc_horizon_steps,
            "mc_paths": self._settings.mc_paths,
            "max_mc_var_inr": self._settings.max_mc_var_inr,
            "max_mc_cvar_inr": self._settings.max_mc_cvar_inr,
            "open_orders": open_orders,
            "realized_pnl": realized,
            "recent_events": recent,
        }

    # ── Private DB helpers (use the session passed in — no new session) ────

    async def _open_orders_count(self, session: AsyncSession) -> int:
        open_states = [
            OrderStatus.NEW, OrderStatus.SENT,
            OrderStatus.ACKED, OrderStatus.PARTIALLY_FILLED,
        ]
        result = await session.execute(
            select(func.count(Order.id)).where(Order.status.in_(open_states))
        )
        return int(result.scalar_one())

    async def _total_realized_pnl(self, session: AsyncSession) -> float:
        result = await session.execute(
            select(func.coalesce(func.sum(Position.realized_pnl), 0.0))
        )
        return float(result.scalar_one() or 0.0)

    async def _monte_carlo_guard(
        self, session: AsyncSession, symbol: str, notional: float
    ) -> RiskDecision | None:
        if not self._settings.enable_monte_carlo_risk:
            return None
        if self._price_history_lookup is None or notional <= 0:
            return None

        lookback = max(
            self._settings.min_risk_history_bars,
            self._settings.mc_horizon_steps + 10,
        )
        history = self._price_history_lookup(symbol, lookback)
        if len(history) < 5:
            return None

        metrics = monte_carlo_var_cvar_from_prices(
            prices=history,
            notional=notional,
            confidence=self._settings.mc_confidence,
            horizon_steps=self._settings.mc_horizon_steps,
            paths=self._settings.mc_paths,
            random_seed=17,
        )
        if metrics is None:
            return None

        if metrics.var_amount > self._settings.max_mc_var_inr:
            session.add(RiskEvent(
                event_type="MC_VAR_BREACH",
                severity="WARNING",
                message=(
                    f"Monte Carlo VaR breach for {symbol}: "
                    f"{metrics.var_amount:.2f} > {self._settings.max_mc_var_inr:.2f}"
                ),
                context={
                    "symbol": symbol,
                    "var_amount": metrics.var_amount,
                    "cvar_amount": metrics.cvar_amount,
                },
            ))
            await session.flush()
            return RiskDecision(False, "Monte Carlo VaR threshold breached")

        if metrics.cvar_amount > self._settings.max_mc_cvar_inr:
            session.add(RiskEvent(
                event_type="MC_CVAR_BREACH",
                severity="WARNING",
                message=(
                    f"Monte Carlo CVaR breach for {symbol}: "
                    f"{metrics.cvar_amount:.2f} > {self._settings.max_mc_cvar_inr:.2f}"
                ),
                context={
                    "symbol": symbol,
                    "var_amount": metrics.var_amount,
                    "cvar_amount": metrics.cvar_amount,
                },
            ))
            await session.flush()
            return RiskDecision(False, "Monte Carlo CVaR threshold breached")

        return None
