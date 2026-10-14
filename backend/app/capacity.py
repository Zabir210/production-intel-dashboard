"""What-if capacity model for one line over one shift.

Balanced-line labor model: every unit needs `cycle_time_min` of touch time at each of the
line's stations, operators are interchangeable, and the line's observed efficiency (calibrated
from recent history) converts available minutes into productive minutes:

    units/min  = headcount * efficiency / (stations * cycle_time_min)
    available  = planned minutes - downtime   (downtime spread evenly across working time)
    earned hrs = units * standard hours per unit

The target pacing line spreads the planned units evenly over planned working minutes.
"""
from __future__ import annotations

from datetime import timedelta

from pydantic import BaseModel, Field
from sqlalchemy import Engine, text

from . import config
from .metrics import FINISHED_CTE, latest_date

BREAK_AFTER_HOUR = 4  # the 30-minute planned break falls in hour 5 of the shift


class SimInput(BaseModel):
    line_id: int
    headcount: float = Field(gt=0, le=40)
    downtime_min: float = Field(ge=0, le=config.PLANNED_MINUTES)
    cycle_time_min: float = Field(gt=0, le=240)
    target_units: float | None = Field(default=None, ge=0)


def baseline(engine: Engine, line_id: int, days: int = 14) -> dict:
    end = latest_date(engine)
    start = end - timedelta(days=days - 1)
    with engine.connect() as conn:
        r = conn.execute(text(f"""
            WITH {FINISHED_CTE},
            shifts AS (
                SELECT st.shift_date, st.shift, st.headcount, st.planned_units,
                       coalesce(f.units, 0) AS units,
                       coalesce((SELECT sum(minutes) FROM downtime_events e
                                  WHERE e.line_id = st.line_id AND e.shift_date = st.shift_date
                                    AND e.shift = st.shift), 0) AS downtime_min
                FROM shift_staffing st
                LEFT JOIN finished f USING (line_id, shift_date, shift)
                WHERE st.line_id = :line_id AND st.shift_date BETWEEN :start AND :end
            )
            SELECT l.name, p.std_hours,
                   (SELECT count(*) FROM stations WHERE line_id = :line_id) AS stations,
                   (SELECT avg(std_cycle_min) FROM stations WHERE line_id = :line_id) AS std_cycle_min,
                   (SELECT avg(cycle_min) FROM part_movements
                     WHERE line_id = :line_id AND shift_date BETWEEN :start AND :end) AS avg_cycle_min,
                   (SELECT avg(headcount) FROM shifts) AS headcount,
                   (SELECT avg(planned_units) FROM shifts) AS planned_units,
                   (SELECT avg(units) FROM shifts) AS units,
                   (SELECT avg(downtime_min) FROM shifts) AS downtime_min
            FROM lines l JOIN parts p USING (part_number)
            WHERE l.line_id = :line_id
        """), dict(line_id=line_id, start=start, end=end)).mappings().one()

    stations = int(r["stations"])
    cycle = float(r["avg_cycle_min"])
    headcount = float(r["headcount"])
    downtime = float(r["downtime_min"])
    units = float(r["units"])
    # Calibrate efficiency so the baseline inputs reproduce the observed average output.
    efficiency = units * stations * cycle / (headcount * (config.PLANNED_MINUTES - downtime))
    return {
        "line_id": line_id,
        "line": r["name"],
        "window": {"start": start.isoformat(), "end": end.isoformat(), "days": days},
        "stations": stations,
        "std_cycle_min": round(float(r["std_cycle_min"]), 2),
        "std_hours_per_unit": float(r["std_hours"]),
        "efficiency": round(efficiency, 3),
        "headcount": round(headcount, 1),
        "downtime_min": round(downtime, 1),
        "cycle_time_min": round(cycle, 2),
        "planned_units": round(float(r["planned_units"]), 1),
        "actual_units": round(units, 1),
    }


def simulate(base: dict, inp: SimInput) -> dict:
    stations = base["stations"]
    eff = base["efficiency"]
    target = inp.target_units if inp.target_units is not None else base["planned_units"]
    planned = config.PLANNED_MINUTES
    working = max(planned - inp.downtime_min, 0.0)
    rate = inp.headcount * eff / (stations * inp.cycle_time_min)  # units per working minute

    series = []
    cum_planned = 0.0
    for hour in range(1, config.SHIFT_MINUTES // 60 + 1):
        planned_this_hour = 60 - (config.BREAK_MINUTES if hour == BREAK_AFTER_HOUR + 1 else 0)
        cum_planned += planned_this_hour
        cum_working = cum_planned * working / planned
        units = rate * cum_working
        series.append({
            "hour": hour,
            "projected_units": round(units, 1),
            "target_units": round(target * cum_planned / planned, 1),
            "projected_earned_hours": round(units * base["std_hours_per_unit"], 1),
            "target_earned_hours": round(target * cum_planned / planned * base["std_hours_per_unit"], 1),
        })

    units = rate * working
    earned = units * base["std_hours_per_unit"]
    labor_hours = inp.headcount * config.SHIFT_MINUTES / 60
    # Headcount needed to hit target at these cycle/downtime settings.
    needed = (target * stations * inp.cycle_time_min / (eff * working)) if working else None
    return {
        "inputs": inp.model_dump(),
        "projected_units": round(units, 1),
        "target_units": round(target, 1),
        "gap_units": round(units - target, 1),
        "attainment_pct": round(100 * units / target, 1) if target else None,
        "earned_hours": round(earned, 1),
        "target_earned_hours": round(target * base["std_hours_per_unit"], 1),
        "labor_hours": round(labor_hours, 1),
        "realization_pct": round(100 * earned / labor_hours, 1) if labor_hours else None,
        "headcount_to_hit_target": round(needed, 1) if needed is not None else None,
        "series": series,
    }
