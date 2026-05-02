"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { BacktestPanel } from "@/app/components/BacktestPanel";
import { FeedPanel } from "@/app/components/FeedPanel";
import { ManualOrderForm } from "@/app/components/ManualOrderForm";
import { MLPanel } from "@/app/components/MLPanel";
import { OrdersTable } from "@/app/components/OrdersTable";
import { PositionsTable } from "@/app/components/PositionsTable";
import { RegimePanel } from "@/app/components/RegimePanel";
import { RiskPanel } from "@/app/components/RiskPanel";
import { StatCard } from "@/app/components/StatCard";
import { StrategyPanel } from "@/app/components/StrategyPanel";
import { api } from "@/app/lib/api";
import type {
  DashboardSummary,
  DecisionRow,
  FillRow,
  OrderRow,
  PositionRow,
  RiskStatus,
  StrategyRow,
  StreamEvent
} from "@/app/lib/types";

const currency = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 2
});

const DEFAULT_SYMBOLS = ["RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"];

export default function HomePage() {
  const [summary, setSummary] = useState<DashboardSummary | null>(null);
  const [orders, setOrders] = useState<OrderRow[]>([]);
  const [fills, setFills] = useState<FillRow[]>([]);
  const [positions, setPositions] = useState<PositionRow[]>([]);
  const [strategies, setStrategies] = useState<StrategyRow[]>([]);
  const [decisions, setDecisions] = useState<DecisionRow[]>([]);
  const [risk, setRisk] = useState<RiskStatus | null>(null);
  const [stream, setStream] = useState<StreamEvent[]>([]);
  const [wsConnected, setWsConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [orderSymbol, setOrderSymbol] = useState("RELIANCE");
  const [orderSide, setOrderSide] = useState<"BUY" | "SELL">("BUY");
  const [orderQty, setOrderQty] = useState(1);

  const activeSymbols = useMemo(() => {
    if (summary?.latest_prices && Object.keys(summary.latest_prices).length > 0) {
      return Object.keys(summary.latest_prices);
    }
    return DEFAULT_SYMBOLS;
  }, [summary]);

  const refresh = useCallback(async () => {
    try {
      const [nextSummary, nextOrders, nextFills, nextPositions, nextStrategies, nextDecisions, nextRisk] =
        await Promise.all([
          api.summary(),
          api.orders(),
          api.fills(),
          api.positions(),
          api.strategies(),
          api.decisions(),
          api.riskStatus()
        ]);
      setSummary(nextSummary);
      setOrders(nextOrders);
      setFills(nextFills);
      setPositions(nextPositions);
      setStrategies(nextStrategies);
      setDecisions(nextDecisions);
      setRisk(nextRisk);
      setError(null);
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "Unknown API error");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const poller = setInterval(() => void refresh(), 5000);
    return () => clearInterval(poller);
  }, [refresh]);

  useEffect(() => {
    const ws = new WebSocket(api.wsUrl());
    ws.onopen = () => setWsConnected(true);
    ws.onclose = () => setWsConnected(false);
    ws.onerror = () => setWsConnected(false);
    ws.onmessage = (event) => {
      try {
        const parsed = JSON.parse(event.data) as StreamEvent;
        setStream((cur) => [parsed, ...cur].slice(0, 40));
        if (
          ["order.filled", "order.updated", "order.rejected", "risk.kill_switch"].includes(
            parsed.event
          )
        ) {
          void refresh();
        }
      } catch {
        setStream((cur) => [{ event: "stream.parse_error", data: {} }, ...cur].slice(0, 40));
      }
    };
    const keepAlive = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) ws.send("ping");
    }, 20_000);
    return () => {
      clearInterval(keepAlive);
      ws.close();
    };
  }, [refresh]);

  const onManualOrderSubmit = useCallback(async () => {
    if (!orderSymbol || orderQty < 1) return;
    await api.placeOrder({ strategy_name: "manual", symbol: orderSymbol, side: orderSide, quantity: orderQty });
    await refresh();
  }, [orderQty, orderSide, orderSymbol, refresh]);

  const onToggleKillSwitch = useCallback(
    async (engaged: boolean) => {
      await api.toggleKillSwitch(engaged);
      await refresh();
    },
    [refresh]
  );

  const onPause = useCallback(async (name: string) => {
    await api.pauseStrategy(name);
    await refresh();
  }, [refresh]);

  const onResume = useCallback(async (name: string) => {
    await api.resumeStrategy(name);
    await refresh();
  }, [refresh]);

  const navTrend = useMemo(() => {
    if (!summary) return "neutral";
    return summary.realized_pnl >= 0 ? "up" : "down";
  }, [summary]);

  return (
    <main>
      {/* ── Header ── */}
      <div className="title-wrap">
        <div>
          <h1>Algo Trading Control Center</h1>
          <p className="subtitle">regime → signal → risk → orders → fills → pnl</p>
        </div>
        <span className={`status-pill ${wsConnected ? "ready" : "down"}`}>
          {wsConnected ? "WebSocket Connected" : "WebSocket Disconnected"}
        </span>
      </div>

      {error && <p className="panel text-bad">API Error: {error}</p>}
      {loading && <p className="panel muted">Loading platform state...</p>}

      {/* ── Stat cards ── */}
      <section className="grid-stats">
        <StatCard
          label="Estimated NAV"
          value={summary ? currency.format(summary.nav_estimate) : "--"}
          trend={navTrend}
        />
        <StatCard
          label="Realized PnL"
          value={summary ? currency.format(summary.realized_pnl) : "--"}
          trend={summary && summary.realized_pnl < 0 ? "down" : "up"}
        />
        <StatCard
          label="Drawdown"
          value={risk?.drawdown ? `${(risk.drawdown.current * 100).toFixed(2)}%` : "--"}
          trend={
            !risk?.drawdown ? "neutral"
            : risk.drawdown.label === "STOP" ? "down"
            : risk.drawdown.label === "CAUTION" ? "neutral"
            : "up"
          }
        />
        <StatCard label="Open Positions" value={summary ? String(summary.open_positions) : "--"} />
        <StatCard label="Open Orders" value={summary ? String(summary.open_orders) : "--"} />
      </section>

      {/* ── Main layout ── */}
      <section className="grid-main">

        {/* Left column */}
        <div>
          <OrdersTable rows={orders} />
          <PositionsTable rows={positions} prices={summary?.latest_prices ?? {}} />
          <FeedPanel fills={fills} decisions={decisions} stream={stream} />
          <RegimePanel symbols={activeSymbols} />
        </div>

        {/* Right column */}
        <div>
          <ManualOrderForm
            symbol={orderSymbol}
            side={orderSide}
            quantity={orderQty}
            onSymbolChange={setOrderSymbol}
            onSideChange={setOrderSide}
            onQuantityChange={setOrderQty}
            onSubmit={onManualOrderSubmit}
          />
          <StrategyPanel strategies={strategies} onPause={onPause} onResume={onResume} />
          <RiskPanel risk={risk} onToggleKillSwitch={onToggleKillSwitch} />
          <MLPanel />
          <BacktestPanel symbols={activeSymbols} />
        </div>

      </section>
    </main>
  );
}
