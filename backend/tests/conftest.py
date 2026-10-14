import os
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import anomaly, main, synth
from app.db import get_engine

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://pid:pid_local_dev@localhost:5434/pid_test")
END = date(2026, 10, 12)  # fixed so injected upsets land on known dates


@pytest.fixture(scope="session")
def engine():
    eng = get_engine(TEST_DATABASE_URL)
    synth.load(eng, END, days=35, seed=42)
    anomaly.refresh(eng)
    return eng


@pytest.fixture
def client(engine):
    main.app.dependency_overrides[main.engine] = lambda: engine
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()
