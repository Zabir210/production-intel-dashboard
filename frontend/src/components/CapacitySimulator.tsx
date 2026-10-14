import { useEffect, useRef, useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { api, fmt, type Baseline, type Line as LineT, type SimResult } from "../api";
import { ChartTooltip } from "./ChartTooltip";
import Tile from "./Tile";

type Inputs = { headcount: number; downtime_min: number; cycle_time_min: number; target_units: number };

export default function CapacitySimulator({ lines }: { lines: LineT[] }) {
  const [lineId, setLineId] = useState(lines[0]?.line_id ?? 1);
  const [base, setBase] = useState<Baseline | null>(null);
  const [inp, setInp] = useState<Inputs | null>(null);
  const [res, setRes] = useState<SimResult | null>(null);
  const [metric, setMetric] = useState<"units" | "earned_hours">("units");
  const [busy, setBusy] = useState(false);
  const reqId = useRef(0);

  const fromBaseline = (b: Baseline): Inputs => ({
    headcount: Math.round(b.headcount), downtime_min: Math.round(b.downtime_min),
    cycle_time_min: b.cycle_time_min, target_units: Math.round(b.planned_units),
  });

  useEffect(() => {
    api.baseline(lineId).then((b) => { setBase(b); setInp(fromBaseline(b)); });
  }, [lineId]);

  useEffect(() => {
    if (!inp) return;
    const id = ++reqId.current;
    setBusy(true);
    const t = setTimeout(() => {
      api.simulate({ line_id: lineId, ...inp })
        .then((r) => { if (id === reqId.current) setRes(r); })
        .finally(() => { if (id === reqId.current) setBusy(false); });
    }, 120);
    return () => clearTimeout(t);
  }, [inp, lineId]);

  const set = (k: keyof Inputs) => (v: number) => setInp((p) => (p ? { ...p, [k]: v } : p));
  const unitsMode = metric === "units";
  const gapTone = res && res.gap_units >= 0 ? "good" : "bad";

  return (
    <div className="card">
      <div className="card-head"><span className="tag">Project 2</span><h3>What-if capacity simulator</h3></div>
      <p className="sub">
        Move headcount, downtime and cycle time to see projected output for one shift against the target pacing
        line. The baseline is the line's last {base?.window.days ?? 14} days, and the model is calibrated so baseline
        inputs reproduce its actual average output.
      </p>

      <div className="sim">
        <div>
          <label className="field" style={{ marginBottom: 18 }}>
            Line
            <select value={lineId} onChange={(e) => setLineId(Number(e.target.value))}>
              {lines.map((l) => <option key={l.line_id} value={l.line_id}>{l.name}</option>)}
            </select>
          </label>
          {base && inp && (
            <>
              <Slider label="Headcount" unit="operators" value={inp.headcount} min={1} max={Math.max(12, Math.ceil(base.headcount * 2))}
                      step={1} base={`baseline ${fmt(base.headcount, 1)}`} onChange={set("headcount")} />
              <Slider label="Downtime" unit="min / shift" value={inp.downtime_min} min={0} max={240} step={5}
                      base={`baseline ${fmt(base.downtime_min)} min`} onChange={set("downtime_min")} />
              <Slider label="Cycle time" unit="min / station" value={inp.cycle_time_min}
                      min={Math.round(base.std_cycle_min * 0.5 * 10) / 10} max={Math.round(base.std_cycle_min * 2 * 10) / 10}
                      step={0.1} digits={1} base={`actual ${fmt(base.cycle_time_min, 1)} · standard ${fmt(base.std_cycle_min, 1)}`}
                      onChange={set("cycle_time_min")} />
              <Slider label="Shift target" unit="units" value={inp.target_units} min={1} max={Math.ceil(base.planned_units * 2)}
                      step={1} base={`plan ${fmt(base.planned_units, 1)}`} onChange={set("target_units")} />
              <button className="btn" onClick={() => setInp(fromBaseline(base))}>Reset to baseline</button>
            </>
          )}
        </div>

        <div className={busy ? "loading" : ""}>
          {res && (
            <div className="tiles compact">
              <Tile label="Projected units" value={fmt(res.projected_units, 1)} note={`target ${fmt(res.target_units)}`} />
              <Tile label="Gap to target" value={`${res.gap_units >= 0 ? "+" : ""}${fmt(res.gap_units, 1)}`}
                    note={`${fmt(res.attainment_pct, 1)}% attainment`} tone={gapTone} />
              <Tile label="Earned hours" value={fmt(res.earned_hours, 1)} note={`target ${fmt(res.target_earned_hours, 1)}`} />
              <Tile label="Realization" value={`${fmt(res.realization_pct, 1)}%`} note={`of ${fmt(res.labor_hours)} labor h`} />
              <Tile label="Crew to hit target" value={fmt(res.headcount_to_hit_target, 1)} note="at these settings" />
            </div>
          )}
          <div className="row-controls" style={{ margin: "16px 0 8px", justifyContent: "space-between" }}>
            <div className="legend" style={{ margin: 0 }}>
              <span><i className="line" style={{ background: "var(--series-1)" }} />Projected (cumulative)</span>
              <span><i className="dash" />Target pacing</span>
            </div>
            <div style={{ display: "flex", gap: 4 }}>
              <button className="chip" aria-pressed={unitsMode} onClick={() => setMetric("units")}
                      style={unitsMode ? { borderColor: "var(--accent)", color: "var(--ink)" } : undefined}>Units</button>
              <button className="chip" aria-pressed={!unitsMode} onClick={() => setMetric("earned_hours")}
                      style={!unitsMode ? { borderColor: "var(--accent)", color: "var(--ink)" } : undefined}>Earned hours</button>
            </div>
          </div>
          <div className="chart" style={{ height: 260 }}>
            <ResponsiveContainer>
              <LineChart data={res?.series ?? []} margin={{ top: 8, right: 12, left: -12, bottom: 0 }}>
                <CartesianGrid vertical={false} stroke="var(--grid)" />
                <XAxis dataKey="hour" tickFormatter={(h: number) => `h${h}`} tick={{ fill: "var(--muted)", fontSize: 11 }}
                       axisLine={{ stroke: "var(--axis)" }} tickLine={false} />
                <YAxis tick={{ fill: "var(--muted)", fontSize: 11 }} axisLine={false} tickLine={false} />
                <Tooltip cursor={{ stroke: "var(--axis)" }} content={
                  <ChartTooltip digits={1} labelFormat={(h) => `End of hour ${h}`} names={{
                    projected_units: "Projected units", target_units: "Target units",
                    projected_earned_hours: "Projected earned h", target_earned_hours: "Target earned h" }} />} />
                <Line dataKey={unitsMode ? "target_units" : "target_earned_hours"} stroke="var(--muted)" strokeWidth={2}
                      strokeDasharray="5 4" dot={false} isAnimationActive={false} />
                <Line dataKey={unitsMode ? "projected_units" : "projected_earned_hours"} stroke="var(--series-1)"
                      strokeWidth={2} dot={{ r: 3, strokeWidth: 0, fill: "var(--series-1)" }} activeDot={{ r: 5 }}
                      isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <p className="muted" style={{ fontSize: 12, margin: "8px 0 0" }}>
            Model: units/min = headcount × efficiency ÷ (stations × cycle time); downtime is spread across the shift and
            the 30-minute break falls in hour 5. Efficiency {base ? fmt(base.efficiency * 100, 0) : "…"}% is calibrated from history.
          </p>
        </div>
      </div>
    </div>
  );
}

function Slider({ label, unit, value, min, max, step, base, digits = 0, onChange }: {
  label: string; unit: string; value: number; min: number; max: number; step: number; base: string;
  digits?: number; onChange: (v: number) => void;
}) {
  return (
    <div className="slider">
      <div className="top"><span>{label}</span><b>{fmt(value, digits)} <span className="muted">{unit}</span></b></div>
      <input type="range" min={min} max={max} step={step} value={value} aria-label={label}
             onChange={(e) => onChange(Number(e.target.value))} />
      <div className="base">{base}</div>
    </div>
  );
}
