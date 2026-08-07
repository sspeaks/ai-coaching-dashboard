from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from extraction_gateway.app import create_app
from extraction_gateway.config import Settings


class FakeOpenAIClient:
    def __init__(self, payload=None, exc: Exception | None = None) -> None:
        self.payload = payload
        self.exc = exc
        self.calls = []

    def extract_json(self, **kwargs):
        self.calls.append(kwargs)
        if self.exc:
            raise self.exc
        return self.payload


@pytest.fixture
def settings() -> Settings:
    return Settings(
        openai_api_key="test-openai-key",
        inbound_api_key="test-shared-gateway-token",
        request_timeout_seconds=5,
    )


@pytest.fixture
def segment():
    return {
        "segment_id": "seg-1",
        "start_ms": 1000,
        "end_ms": 2500,
        "text": "Coach: Lead, release the sound. That was cleaner after the change.",
        "provider_speaker_label": "SPEAKER_00",
    }


@pytest.fixture
def extraction_body(segment):
    return {
        "schema_version": "coaching-ledger-v1",
        "session": {"id": "session-1", "title": "Coaching session"},
        "transcript_revision_id": "revision-1",
        "timestamp_unit": "milliseconds",
        "instructions": [
            "Use only supplied transcript evidence.",
            "Never infer singer identity from singing, overlap, or provider labels.",
            "Every entry must contain at least one timestamped evidence reference.",
            "Use null for absent facts.",
        ],
        "segments": [segment],
    }


@pytest.fixture
def auth_headers(settings):
    return {"Authorization": f"Bearer {settings.inbound_api_key}"}


@contextmanager
def make_client(settings, payload=None, exc=None):
    fake = FakeOpenAIClient(payload=payload, exc=exc)
    with TestClient(create_app(settings, fake)) as client:
        yield client, fake
