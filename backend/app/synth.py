"""Synthetic part-movement data for five generic manufacturing lines.

Everything here is invented: line names, part numbers (SYN-*), cycle times and defect codes.
A handful of process upsets are injected near the end of the window so the anomaly
detector and the shift report have something real to find.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import numpy as np
from sqlalchemy import Engine

from . import config
from .db import reset_schema

EFFICIENCY = 0.85  # personal, fatigue and delay allowance applied to planned minutes

# (line_id, name, part_number, part description, planned headcount, [(station, std cycle min)])
LINES = [
    (1, "Line 1 - Bracket Machining", "SYN-1100", "Machined bracket", 4,
     [("Saw cut", 6), ("CNC rough", 18), ("CNC finish", 16), ("Deburr", 8), ("CMM inspect", 10)]),
    (2, "Line 2 - Panel Drilling", "SYN-2100", "Drilled skin panel", 5,
     [("Load fixture", 8), ("Auto drill", 20), ("Countersink", 12), ("Fastener install", 22)]),
    (3, "Line 3 - Harness Assembly", "SYN-3100", "Wire harness", 4,
     [("Cut & strip", 7), ("Crimp & terminate", 15), ("Route & tie", 20), ("Continuity test", 9)]),
    (4, "Line 4 - Composite Layup", "SYN-4100", "Composite fairing", 5,
     [("Ply cut", 10), ("Layup", 30), ("Bag & cure prep", 14), ("Trim", 12)]),
    (5, "Line 5 - Final Inspection", "SYN-5100", "Inspected assembly", 3,
     [("Visual inspect", 12), ("Dimensional check", 14), ("Paperwork review", 8)]),
]

DEFECTS = {
    1: [("DIM-OOT", "Dimension out of tolerance"), ("BURR", "Burr remaining on edge"),
        ("SURF", "Surface finish below spec")],
    2: [("HOLE-POS", "Hole position out of tolerance"), ("CSK-DEPTH", "Countersink depth out of spec"),
        ("FAST-GAP", "Fastener head gap")],
    3: [("CRIMP-PULL", "Crimp failed pull test"), ("WIRE-NICK", "Nicked conductor"),
        ("CONT-FAIL", "Continuity test failure")],
    4: [("VOID", "Void found in laminate"), ("WRINKLE", "Ply wrinkle"), ("FOD", "Foreign object debris")],
    5: [("DOC-MISS", "Missing traceability record"), ("DIM-OOT", "Dimension out of tolerance"),
        ("COSM", "Cosmetic damage")],
}

DOWNTIME_REASONS = ["Tooling change", "Material shortage", "Unplanned maintenance",
                    "Waiting on inspection", "Quality hold", "IT / MES outage"]


@dataclass
class Upset:
    cycle_mult: float = 1.0
    nc_prob: float | None = None
    queue_add: float = 0.0
    downtime: list[tuple[float, str]] = field(default_factory=list)


def station_id(line_id: int, seq: int) -> int:
    return line_id * 10 + seq


def shift_start(d: date, shift: str) -> datetime:
    return datetime(d.year, d.month, d.day, config.SHIFTS[shift])


def planned_units(headcount: int, labor_min: float) -> int:
    return round(headcount * config.PLANNED_MINUTES * EFFICIENCY / labor_min)


def injected_upsets(end: date) -> dict[tuple[int, int, date, str], Upset]:
    d = lambda n: end - timedelta(days=n)  # noqa: E731
    upsets = {}
    for n in (6, 5, 4):  # line 3 crimp station degrading on B shift for three days
        upsets[(3, station_id(3, 2), d(n), "B")] = Upset(cycle_mult=1.7, nc_prob=0.14, queue_add=12)
    upsets[(1, station_id(1, 2), d(2), "A")] = Upset(downtime=[(170, "Unplanned maintenance")])
    upsets[(4, station_id(4, 2), d(10), "C")] = Upset(cycle_mult=1.55, nc_prob=0.10)
    upsets[(2, station_id(2, 4), d(0), "C")] = Upset(queue_add=25, downtime=[(95, "Material shortage")])
    return upsets


def generate(end: date, days: int = 35, seed: int = 42) -> dict[str, list[tuple]]:
    """Return rows per table for the `days` production days ending on `end` (inclusive)."""
    rng = np.random.default_rng(seed)
    upsets = injected_upsets(end)
    out: dict[str, list[tuple]] = {k: [] for k in (
        "lines", "stations", "parts", "shift_staffing", "part_movements",
        "nonconformances", "downtime_events")}

    for line_id, name, pn, desc, _, stations in LINES:
        labor = sum(c for _, c in stations)
        out["lines"].append((line_id, name, pn))
        out["parts"].append((pn, f"{desc} (synthetic)", round(labor / 60, 3)))
        for seq, (sname, cyc) in enumerate(stations, 1):
            out["stations"].append((station_id(line_id, seq), line_id, seq, sname, cyc))

    serial_counter = {pn: 0 for _, _, pn, *_ in LINES}
    for day_offset in range(days - 1, -1, -1):
        d = end - timedelta(days=day_offset)
        age_days = (end - d).days
        for shift in config.SHIFTS:
            start = shift_start(d, shift)
            for line_id, _, pn, _, base_hc, stations in LINES:
                labor = sum(c for _, c in stations)
                headcount = max(2, base_hc + int(rng.choice([-1, 0, 0, 0, 0, 1])))
                plan = planned_units(base_hc, labor)
                out["shift_staffing"].append((line_id, d, shift, headcount, plan))

                # Per-station conditions for this shift.
                shift_mult = rng.normal(1.0, 0.04) * (1.05 if shift == "C" else 1.0)
                cond = []
                downtime_total = 0.0
                for seq, (_, cyc) in enumerate(stations, 1):
                    sid = station_id(line_id, seq)
                    up = upsets.get((line_id, sid, d, shift), Upset())
                    cond.append((sid, cyc, up))
                    events = list(up.downtime)
                    if rng.random() < 0.18:
                        events.append((float(rng.choice([5, 10, 15, 20, 30, 45])),
                                       str(rng.choice(DOWNTIME_REASONS))))
                    for minutes, reason in events:
                        t0 = start + timedelta(minutes=float(rng.uniform(20, config.SHIFT_MINUTES - minutes - 20)))
                        out["downtime_events"].append((line_id, sid, d, shift, t0, minutes, reason))
                        downtime_total += minutes

                actual_labor = sum(cyc * up.cycle_mult for _, cyc, up in cond) * shift_mult
                available = max(0.0, config.PLANNED_MINUTES - downtime_total)
                units = int(headcount * available * EFFICIENCY / actual_labor * rng.normal(1.0, 0.03))
                units = max(units, 0)

                spacing = config.SHIFT_MINUTES / max(units, 1)
                for k in range(units):
                    serial_counter[pn] += 1
                    serial = f"{pn}-{serial_counter[pn]:06d}"
                    t = start + timedelta(minutes=k * spacing + float(rng.uniform(0, 3)))
                    queue_boost = 0.0
                    for sid, cyc, up in cond:
                        queue_boost += up.queue_add
                        queue = float(rng.exponential(2.0 + (sid % 10))) + queue_boost
                        cycle = cyc * up.cycle_mult * shift_mult * float(rng.lognormal(0, 0.12))
                        t_start = t + timedelta(minutes=queue)
                        t_end = t_start + timedelta(minutes=cycle)
                        out["part_movements"].append(
                            (serial, pn, line_id, sid, d, shift, t_start, t_end,
                             round(cycle, 2), round(queue, 2)))
                        nc_p = up.nc_prob if up.nc_prob is not None else (0.018 if shift == "C" else 0.011)
                        if rng.random() < nc_p:
                            code, text = DEFECTS[line_id][int(rng.integers(len(DEFECTS[line_id])))]
                            sev = str(rng.choice(["minor", "major", "critical"], p=[0.7, 0.25, 0.05]))
                            if age_days > 7:
                                status = str(rng.choice(["closed", "dispositioned"], p=[0.85, 0.15]))
                            else:
                                status = str(rng.choice(["open", "dispositioned", "closed"], p=[0.5, 0.3, 0.2]))
                            out["nonconformances"].append(
                                (serial, pn, line_id, sid, d, shift, t_end, code, text, sev, status))
                        t = t_end
    return out


COLUMNS = {
    "lines": "line_id, name, part_number",
    "parts": "part_number, description, std_hours",
    "stations": "station_id, line_id, seq, name, std_cycle_min",
    "shift_staffing": "line_id, shift_date, shift, headcount, planned_units",
    "part_movements": ("serial_number, part_number, line_id, station_id, shift_date, shift, "
                       "started_at, completed_at, cycle_min, queue_min"),
    "nonconformances": ("serial_number, part_number, line_id, station_id, shift_date, shift, "
                        "detected_at, defect_code, description, severity, status"),
    "downtime_events": "line_id, station_id, shift_date, shift, started_at, minutes, reason",
}


def load(engine: Engine, end: date, days: int = 35, seed: int = 42) -> dict[str, int]:
    rows = generate(end, days, seed)
    reset_schema(engine)
    counts = {}
    with engine.begin() as conn:
        cur = conn.connection.driver_connection.cursor()
        for table in ("lines", "parts", "stations", "shift_staffing", "part_movements",
                      "nonconformances", "downtime_events"):
            with cur.copy(f"COPY {table} ({COLUMNS[table]}) FROM STDIN") as cp:
                for r in rows[table]:
                    cp.write_row([None if (isinstance(v, float) and math.isnan(v)) else v for v in r])
            counts[table] = len(rows[table])
    return counts
