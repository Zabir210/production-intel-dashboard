import { useEffect, useState } from "react";
import { Bar, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, fmt, type Anomaly, type Kpis, type Line as LineT, type ThroughputDay } from "../api";
import { ChartTooltip } from "./ChartTooltip";
import Tile from "./Tile";

const RANGES = [7, 14, 30];
export const seriesColor = (lineId: number) => `var(--series-${lineId})`;

export default function Overview({ lines }: { lines: LineT[] }) {
  const [days, setDays] = useState(14);
  const [kpis, setKpis] = useState<Kpis | null>(null);
  const [tp, setTp] = useState<ThroughputDay[]>([]);
  const [anoms, setAnoms] = useState<Anomaly[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    Promise.all([api.kpis(days), api.throughput(days)])
      .then(([k, t]) => { setKpis(k); setTp(t); })
      .finally(() => setLoading(false));
  }, [days]);
  useEffect(() => { api.anomalies(12).then(setAnoms); }, []);

  const shortName = (name: string) => name.replace(/^Line (\d) - /, "L$1 ");

  return (
    <>
      <div className="section-head">
        <h2>Overview</h2>
        <p>Finished units by line against plan, plus station-shifts the Isolation Forest flagged as unusual.</p>
      </div>
      <div className="row-controls" style={{ marginBottom: 12 }}>
        {RANGES.map((d) => (
          <button key={d} className={`btn ${d === days ? "primary" : ""}`} onClick={() => setDays(d)}>
            Last {d} days
          </button>
        ))}
      </div>

      <div className={`tiles ${loading ? "loading" : ""}`}>
        <Tile label="Finished units" value={fmt(kpis?.units)} note={`plan ${fmt(kpis?.planned_units)}`} />
        <Tile label="Plan attainment" value={`${fmt(kpis?.attainment_pct, 1)}%`}
              tone={kpis?.attainment_pct != null ? (kpis.attainment_pct >= 95 ? "good" : "bad") : undefined} />
        <Tile label="Earned hours" value={fmt(kpis?.earned_hours)}
              note={`${fmt(kpis?.realization_pct, 1)}% of ${fmt(kpis?.labor_hours)} labor h`} />
        <Tile label="First-pass yield" value={`${fmt(kpis?.first_pass_yield_pct, 1)}%`}
              note={`${fmt(kpis?.nc_count)} nonconformances`} />
        <Tile label="Downtime" value={`${fmt(kpis?.downtime_min)} min`} note={`${fmt(kpis?.anomalies)} anomalies flagged`} />
      </div>

      <div className="grid-2">
        <div className={`card ${loading ? "loading" : ""}`}>
          <h3>Daily finished units by line</h3>
          <p className="sub">Stacked by line; the dashed line is the plant plan for the day.</p>
          <div className="legend">
            {lines.map((l) => (
              <span key={l.line_id}><i style={{ background: seriesColor(l.line_id) }} />{shortName(l.name)}</span>
            ))}
            <span><i className="dash" />Plan</span>
          </div>
          <div className="chart">
            <ResponsiveContainer>
              <ComposedChart data={tp} margin={{ top: 8, right: 8, left: -12, bottom: 0 }}>
                <CartesianGrid vertical={false} stroke="var(--grid)" />
                <XAxis dataKey="date" tickFormatter={(d: string) => d.slice(5)} tick={{ fill: "var(--muted)", fontSize: 11 }}
                       axisLine={{ stroke: "var(--axis)" }} tickLine={false} minTickGap={16} />
                <YAxis tick={{ fill: "var(--muted)", fontSize: 11 }} axisLine={false} tickLine={false} />
                <Tooltip cursor={{ fill: "var(--surface-2)" }}
                         content={<ChartTooltip labelFormat={(l) => String(l)} names={Object.fromEntries(
                           lines.map((l) => [`line_${l.line_id}`, shortName(l.name)]).concat([["planned", "Plan"]]))} />} />
                {lines.map((l, i) => (
                  <Bar key={l.line_id} dataKey={`line_${l.line_id}`} stackId="u" fill={seriesColor(l.line_id)}
                       stroke="var(--surface)" strokeWidth={1} isAnimationActive={false}
                       radius={i === lines.length - 1 ? [4, 4, 0, 0] : 0} />
                ))}
                <Line dataKey="planned" stroke="var(--muted)" strokeDasharray="5 4" strokeWidth={2} dot={false}
                      isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        </div>

        <div className="card">
          <h3>Recent anomalies</h3>
          <p className="sub">Station-shifts scored by Isolation Forest on cycle time, queue, defects, downtime and output.</p>
          <div className="table-wrap" style={{ maxHeight: 330 }}>
            <table>
              <thead><tr><th>Shift</th><th>Where</th><th>What stood out</th></tr></thead>
              <tbody>
                {anoms.map((a) => (
                  <tr key={a.anomaly_id}>
                    <td style={{ whiteSpace: "nowrap" }}>{a.shift_date.slice(5)} {a.shift}</td>
                    <td>{shortName(a.line)}<div className="muted">{a.station}</div></td>
                    <td>{a.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </>
  );
}
