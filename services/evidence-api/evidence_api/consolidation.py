from typing import Protocol

import httpx

from .config import Settings


class ConsolidationError(RuntimeError):
    code = "consolidation_error"


class ConsolidationConfigurationError(ConsolidationError):
    code = "consolidation_not_configured"


class ConsolidationResult:
    """Groups of entry IDs that represent the same coaching point."""

    def __init__(self, groups: list[dict]) -> None:
        self.groups = groups

    def entry_id_to_group_topic(self) -> dict[str, str]:
        """Map each entry ID to its canonical group topic."""
        mapping: dict[str, str] = {}
        for group in self.groups:
            for entry_id in group.get("entry_ids", []):
                mapping[entry_id] = group.get("canonical_topic", "")
        return mapping


class ConsolidationProvider(Protocol):
    def consolidate(
        self,
        *,
        session_id: str,
        title: str,
        entries: list[dict],
    ) -> ConsolidationResult: ...


class DisabledConsolidationProvider:
    def consolidate(self, **_) -> ConsolidationResult:
        raise ConsolidationConfigurationError(
            "consolidation is disabled; configure "
            "EVIDENCE_EXTRACTION_PROVIDER=http_json"
        )


class HttpJsonConsolidationProvider:
    """Consolidates ledger entries via the extraction gateway.

    This is the Option B two-pass approach: a separate model call clusters
    entries that represent the same coaching point before summarization.
    """

    def __init__(self, settings: Settings) -> None:
        self.endpoint = settings.consolidation_endpoint
        self.api_key = settings.extraction_api_key
        self.timeout = settings.extraction_timeout_seconds

    def consolidate(
        self,
        *,
        session_id: str,
        title: str,
        entries: list[dict],
    ) -> ConsolidationResult:
        if not self.endpoint or not self.api_key:
            raise ConsolidationConfigurationError(
                "http_json consolidation requires EVIDENCE_EXTRACTION_ENDPOINT and "
                "EVIDENCE_EXTRACTION_API_KEY"
            )
        request_body = {
            "schema_version": "coaching-ledger-v1",
            "session": {"id": session_id, "title": title},
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
            data = response.json()
            return ConsolidationResult(groups=data.get("groups", []))
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise ConsolidationError(f"consolidation failed: {exc}") from exc


def create_consolidation_provider(settings: Settings) -> ConsolidationProvider:
    if settings.extraction_provider == "http_json":
        return HttpJsonConsolidationProvider(settings)
    return DisabledConsolidationProvider()
