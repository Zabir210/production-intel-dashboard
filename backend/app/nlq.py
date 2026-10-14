"""Plain-English questions -> one read-only PostgreSQL SELECT -> rows.

Safety does not rely on the model behaving:
  1. sqlglot must parse exactly one statement, and it must be a query (SELECT / UNION / CTE).
  2. No DML/DDL nodes anywhere in the tree, no tables outside the dashboard schema,
     no server-side functions that touch files, sessions or other databases.
  3. It runs inside a READ ONLY transaction with a statement timeout and a row cap.
"""
from __future__ import annotations

import json
from datetime import date
from typing import Callable

import sqlglot
from sqlglot import exp
from sqlalchemy import Engine, text

from . import config
from .db import SCHEMA_SQL

ALLOWED_TABLES = {"lines", "stations", "parts", "shift_staffing", "part_movements",
                  "nonconformances", "downtime_events", "anomalies"}
FORBIDDEN_NODES = (exp.Insert, exp.Update, exp.Delete, exp.Merge, exp.Create, exp.Drop,
                   exp.Alter, exp.TruncateTable, exp.Command, exp.Into, exp.Copy, exp.Set,
                   exp.Transaction, exp.Commit, exp.Rollback, exp.Grant, exp.Lock)
FORBIDDEN_FUNC_PREFIXES = ("pg_", "lo_", "dblink", "set_config", "current_setting", "query_to_xml",
                           "txid_", "inet_")

SYSTEM_PROMPT = f"""You translate questions from manufacturing supervisors into a single PostgreSQL 16 SELECT query against this schema.

{SCHEMA_SQL}

Plant facts:
- Shifts: 'A' 06:00-14:00, 'B' 14:00-22:00, 'C' 22:00-06:00. shift_date is the production day the shift belongs to.
- A finished unit is a part_movements row at the line's last station (max stations.seq for that line).
- "Line 3" means line_id = 3. "Last week" means the 7 days ending on the latest shift_date in the data unless the user names dates.
- Earned hours = finished units * parts.std_hours.

Rules:
- Return exactly one SELECT (CTEs are fine). Never modify data.
- Join to lines/stations to return readable names rather than bare ids.
- Prefer ORDER BY on the most useful column, and keep results under 200 rows (aggregate or LIMIT when needed).
- If the question cannot be answered from this schema, return an empty sql string and explain why in `explanation`."""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "sql": {"type": "string"},
        "explanation": {"type": "string"},
    },
    "required": ["sql", "explanation"],
    "additionalProperties": False,
}


class NLQError(Exception):
    def __init__(self, message: str, status: int = 400, sql: str | None = None):
        super().__init__(message)
        self.status = status
        self.sql = sql


Translator = Callable[[str, date], dict]


def claude_translator(question: str, latest: date) -> dict:
    """Ask Claude for {sql, explanation}. Raises NLQError on refusal or API failure."""
    import anthropic

    if not config.llm_configured():
        raise NLQError("ANTHROPIC_API_KEY is not set on the server, so plain-English queries are "
                       "disabled. Add it to .env and restart the API.", status=503)
    client = anthropic.Anthropic()
    try:
        response = client.beta.messages.create(
            model=config.NLQ_MODEL,
            max_tokens=16000,
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            output_config={"effort": "medium",
                           "format": {"type": "json_schema", "schema": OUTPUT_SCHEMA}},
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content":
                       f"Latest shift_date in the data: {latest.isoformat()}\n\nQuestion: {question}"}],
        )
    except anthropic.AuthenticationError:
        raise NLQError("The Anthropic API key was rejected. Check ANTHROPIC_API_KEY in .env.", 502)
    except anthropic.RateLimitError:
        raise NLQError("The language model is rate limited right now. Try again in a minute.", 503)
    except anthropic.APIStatusError as e:
        raise NLQError(f"Language model error ({e.status_code}).", 502)
    except anthropic.APIConnectionError:
        raise NLQError("Could not reach the language model API.", 502)

    if response.stop_reason == "refusal":
        raise NLQError("The model declined to answer this question.", 422)
    if response.stop_reason == "max_tokens":
        raise NLQError("The model's answer was cut off. Try a narrower question.", 502)
    body = next((b.text for b in response.content if b.type == "text"), "")
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        raise NLQError("The model returned an unreadable answer. Try rephrasing.", 502)


def validate_sql(sql: str) -> str:
    """Return a normalised single SELECT, or raise NLQError explaining what was rejected."""
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except sqlglot.errors.ParseError as e:
        raise NLQError(f"Generated SQL did not parse: {e.errors[0]['description'] if e.errors else e}", sql=sql)
    if len(statements) != 1:
        raise NLQError("Only a single SQL statement is allowed.", sql=sql)
    tree = statements[0]
    if not isinstance(tree, exp.Query):
        raise NLQError("Only SELECT queries are allowed.", sql=sql)
    bad = next((n for n in tree.walk() if isinstance(n, FORBIDDEN_NODES)), None)
    if bad is not None:
        raise NLQError(f"Query contains a disallowed operation ({bad.key.upper()}).", sql=sql)

    cte_names = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    for t in tree.find_all(exp.Table):
        name = t.name.lower()
        if t.args.get("db") or t.args.get("catalog"):
            raise NLQError(f"Schema-qualified table '{t.sql()}' is not allowed.", sql=sql)
        if name and name not in ALLOWED_TABLES and name not in cte_names:
            raise NLQError(f"Table '{t.name}' is not part of the dashboard data.", sql=sql)
    for f in tree.find_all(exp.Func):
        fname = (f.sql_name() if not isinstance(f, exp.Anonymous) else f.name).lower()
        if fname.startswith(FORBIDDEN_FUNC_PREFIXES):
            raise NLQError(f"Function '{fname}' is not allowed.", sql=sql)
    return tree.sql(dialect="postgres")


def run_sql(engine: Engine, safe_sql: str, max_rows: int) -> dict:
    with engine.connect() as conn:
        with conn.begin():
            conn.execute(text("SET TRANSACTION READ ONLY"))
            conn.execute(text(f"SET LOCAL statement_timeout = {int(config.NLQ_STATEMENT_TIMEOUT_MS)}"))
            try:
                # exec_driver_sql: the model's SQL is not a SQLAlchemy template (":" must stay literal).
                result = conn.exec_driver_sql(
                    f"SELECT * FROM ({safe_sql}) AS nlq_result LIMIT {max_rows + 1}")
            except Exception as e:  # surfaced to the user next to the SQL so they can rephrase
                msg = str(getattr(e, "orig", e)).splitlines()[0]
                raise NLQError(f"Database rejected the query: {msg}", sql=safe_sql)
            columns = list(result.keys())
            rows = [list(r) for r in result.fetchall()]
    truncated = len(rows) > max_rows
    return {"columns": columns, "rows": rows[:max_rows], "row_count": min(len(rows), max_rows),
            "truncated": truncated}


def answer(engine: Engine, question: str, latest: date, translate: Translator = claude_translator,
           max_rows: int = config.NLQ_MAX_ROWS) -> dict:
    question = question.strip()
    if not question:
        raise NLQError("Type a question first.")
    if len(question) > 500:
        raise NLQError("Keep the question under 500 characters.")
    out = translate(question, latest)
    sql, explanation = (out.get("sql") or "").strip(), out.get("explanation", "")
    if not sql:
        raise NLQError(explanation or "That question can't be answered from the dashboard data.", 422)
    safe = validate_sql(sql)
    result = run_sql(engine, safe, max_rows)
    return {"question": question, "sql": sql, "executed_sql": safe, "explanation": explanation, **result}
