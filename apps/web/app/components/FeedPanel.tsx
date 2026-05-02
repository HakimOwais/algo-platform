"use client";

import type { DecisionRow, FillRow, StreamEvent } from "@/app/lib/types";

interface FeedPanelProps {
  fills: FillRow[];
  decisions: DecisionRow[];
  stream: StreamEvent[];
}

function RegimeBadge({ label }: { label?: string }) {
  if (!label) return null;
  const cls = label === "TRENDING" ? "regime-trending" : "regime-choppy";
  return <span className={`regime-badge ${cls}`}>{label}</span>;
}

function MLBadge({ direction, mlVeto }: { direction?: number; mlVeto?: boolean }) {
  if (mlVeto) return <span className="regime-badge regime-stop">ML VETO</span>;
  if (direction === 1) return <span className="regime-badge regime-trending">ML ▲</span>;
  if (direction === -1) return <span className="regime-badge regime-stop">ML ▼</span>;
  return null;
}

function streamEventColour(event: string): string {
  if (event.includes("fill") || event.includes("filled")) return "var(--good)";
  if (event.includes("reject") || event.includes("veto") || event.includes("breach")) return "var(--danger)";
  if (event.includes("signal") || event.includes("transition")) return "var(--accent)";
  if (event.includes("risk") || event.includes("kill")) return "var(--warn)";
  return "var(--muted)";
}

export function FeedPanel({ fills, decisions, stream }: FeedPanelProps) {
  return (
    <section className="panel">
      <div className="panel-header">
        <h3>Execution Feed</h3>
      </div>
      <div className="feed-grid">

        {/* ── Recent Fills ── */}
        <div>
          <h4>Recent Fills</h4>
          <ul className="compact-list">
            {fills.slice(0, 8).map((fill) => (
              <li key={fill.id} className="fill-row">
                <span><strong>{fill.symbol}</strong></span>
                <span>{fill.quantity} @ ₹{fill.price.toFixed(2)}</span>
                <span className="muted">fee ₹{fill.fee.toFixed(2)}</span>
              </li>
            ))}
            {fills.length === 0 && <li className="muted">No fills yet</li>}
          </ul>
        </div>

        {/* ── Recent Signals ── */}
        <div>
          <h4>Recent Signals</h4>
          <ul className="signal-list">
            {decisions.slice(0, 8).map((d) => {
              const regime = d.payload?.regime?.label;
              const mlDir = d.payload?.ml?.direction;
              const mlVeto = d.payload?.ml_veto;
              const vol = d.payload?.volatility?.annualized;
              return (
                <li key={d.id}>
                  <div className="signal-row-top">
                    <strong>{d.symbol}</strong>
                    <span className={d.signal === "BUY" ? "text-good" : "text-bad"}>{d.signal}</span>
                    <RegimeBadge label={regime} />
                    <MLBadge direction={mlDir} mlVeto={mlVeto} />
                  </div>
                  <div className="signal-row-bottom">
                    <span className="muted">conf {d.confidence.toFixed(4)}</span>
                    {vol !== undefined && (
                      <span className="muted">σ {(vol * 100).toFixed(1)}%</span>
                    )}
                    <span className="muted">{new Date(d.created_at).toLocaleTimeString()}</span>
                  </div>
                </li>
              );
            })}
            {decisions.length === 0 && <li className="muted">No signals yet</li>}
          </ul>
        </div>

        {/* ── Live Stream ── */}
        <div>
          <h4>Live Stream</h4>
          <ul className="compact-list stream-list">
            {stream.slice(0, 10).map((event, index) => (
              <li key={`${event.event}-${index}`}>
                <span style={{ color: streamEventColour(event.event) }}>{event.event}</span>
                <span className="muted">
                  {event.timestamp ? new Date(event.timestamp).toLocaleTimeString() : "--"}
                </span>
              </li>
            ))}
            {stream.length === 0 && <li className="muted">Waiting for events...</li>}
          </ul>
        </div>

      </div>
    </section>
  );
}
