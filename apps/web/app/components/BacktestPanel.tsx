"use client";

import { useCallback, useState } from "react";
import { api } from "@/app/lib/api";
import type { BacktestResponse } from "@/app/lib/types";

const currency = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });

interface MetricProps { label: string; value: string; colour?: string }
function Metric({ label, value, colour }: MetricProps) {
  return (
    <div className="bt-metric">
      <span className="muted">{label}</span>
      <strong style={colour ? { color: colour } : undefined}>{value}</strong>
    </div>
  );
}

function sharpeColour(v: number) {
  return v >= 1.5 ? "var(--good)" : v >= 0.8 ? "var(--warn)" : "var(--danger)";
}
function ddColour(v: number) {
  return v <= 5 ? "var(--good)" : v <= 15 ? "var(--warn)" : "var(--danger)";
}

interface BacktestPanelProps {
  symbols: string[];
}

export function BacktestPanel({ symbols }: BacktestPanelProps) {
  const [symbol, setSymbol] = useState(symbols[0] ?? "RELIANCE");
  const [fast, setFast] = useState(8);
  const [slow, setSlow] = useState(21);
  const [qty, setQty] = useState(10);
  const [slippage, setSlippage] = useState(5);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<BacktestResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const onRun = useCallback(async () => {
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const r = await api.runBacktest({
        symbol,
        fast_window: fast,
        slow_window: slow,
        trade_qty: qty,
        slippage_bps: slippage,
      });
      setResult(r);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Backtest failed");
    } finally {
      setRunning(false);
    }
  }, [symbol, fast, slow, qty, slippage]);

  return (
    <section className="panel">
      <div className="panel-header">
        <h3>Strategy Backtest</h3>
      </div>

      <div className="bt-controls">
        <label>
          Symbol
          <select suppressHydrationWarning value={symbol} onChange={(e) => setSymbol(e.target.value)}>
            {symbols.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </label>
        <label>
          Fast EMA
          <input suppressHydrationWarning type="number" value={fast} min={2} max={50} onChange={(e) => setFast(Number(e.target.value))} />
        </label>
        <label>
          Slow EMA
          <input suppressHydrationWarning type="number" value={slow} min={5} max={200} onChange={(e) => setSlow(Number(e.target.value))} />
        </label>
        <label>
          Trade qty
          <input suppressHydrationWarning type="number" value={qty} min={1} onChange={(e) => setQty(Number(e.target.value))} />
        </label>
        <label>
          Slippage (bps)
          <input suppressHydrationWarning type="number" value={slippage} min={0} max={50} step={0.5} onChange={(e) => setSlippage(Number(e.target.value))} />
        </label>
      </div>

      <div className="button-row">
        <button suppressHydrationWarning className="btn" onClick={onRun} disabled={running}>
          {running ? "Running…" : "Run Backtest"}
        </button>
      </div>

      {error && <p className="text-bad" style={{ fontSize: "0.82rem", marginTop: 8 }}>{error}</p>}

      {result && (
        <div className="bt-results">
          <p className="muted" style={{ fontSize: "0.78rem", marginBottom: 8 }}>
            {result.symbol} · {result.n_bars} bars · {result.total_trades} trades
          </p>

          <div className="bt-metrics-grid">
            <Metric
              label="Total return"
              value={`${result.total_return_pct >= 0 ? "+" : ""}${result.total_return_pct.toFixed(2)}%`}
              colour={result.total_return_pct >= 0 ? "var(--good)" : "var(--danger)"}
            />
            <Metric
              label="Ann. return"
              value={`${result.annualised_return_pct >= 0 ? "+" : ""}${result.annualised_return_pct.toFixed(2)}%`}
              colour={result.annualised_return_pct >= 0 ? "var(--good)" : "var(--danger)"}
            />
            <Metric
              label="Sharpe"
              value={result.sharpe_ratio.toFixed(3)}
              colour={sharpeColour(result.sharpe_ratio)}
            />
            <Metric
              label="Sortino"
              value={result.sortino_ratio.toFixed(3)}
              colour={sharpeColour(result.sortino_ratio)}
            />
            <Metric
              label="Max drawdown"
              value={`${result.max_drawdown_pct.toFixed(2)}%`}
              colour={ddColour(result.max_drawdown_pct)}
            />
            <Metric
              label="Win rate"
              value={`${result.win_rate_pct.toFixed(1)}%`}
              colour={result.win_rate_pct >= 50 ? "var(--good)" : "var(--warn)"}
            />
            <Metric
              label="Profit factor"
              value={result.profit_factor >= 9999 ? "∞" : result.profit_factor.toFixed(2)}
              colour={result.profit_factor >= 1.5 ? "var(--good)" : "var(--warn)"}
            />
            <Metric label="Avg bars held" value={result.avg_bars_held.toFixed(1)} />
            <Metric label="Avg net PnL" value={`₹${result.avg_net_pnl.toFixed(0)}`} />
            <Metric label="Total costs" value={`₹${result.total_costs.toFixed(0)}`} />
            <Metric label="Final NAV" value={currency.format(result.final_nav)} />
          </div>

          {/* Last 5 trades */}
          {result.trades.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <p className="muted" style={{ fontSize: "0.78rem", marginBottom: 4 }}>Recent trades</p>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Entry</th>
                      <th>Exit</th>
                      <th>Qty</th>
                      <th>Net PnL</th>
                      <th>Costs</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.trades.slice(-5).reverse().map((t, i) => (
                      <tr key={i}>
                        <td>₹{t.entry_price.toFixed(2)}</td>
                        <td>₹{t.exit_price.toFixed(2)}</td>
                        <td>{t.qty}</td>
                        <td className={t.net_pnl >= 0 ? "text-good" : "text-bad"}>
                          ₹{t.net_pnl.toFixed(2)}
                        </td>
                        <td className="muted">₹{t.costs.toFixed(2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
