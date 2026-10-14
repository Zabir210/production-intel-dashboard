"""Rebuild the database with synthetic data and rerun anomaly detection.

    python -m app.seed                   # 35 days ending today
    python -m app.seed --days 60 --end 2026-10-12
"""
import argparse
from datetime import date

from . import anomaly, synth
from .db import get_engine, grant_reader


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=35)
    p.add_argument("--end", type=date.fromisoformat, default=date.today())
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--database-url")
    a = p.parse_args()

    engine = get_engine(a.database_url)
    counts = synth.load(engine, a.end, a.days, a.seed)
    counts["anomalies"] = anomaly.refresh(engine)
    for table, n in counts.items():
        print(f"{table:16s} {n:>7,d}")
    if grant_reader(engine):
        print("granted SELECT to read-only role")


if __name__ == "__main__":
    main()
