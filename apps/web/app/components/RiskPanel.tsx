"use client";

import type { RiskStatus } from "@/app/lib/types";

interface RiskPanelProps {
  risk: RiskStatus | null;
  onToggleKillSwitch: (engaged: boolean) => Promise<void>;
}

function DrawdownBar({ value, label }: { value: number; label: string }) {
  const pct = Math.min(value * 100, 100);
  const colour =
    label === "STOP" ? "var(--danger)" : label === "CAUTION" ? "var(--warn)" : "var(--good)";
  return (
    <div className="dd-wrap">
      <div className="dd-bar-bg">
        <div className="dd-bar-fill" style={{ width: `${pct}%`, background: colour }} />
      </div>
      <span style={{ color: colour }}>{pct.toFixed(1)}%</span>
    </div>
  );
}

export function RiskPanel({ risk, onToggleKillSwitch }: RiskPanelProps) {
  const dd = risk?.drawdown;

  return (
    <section className="panel">
      <div className="panel-header">
        <h3>Risk Engine</h3>
        {dd && (
          <span
            className={`regime-badge ${dd.label === "NORMAL" ? "regime-trending" : dd.label === "CAUTION" ? "regime-caution" : "regime-stop"}`}
          >
            {dd.label}
          </span>
        )}
      </div>

      {risk ? (
        <>
          <div className="risk-grid">
            <div>
              <span>Kill switch</span>
              <strong className={risk.kill_switch ? "text-bad" : "text-good"}>
                {risk.kill_switch ? "ENGAGED" : "DISENGAGED"}
              </strong>
            </div>
            <div>
              <span>Realized PnL</span>
              <strong className={risk.realized_pnl >= 0 ? "text-good" : "text-bad"}>
                ₹{risk.realized_pnl.toFixed(2)}
              </strong>
            </div>
            <div>
              <span>Peak NAV</span>
              <strong>₹{(risk.peak_nav ?? 1_000_000).toLocaleString("en-IN")}</strong>
            </div>
            <div>
              <span>Daily loss limit</span>
              <strong>₹{risk.max_daily_loss_inr.toFixed(0)}</strong>
            </div>
          </div>

          {dd && (
            <div className="dd-section">
              <div className="dd-row">
                <span className="muted">Drawdown from peak</span>
                <span className="muted">
                  Size scalar:{" "}
                  <strong style={{ color: dd.position_scalar === 1 ? "var(--good)" : dd.position_scalar === 0 ? "var(--danger)" : "var(--warn)" }}>
                    {dd.position_scalar === 0 ? "HALTED" : `${(dd.position_scalar * 100).toFixed(0)}%`}
                  </strong>
                </span>
              </div>
              <DrawdownBar value={dd.current} label={dd.label} />
            </div>
          )}

          <div className="button-row">
            <button className="btn danger" onClick={() => onToggleKillSwitch(true)} disabled={risk.kill_switch}>
              Engage Kill Switch
            </button>
            <button className="btn" onClick={() => onToggleKillSwitch(false)} disabled={!risk.kill_switch}>
              Release Kill Switch
            </button>
          </div>

          <ul className="event-list">
            {risk.recent_events.slice(0, 5).map((ev, idx) => (
              <li key={`${ev.created_at}-${idx}`}>
                <span className={ev.severity === "CRITICAL" ? "text-bad" : ev.severity === "WARNING" ? "text-warn" : ""}>
                  {ev.severity}
                </span>
                <p>{ev.message}</p>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p className="muted">Loading risk status...</p>
      )}
    </section>
  );
}
