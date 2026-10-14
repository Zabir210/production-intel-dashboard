from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import Engine, text

from . import capacity, config, metrics, nlq, report
from .db import get_engine

app = FastAPI(title="Production Intelligence Dashboard API")

Shift = Query(pattern="^[ABC]$")


def engine() -> Engine:
    return get_engine()


def translator() -> nlq.Translator:
    return nlq.claude_translator


@app.get("/api/health")
def health(db: Engine = Depends(engine)):
    with db.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok", "llm_configured": config.llm_configured(), "nlq_model": config.NLQ_MODEL}


@app.get("/api/meta")
def meta(db: Engine = Depends(engine)):
    return {"latest_date": metrics.latest_date(db).isoformat(), "lines": metrics.lines(db),
            "shifts": {k: f"{v:02d}:00" for k, v in config.SHIFTS.items()},
            "llm_configured": config.llm_configured()}


@app.get("/api/kpis")
def kpis(days: int = Query(7, ge=1, le=90), db: Engine = Depends(engine)):
    end = metrics.latest_date(db)
    start = end - timedelta(days=days - 1)
    return {"start": start.isoformat(), "end": end.isoformat(), **metrics.kpis(db, start, end)}


@app.get("/api/throughput")
def throughput(days: int = Query(14, ge=1, le=90), db: Engine = Depends(engine)):
    return metrics.daily_throughput(db, days)


@app.get("/api/anomalies")
def anomalies(limit: int = Query(25, ge=1, le=200), db: Engine = Depends(engine)):
    return metrics.anomalies(db, limit)


# --- Work projects ---------------------------------------------------------------------------

class NLQRequest(BaseModel):
    question: str


@app.post("/api/nlq")
def ask(body: NLQRequest, db: Engine = Depends(engine), translate=Depends(translator)):
    try:
        return nlq.answer(db, body.question, metrics.latest_date(db), translate)
    except nlq.NLQError as e:
        return JSONResponse(status_code=e.status, content={"detail": str(e), "sql": e.sql})


def _check_line(db: Engine, line_id: int) -> None:
    if line_id not in {ln["line_id"] for ln in metrics.lines(db)}:
        raise HTTPException(404, f"Unknown line {line_id}")


@app.get("/api/capacity/baseline")
def capacity_baseline(line_id: int, days: int = Query(14, ge=1, le=90), db: Engine = Depends(engine)):
    _check_line(db, line_id)
    return capacity.baseline(db, line_id, days)


@app.post("/api/capacity/simulate")
def capacity_simulate(inp: capacity.SimInput, db: Engine = Depends(engine)):
    _check_line(db, inp.line_id)
    return capacity.simulate(capacity.baseline(db, inp.line_id), inp)


def _shift_detail(db: Engine, d: date | None, shift: str, line_id: int | None) -> dict:
    d = d or metrics.latest_date(db)
    if line_id is not None:
        _check_line(db, line_id)
    detail = metrics.shift_detail(db, d, shift, line_id)
    if not detail["lines"]:
        raise HTTPException(404, f"No production data for {d.isoformat()} shift {shift}")
    detail["actions"] = metrics.recommended_actions(detail)
    return detail


@app.get("/api/shift-report")
def shift_report(date: date | None = None, shift: str = Shift, line_id: int | None = None,
                 db: Engine = Depends(engine)):
    return _shift_detail(db, date, shift, line_id)


@app.get("/api/shift-report.pdf")
def shift_report_pdf(date: date | None = None, shift: str = Shift, line_id: int | None = None,
                     db: Engine = Depends(engine)):
    detail = _shift_detail(db, date, shift, line_id)
    pdf = report.build_pdf(detail, detail["actions"])
    suffix = f"-line{line_id}" if line_id else ""
    name = f"shift-report-{detail['date']}-{shift}{suffix}.pdf"
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


# Serve the built frontend from the same origin in production (one container, no CORS).
DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if DIST.is_dir():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="frontend")
