"""One-time production database setup. Run from the repo root:

    .venv/bin/python scripts/neon_setup.py

Reads NEON_OWNER_URL from .env.neon, creates (or rotates) the read-only role pid_reader,
seeds synthetic data, re-grants SELECT, and writes the reader's pooled URL to .env.neon as
READER_URL. Nothing secret is printed.
"""
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from app import anomaly, config, synth  # noqa: E402
from app.db import get_engine, grant_reader  # noqa: E402

ENV = ROOT / ".env.neon"


def read_env() -> dict[str, str]:
    out = {}
    for line in ENV.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def main() -> None:
    from datetime import date

    env = read_env()
    owner = get_engine(env["NEON_OWNER_URL"])
    password = secrets.token_urlsafe(24)
    role = config.READER_ROLE
    with owner.begin() as c:
        exists = c.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}).first()
        verb = "ALTER" if exists else "CREATE"
        c.execute(text(f"{verb} ROLE {role} LOGIN PASSWORD '{password}'"))
        c.execute(text(f"ALTER ROLE {role} SET default_transaction_read_only = on"))
        c.execute(text(f"ALTER ROLE {role} SET statement_timeout = '15s'"))
        c.execute(text(f"GRANT CONNECT ON DATABASE {make_url(config.sqlalchemy_url(env['NEON_OWNER_URL'])).database} TO {role}"))
    print(f"{verb.lower()}d role {role}")

    counts = synth.load(owner, date.today(), days=35, seed=42)
    counts["anomalies"] = anomaly.refresh(owner)
    print("seeded:", ", ".join(f"{k}={v:,}" for k, v in counts.items()))
    assert grant_reader(owner)

    u = make_url(config.sqlalchemy_url(env["NEON_OWNER_URL"]))
    host = u.host.replace(".c-", "-pooler.c-", 1) if "-pooler" not in u.host else u.host
    reader = u.set(username=role, password=password, host=host)
    reader_url = reader.render_as_string(hide_password=False).replace("postgresql+psycopg://", "postgresql://")

    with get_engine(reader_url).connect() as c:
        n = c.execute(text("SELECT count(*) FROM part_movements")).scalar_one()
        ro = c.execute(text("SHOW default_transaction_read_only")).scalar_one()
    print(f"reader check: {n:,} movements visible, default_transaction_read_only={ro}")

    lines = [ln for ln in ENV.read_text().splitlines() if not ln.startswith("READER_URL=")]
    ENV.write_text("\n".join(lines + [f"READER_URL={reader_url}"]) + "\n")
    print("wrote READER_URL to .env.neon")


if __name__ == "__main__":
    main()
