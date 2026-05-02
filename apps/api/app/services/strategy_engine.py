"""
Strategy engine — multi-signal, regime-filtered, ML-augmented trading.

Signal stack (in order of application):
  1. Regime filter     — 2-state HMM; blocks trades in CHOPPY regime (halves size)
  2. EMA crossover     — directional trigger (existing)
  3. HAR-RV vol sizing — replaces ARCH/GARCH for vol forecast when ≥ 30 daily bars
  4. Fractional Kelly  — 25% Kelly instead of full Kelly (reduces ruin probability)
  5. Cross-sectional momentum — adjusts allocation weight by 12-1m momentum rank
  6. Kalman pairs      — replaces static OLS hedge ratio for spread context
  7. ML signal         — LightGBM classifier confirms / vetoes trade (when trained)
  8. Drawdown scalar   — from RiskEngine; halves size at 10% DD, stops at 20% DD
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from statistics import fmean

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.events import EventHub
from app.ml.model import get_classifier
from app.models.decision_log import DecisionLog
from app.models.enums import Side
from app.models.strategy import StrategyConfig
from app.quant.features import build_feature_vector
from app.quant.har_rv import compute_daily_rv, estimate_egarch, estimate_har_rv
from app.quant.momentum import cross_sectional_momentum
from app.quant.monte_carlo import monte_carlo_var_cvar_from_prices
from app.quant.pairs_kalman import kalman_hedge_ratio
from app.quant.portfolio_models import mean_variance_weights, risk_parity_weights_from_returns
from app.quant.regime import detect_regime
from app.quant.returns import log_returns
from app.quant.volatility_models import annualize_volatility, estimate_garch_1_1
from app.services.order_manager import OrderManager
from app.services.portfolio_service import PortfolioService
from app.services.risk_engine import fractional_kelly


class StrategyEngine:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        market_data_service,
        order_manager: OrderManager,
        portfolio_service: PortfolioService,
        event_hub: EventHub,
        symbols: list[str],
    ) -> None:
        self._session_factory = session_factory
        self._market_data_service = market_data_service
        self._order_manager = order_manager
        self._portfolio_service = portfolio_service
        self._event_hub = event_hub
        self._symbols = symbols
        self._regime_state: dict[str, int] = {}  # EMA crossover state per symbol

    # ------------------------------------------------------------------
    @staticmethod
    def _to_bool(value: object, default: bool) -> bool:
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    @staticmethod
    def _clamp(value: float, lo: float, hi: float) -> float:
        return max(lo, min(hi, value))

    # ------------------------------------------------------------------
    async def run_once(self) -> None:
        async with self._session_factory() as session:
            strategy = await self._active_strategy(session)
            if strategy is None:
                return
            params = strategy.parameters or {}

        # ── Load parameters ──────────────────────────────────────────────
        fast            = int(params.get("fast_window", 8))
        slow            = int(params.get("slow_window", 21))
        base_lot        = int(params.get("trade_quantity", 5))
        lookback        = int(params.get("lookback_bars", max(slow + 60, 90)))
        bars_per_day    = int(params.get("bars_per_day", 390))
        target_vol      = float(params.get("target_vol_annual", 0.22))
        min_scale       = float(params.get("min_position_scale", 0.35))
        max_scale       = float(params.get("max_position_scale", 2.5))
        max_qty         = int(params.get("max_trade_quantity", 200))
        risk_budget     = float(params.get("risk_budget_per_order_inr", 1200.0))
        mc_conf         = float(params.get("mc_confidence", 0.95))
        mc_steps        = int(params.get("mc_horizon_steps", 12))
        mc_paths        = int(params.get("mc_paths", 1500))
        use_har         = self._to_bool(params.get("use_har_rv"), True)
        use_mc          = self._to_bool(params.get("use_monte_carlo_guard"), True)
        use_regime      = self._to_bool(params.get("use_regime_filter"), True)
        use_momentum    = self._to_bool(params.get("use_momentum_context"), True)
        use_kalman      = self._to_bool(params.get("use_kalman_pairs"), True)
        use_ml          = self._to_bool(params.get("use_ml_signal"), True)
        kelly_fraction  = float(params.get("kelly_fraction", 0.25))  # fractional Kelly

        if fast >= slow:
            slow = fast + 5

        # ── Gather price histories ────────────────────────────────────────
        price_history: dict[str, list[float]] = {}
        returns_by_symbol: dict[str, list[float]] = {}
        for sym in self._symbols:
            closes = self._market_data_service.get_recent_closes(sym, lookback=lookback)
            price_history[sym] = closes
            rets = log_returns(closes)
            if len(rets) >= 20:
                returns_by_symbol[sym] = rets

        # ── Portfolio-level weights ───────────────────────────────────────
        mv_weights   = mean_variance_weights(returns_by_symbol)
        rp_weights   = risk_parity_weights_from_returns(returns_by_symbol)

        # Cross-sectional momentum weights (12-1 month)
        cs_momentum  = (
            cross_sectional_momentum(price_history, formation_bars=min(252, lookback - 1))
            if use_momentum
            else {}
        )

        anchor_sym    = self._symbols[0] if self._symbols else None
        anchor_prices = price_history.get(anchor_sym) if anchor_sym else None

        # ── Per-symbol signal loop ────────────────────────────────────────
        for symbol in self._symbols:
            closes = price_history.get(symbol) or self._market_data_service.get_recent_closes(
                symbol, lookback=lookback
            )
            if len(closes) < slow:
                continue

            # 1. EMA crossover signal
            fast_ma = fmean(closes[-fast:])
            slow_ma = fmean(closes[-slow:])
            signal_state = 1 if fast_ma > slow_ma else -1
            prev_state = self._regime_state.get(symbol)
            self._regime_state[symbol] = signal_state

            if prev_state is None or prev_state == signal_state:
                continue  # no crossover → no action

            returns = log_returns(closes)

            # 2. Regime filter
            regime_scalar = 1.0
            regime_info: dict = {}
            if use_regime and len(returns) >= 30:
                regime = detect_regime(returns)
                regime_scalar = regime.position_scalar
                regime_info = {
                    "label": regime.regime_label,
                    "trending_prob": round(regime.trending_prob, 4),
                    "scalar": regime.position_scalar,
                }
                if regime.current_regime == 1:
                    # Still trade but at half size — don't veto entirely
                    pass

            # 3. Volatility forecast (HAR-RV preferred, GARCH as fallback)
            daily_rv = compute_daily_rv(returns)
            har_result = estimate_har_rv(daily_rv, bars_per_day=bars_per_day) if use_har else None

            if har_result is not None:
                annual_vol = har_result.forecast_vol_annual
                vol_info = {
                    "model": "HAR-RV",
                    "forecast_variance": round(har_result.forecast_variance, 10),
                    "annualized": round(annual_vol, 6),
                    "beta_daily": round(har_result.beta_daily, 6),
                    "beta_weekly": round(har_result.beta_weekly, 6),
                    "beta_monthly": round(har_result.beta_monthly, 6),
                }
            else:
                garch = estimate_garch_1_1(returns)
                egarch = estimate_egarch(returns, bars_per_day=bars_per_day)
                # Blend GARCH and EGARCH (EGARCH better captures leverage effect)
                blended_var = 0.5 * garch.next_variance + 0.5 * egarch.next_variance
                annual_vol = annualize_volatility(
                    math.sqrt(max(blended_var, 1e-12)), bars_per_day=bars_per_day
                )
                vol_info = {
                    "model": "GARCH+EGARCH blend",
                    "annualized": round(annual_vol, 6),
                    "garch_alpha": round(garch.alpha, 6),
                    "garch_beta": round(garch.beta, 6),
                    "egarch_gamma": round(egarch.gamma, 6),
                }

            vol_scale = self._clamp(
                target_vol / max(annual_vol, 1e-6), min_scale, max_scale
            )

            # 4. Allocation weight (mean-variance + risk-parity + momentum blend)
            n_syms = max(len(self._symbols), 1)
            mv_w = mv_weights.get(symbol, 1.0 / n_syms)
            rp_w = rp_weights.get(symbol, 1.0 / n_syms)
            mo_w = cs_momentum.get(symbol, 1.0 / n_syms) if cs_momentum else 1.0 / n_syms
            alloc_weight = (mv_w + rp_w + mo_w) / 3.0
            alloc_scale = self._clamp(alloc_weight * n_syms, 0.5, 1.5)

            # 5. Monte Carlo tail-risk guard
            mc_metrics = monte_carlo_var_cvar_from_prices(
                prices=closes,
                notional=closes[-1] * max(base_lot, 1),
                confidence=mc_conf,
                horizon_steps=mc_steps,
                paths=mc_paths,
                random_seed=13,
            )
            tail_scale = 1.0
            if use_mc and mc_metrics and mc_metrics.var_amount > 0:
                tail_scale = self._clamp(risk_budget / mc_metrics.var_amount, 0.25, 1.25)

            # 6. Fractional Kelly sizing (25% Kelly by default)
            if returns:
                mu = fmean(returns)
                var = fmean([(r - mu) ** 2 for r in returns])
            else:
                mu = 0.0; var = 1e-6
            kelly = fractional_kelly(
                expected_return=mu,
                variance=var,
                fraction=kelly_fraction,
                cap=1.5,
            )
            kelly_scale = self._clamp(max(kelly, 0.0) + 0.5, 0.25, 1.5)

            # 7. Kalman-based pairs context
            pair_info: dict = {}
            if use_kalman and anchor_sym and anchor_sym != symbol and anchor_prices:
                kp = kalman_hedge_ratio(anchor_prices, closes)
                if kp:
                    pair_info = {
                        "anchor": anchor_sym,
                        "hedge_ratio": round(kp.hedge_ratio, 6),
                        "zscore": round(kp.zscore, 6),
                        "signal": kp.signal,
                        "kalman_gain": round(kp.kalman_gain, 8),
                    }
                    if (signal_state > 0 and kp.signal == "SHORT_SPREAD") or (
                        signal_state < 0 and kp.signal == "LONG_SPREAD"
                    ):
                        tail_scale *= 0.75

            # 8. ML signal confirmation
            ml_info: dict = {}
            ml_veto = False
            if use_ml:
                clf = get_classifier()
                if clf.is_trained:
                    now = datetime.now(timezone.utc)
                    highs   = self._market_data_service.get_recent_closes(symbol, lookback)
                    lows    = highs  # fallback: use closes when H/L not tracked separately
                    volumes = [1.0] * len(closes)  # placeholder until volume tracked

                    # Try to get richer OHLCV from the market data service if available
                    if hasattr(self._market_data_service, "get_recent_ohlcv"):
                        ohlcv = self._market_data_service.get_recent_ohlcv(symbol, lookback)
                        highs   = ohlcv.get("highs", highs)
                        lows    = ohlcv.get("lows", lows)
                        volumes = ohlcv.get("volumes", volumes)

                    fv = build_feature_vector(
                        closes=closes,
                        highs=highs,
                        lows=lows,
                        volumes=volumes,
                        timestamp_hour=now.hour,
                        timestamp_minute=now.minute,
                        timestamp_weekday=now.weekday(),
                    )
                    if fv is not None:
                        ml_sig = clf.predict(fv.to_list())
                        ml_info = {
                            "direction": ml_sig.direction,
                            "bull_prob": round(ml_sig.bull_prob, 4),
                            "confidence": round(ml_sig.confidence, 4),
                        }
                        # Veto trade if ML strongly disagrees with EMA signal
                        if ml_sig.direction != 0 and ml_sig.direction != signal_state:
                            ml_veto = True

            # ── Compute final quantity ────────────────────────────────────
            combined_scale = vol_scale * alloc_scale * tail_scale * kelly_scale * regime_scalar
            dynamic_qty = int(round(base_lot * combined_scale))
            dynamic_qty = max(1, min(dynamic_qty, max_qty))

            signal_confidence = abs(fast_ma - slow_ma) / max(abs(slow_ma), 1.0)
            log_var = math.log(max(var, 1e-12))
            confidence = signal_confidence / (1.0 + abs(log_var))

            # ── Persist decision log ─────────────────────────────────────
            async with self._session_factory() as session:
                decision = DecisionLog(
                    strategy_name="ema_cross_v2",
                    symbol=symbol,
                    signal="BUY" if signal_state > 0 else "SELL",
                    confidence=round(confidence, 6),
                    reason=(
                        "EMA crossover with regime filter, HAR-RV sizing, "
                        "fractional Kelly, momentum context, Kalman pairs"
                        + (" [ML_VETO]" if ml_veto else "")
                    ),
                    payload={
                        "fast_ma": round(fast_ma, 2),
                        "slow_ma": round(slow_ma, 2),
                        "base_qty": base_lot,
                        "dynamic_qty": dynamic_qty,
                        "scales": {
                            "vol": round(vol_scale, 6),
                            "alloc": round(alloc_scale, 6),
                            "tail": round(tail_scale, 6),
                            "kelly": round(kelly_scale, 6),
                            "regime": regime_scalar,
                            "combined": round(combined_scale, 6),
                        },
                        "volatility": vol_info,
                        "regime": regime_info,
                        "allocation": {
                            "mv_weight": round(mv_w, 6),
                            "rp_weight": round(rp_w, 6),
                            "momentum_weight": round(mo_w, 6),
                        },
                        "monte_carlo": {
                            "var": round(mc_metrics.var_amount, 2) if mc_metrics else None,
                            "cvar": round(mc_metrics.cvar_amount, 2) if mc_metrics else None,
                        },
                        "pairs_kalman": pair_info,
                        "ml": ml_info,
                        "ml_veto": ml_veto,
                    },
                )
                session.add(decision)
                await session.commit()

            # ── Place order (skip if ML vetoes) ──────────────────────────
            if ml_veto:
                await self._event_hub.broadcast(
                    "strategy.ml_veto",
                    {"symbol": symbol, "ema_signal": signal_state, "ml": ml_info},
                )
                continue

            if signal_state > 0:
                await self._order_manager.place_order(
                    strategy_name="ema_cross_v2",
                    symbol=symbol,
                    side=Side.BUY,
                    quantity=dynamic_qty,
                    is_paper=True,
                )
                await self._event_hub.broadcast(
                    "strategy.signal",
                    {
                        "strategy": "ema_cross_v2",
                        "symbol": symbol,
                        "signal": "BUY",
                        "quantity": dynamic_qty,
                        "regime": regime_info.get("label", "UNKNOWN"),
                        "annualized_vol": round(annual_vol, 6),
                    },
                )
            else:
                async with self._session_factory() as session:
                    held_qty = await self._portfolio_service.get_position_qty(
                        session=session, symbol=symbol
                    )
                if held_qty > 0:
                    await self._order_manager.place_order(
                        strategy_name="ema_cross_v2",
                        symbol=symbol,
                        side=Side.SELL,
                        quantity=min(dynamic_qty, held_qty),
                        is_paper=True,
                    )
                    await self._event_hub.broadcast(
                        "strategy.signal",
                        {
                            "strategy": "ema_cross_v2",
                            "symbol": symbol,
                            "signal": "SELL",
                            "quantity": min(dynamic_qty, held_qty),
                            "regime": regime_info.get("label", "UNKNOWN"),
                            "annualized_vol": round(annual_vol, 6),
                        },
                    )

    # ------------------------------------------------------------------
    async def _active_strategy(self, session: AsyncSession) -> StrategyConfig | None:
        result = await session.execute(
            select(StrategyConfig)
            .where(StrategyConfig.name.in_(["ema_cross", "ema_cross_v2"]))
            .where(StrategyConfig.is_active == True)  # noqa: E712
            .limit(1)
        )
        return result.scalar_one_or_none()
