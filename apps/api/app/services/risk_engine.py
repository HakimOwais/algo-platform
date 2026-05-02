"""
Risk engine — pre-trade checks, drawdown-based position scaling, and daily loss limits.

Additions over the original:
- Peak NAV tracking and drawdown scalar (halve sizes at 10% DD, stop at 20% DD)
- Fractional Kelly applied at strategy level (this module exposes the helper)
- All existing MC VaR / CVaR guards retained
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from collections.abc import Callable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.enums import OrderStatus
from app.models.order import Order
from app.models.risk_event import RiskEvent
from app.quant.monte_carlo import monte_carlo_var_cvar_from_prices
from app.services.portfolio_service import PortfolioService

_BASE_CAPITAL = 1_000_000.0  # ₹10L starting NAV assumption for drawdown calculation


@dataclass
class RiskDecision:
    allowed: bool
    reason: str


@dataclass(frozen=True)
class DrawdownState:
    current_drawdown: float   # fraction, e.g. 0.12 = 12%
    position_scalar: float    # multiply position sizes by this (1.0 / 0.5 / 0.0)
    label: str                # "NORMAL" | "CAUTION" | "STOP"


def compute_drawdown_scalar(
    peak_nav: float,
    current_nav: float,
    caution_threshold: float = 0.10,
    stop_threshold: float = 0.20,
) -> DrawdownState:
    """
    Return a position-size scalar based on current drawdown from peak NAV.

    - Below caution_threshold  → scalar = 1.0 (trade normally)
    - Between thresholds       → scalar = 0.5 (half position sizes)
    - Above stop_threshold     → scalar = 0.0 (stop all new trades)
    """
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
    """
    Full Kelly = μ / σ².  We use 25% Kelly by default (quarter-Kelly).
    Full Kelly is theoretically optimal but catastrophic in practice due to
    estimation error — fractional Kelly dramatically reduces ruin probability.
    """
    eps = 1e-12
    if variance <= eps:
        return 0.0
    raw = (expected_return / variance) * fraction
    return max(floor, min(raw, cap))


class RiskEngine:
    def __init__(
        self,
        settings: Settings,
        portfolio_service: PortfolioService,
        price_history_lookup: Callable[[str, int], list[float]] | None = None,
    ) -> None:
        self._settings = settings
        self._portfolio_service = portfolio_service
        self._price_history_lookup = price_history_lookup
        self._kill_switch = False
        self._current_day = date.today()
        # Peak NAV for drawdown calculation (persists in memory across the session)
        self._peak_nav: float = _BASE_CAPITAL

    @property
    def kill_switch(self) -> bool:
        return self._kill_switch

    def update_peak_nav(self, current_nav: float) -> DrawdownState:
        """Call this after each strategy cycle to keep peak NAV current."""
        if current_nav > self._peak_nav:
            self._peak_nav = current_nav
        return compute_drawdown_scalar(
            self._peak_nav,
            current_nav,
            caution_threshold=0.10,
            stop_threshold=0.20,
        )

    def get_drawdown_state(self, current_nav: float) -> DrawdownState:
        return compute_drawdown_scalar(self._peak_nav, current_nav)

    # ------------------------------------------------------------------
    async def set_kill_switch(self, session: AsyncSession, engaged: bool, message: str) -> None:
        self._kill_switch = engaged
        event = RiskEvent(
            event_type="KILL_SWITCH_ON" if engaged else "KILL_SWITCH_OFF",
            severity="CRITICAL" if engaged else "INFO",
            message=message,
            context={"engaged": engaged},
        )
        session.add(event)
        await session.commit()

    async def _open_orders_count(self, session: AsyncSession) -> int:
        states = [
            OrderStatus.NEW,
            OrderStatus.SENT,
            OrderStatus.ACKED,
            OrderStatus.PARTIALLY_FILLED,
        ]
        result = await session.execute(
            select(func.count(Order.id)).where(Order.status.in_(states))
        )
        return int(result.scalar_one())

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
            return RiskDecision(False, f"Order quantity exceeds max ({self._settings.max_order_qty})")
        if notional > self._settings.max_position_notional_inr:
            return RiskDecision(
                False, f"Order notional exceeds max ({self._settings.max_position_notional_inr:.0f})"
            )

        open_orders = await self._open_orders_count(session)
        if open_orders >= self._settings.max_open_orders:
            return RiskDecision(False, "Open order limit reached")

        mc_decision = await self._monte_carlo_guard(session=session, symbol=symbol, notional=notional)
        if mc_decision is not None:
            return mc_decision

        # Daily loss + auto kill-switch
        realized = await self._portfolio_service.total_realized_pnl(session)
        if realized <= -abs(self._settings.max_daily_loss_inr):
            session.add(RiskEvent(
                event_type="DAILY_LOSS_LIMIT",
                severity="CRITICAL",
                message="Daily loss threshold breached; activating kill switch",
                context={"realized_pnl": realized, "threshold": self._settings.max_daily_loss_inr},
            ))
            await session.flush()
            self._kill_switch = True
            return RiskDecision(False, "Daily loss threshold breached")

        return RiskDecision(True, "OK")

    async def _monte_carlo_guard(
        self,
        session: AsyncSession,
        symbol: str,
        notional: float,
    ) -> RiskDecision | None:
        if not self._settings.enable_monte_carlo_risk:
            return None
        if self._price_history_lookup is None or notional <= 0:
            return None

        lookback = max(self._settings.min_risk_history_bars, self._settings.mc_horizon_steps + 10)
        try:
            history = self._price_history_lookup(symbol, lookback)
        except TypeError:
            history = self._price_history_lookup(symbol, lookback=lookback)  # type: ignore[misc]
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

    async def status(self, session: AsyncSession) -> dict:
        open_orders = await self._open_orders_count(session)
        realized = await self._portfolio_service.total_realized_pnl(session)
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
        current_nav = _BASE_CAPITAL + realized
        dd_state = self.get_drawdown_state(current_nav)
        return {
            "kill_switch": self._kill_switch,
            "peak_nav": self._peak_nav,
            "current_nav_estimate": current_nav,
            "drawdown": {
                "current": round(dd_state.current_drawdown, 4),
                "position_scalar": dd_state.position_scalar,
                "label": dd_state.label,
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
