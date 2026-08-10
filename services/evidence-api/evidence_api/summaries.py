from typing import Protocol

import httpx

from coaching_contracts import SessionSummaryCreate

from .config import Settings


class SummaryError(RuntimeError):
    code = "summary_error"


class SummaryConfigurationError(SummaryError):
    code = "summary_not_configured"


class SummaryProvider(Protocol):
    def summarize(
        self,
        *,
        session_id: str,
        title: str,
        transcript_revision_id: str,
        theme_count: int,
        entries: list[dict],
    ) -> SessionSummaryCreate: ...


class DisabledSummaryProvider:
    def summarize(self, **_) -> SessionSummaryCreate:
        raise SummaryConfigurationError(
            "session summaries are disabled; configure "
            "EVIDENCE_EXTRACTION_PROVIDER=http_json"
        )


class HttpJsonSummaryProvider:
    """Summarizes a session by calling the project-controlled gateway.

    Deliberately summarizes the ledger rather than the transcript: every
    headline then traces back to an entry that already carries verified
    evidence, instead of being a second, unciteable reading of the recording.
    """

    def __init__(self, settings: Settings) -> None:
        self.endpoint = settings.summary_endpoint
        self.api_key = settings.extraction_api_key
        self.timeout = settings.extraction_timeout_seconds

    def summarize(
        self,
        *,
        session_id: str,
        title: str,
        transcript_revision_id: str,
        theme_count: int,
        entries: list[dict],
    ) -> SessionSummaryCreate:
        if not self.endpoint or not self.api_key:
            raise SummaryConfigurationError(
                "http_json summaries require EVIDENCE_EXTRACTION_ENDPOINT and "
                "EVIDENCE_EXTRACTION_API_KEY"
            )
        request_body = {
            "schema_version": "coaching-ledger-v1",
            "session": {"id": session_id, "title": title},
            "transcript_revision_id": transcript_revision_id,
            "theme_count": theme_count,
            "entries": entries,
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
            return SessionSummaryCreate.model_validate(response.json())
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise SummaryError(f"session summary failed: {exc}") from exc


def create_summary_provider(settings: Settings) -> SummaryProvider:
    if settings.extraction_provider == "http_json":
        return HttpJsonSummaryProvider(settings)
    return DisabledSummaryProvider()
