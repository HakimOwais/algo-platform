"""StrategyPipeline — composes signal stages and dispatches orders.

Design decisions:
  - All CPU-bound quant work (HMM, GARCH, EGARCH, Kalman, MC) runs inside
    asyncio.to_thread so the event loop is never blocked.
  - Stages are plain functions registered in STAGES tuple; adding a new signal
    requires only a new file + one line here, not modifying run_once.
  - DB access is delegated entirely to repositories injected at construction.
  - The strategy loop calls run_once(); the orchestrator drives the clock.
"""
from __future__ import annotations

import asyncio
import logging
import math
from datetime import datetime, timezone

from app.core.events import EventHub
from app.models.decision_log import DecisionLog
from app.models.enums import Side
from app.ports.market_data import MarketDataPort
from app.ports.repositories import DecisionRepo, PositionRepo, StrategyRepo
from app.quant._numeric import mean, variance
from app.quant.momentum import cross_sectional_momentum
from app.quant.portfolio_models import (
    mean_variance_weights,
    risk_parity_weights_from_returns,
)
from app.quant.returns import log_returns
from app.services.order_manager import OrderManager
from app.services.strategy.context import CycleContext, SignalContext
from app.services.strategy.stages.allocation import apply_allocation
from app.services.strategy.stages.kelly import apply_kelly
from app.services.strategy.stages.ml_signal import apply_ml_signal
from app.services.strategy.stages.pairs import apply_pairs
from app.services.strategy.stages.regime import apply_regime
from app.services.strategy.stages.tail_risk import apply_tail_risk
from app.services.strategy.stages.volatility import apply_volatility

logger = logging.getLogger(__name__)

# Ordered pipeline of CPU-bound stages — no I/O, no DB, no async.
_STAGES = (
    apply_regime,
    apply_volatility,
    apply_allocation,
    apply_tail_risk,
    apply_kelly,
    apply_pairs,
)

_ACTIVE_STRATEGY_NAMES = ("ema_cross", "ema_cross_v2")


class StrategyPipeline:
    def __init__(
        self,
        *,
        market_data: MarketDataPort,
        order_manager: OrderManager,
        position_repo: PositionRepo,
        decision_repo: DecisionRepo,
        strategy_repo: StrategyRepo,
        event_hub: EventHub,
        symbols: list[str],
    ) -> None:
        self._market_data = market_data
        self._order_manager = order_manager
        self._position_repo = position_repo
        self._decision_repo = decision_repo
        self._strategy_repo = strategy_repo
        self._event_hub = event_hub
        self._symbols = symbols
        self._ema_state: dict[str, int] = {}  # last EMA crossover state per symbol

    # ── Entry point ────────────────────────────────────────────────────────

    async def run_once(self) -> None:
        strategy = await self._strategy_repo.get_active(_ACTIVE_STRATEGY_NAMES)
        if strategy is None:
            return
        params = strategy.parameters or {}

        # Build shared cycle context (also CPU-bound: portfolio weights, momentum)
        cycle = await asyncio.to_thread(self._build_cycle, params)

        for symbol in self._symbols:
            ctx = self._build_signal_context(cycle, symbol, params)
            if ctx is None:
                continue  # no crossover this tick

            # All CPU-intensive quant stages run off the event loop
            await asyncio.to_thread(self._run_cpu_stages, cycle, ctx)

            # ML stage is async-safe but calls a synchronous model.predict
            await asyncio.to_thread(apply_ml_signal, cycle, ctx, self._market_data)

            await self._dispatch(ctx, params)

    # ── CPU-bound work (called via to_thread) ──────────────────────────────

    def _build_cycle(self, params: dict) -> CycleContext:
        lookback = int(params.get("lookback_bars", 90))
        price_history: dict[str, list[float]] = {}
        returns_by_symbol: dict[str, list[float]] = {}
        for sym in self._symbols:
            closes = self._market_data.get_recent_closes(sym, lookback=lookback)
            price_history[sym] = closes
            rets = log_returns(closes)
            if len(rets) >= 20:
                returns_by_symbol[sym] = rets

        use_momentum = params.get("use_momentum_context", True)
        cs_momentum = (
            cross_sectional_momentum(
                price_history,
                formation_bars=min(252, lookback - 1),
            )
            if use_momentum
            else {}
        )

        return CycleContext(
            params=params,
            price_history=price_history,
            returns_by_symbol=returns_by_symbol,
            mv_weights=mean_variance_weights(returns_by_symbol),
            rp_weights=risk_parity_weights_from_returns(returns_by_symbol),
            cs_momentum=cs_momentum,
            anchor_symbol=self._symbols[0] if self._symbols else None,
        )

    @staticmethod
    def _run_cpu_stages(cycle: CycleContext, ctx: SignalContext) -> None:
        for stage in _STAGES:
            try:
                stage(cycle, ctx)
            except Exception:
                logger.exception("Stage %s failed for %s — skipping", stage.__name__, ctx.symbol)

    # ── Crossover detection (fast — no quant, no I/O) ─────────────────────

    def _build_signal_context(
        self, cycle: CycleContext, symbol: str, params: dict
    ) -> SignalContext | None:
        fast = int(params.get("fast_window", 8))
        slow = int(params.get("slow_window", 21))
        if fast >= slow:
            slow = fast + 5

        closes = cycle.price_history.get(symbol) or []
        if len(closes) < slow:
            return None

        fast_ma = _ema(closes, fast)
        slow_ma = _ema(closes, slow)
        signal_state = 1 if fast_ma > slow_ma else -1
        prev_state = self._ema_state.get(symbol)
        self._ema_state[symbol] = signal_state

        if prev_state is None or prev_state == signal_state:
            return None  # no crossover → skip

        ctx = SignalContext(
            symbol=symbol,
            closes=closes,
            returns=log_returns(closes),
            signal_state=signal_state,
            base_qty=int(params.get("trade_quantity", 5)),
        )
        ctx.diagnostics["fast_ma"] = round(fast_ma, 2)
        ctx.diagnostics["slow_ma"] = round(slow_ma, 2)
        return ctx

    # ── Async side-effects: persist + order ───────────────────────────────

    async def _dispatch(self, ctx: SignalContext, params: dict) -> None:
        max_qty = int(params.get("max_trade_quantity", 200))
        qty = max(1, min(int(round(ctx.base_qty * ctx.combined_scale)), max_qty))
        confidence = _confidence(ctx)

        await self._decision_repo.record(
            DecisionLog(
                strategy_name="ema_cross_v2",
                symbol=ctx.symbol,
                signal="BUY" if ctx.signal_state > 0 else "SELL",
                confidence=round(confidence, 6),
                reason=_reason(ctx),
                payload={
                    "base_qty": ctx.base_qty,
                    "dynamic_qty": qty,
                    "scales": {
                        "vol": round(ctx.vol_scale, 6),
                        "alloc": round(ctx.alloc_scale, 6),
                        "tail": round(ctx.tail_scale, 6),
                        "kelly": round(ctx.kelly_scale, 6),
                        "regime": ctx.regime_scalar,
                        "combined": round(ctx.combined_scale, 6),
                    },
                    **ctx.diagnostics,
                    "ml_veto": ctx.ml_veto,
                },
            )
        )

        if ctx.ml_veto:
            await self._event_hub.broadcast(
                "strategy.ml_veto",
                {
                    "symbol": ctx.symbol,
                    "ema_signal": ctx.signal_state,
                    "ml": ctx.diagnostics.get("ml", {}),
                },
            )
            return

        if ctx.signal_state > 0:
            await self._order_manager.place_order(
                strategy_name="ema_cross_v2",
                symbol=ctx.symbol,
                side=Side.BUY,
                quantity=qty,
                is_paper=True,
            )
        else:
            held = await self._position_repo.held_qty(ctx.symbol)
            if held > 0:
                await self._order_manager.place_order(
                    strategy_name="ema_cross_v2",
                    symbol=ctx.symbol,
                    side=Side.SELL,
                    quantity=min(qty, held),
                    is_paper=True,
                )

        await self._event_hub.broadcast(
            "strategy.signal",
            {
                "strategy": "ema_cross_v2",
                "symbol": ctx.symbol,
                "signal": "BUY" if ctx.signal_state > 0 else "SELL",
                "quantity": qty,
                "regime": ctx.diagnostics.get("regime", {}).get("label", "UNKNOWN"),
                "annualized_vol": ctx.diagnostics.get("volatility", {}).get("annualized", 0.0),
            },
        )


# ── Module-level pure helpers ──────────────────────────────────────────────


def _ema(prices: list[float], window: int) -> float:
    if not prices:
        return 0.0
    alpha = 2.0 / (window + 1)
    ema = prices[0]
    for p in prices[1:]:
        ema = alpha * p + (1.0 - alpha) * ema
    return ema


def _confidence(ctx: SignalContext) -> float:
    fast_ma = ctx.diagnostics.get("fast_ma", 0.0)
    slow_ma = ctx.diagnostics.get("slow_ma", 1.0)
    signal_conf = abs(fast_ma - slow_ma) / max(abs(slow_ma), 1.0)
    rets = ctx.returns
    var = variance(rets) if rets else 1e-6
    log_var = math.log(max(var, 1e-12))
    return signal_conf / (1.0 + abs(log_var))


def _reason(ctx: SignalContext) -> str:
    base = (
        "EMA crossover with regime filter, HAR-RV sizing, "
        "fractional Kelly, momentum context, Kalman pairs"
    )
    return base + (" [ML_VETO]" if ctx.ml_veto else "")
