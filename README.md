# Production Intelligence Dashboard

Analytics for manufacturing part movement: where units are, how long they wait, what went wrong, and
whether each shift will make its number. FastAPI + PostgreSQL + Isolation Forest on the back end,
React + Recharts on the front end.

**All data is synthetic.** Line names, part numbers (`SYN-*`), cycle times and defect codes are generated
by `backend/app/synth.py`. No employer or customer data is used anywhere.

## What's in it

**Overview**: finished units by line against plan, plan attainment, earned hours, first-pass yield,
downtime, and the station-shifts an Isolation Forest flagged as unusual. The generator injects four
process upsets (a degrading crimp station, a spindle outage, a slow layup cell, a material shortage), and
the test suite fails if the detector misses any of them.

**Work Projects**
1. **Ask the data.** Type a question such as *"show nonconformances on line 3 last week"*. Claude writes one
   PostgreSQL query, and the UI shows the SQL next to the rows so the answer can be checked. The model is
   not trusted: sqlglot must parse exactly one SELECT over the dashboard tables (no DML/DDL, no `pg_*` or
   settings functions, no other schemas), and it runs in a `READ ONLY` transaction with a statement timeout
   and a row cap. In production the app also connects as a role that only has `SELECT`.
2. **What-if capacity simulator.** Sliders for headcount, downtime and cycle time project one shift's
   cumulative output and earned hours against a target pacing line. The line's efficiency is calibrated
   from its last 14 days, so baseline inputs reproduce its actual average.
3. **Shift report.** One click produces a PDF with KPIs, per-line results, anomalies, downtime,
   nonconformances and rule-based follow-up actions for the hand-off.

## Run it locally

Requires Docker, Python 3.12 and Node 22.

```bash
docker compose up -d db                                 # Postgres on localhost:5434
python3.12 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cp .env.example .env                                    # add ANTHROPIC_API_KEY for the query bar
docker compose exec db psql -U pid -c "create database pid_test"   # once, for tests
cd backend && ../.venv/bin/python -m app.seed           # 35 days of data, then anomaly detection
../.venv/bin/uvicorn app.main:app --port 8010 --env-file ../.env
```

In a second terminal: `cd frontend && npm ci && npm run dev`, then open http://localhost:5180.

Tests: `cd backend && ../.venv/bin/python -m pytest`.

## Layout

```
backend/app/
  synth.py      synthetic lines, stations, movements, NCs, downtime (+ injected upsets)
  anomaly.py    station-shift features -> Isolation Forest -> anomalies table
  metrics.py    KPIs, throughput, shift detail, rule-based actions
  nlq.py        question -> Claude -> validated read-only SQL -> rows
  capacity.py   calibrated balanced-line capacity model
  report.py     shift report PDF (reportlab)
  main.py       FastAPI routes under /api
api/index.py    Vercel entrypoint
frontend/src/   React app (Overview + Work Projects)
```

## Deployment

Vercel serves the built frontend and runs the API as a Python function (`vercel.json`). The database is
Neon Postgres. The deployed function connects as `pid_reader`, which has `SELECT` only; reseeding runs
from a workstation with the owner role (`python -m app.seed --database-url ...`) and re-grants it.
