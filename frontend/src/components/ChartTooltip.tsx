type Item = { dataKey?: string | number; value?: number | string; color?: string; stroke?: string; fill?: string };

/** Value-first tooltip with line keys; every series at the hovered X is listed. */
export function ChartTooltip({ active, payload, label, names, labelFormat, digits = 0 }: {
  active?: boolean; payload?: Item[]; label?: string | number;
  names: Record<string, string>; labelFormat: (l: string | number) => string; digits?: number;
}) {
  if (!active || !payload?.length || label == null) return null;
  return (
    <div className="tooltip">
      <div className="t">{labelFormat(label)}</div>
      {[...payload].reverse().map((p) => {
        const key = String(p.dataKey);
        const color = key === "planned" || key.startsWith("target") ? "var(--muted)" : (p.fill && p.fill !== "none" ? p.fill : p.stroke);
        return (
          <div className="row" key={key}>
            <i style={{ background: color }} />
            <b>{typeof p.value === "number" ? p.value.toFixed(digits) : p.value}</b>
            <span>{names[key] ?? key}</span>
          </div>
        );
      })}
    </div>
  );
}
