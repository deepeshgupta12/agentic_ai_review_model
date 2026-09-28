"""Shared fixtures. Integration tests use a real MongoDB replica set (docker compose up -d mongodb mongo-init)
and a fresh database per test; they fail, not skip, when MongoDB is unreachable."""

from __future__ import annotations

import os
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from pymongo import MongoClient
from pymongo.database import Database

from app.config import REPO_ROOT, Mode, Settings
from app.contracts import ContractStore

TEST_URI = os.environ.get("TEST_MONGODB_URI", "mongodb://localhost:27017/?replicaSet=rs0&directConnection=true")
sys.path.insert(0, str(REPO_ROOT / "scripts"))


@pytest.fixture(scope="session")
def contracts() -> ContractStore:
    return ContractStore(REPO_ROOT / "contracts" / "v1")


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        app_mode=Mode.FIXTURE,
        mongodb_uri=TEST_URI,
        session_secret=SecretStr("test-session-secret-" + "x" * 32),
        login_attempts_per_window=3,
        model_max_attempts=3,
    )


@pytest.fixture(scope="session")
def mongo_client() -> Iterator[MongoClient[dict[str, Any]]]:
    client: MongoClient[dict[str, Any]] = MongoClient(TEST_URI, tz_aware=True, serverSelectionTimeoutMS=3000)
    try:
        hello = client.admin.command("hello")
    except Exception as exc:
        pytest.fail(
            f"MongoDB is not reachable at {TEST_URI}: start it with `docker compose up -d mongodb mongo-init` ({exc})"
        )
    if not hello.get("setName"):
        pytest.fail("MongoDB must run as a replica set (transactions are required)")
    yield client
    client.close()


@pytest.fixture
def db(mongo_client: MongoClient[dict[str, Any]], contracts: ContractStore) -> Iterator[Database[dict[str, Any]]]:
    from app.setup.database import setup_database

    database = mongo_client[f"sy_poc_test_{uuid.uuid4().hex[:10]}"]
    setup_database(database, contracts)
    yield database
    mongo_client.drop_database(database.name)


@pytest.fixture
def raw_db(mongo_client: MongoClient[dict[str, Any]]) -> Iterator[Database[dict[str, Any]]]:
    """A fresh, empty database without setup (for setup tests)."""
    database = mongo_client[f"sy_poc_test_{uuid.uuid4().hex[:10]}"]
    yield database
    mongo_client.drop_database(database.name)


@pytest.fixture
def api(db: Database[dict[str, Any]], settings: Settings, contracts: ContractStore) -> Iterator[TestClient]:
    from app.api.deps import contracts_dep, db_dep, settings_dep
    from app.api.main import create_app

    app = create_app()
    app.dependency_overrides[db_dep] = lambda: db
    app.dependency_overrides[settings_dep] = lambda: settings
    app.dependency_overrides[contracts_dep] = lambda: contracts
    with TestClient(app) as client:
        yield client


PASSWORD = "correct-horse-battery-9"


@pytest.fixture
def make_user(db: Database[dict[str, Any]]) -> Any:
    from app.seed.users import seed_users

    def create(roles: list[str], email: str | None = None, password: str = PASSWORD) -> dict[str, Any]:
        email = email or f"{'-'.join(roles)}-{uuid.uuid4().hex[:6]}@example.test"
        seed_users(db, [{"email": email, "display_name": "Test User", "roles": roles}], password)
        user = db["users"].find_one({"email": email})
        assert user is not None
        return user

    return create


def login(api: TestClient, email: str, password: str = PASSWORD) -> dict[str, Any]:
    response = api.post("/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def fixture_path(*parts: str) -> Path:
    return REPO_ROOT.joinpath(*parts)
