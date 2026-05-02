"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/app/lib/api";
import type { MLModelStatus, MLTrainResponse } from "@/app/lib/types";

export function MLPanel() {
  const [status, setStatus] = useState<MLModelStatus | null>(null);
  const [trainResult, setTrainResult] = useState<MLTrainResponse | null>(null);
  const [training, setTraining] = useState(false);
  const [forwardBars, setForwardBars] = useState(5);
  const [threshold, setThreshold] = useState(0.55);
  const [error, setError] = useState<string | null>(null);

  const fetchStatus = useCallback(async () => {
    try {
      const s = await api.mlStatus();
      setStatus(s);
    } catch {
      // backend may not be up yet
    }
  }, []);

  useEffect(() => {
    void fetchStatus();
  }, [fetchStatus]);

  const onTrain = useCallback(async () => {
    setTraining(true);
    setError(null);
    setTrainResult(null);
    try {
      const result = await api.mlTrain({ forward_bars: forwardBars, threshold });
      setTrainResult(result);
      await fetchStatus();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Training failed");
    } finally {
      setTraining(false);
    }
  }, [forwardBars, threshold, fetchStatus]);

  const onDelete = useCallback(async () => {
    await api.mlDeleteModel();
    setTrainResult(null);
    await fetchStatus();
  }, [fetchStatus]);

  const aucColour = (auc: number) =>
    auc >= 0.56 ? "var(--good)" : auc >= 0.52 ? "var(--warn)" : "var(--danger)";

  return (
    <section className="panel">
      <div className="panel-header">
        <h3>ML Training</h3>
        {status && (
          <span className={`regime-badge ${status.is_trained ? "regime-trending" : "regime-stop"}`}>
            {status.is_trained ? "TRAINED" : "UNTRAINED"}
          </span>
        )}
      </div>

      <div className="ml-status-row">
        {status ? (
          <>
            <div className="ml-stat">
              <span className="muted">Features</span>
              <strong>{status.n_features || "—"}</strong>
            </div>
            <div className="ml-stat">
              <span className="muted">Threshold</span>
              <strong>{(status.threshold * 100).toFixed(0)}%</strong>
            </div>
          </>
        ) : (
          <span className="muted">Loading...</span>
        )}
      </div>

      <div className="ml-train-controls">
        <label>
          Forward bars (label horizon)
          <input
            suppressHydrationWarning
            type="number"
            value={forwardBars}
            min={1}
            max={20}
            onChange={(e) => setForwardBars(Number(e.target.value))}
          />
        </label>
        <label>
          Signal threshold
          <input
            suppressHydrationWarning
            type="number"
            value={threshold}
            min={0.5}
            max={0.95}
            step={0.01}
            onChange={(e) => setThreshold(Number(e.target.value))}
          />
        </label>
      </div>

      <div className="button-row">
        <button suppressHydrationWarning className="btn" onClick={onTrain} disabled={training}>
          {training ? "Training…" : "Train Model"}
        </button>
        {status?.is_trained && (
          <button suppressHydrationWarning className="btn warning" onClick={onDelete}>
            Delete Model
          </button>
        )}
      </div>

      {error && <p className="text-bad" style={{ fontSize: "0.82rem", marginTop: 8 }}>{error}</p>}

      {trainResult && (
        <div className="train-result">
          {trainResult.status === "error" ? (
            <p className="text-bad" style={{ fontSize: "0.82rem" }}>{trainResult.message}</p>
          ) : (
            <>
              <div className="train-metrics">
                <div>
                  <span className="muted">Samples</span>
                  <strong>{trainResult.n_samples.toLocaleString()}</strong>
                </div>
                <div>
                  <span className="muted">CV AUC</span>
                  <strong style={{ color: aucColour(trainResult.mean_cv_auc) }}>
                    {trainResult.mean_cv_auc.toFixed(4)}
                  </strong>
                </div>
                <div>
                  <span className="muted">Features</span>
                  <strong>{trainResult.n_features}</strong>
                </div>
              </div>
              <p className="muted" style={{ fontSize: "0.78rem", marginTop: 6 }}>{trainResult.message}</p>
              {Object.keys(trainResult.top_features).length > 0 && (
                <div className="feature-importance">
                  <p className="muted" style={{ fontSize: "0.78rem", marginBottom: 4 }}>Top features</p>
                  {Object.entries(trainResult.top_features)
                    .sort(([, a], [, b]) => b - a)
                    .slice(0, 8)
                    .map(([name, imp]) => (
                      <div key={name} className="feat-row">
                        <span>{name}</span>
                        <div className="feat-bar-bg">
                          <div
                            className="feat-bar-fill"
                            style={{
                              width: `${Math.min(imp / Math.max(...Object.values(trainResult.top_features)) * 100, 100)}%`
                            }}
                          />
                        </div>
                        <span className="muted">{imp.toFixed(0)}</span>
                      </div>
                    ))}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </section>
  );
}
