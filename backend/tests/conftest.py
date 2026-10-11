import os
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite:///./test_smart_operator.db"
os.environ["VERIFICATION_PROVIDER"] = "mock"
os.environ["EVIDENCE_DIR"] = "./test_evidence"

import pytest
from fastapi.testclient import TestClient

from app.db import Base, engine
from app.main import app, seed


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        Base.metadata.drop_all(engine)
        Base.metadata.create_all(engine)
        seed()
        yield test_client


@pytest.fixture(autouse=True)
def clean_evidence():
    directory = Path("./test_evidence")
    yield
    if directory.exists():
        for path in directory.iterdir():
            if path.is_file():
                path.unlink()
