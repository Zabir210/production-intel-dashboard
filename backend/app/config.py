"""Runtime settings. Every value that needs the owner's input lives in .env (see .env.example)."""
import os


def sqlalchemy_url(url: str) -> str:
    """Accept plain postgres:// URLs (as Neon and Vercel hand them out) and pin the psycopg 3 driver."""
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


DATABASE_URL = sqlalchemy_url(os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://pid:pid_local_dev@localhost:5434/pid"
))

# Read-only role the deployed app connects as. The seed grants it SELECT after every reload.
READER_ROLE = "pid_reader"

# Text-to-SQL model. Credentials come from ANTHROPIC_API_KEY (or ANTHROPIC_AUTH_TOKEN).
NLQ_MODEL = os.environ.get("NLQ_MODEL", "claude-opus-5-5")
NLQ_MAX_ROWS = int(os.environ.get("NLQ_MAX_ROWS", "500"))
NLQ_STATEMENT_TIMEOUT_MS = int(os.environ.get("NLQ_STATEMENT_TIMEOUT_MS", "5000"))

# Shift calendar: three 8-hour shifts, 30 minutes of planned breaks each.
SHIFTS = {"A": 6, "B": 14, "C": 22}  # shift letter -> start hour
SHIFT_MINUTES = 480
BREAK_MINUTES = 30
PLANNED_MINUTES = SHIFT_MINUTES - BREAK_MINUTES


def llm_configured() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
