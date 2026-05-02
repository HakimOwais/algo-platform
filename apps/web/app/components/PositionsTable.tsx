import type { PositionRow } from "@/app/lib/types";

interface PositionsTableProps {
  rows: PositionRow[];
  prices: Record<string, number>;
}

export function PositionsTable({ rows, prices }: PositionsTableProps) {
  return (
    <section className="panel">
      <div className="panel-header">
        <h3>Positions</h3>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Qty</th>
              <th>Avg</th>
              <th>LTP</th>
              <th>Unrealized</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((position) => {
              const ltp = prices[position.symbol] ?? position.avg_price;
              const unrealized = (ltp - position.avg_price) * position.quantity;
              return (
                <tr key={position.id}>
                  <td>{position.symbol}</td>
                  <td>{position.quantity}</td>
                  <td>{position.avg_price.toFixed(2)}</td>
                  <td>{ltp.toFixed(2)}</td>
                  <td className={unrealized >= 0 ? "text-good" : "text-bad"}>
                    {unrealized.toFixed(2)}
                  </td>
                </tr>
              );
            })}
            {rows.length === 0 ? (
              <tr>
                <td colSpan={5} className="empty-row">
                  No positions yet
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </section>
  );
}

