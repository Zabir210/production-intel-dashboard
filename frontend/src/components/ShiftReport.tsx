import { useEffect, useMemo, useState } from "react";
import { api, ApiError, fmt, type Meta, type ShiftDetail } from "../api";
import Tile from "./Tile";

export default function ShiftReport({ meta }: { meta: Meta }) {
  const [date, setDate] = useState(meta.latest_date);
  const [shift, setShift] = useState("A");
  const [lineId, setLineId] = useState("");
  const [detail, setDetail] = useState<ShiftDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const query = useMemo(() => {
    const q = new URLSearchParams({ date, shift });
    if (lineId) q.set("line_id", lineId);
    return q;
  }, [date, shift, lineId]);

  useEffect(() => {
    setBusy(true);
    setError(null);
    api.shiftReport(query)
      .then(setDetail)
      .catch((e) => { setDetail(null); setError(e instanceof ApiError ? e.message : String(e)); })
      .finally(() => setBusy(false));
  }, [query]);

  const k = detail?.kpis;
  return (
    <div className="card">
      <div className="card-head"><span className="tag">Project 3</span><h3>Shift report</h3></div>
      <p className="sub">
        Pick a shift and download a PDF with the KPIs, anomalies, downtime, nonconformances and follow-up actions
        for the hand-off. Actions come from fixed rules, so the same shift always produces the same report.
      </p>
      <div className="row-controls">
        <label className="field">Date
          <input type="date" value={date} max={meta.latest_date} onChange={(e) => e.target.value && setDate(e.target.value)} />
        </label>
        <label className="field">Shift
          <select value={shift} onChange={(e) => setShift(e.target.value)}>
            {Object.entries(meta.shifts).map(([s, start]) => <option key={s} value={s}>{s} (starts {start})</option>)}
          </select>
        </label>
        <label className="field">Scope
          <select value={lineId} onChange={(e) => setLineId(e.target.value)}>
            <option value="">All lines</option>
            {meta.lines.map((l) => <option key={l.line_id} value={l.line_id}>{l.name}</option>)}
          </select>
        </label>
        <a className={`btn primary ${detail ? "" : "disabled"}`} href={detail ? api.shiftReportPdfUrl(query) : undefined}
           aria-disabled={!detail} download>
          Download PDF
        </a>
      </div>

      {error && <div className="notice error">{error}</div>}
      {detail && k && (
        <div className={busy ? "loading" : ""} style={{ marginTop: 16 }}>
          <div className="tiles compact">
            <Tile label="Units vs plan" value={`${k.units} / ${k.planned_units}`} note={`${fmt(k.attainment_pct, 1)}% attainment`}
                  tone={k.attainment_pct != null && k.attainment_pct < 90 ? "bad" : undefined} />
            <Tile label="Earned hours" value={fmt(k.earned_hours, 1)} note={`${fmt(k.realization_pct, 1)}% realization`} />
            <Tile label="First-pass yield" value={`${fmt(k.first_pass_yield_pct, 1)}%`} note={`${k.nc_count} NCs`} />
            <Tile label="Downtime" value={`${k.downtime_min} min`} note={`${detail.downtime.length} events`} />
            <Tile label="Anomalies" value={String(k.anomalies)} note="flagged station-shifts"
                  tone={k.anomalies ? "bad" : undefined} />
          </div>
          <div className="label-row"><span>Actions in the report</span></div>
          <ol className="actions-list">{detail.actions.map((a, i) => <li key={i}>{a}</li>)}</ol>
        </div>
      )}
    </div>
  );
}
