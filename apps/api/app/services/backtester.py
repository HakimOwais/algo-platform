"""
Vectorized backtester with real NSE transaction cost model.

Features:
- Accurate NSE costs via quant.costs (single source of truth)
- Point-in-time signal evaluation (executes on next bar's open, no look-ahead)
- Long-only (no shorting in paper mode)
- Full performance report: Sharpe, Sortino, max drawdown, win rate, profit factor
- Walk-forward friendly: returns equity curve and trade log for further analysis
"""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

from app.quant.costs import nse_cost


@dataclass
class Trade:
    symbol: str
    entry_bar: int
    exit_bar: int
    entry_price: float
    exit_price: float
    qty: int
    gross_pnl: float
    costs: float
    net_pnl: float
    bars_held: int


@dataclass
class BacktestResult:
    symbol: str
    total_return: float
    annualised_return: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    win_rate: float
    profit_factor: float
    total_trades: int
    avg_bars_held: float
    avg_net_pnl: float
    total_costs: float
    final_nav: float
    initial_capital: float
    trades: list[Trade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
    bar_returns: list[float] = field(default_factory=list)


SignalFn = Callable[
    [list[float], list[float], list[float], list[float]],
    int,
]


def _safe_div(a: float, b: float, default: float = 0.0) -> float:
    return a / b if abs(b) > 1e-12 else default


def run_backtest(
    symbol: str,
    closes: list[float],
    highs: list[float],
    lows: list[float],
    volumes: list[float],
    signal_fn: SignalFn,
    initial_capital: float = 1_000_000.0,
    trade_qty: int = 10,
    lookback: int = 60,
    slippage_bps: float = 5.0,
    bars_per_year: int = 252,
) -> BacktestResult:
    """
    Run a vectorized backtest of `signal_fn` on historical OHLCV data.

    signal_fn receives point-in-time slices (closes[:t+1] etc.) and returns:
        +1 → hold long
         0 → flat (exit if holding)
    Orders execute at the *next* bar's close with slippage applied.
    """
    n = min(len(closes), len(highs), len(lows), len(volumes))
    closes = closes[:n]; highs = highs[:n]
    lows = lows[:n];     volumes = volumes[:n]

    slippage = slippage_bps / 10_000.0
    capital = initial_capital
    position = 0
    entry_price = 0.0
    entry_bar = 0
    trades: list[Trade] = []
    total_costs = 0.0
    equity: list[float] = [capital]

    for t in range(lookback, n - 1):
        signal = signal_fn(closes[:t + 1], highs[:t + 1], lows[:t + 1], volumes[:t + 1])
        exec_price = closes[t + 1]

        if position == 0 and signal > 0:
            fill = exec_price * (1.0 + slippage)
            cost = nse_cost(fill, trade_qty, "BUY")
            capital -= cost
            total_costs += cost
            position = 1
            entry_price = fill
            entry_bar = t + 1

        elif position == 1 and signal <= 0:
            fill = exec_price * (1.0 - slippage)
            cost = nse_cost(fill, trade_qty, "SELL")
            gross = (fill - entry_price) * trade_qty
            net = gross - cost
            capital += net
            total_costs += cost
            trades.append(Trade(
                symbol=symbol,
                entry_bar=entry_bar, exit_bar=t + 1,
                entry_price=entry_price, exit_price=fill,
                qty=trade_qty, gross_pnl=gross, costs=cost,
                net_pnl=net, bars_held=t + 1 - entry_bar,
            ))
            position = 0

        nav = capital + (closes[t + 1] - entry_price) * trade_qty if position == 1 else capital
        equity.append(nav)

    if position == 1:
        fill = closes[-1] * (1.0 - slippage)
        cost = nse_cost(fill, trade_qty, "SELL")
        gross = (fill - entry_price) * trade_qty
        net = gross - cost
        capital += net
        total_costs += cost
        trades.append(Trade(
            symbol=symbol,
            entry_bar=entry_bar, exit_bar=n - 1,
            entry_price=entry_price, exit_price=fill,
            qty=trade_qty, gross_pnl=gross, costs=cost,
            net_pnl=net, bars_held=n - 1 - entry_bar,
        ))
        equity.append(capital)

    bar_rets = [
        (equity[i] / equity[i - 1]) - 1.0
        for i in range(1, len(equity))
        if equity[i - 1] > 0
    ]

    total_ret = (equity[-1] / initial_capital) - 1.0 if initial_capital > 0 else 0.0
    n_bars = len(equity) - 1
    ann_ret = (
        (1.0 + total_ret) ** (bars_per_year / max(n_bars, 1)) - 1.0
        if n_bars > 0 else 0.0
    )

    if bar_rets:
        mu = sum(bar_rets) / len(bar_rets)
        sigma = math.sqrt(sum((r - mu) ** 2 for r in bar_rets) / max(len(bar_rets) - 1, 1))
        sharpe = _safe_div(mu, sigma) * math.sqrt(bars_per_year)
        neg = [r for r in bar_rets if r < 0]
        down_std = math.sqrt(sum(r ** 2 for r in neg) / len(neg)) if neg else sigma
        sortino = _safe_div(mu, down_std) * math.sqrt(bars_per_year)
    else:
        sharpe = sortino = 0.0

    peak = equity[0]
    max_dd = 0.0
    for v in equity:
        peak = max(peak, v)
        dd = (peak - v) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, dd)

    wins   = [t for t in trades if t.net_pnl > 0]
    losses = [t for t in trades if t.net_pnl <= 0]
    win_rate = len(wins) / max(len(trades), 1)
    gross_profit = sum(t.net_pnl for t in wins)
    gross_loss   = abs(sum(t.net_pnl for t in losses))
    profit_factor = _safe_div(gross_profit, gross_loss, default=float("inf") if wins else 0.0)

    return BacktestResult(
        symbol=symbol,
        total_return=total_ret,
        annualised_return=ann_ret,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        max_drawdown=max_dd,
        win_rate=win_rate,
        profit_factor=profit_factor,
        total_trades=len(trades),
        avg_bars_held=sum(t.bars_held for t in trades) / max(len(trades), 1),
        avg_net_pnl=sum(t.net_pnl for t in trades) / max(len(trades), 1),
        total_costs=total_costs,
        final_nav=equity[-1],
        initial_capital=initial_capital,
        trades=trades,
        equity_curve=equity,
        bar_returns=bar_rets,
    )


def ema_cross_signal_fn(fast: int = 8, slow: int = 21) -> SignalFn:
    """Return a simple EMA-crossover signal function for use as a backtest baseline."""
    def _fn(closes: list[float], highs: list[float], lows: list[float], volumes: list[float]) -> int:
        if len(closes) < slow:
            return 0
        k_fast = 2.0 / (fast + 1)
        k_slow = 2.0 / (slow + 1)
        ema_f = ema_s = closes[0]
        for c in closes[1:]:
            ema_f = c * k_fast + ema_f * (1.0 - k_fast)
            ema_s = c * k_slow + ema_s * (1.0 - k_slow)
        return 1 if ema_f > ema_s else 0
    return _fn
