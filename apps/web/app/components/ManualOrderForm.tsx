interface ManualOrderFormProps {
  symbol: string;
  side: "BUY" | "SELL";
  quantity: number;
  onSymbolChange: (value: string) => void;
  onSideChange: (value: "BUY" | "SELL") => void;
  onQuantityChange: (value: number) => void;
  onSubmit: () => Promise<void>;
}

export function ManualOrderForm({
  symbol,
  side,
  quantity,
  onSymbolChange,
  onSideChange,
  onQuantityChange,
  onSubmit
}: ManualOrderFormProps) {
  return (
    <section className="panel">
      <div className="panel-header">
        <h3>Manual Order</h3>
      </div>
      <div className="form-row">
        <label>
          Symbol
          <input
            suppressHydrationWarning
            value={symbol}
            onChange={(event) => onSymbolChange(event.target.value.toUpperCase())}
          />
        </label>
        <label>
          Side
          <select
            suppressHydrationWarning
            value={side}
            onChange={(event) => onSideChange(event.target.value as "BUY" | "SELL")}
          >
            <option value="BUY">BUY</option>
            <option value="SELL">SELL</option>
          </select>
        </label>
        <label>
          Quantity
          <input
            suppressHydrationWarning
            type="number"
            min={1}
            value={quantity}
            onChange={(event) => onQuantityChange(Number(event.target.value))}
          />
        </label>
      </div>
      <div className="button-row">
        <button suppressHydrationWarning className="btn" onClick={() => onSubmit()}>
          Place Order
        </button>
      </div>
    </section>
  );
}
