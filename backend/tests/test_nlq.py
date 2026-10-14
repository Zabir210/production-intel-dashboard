import pytest

from app import main, nlq

GOOD = """
WITH last_week AS (SELECT max(shift_date) - 6 AS d0, max(shift_date) AS d1 FROM part_movements)
SELECT n.shift_date, s.name AS station, n.defect_code, n.severity, n.status
FROM nonconformances n JOIN stations s USING (station_id), last_week
WHERE n.line_id = 3 AND n.shift_date BETWEEN last_week.d0 AND last_week.d1
ORDER BY n.shift_date
"""


@pytest.mark.parametrize("sql, why", [
    ("DROP TABLE lines", "SELECT"),
    ("SELECT 1; DELETE FROM lines", "single"),
    ("WITH x AS (DELETE FROM lines RETURNING *) SELECT * FROM x", "disallowed"),
    ("SELECT pg_sleep(10)", "pg_sleep"),
    ("SELECT pg_read_file('/etc/passwd')", "pg_read_file"),
    ("SELECT * FROM pg_catalog.pg_user", "Schema-qualified"),
    ("SELECT * FROM information_schema.tables", "Schema-qualified"),
    ("SELECT * FROM users", "not part"),
    ("SELECT * INTO new_table FROM lines", "disallowed"),
    ("SELECT set_config('x', 'y', false)", "set_config"),
    ("SELECT current_setting('data_directory')", "current_setting"),
])
def test_validator_rejects(sql, why):
    with pytest.raises(nlq.NLQError, match=why):
        nlq.validate_sql(sql)


def test_validator_accepts_cte_join():
    assert nlq.validate_sql(GOOD).upper().startswith("WITH")


def test_read_only_transaction_blocks_side_effect_functions(engine):
    # nextval() is a plain SELECT that writes; the READ ONLY transaction must stop it.
    with pytest.raises(nlq.NLQError, match="read-only"):
        nlq.run_sql(engine, "SELECT nextval('nonconformances_nc_id_seq')", 10)


def test_colons_and_row_cap(engine):
    out = nlq.run_sql(engine, "SELECT serial_number, '08:30' AS t FROM part_movements", 50)
    assert out["row_count"] == 50 and out["truncated"] and out["rows"][0][1] == "08:30"


def fake(sql):
    return lambda question, latest: {"sql": sql, "explanation": "test"}


def test_endpoint_runs_generated_sql(client):
    main.app.dependency_overrides[main.translator] = lambda: fake(GOOD)
    r = client.post("/api/nlq", json={"question": "show nonconformances on line 3 last week"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sql"].strip() == GOOD.strip()
    assert body["columns"] == ["shift_date", "station", "defect_code", "severity", "status"]
    assert body["row_count"] > 0  # the crimp-station upset lands inside that week


def test_endpoint_returns_sql_with_rejection(client):
    main.app.dependency_overrides[main.translator] = lambda: fake("UPDATE lines SET name = 'x'")
    r = client.post("/api/nlq", json={"question": "rename line 1"})
    assert r.status_code == 400 and r.json()["sql"] == "UPDATE lines SET name = 'x'"


def test_endpoint_without_api_key_is_503(client, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    r = client.post("/api/nlq", json={"question": "how many units yesterday?"})
    assert r.status_code == 503 and "ANTHROPIC_API_KEY" in r.json()["detail"]


def test_reader_role_can_select_but_not_write(engine):
    """Production connects as pid_reader; prove the grant works and writes are refused."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import ProgrammingError
    from app.db import grant_reader

    with engine.begin() as c:
        c.execute(text("""DO $$ BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pid_reader') THEN
                CREATE ROLE pid_reader LOGIN PASSWORD 'pid_reader_local';
            END IF; END $$"""))
    assert grant_reader(engine)
    url = engine.url.set(username="pid_reader", password="pid_reader_local")
    reader = create_engine(url, connect_args={"prepare_threshold": None})
    with reader.connect() as c:
        assert c.execute(text("SELECT count(*) FROM lines")).scalar_one() == 5
        with pytest.raises(ProgrammingError, match="permission denied"):
            c.execute(text("UPDATE lines SET name = 'x'"))
    reader.dispose()
