from datetime import timedelta

from sqlalchemy import text

from app import synth
from tests.conftest import END


def scalar(engine, sql, **p):
    with engine.connect() as c:
        return c.execute(text(sql), p).scalar_one()


def test_generator_is_deterministic():
    a = synth.generate(END, days=3, seed=7)
    b = synth.generate(END, days=3, seed=7)
    assert a["part_movements"] == b["part_movements"]
    assert a["nonconformances"] == b["nonconformances"]


def test_volume_and_synthetic_part_numbers(engine):
    assert scalar(engine, "SELECT count(*) FROM part_movements") > 40_000
    assert scalar(engine, "SELECT count(*) FROM parts WHERE part_number NOT LIKE 'SYN-%'") == 0
    assert scalar(engine, "SELECT count(DISTINCT shift_date) FROM shift_staffing") == 35
    assert scalar(engine, "SELECT max(shift_date) FROM part_movements") == END


def flagged(engine, line_id, station_seq, days_ago, shift):
    return scalar(engine, """
        SELECT count(*) FROM anomalies
        WHERE line_id = :l AND station_id = :s AND shift_date = :d AND shift = :sh""",
                  l=line_id, s=synth.station_id(line_id, station_seq), d=END - timedelta(days=days_ago), sh=shift)


def test_isolation_forest_finds_every_injected_upset(engine):
    for days_ago in (6, 5, 4):
        assert flagged(engine, 3, 2, days_ago, "B"), f"line 3 crimp, {days_ago} days ago"
    assert flagged(engine, 1, 2, 2, "A"), "line 1 CNC rough 170 min outage"
    assert flagged(engine, 4, 2, 10, "C"), "line 4 layup slow + defects"
    assert flagged(engine, 2, 4, 0, "C"), "line 2 material shortage"


def test_anomaly_rate_stays_small(engine):
    total = scalar(engine, "SELECT count(*) FROM (SELECT DISTINCT station_id, shift_date, shift FROM part_movements) x")
    assert scalar(engine, "SELECT count(*) FROM anomalies") <= 0.015 * total


def test_overview_endpoints(client):
    k = client.get("/api/kpis?days=7").json()
    assert k["end"] == END.isoformat() and k["units"] > 0 and 50 < k["attainment_pct"] < 120
    t = client.get("/api/throughput?days=14").json()
    assert len(t) == 14 and {"line_1", "line_5", "planned"} <= set(t[0])
    a = client.get("/api/anomalies?limit=5").json()
    assert len(a) == 5 and a[0]["reason"]
