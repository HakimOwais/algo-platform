import type { OrderRow } from "@/app/lib/types";

interface OrdersTableProps {
  rows: OrderRow[];
}

export function OrdersTable({ rows }: OrdersTableProps) {
  return (
    <section className="panel">
      <div className="panel-header">
        <h3>Orders</h3>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>Symbol</th>
              <th>Side</th>
              <th>Qty</th>
              <th>Status</th>
              <th>Strategy</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((order) => (
              <tr key={order.id}>
                <td>{new Date(order.requested_at).toLocaleTimeString()}</td>
                <td>{order.symbol}</td>
                <td className={order.side === "BUY" ? "text-good" : "text-bad"}>{order.side}</td>
                <td>{order.quantity}</td>
                <td>{order.status}</td>
                <td>{order.strategy_name}</td>
              </tr>
            ))}
            {rows.length === 0 ? (
              <tr>
                <td colSpan={6} className="empty-row">
                  No orders yet
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </section>
  );
}

