from coaching_contracts import TranscriptSegment

from evidence_api.config import Settings
from evidence_api.extraction import HttpJsonExtractionProvider


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "entries": [
                {
                    "topic": "Release",
                    "confidence": 0.8,
                    "evidence": [
                        {
                            "transcript_revision_id": "revision-1",
                            "start_ms": 1000,
                            "end_ms": 2000,
                            "segment_ids": ["seg-1"],
                        }
                    ],
                }
            ],
            "model_entry_count": 1,
            "rejected_entry_count": 0,
        }


def test_http_json_extraction_tolerates_gateway_metadata(monkeypatch):
    calls = []

    def fake_post(*args, **kwargs):
        calls.append((args, kwargs))
        return FakeResponse()

    monkeypatch.setattr("evidence_api.extraction.httpx.post", fake_post)
    provider = HttpJsonExtractionProvider(
        Settings(
            environment="test",
            auth_mode="development",
            extraction_endpoint="http://gateway/",
            extraction_api_key="shared-key",
        )
    )

    entries = provider.extract(
        session_id="session-1",
        title="Coaching session",
        transcript_revision_id="revision-1",
        segments=[
            TranscriptSegment(
                segment_id="seg-1",
                start_ms=1000,
                end_ms=2000,
                text="Coach: release the sound.",
            )
        ],
    )

    assert len(entries) == 1
    assert entries[0].topic == "Release"
    assert calls
