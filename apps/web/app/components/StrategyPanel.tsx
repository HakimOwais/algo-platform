import type { StrategyRow } from "@/app/lib/types";

interface StrategyPanelProps {
  strategies: StrategyRow[];
  onPause: (name: string) => Promise<void>;
  onResume: (name: string) => Promise<void>;
}

export function StrategyPanel({ strategies, onPause, onResume }: StrategyPanelProps) {
  return (
    <section className="panel">
      <div className="panel-header">
        <h3>Strategies</h3>
      </div>
      <ul className="strategy-list">
        {strategies.map((strategy) => (
          <li key={strategy.id}>
            <div>
              <strong>{strategy.name}</strong>
              <span>
                v{strategy.version} | {strategy.mode}
              </span>
            </div>
            <div className="button-row">
              <button
                className="btn"
                onClick={() => onResume(strategy.name)}
                disabled={strategy.is_active}
              >
                Resume
              </button>
              <button
                className="btn warning"
                onClick={() => onPause(strategy.name)}
                disabled={!strategy.is_active}
              >
                Pause
              </button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

