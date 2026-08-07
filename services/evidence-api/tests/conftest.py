import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from evidence_api.app import create_app
from evidence_api.config import Settings


@pytest.fixture
def settings() -> Settings:
    root = Path("services/evidence-api/tests/.runtime")
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    return Settings(
        environment="test",
        auth_mode="development",
        database_url=f"sqlite:///{root / 'evidence.db'}",
        media_root=root / "media",
        speakr_webhook_secret="test-webhook-secret",
        reconciliation_interval_seconds=3600,
    )


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    # Development auth mode now requires loopback-origin connections; the
    # default TestClient host ("testclient") is not loopback.
    with TestClient(app, client=("127.0.0.1", 50000)) as test_client:
        yield test_client
