"""Isolation Forest over station-shift aggregates.

One row per (line, station, shift_date, shift). Features are normalised so stations with
different standard cycle times are comparable. Flagged rows are written to `anomalies`
with a plain-English reason naming the feature that deviates most from the station's norm.
"""
from __future__ import annotations

import pandas as pd
from sklearn.ensemble import IsolationForest
from sqlalchemy import Engine, text

FEATURES = ["cycle_ratio", "avg_queue_min", "nc_rate", "downtime_min", "units_short"]

AGG_SQL = """
WITH mv AS (
    SELECT m.line_id, m.station_id, m.shift_date, m.shift,
           count(*) AS units,
           avg(m.cycle_min) / max(s.std_cycle_min) AS cycle_ratio,
           avg(m.queue_min) AS avg_queue_min
    FROM part_movements m JOIN stations s USING (station_id)
    GROUP BY 1, 2, 3, 4
), nc AS (
    SELECT station_id, shift_date, shift, count(*) AS nc_count
    FROM nonconformances GROUP BY 1, 2, 3
), dt AS (
    SELECT station_id, shift_date, shift, sum(minutes) AS downtime_min
    FROM downtime_events GROUP BY 1, 2, 3
)
SELECT mv.*, coalesce(nc.nc_count, 0) AS nc_count, coalesce(dt.downtime_min, 0) AS downtime_min
FROM mv
LEFT JOIN nc USING (station_id, shift_date, shift)
LEFT JOIN dt USING (station_id, shift_date, shift)
"""

LABELS = {
    "cycle_ratio": lambda r: f"cycle time {r.cycle_ratio:.2f}x standard",
    "avg_queue_min": lambda r: f"avg queue {r.avg_queue_min:.0f} min",
    "nc_rate": lambda r: f"{int(r.nc_count)} nonconformance{'' if r.nc_count == 1 else 's'} on {int(r.units)} units",
    "downtime_min": lambda r: f"{r.downtime_min:.0f} min downtime",
    "units_short": lambda r: f"only {int(r.units)} units through the station",
}


def detect(engine: Engine, contamination: float = 0.01, seed: int = 42) -> pd.DataFrame:
    with engine.connect() as conn:
        df = pd.read_sql(text(AGG_SQL), conn)
    for c in ("cycle_ratio", "avg_queue_min", "downtime_min"):
        df[c] = df[c].astype(float)
    df["nc_rate"] = df["nc_count"] / df["units"].clip(lower=1)
    df["units_short"] = -df["units"].astype(float)  # higher = fewer units than usual

    # Deviation from each station's own median, scaled by the plant-wide spread of the feature.
    # (A per-station std collapses on mostly-zero features like downtime and overstates small stops.)
    dev = df[FEATURES] - df.groupby("station_id")[FEATURES].transform("median")
    z = dev / dev.std().replace(0, 1)

    model = IsolationForest(n_estimators=300, contamination=contamination, random_state=seed)
    model.fit(z)
    df["score"] = model.decision_function(z)
    df["flag"] = model.predict(z) == -1

    def reason(i: int) -> str:
        row = df.loc[i]
        top = sorted(FEATURES, key=lambda f: z.loc[i, f], reverse=True)
        parts = [LABELS[f](row) for f in top if z.loc[i, f] > 2.0][:2] or [LABELS[top[0]](row)]
        return "; ".join(parts)

    flagged = df[df["flag"]].copy()
    flagged["reason"] = [reason(i) for i in flagged.index]
    return flagged.sort_values("score")


def refresh(engine: Engine) -> int:
    flagged = detect(engine)
    cols = ["line_id", "station_id", "shift_date", "shift", "score", "units", "cycle_ratio",
            "avg_queue_min", "nc_count", "downtime_min", "reason"]
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE anomalies RESTART IDENTITY"))
        if len(flagged):
            conn.execute(
                text(f"INSERT INTO anomalies ({', '.join(cols)}) VALUES ({', '.join(':' + c for c in cols)})"),
                [{c: (v.item() if hasattr(v, "item") else v) for c, v in r.items()}
                 for r in flagged[cols].to_dict("records")],
            )
    return len(flagged)
