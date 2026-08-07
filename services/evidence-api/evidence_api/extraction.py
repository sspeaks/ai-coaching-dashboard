from typing import Protocol

import httpx

from coaching_contracts import LedgerEntryCreate, TranscriptSegment

from .config import Settings


class ExtractionError(RuntimeError):
    code = "extraction_error"


class ExtractionConfigurationError(ExtractionError):
    code = "extraction_not_configured"


class ExtractionProvider(Protocol):
    def extract(
        self,
        *,
        session_id: str,
        title: str,
        transcript_revision_id: str,
        segments: list[TranscriptSegment],
    ) -> list[LedgerEntryCreate]: ...


class DisabledExtractionProvider:
    def extract(self, **_) -> list[LedgerEntryCreate]:
        raise ExtractionConfigurationError(
            "structured extraction is disabled; configure "
            "EVIDENCE_EXTRACTION_PROVIDER=http_json"
        )


class HttpJsonExtractionProvider:
    """Calls a project-controlled structured extraction gateway."""

    def __init__(self, settings: Settings) -> None:
        self.endpoint = settings.extraction_endpoint
        self.api_key = settings.extraction_api_key
        self.timeout = settings.extraction_timeout_seconds

    def extract(
        self,
        *,
        session_id: str,
        title: str,
        transcript_revision_id: str,
        segments: list[TranscriptSegment],
    ) -> list[LedgerEntryCreate]:
        if not self.endpoint or not self.api_key:
            raise ExtractionConfigurationError(
                "http_json extraction requires EVIDENCE_EXTRACTION_ENDPOINT and "
                "EVIDENCE_EXTRACTION_API_KEY"
            )
        request_body = {
            "schema_version": "coaching-ledger-v1",
            "session": {"id": session_id, "title": title},
            "transcript_revision_id": transcript_revision_id,
            "timestamp_unit": "milliseconds",
            "instructions": [
                "Use only supplied transcript evidence.",
                "Never infer singer identity from singing, overlap, or provider labels.",
                "Never claim improvement unless explicitly evaluated in the transcript.",
                "Every entry must contain at least one timestamped evidence reference.",
                "Use null for absent facts and keep quotations separate from paraphrases.",
            ],
            "segments": [segment.model_dump(mode="json") for segment in segments],
        }
        try:
            response = httpx.post(
                self.endpoint,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=request_body,
                timeout=self.timeout,
                follow_redirects=False,
            )
            response.raise_for_status()
            payload = response.json()
            entries = payload["entries"]
            if not isinstance(entries, list):
                raise TypeError("entries is not a list")
            return [LedgerEntryCreate.model_validate(entry) for entry in entries]
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise ExtractionError(f"structured extraction failed: {exc}") from exc


def create_extraction_provider(settings: Settings) -> ExtractionProvider:
    if settings.extraction_provider == "http_json":
        return HttpJsonExtractionProvider(settings)
    return DisabledExtractionProvider()
