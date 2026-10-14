from datetime import timedelta

import pytest

from app import capacity
from tests.conftest import END


@pytest.fixture
def base(engine):
    return capacity.baseline(engine, 3)


def sim(base, **kw):
    args = dict(line_id=3, headcount=base["headcount"], downtime_min=base["downtime_min"],
                cycle_time_min=base["cycle_time_min"]) | kw
    return capacity.simulate(base, capacity.SimInput(**args))


def test_baseline_inputs_reproduce_observed_output(base):
    assert sim(base)["projected_units"] == pytest.approx(base["actual_units"], rel=0.05)


def test_levers_move_output_the_right_way(base):
    b = sim(base)["projected_units"]
    assert sim(base, headcount=base["headcount"] + 1)["projected_units"] > b
    assert sim(base, downtime_min=base["downtime_min"] + 60)["projected_units"] < b
    assert sim(base, cycle_time_min=base["cycle_time_min"] * 1.2)["projected_units"] < b
    assert sim(base, downtime_min=450)["projected_units"] == 0


def test_series_and_headcount_to_target(base):
    out = sim(base, target_units=30)
    s = out["series"]
    assert len(s) == 8 and s[-1]["target_units"] == 30
    assert all(a["projected_units"] <= b["projected_units"] for a, b in zip(s, s[1:]))
    assert s[4]["target_units"] - s[3]["target_units"] < s[1]["target_units"] - s[0]["target_units"]  # break hour
    hit = sim(base, target_units=30, headcount=out["headcount_to_hit_target"])
    assert hit["projected_units"] == pytest.approx(30, abs=0.2)


def test_capacity_endpoints(client):
    b = client.get("/api/capacity/baseline?line_id=2").json()
    r = client.post("/api/capacity/simulate", json={"line_id": 2, "headcount": b["headcount"],
                                                     "downtime_min": 0, "cycle_time_min": b["std_cycle_min"]})
    assert r.status_code == 200 and r.json()["projected_units"] > b["actual_units"]
    assert client.post("/api/capacity/simulate", json={"line_id": 2, "headcount": -1, "downtime_min": 0,
                                                       "cycle_time_min": 10}).status_code == 422
    assert client.get("/api/capacity/baseline?line_id=99").status_code == 404


def test_shift_report_flags_the_crimp_upset(client):
    d = (END - timedelta(days=5)).isoformat()
    r = client.get(f"/api/shift-report?date={d}&shift=B&line_id=3").json()
    assert r["kpis"]["units"] < r["kpis"]["planned_units"]
    assert any(a["station"] == "Crimp & terminate" for a in r["anomalies"])
    assert any("Crimp & terminate" in a for a in r["actions"])


def test_shift_report_pdf(client):
    r = client.get("/api/shift-report.pdf?shift=A")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content[:5] == b"%PDF-" and len(r.content) > 3000
    assert f"shift-report-{END.isoformat()}-A.pdf" in r.headers["content-disposition"]


def test_shift_report_errors(client):
    assert client.get("/api/shift-report.pdf?shift=X").status_code == 422
    assert client.get("/api/shift-report.pdf?date=2020-01-01&shift=A").status_code == 404
