interface StatCardProps {
  label: string;
  value: string;
  trend?: "up" | "down" | "neutral";
}

export function StatCard({ label, value, trend = "neutral" }: StatCardProps) {
  return (
    <article className="panel stat-card">
      <p className="stat-label">{label}</p>
      <p
        className={`stat-value ${
          trend === "up" ? "text-good" : trend === "down" ? "text-bad" : "text-plain"
        }`}
      >
        {value}
      </p>
    </article>
  );
}

