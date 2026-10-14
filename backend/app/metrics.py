"""Read-side queries for the overview dashboard and the shift report."""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import Engine, text

# Finished units = units completing the last station of their line.
FINISHED_CTE = """
finished AS (
    SELECT m.line_id, m.shift_date, m.shift, count(*) AS units
    FROM part_movements m
    JOIN stations s ON s.station_id = m.station_id
    WHERE s.seq = (SELECT max(seq) FROM stations s2 WHERE s2.line_id = m.line_id)
    GROUP BY 1, 2, 3
)
"""


def latest_date(engine: Engine) -> date:
    with engine.connect() as conn:
        return conn.execute(text("SELECT max(shift_date) FROM part_movements")).scalar_one()


def _rows(engine: Engine, sql: str, **params) -> list[dict]:
    with engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(text(sql), params)]


def _num(v):
    return float(v) if v is not None else 0.0


def kpis(engine: Engine, start: date, end: date, shift: str | None = None,
         line_id: int | None = None) -> dict:
    """Plant (or line) KPIs over [start, end], optionally one shift."""
    where = "shift_date BETWEEN :start AND :end" \
            + (" AND shift = :shift" if shift else "") \
            + (" AND line_id = :line_id" if line_id else "")
    p = dict(start=start, end=end, shift=shift, line_id=line_id)
    r = _rows(engine, f"""
        WITH {FINISHED_CTE},
        f AS (SELECT * FROM finished WHERE {where}),
        st AS (SELECT * FROM shift_staffing WHERE {where})
        SELECT
            (SELECT coalesce(sum(units), 0) FROM f) AS units,
            (SELECT coalesce(sum(planned_units), 0) FROM st) AS planned_units,
            (SELECT coalesce(sum(f.units * p.std_hours), 0)
               FROM f JOIN lines l USING (line_id) JOIN parts p USING (part_number)) AS earned_hours,
            (SELECT coalesce(sum(headcount) * 8, 0) FROM st) AS labor_hours,
            (SELECT count(*) FROM nonconformances WHERE {where}) AS nc_count,
            (SELECT count(DISTINCT serial_number) FROM nonconformances WHERE {where}) AS nc_units,
            (SELECT coalesce(sum(minutes), 0) FROM downtime_events WHERE {where}) AS downtime_min,
            (SELECT count(*) FROM anomalies WHERE {where}) AS anomalies
    """, **p)[0]
    units = int(r["units"])
    planned = int(r["planned_units"])
    earned = _num(r["earned_hours"])
    labor = _num(r["labor_hours"])
    return {
        "units": units,
        "planned_units": planned,
        "attainment_pct": round(100 * units / planned, 1) if planned else None,
        "earned_hours": round(earned, 1),
        "labor_hours": round(labor, 1),
        "realization_pct": round(100 * earned / labor, 1) if labor else None,
        "nc_count": int(r["nc_count"]),
        "first_pass_yield_pct": round(100 * (1 - r["nc_units"] / units), 1) if units else None,
        "downtime_min": round(_num(r["downtime_min"])),
        "anomalies": int(r["anomalies"]),
    }


def daily_throughput(engine: Engine, days: int) -> list[dict]:
    end = latest_date(engine)
    start = end - timedelta(days=days - 1)
    rows = _rows(engine, f"""
        WITH {FINISHED_CTE},
        plan AS (SELECT shift_date, sum(planned_units) AS planned FROM shift_staffing
                 WHERE shift_date BETWEEN :start AND :end GROUP BY 1)
        SELECT f.shift_date, f.line_id, sum(f.units) AS units, max(plan.planned) AS planned
        FROM finished f JOIN plan USING (shift_date)
        WHERE f.shift_date BETWEEN :start AND :end
        GROUP BY 1, 2 ORDER BY 1, 2
    """, start=start, end=end)
    by_day: dict[str, dict] = {}
    for r in rows:
        d = by_day.setdefault(r["shift_date"].isoformat(), {"date": r["shift_date"].isoformat(),
                                                            "planned": int(r["planned"])})
        d[f"line_{r['line_id']}"] = int(r["units"])
    return list(by_day.values())


def anomalies(engine: Engine, limit: int = 25, start: date | None = None, end: date | None = None,
              shift: str | None = None, line_id: int | None = None) -> list[dict]:
    filters = ["TRUE"]
    if start:
        filters.append("a.shift_date BETWEEN :start AND :end")
    if shift:
        filters.append("a.shift = :shift")
    if line_id:
        filters.append("a.line_id = :line_id")
    rows = _rows(engine, f"""
        SELECT a.anomaly_id, a.shift_date, a.shift, a.line_id, l.name AS line, s.name AS station,
               a.score, a.units, a.cycle_ratio, a.avg_queue_min, a.nc_count, a.downtime_min, a.reason
        FROM anomalies a JOIN lines l USING (line_id) JOIN stations s USING (station_id)
        WHERE {' AND '.join(filters)}
        ORDER BY a.shift_date DESC, a.score LIMIT :limit
    """, limit=limit, start=start, end=end, shift=shift, line_id=line_id)
    for r in rows:
        r["shift_date"] = r["shift_date"].isoformat()
        r["score"] = round(r["score"], 3)
        r["cycle_ratio"] = round(r["cycle_ratio"], 2)
        r["avg_queue_min"] = round(r["avg_queue_min"], 1)
    return rows


def lines(engine: Engine) -> list[dict]:
    return _rows(engine, "SELECT line_id, name, part_number FROM lines ORDER BY line_id")


def shift_detail(engine: Engine, d: date, shift: str, line_id: int | None = None) -> dict:
    """Everything the shift report needs, as plain data."""
    def lf(alias: str) -> str:
        return f" AND {alias}.line_id = :line_id" if line_id else ""

    p = dict(d=d, shift=shift, line_id=line_id)
    per_line = _rows(engine, f"""
        WITH {FINISHED_CTE}
        SELECT l.line_id, l.name, st.headcount, st.planned_units,
               coalesce(f.units, 0) AS units,
               round(coalesce(f.units, 0) * p.std_hours, 1) AS earned_hours,
               (SELECT count(*) FROM nonconformances n
                 WHERE n.line_id = l.line_id AND n.shift_date = :d AND n.shift = :shift) AS nc_count,
               (SELECT coalesce(sum(minutes), 0) FROM downtime_events e
                 WHERE e.line_id = l.line_id AND e.shift_date = :d AND e.shift = :shift) AS downtime_min
        FROM lines l
        JOIN parts p USING (part_number)
        JOIN shift_staffing st ON st.line_id = l.line_id AND st.shift_date = :d AND st.shift = :shift
        LEFT JOIN finished f ON f.line_id = l.line_id AND f.shift_date = :d AND f.shift = :shift
        WHERE TRUE {lf('l')}
        ORDER BY l.line_id
    """, **p)
    downtime = _rows(engine, f"""
        SELECT e.reason, l.name AS line, s.name AS station, e.minutes, e.started_at
        FROM downtime_events e JOIN lines l USING (line_id) JOIN stations s USING (station_id)
        WHERE e.shift_date = :d AND e.shift = :shift {lf('e')}
        ORDER BY e.minutes DESC
    """, **p)
    ncs = _rows(engine, f"""
        SELECT n.nc_id, n.serial_number, l.name AS line, s.name AS station, n.defect_code,
               n.description, n.severity, n.status
        FROM nonconformances n JOIN lines l USING (line_id) JOIN stations s USING (station_id)
        WHERE n.shift_date = :d AND n.shift = :shift {lf('n')}
        ORDER BY CASE n.severity WHEN 'critical' THEN 0 WHEN 'major' THEN 1 ELSE 2 END, n.nc_id
    """, **p)
    for r in per_line:
        r["earned_hours"] = _num(r["earned_hours"])
        r["downtime_min"] = round(_num(r["downtime_min"]))
    for r in downtime:
        r["minutes"] = round(_num(r["minutes"]))
        r["started_at"] = r["started_at"].strftime("%H:%M")
    return {
        "date": d.isoformat(),
        "shift": shift,
        "line_id": line_id,
        "kpis": kpis(engine, d, d, shift, line_id),
        "lines": per_line,
        "anomalies": anomalies(engine, 50, d, d, shift, line_id),
        "downtime": downtime,
        "nonconformances": ncs,
    }


def recommended_actions(detail: dict) -> list[str]:
    """Deterministic, rule-based follow-ups so the report is reproducible and auditable."""
    actions = []
    for a in detail["anomalies"]:
        actions.append(f"Investigate {a['station']} on {a['line']}: {a['reason']}.")
    for ln in detail["lines"]:
        plan, units = ln["planned_units"], ln["units"]
        if plan and units < 0.9 * plan:
            actions.append(f"{ln['name']} finished {units} of {plan} planned units "
                           f"({plan - units} short); confirm recovery plan with the next shift.")
    by_reason: dict[str, int] = {}
    for e in detail["downtime"]:
        by_reason[e["reason"]] = by_reason.get(e["reason"], 0) + e["minutes"]
    for reason, minutes in sorted(by_reason.items(), key=lambda kv: -kv[1]):
        if minutes >= 60:
            actions.append(f"Review {minutes} min of '{reason}' downtime and log the root cause.")
    for n in detail["nonconformances"]:
        if n["status"] == "open" and n["severity"] in ("major", "critical"):
            actions.append(f"Disposition NC-{n['nc_id']} ({n['severity']}, {n['defect_code']} on "
                           f"{n['serial_number']}) before the unit moves on.")
    return actions or ["No follow-ups: the shift ran to plan with no anomalies or open major NCs."]
