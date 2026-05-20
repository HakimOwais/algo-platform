"""
Backtest API endpoint.

POST /backtest/run       — run a strategy on in-memory price history
GET  /backtest/costs     — show NSE transaction cost breakdown for a given trade
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_container
from app.core.container import ServiceContainer
from app.services.backtester import BacktestResult, ema_cross_signal_fn, nse_cost, run_backtest

router = APIRouter(prefix="/backtest", tags=["backtest"])


class BacktestRequest(BaseModel):
    symbol: str = Field(..., description="NSE symbol, e.g. RELIANCE")
    fast_window: int = Field(8, ge=2, le=50)
    slow_window: int = Field(21, ge=5, le=200)
    initial_capital: float = Field(1_000_000.0, gt=0)
    trade_qty: int = Field(10, ge=1, le=10_000)
    lookback: int = Field(60, ge=20, le=500)
    slippage_bps: float = Field(5.0, ge=0.0, le=100.0)


class TradeRow(BaseModel):
    entry_bar: int
    exit_bar: int
    entry_price: float
    exit_price: float
    qty: int
    gross_pnl: float
    costs: float
    net_pnl: float
    bars_held: int


class BacktestResponse(BaseModel):
    symbol: str
    total_return_pct: float
    annualised_return_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown_pct: float
    win_rate_pct: float
    profit_factor: float
    total_trades: int
    avg_bars_held: float
    avg_net_pnl: float
    total_costs: float
    final_nav: float
    initial_capital: float
    n_bars: int
    trades: list[TradeRow]


class CostRequest(BaseModel):
    price: float = Field(..., gt=0)
    quantity: int = Field(..., ge=1)
    side: str = Field(..., pattern="^(BUY|SELL)$")


class CostBreakdown(BaseModel):
    price: float
    quantity: int
    side: str
    notional: float
    brokerage: float
    stt: float
    exchange_fee: float
    sebi_fee: float
    gst: float
    stamp_duty: float
    total_cost: float
    cost_bps: float


@router.post("/run", response_model=BacktestResponse)
async def run_backtest_endpoint(
    req: BacktestRequest,
    container: ServiceContainer = Depends(get_container),
) -> BacktestResponse:
    """
    Backtest an EMA-crossover strategy on the in-memory price history for `symbol`.
    The price history is whatever the market-data service has accumulated since startup
    (synthetic GBM by default; real data once Angel One feed is enabled).
    """
    symbol = req.symbol.upper()
    closes = container.market_data.get_recent_closes(symbol, lookback=req.lookback)
    if len(closes) < req.slow_window + 10:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Insufficient price history for {symbol}: "
                f"have {len(closes)} bars, need ≥ {req.slow_window + 10}"
            ),
        )

    # Use closes as a proxy for highs, lows, volumes when not separately tracked
    signal_fn = ema_cross_signal_fn(fast=req.fast_window, slow=req.slow_window)
    result: BacktestResult = run_backtest(
        symbol=symbol,
        closes=closes,
        highs=closes,
        lows=closes,
        volumes=[1.0] * len(closes),
        signal_fn=signal_fn,
        initial_capital=req.initial_capital,
        trade_qty=req.trade_qty,
        lookback=req.lookback,
        slippage_bps=req.slippage_bps,
    )

    trades = [
        TradeRow(
            entry_bar=t.entry_bar, exit_bar=t.exit_bar,
            entry_price=round(t.entry_price, 2), exit_price=round(t.exit_price, 2),
            qty=t.qty, gross_pnl=round(t.gross_pnl, 2),
            costs=round(t.costs, 2), net_pnl=round(t.net_pnl, 2),
            bars_held=t.bars_held,
        )
        for t in result.trades
    ]

    return BacktestResponse(
        symbol=result.symbol,
        total_return_pct=round(result.total_return * 100, 4),
        annualised_return_pct=round(result.annualised_return * 100, 4),
        sharpe_ratio=round(result.sharpe_ratio, 4),
        sortino_ratio=round(result.sortino_ratio, 4),
        max_drawdown_pct=round(result.max_drawdown * 100, 4),
        win_rate_pct=round(result.win_rate * 100, 2),
        profit_factor=round(result.profit_factor, 4) if result.profit_factor != float("inf") else 9999.0,
        total_trades=result.total_trades,
        avg_bars_held=round(result.avg_bars_held, 1),
        avg_net_pnl=round(result.avg_net_pnl, 2),
        total_costs=round(result.total_costs, 2),
        final_nav=round(result.final_nav, 2),
        initial_capital=result.initial_capital,
        n_bars=len(closes),
        trades=trades,
    )


@router.post("/costs", response_model=CostBreakdown)
async def compute_costs(req: CostRequest) -> CostBreakdown:
    """Show the full NSE transaction cost breakdown for a hypothetical trade."""
    p = req.price; q = req.quantity; side = req.side.upper()
    notional = p * q

    brokerage    = min(notional * 0.0003, 20.0)
    stt          = notional * 0.001 if side == "SELL" else 0.0
    exchange_fee = notional * 0.0000335
    sebi_fee     = notional * 0.000001
    gst          = (brokerage + exchange_fee) * 0.18
    stamp        = notional * 0.00015 if side == "BUY" else 0.0
    total        = brokerage + stt + exchange_fee + sebi_fee + gst + stamp

    return CostBreakdown(
        price=p, quantity=q, side=side,
        notional=round(notional, 2),
        brokerage=round(brokerage, 4),
        stt=round(stt, 4),
        exchange_fee=round(exchange_fee, 4),
        sebi_fee=round(sebi_fee, 4),
        gst=round(gst, 4),
        stamp_duty=round(stamp, 4),
        total_cost=round(total, 4),
        cost_bps=round(total / max(notional, 1e-6) * 10_000, 2),
    )
