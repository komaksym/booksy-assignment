from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hardware_hub.config import Settings


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        tinydb_path=tmp_path / "hardware-hub.json",
        session_secret="test-session-secret-at-least-32-characters",
        bootstrap_admin_email="admin@booksy.test",
        bootstrap_admin_password="admin-password",
    )


@pytest.fixture
def app(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setenv("SESSION_SECRET", "import-session-secret-at-least-32-characters")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_EMAIL", "import-admin@booksy.test")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "import-admin-password")

    from hardware_hub.app import create_app

    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
