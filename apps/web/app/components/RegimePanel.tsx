"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/app/lib/api";
import type { MLPredictResponse } from "@/app/lib/types";

interface RegimePanelProps {
  symbols: string[];
}

function DirectionArrow({ direction }: { direction: -1 | 0 | 1 }) {
  if (direction === 1) return <span className="text-good">▲ BULL</span>;
  if (direction === -1) return <span className="text-bad">▼ BEAR</span>;
  return <span className="muted">— NEUTRAL</span>;
}

function ProbBar({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  const colour = pct >= 55 ? "var(--good)" : pct <= 45 ? "var(--danger)" : "var(--warn)";
  return (
    <div className="prob-bar-bg">
      <div className="prob-bar-fill" style={{ width: `${pct}%`, background: colour }} />
      <span className="prob-bar-label">{pct}%</span>
    </div>
  );
}

export function RegimePanel({ symbols }: RegimePanelProps) {
  const [signals, setSignals] = useState<Record<string, MLPredictResponse>>({});
  const [loading, setLoading] = useState(false);
  const [modelTrained, setModelTrained] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const fetchSignals = useCallback(async () => {
    setLoading(true);
    try {
      const results = await Promise.all(
        symbols.map((sym) =>
          api.mlPredict(sym).catch(() => null)
        )
      );
      const map: Record<string, MLPredictResponse> = {};
      results.forEach((r, i) => {
        if (r) {
          map[symbols[i]] = r;
          if (r.model_trained) setModelTrained(true);
        }
      });
      setSignals(map);
      setLastUpdated(new Date());
    } finally {
      setLoading(false);
    }
  }, [symbols]);

  useEffect(() => {
    void fetchSignals();
    const id = setInterval(() => void fetchSignals(), 30_000);
    return () => clearInterval(id);
  }, [fetchSignals]);

  return (
    <section className="panel">
      <div className="panel-header">
        <h3>ML Signals</h3>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {lastUpdated && (
            <span className="muted" style={{ fontSize: "0.75rem" }}>
              {lastUpdated.toLocaleTimeString()}
            </span>
          )}
          <button suppressHydrationWarning className="btn" onClick={() => void fetchSignals()} disabled={loading} style={{ padding: "4px 10px", fontSize: "0.78rem" }}>
            {loading ? "…" : "Refresh"}
          </button>
        </div>
      </div>

      {!modelTrained && (
        <p className="muted" style={{ fontSize: "0.82rem", marginBottom: 8 }}>
          Model not yet trained — train it via the ML Training panel below.
        </p>
      )}

      <table className="regime-table">
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Direction</th>
            <th>Bull probability</th>
            <th>Confidence</th>
          </tr>
        </thead>
        <tbody>
          {symbols.map((sym) => {
            const s = signals[sym];
            return (
              <tr key={sym}>
                <td><strong>{sym}</strong></td>
                <td>{s ? <DirectionArrow direction={s.direction} /> : <span className="muted">—</span>}</td>
                <td style={{ minWidth: 120 }}>
                  {s ? <ProbBar value={s.bull_prob} /> : <span className="muted">—</span>}
                </td>
                <td className="muted">{s ? `${(s.confidence * 100).toFixed(1)}%` : "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}
