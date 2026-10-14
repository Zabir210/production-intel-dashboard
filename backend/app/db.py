from functools import lru_cache

from sqlalchemy import Engine, create_engine, text

from . import config

# Column comments double as the schema description handed to the text-to-SQL model.
SCHEMA_SQL = """
CREATE TABLE lines (
    line_id integer PRIMARY KEY,
    name text NOT NULL,                       -- e.g. 'Line 3 - Harness Assembly'
    part_number text NOT NULL                 -- the part family this line builds
);

CREATE TABLE stations (
    station_id integer PRIMARY KEY,
    line_id integer NOT NULL REFERENCES lines(line_id),
    seq integer NOT NULL,                     -- position in the line, 1 = first
    name text NOT NULL,
    std_cycle_min numeric NOT NULL            -- standard cycle time per unit, minutes
);

CREATE TABLE parts (
    part_number text PRIMARY KEY,             -- synthetic, e.g. 'SYN-3100'
    description text NOT NULL,
    std_hours numeric NOT NULL                -- standard (earned) labor hours per finished unit
);

CREATE TABLE shift_staffing (
    line_id integer NOT NULL REFERENCES lines(line_id),
    shift_date date NOT NULL,                 -- production day the shift belongs to
    shift char(1) NOT NULL,                   -- 'A' 06:00-14:00, 'B' 14:00-22:00, 'C' 22:00-06:00
    headcount integer NOT NULL,               -- operators on the line that shift
    planned_units integer NOT NULL,           -- target finished units for the shift
    PRIMARY KEY (line_id, shift_date, shift)
);

CREATE TABLE part_movements (
    movement_id bigserial PRIMARY KEY,
    serial_number text NOT NULL,              -- unit serial, e.g. 'SYN-3100-000123'
    part_number text NOT NULL REFERENCES parts(part_number),
    line_id integer NOT NULL REFERENCES lines(line_id),
    station_id integer NOT NULL REFERENCES stations(station_id),
    shift_date date NOT NULL,
    shift char(1) NOT NULL,
    started_at timestamp NOT NULL,            -- unit arrives and work starts at the station
    completed_at timestamp NOT NULL,          -- unit leaves the station
    cycle_min numeric NOT NULL,               -- actual touch time at the station, minutes
    queue_min numeric NOT NULL                -- wait before the station started the unit, minutes
);

CREATE TABLE nonconformances (
    nc_id serial PRIMARY KEY,
    serial_number text NOT NULL,
    part_number text NOT NULL REFERENCES parts(part_number),
    line_id integer NOT NULL REFERENCES lines(line_id),
    station_id integer NOT NULL REFERENCES stations(station_id),
    shift_date date NOT NULL,
    shift char(1) NOT NULL,
    detected_at timestamp NOT NULL,
    defect_code text NOT NULL,                -- e.g. 'DIM-OOT', 'CRIMP-PULL'
    description text NOT NULL,
    severity text NOT NULL,                   -- 'minor' | 'major' | 'critical'
    status text NOT NULL                      -- 'open' | 'dispositioned' | 'closed'
);

CREATE TABLE downtime_events (
    event_id serial PRIMARY KEY,
    line_id integer NOT NULL REFERENCES lines(line_id),
    station_id integer NOT NULL REFERENCES stations(station_id),
    shift_date date NOT NULL,
    shift char(1) NOT NULL,
    started_at timestamp NOT NULL,
    minutes numeric NOT NULL,
    reason text NOT NULL                      -- e.g. 'Tooling change', 'Material shortage'
);

CREATE TABLE anomalies (
    anomaly_id serial PRIMARY KEY,
    line_id integer NOT NULL REFERENCES lines(line_id),
    station_id integer NOT NULL REFERENCES stations(station_id),
    shift_date date NOT NULL,
    shift char(1) NOT NULL,
    score double precision NOT NULL,          -- Isolation Forest score; lower = more anomalous
    units integer NOT NULL,
    cycle_ratio double precision NOT NULL,    -- avg actual cycle / standard cycle
    avg_queue_min double precision NOT NULL,
    nc_count integer NOT NULL,
    downtime_min double precision NOT NULL,
    reason text NOT NULL
);

CREATE INDEX ON part_movements (shift_date, shift, line_id);
CREATE INDEX ON nonconformances (shift_date, line_id);
CREATE INDEX ON downtime_events (shift_date, line_id);
"""

TABLES = [
    "anomalies", "downtime_events", "nonconformances", "part_movements",
    "shift_staffing", "stations", "parts", "lines",
]


@lru_cache(maxsize=None)
def get_engine(url: str | None = None) -> Engine:
    # prepare_threshold=None: no server-side prepared statements, so Neon's pgbouncer pooler is safe.
    return create_engine(config.sqlalchemy_url(url or config.DATABASE_URL), pool_pre_ping=True,
                         pool_size=2, max_overflow=2, connect_args={"prepare_threshold": None})


def reset_schema(engine: Engine) -> None:
    with engine.begin() as conn:
        for t in TABLES:
            conn.execute(text(f"DROP TABLE IF EXISTS {t} CASCADE"))
        conn.exec_driver_sql(SCHEMA_SQL)


def grant_reader(engine: Engine) -> bool:
    """Re-grant SELECT to the read-only role (dropped tables lose their grants). No-op if it doesn't exist."""
    with engine.begin() as conn:
        exists = conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"),
                              {"r": config.READER_ROLE}).first()
        if exists:
            conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {config.READER_ROLE}"))
            conn.execute(text(f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {config.READER_ROLE}"))
    return bool(exists)
