import argparse
import hmac
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Literal

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError

from coaching_contracts import LedgerEntryCreate, TranscriptSegment

from .config import Settings, get_settings
from .openai_client import OpenAIClient, OpenAIClientError, OpenAITimeoutError

logger = logging.getLogger(__name__)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExtractionSession(StrictModel):
    id: str
    title: str


class ExtractionRequest(StrictModel):
    schema_version: Literal["coaching-ledger-v1"]
    session: ExtractionSession
    transcript_revision_id: str
    timestamp_unit: Literal["milliseconds"]
    instructions: list[str]
    segments: list[TranscriptSegment]


class ModelExtractionResponse(StrictModel):
    entries: list[LedgerEntryCreate]


class GatewayExtractionResponse(ModelExtractionResponse):
    model_entry_count: int
    rejected_entry_count: int


@dataclass(frozen=True)
class EntryRejection:
    reason: Literal["unknown_segment_id", "revision_mismatch", "range_mismatch"]
    topic: str
    segment_ids: list[str]


def _http_error(code: str, message: str, status_code: int) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message},
    )


def _authorize(
    settings: Settings, authorization: str | None = Header(default=None)
) -> None:
    if not settings.inbound_api_key:
        raise _http_error(
            "gateway_not_configured",
            "inbound bearer credential is not configured",
            status.HTTP_401_UNAUTHORIZED,
        )
    prefix = "Bearer "
    if not authorization or not authorization.startswith(prefix):
        raise _http_error(
            "unauthorized",
            "missing bearer token",
            status.HTTP_401_UNAUTHORIZED,
        )
    supplied = authorization[len(prefix) :]
    if not hmac.compare_digest(supplied, settings.inbound_api_key):
        raise _http_error(
            "unauthorized",
            "invalid bearer token",
            status.HTTP_401_UNAUTHORIZED,
        )


def _build_messages(body: ExtractionRequest) -> list[dict[str, str]]:
    payload = {
        "schema_version": body.schema_version,
        "session": body.session.model_dump(mode="json"),
        "transcript_revision_id": body.transcript_revision_id,
        "timestamp_unit": body.timestamp_unit,
        "instructions": body.instructions,
        "segments": [segment.model_dump(mode="json") for segment in body.segments],
    }
    return [
        {
            "role": "system",
            "content": (
                "Extract source-grounded coaching ledger entries from transcript "
                "segments. Return only JSON matching the supplied schema. Treat "
                "segment IDs and timestamps as evidence constraints. "
                "`exact_coach_feedback` must be copied character for character "
                "from the text of a cited segment -- never paraphrased, "
                "summarized, tidied up, or stitched together across segments. "
                "Use null whenever no such verbatim span exists."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        },
    ]


_SIGNIFICANT_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9'-]{2,}", re.IGNORECASE)
_SUPPORTED_APPLIES_TO_SHORT_VALUES = frozenset(
    {"lead", "tenor", "baritone", "bass", "coach"}
)


def _supported_by_evidence(
    value: str | None,
    evidence_text: str,
    *,
    allowed_short_values: frozenset[str] = frozenset(),
) -> bool:
    if value is None:
        return True
    # Deliberately blunt guardrail: this only checks lexical support in the
    # cited segments. It catches unsupported invented fields and trivial
    # one-word claims, but it is not a semantic entailment or probability check.
    value_tokens = set(_SIGNIFICANT_TOKEN_RE.findall(value.casefold()))
    evidence_tokens = set(_SIGNIFICANT_TOKEN_RE.findall(evidence_text.casefold()))
    if not value_tokens:
        return False
    if len(value_tokens) == 1:
        token = next(iter(value_tokens))
        return token in allowed_short_values and token in evidence_tokens
    return len(value_tokens & evidence_tokens) / len(value_tokens) >= 0.6


def _is_verbatim_quote(value: str | None, cited_text: list[str]) -> bool:
    if value is None:
        return True
    # Must match evidence-api's rule exactly: it rejects the whole extraction if
    # the quote is not a substring of the cited segment text, so anything this
    # lets through has to survive that check verbatim.
    quote = _normalize_quote_text(value)
    return bool(quote) and quote in _normalize_quote_text(" ".join(cited_text))


def _normalize_quote_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _normalize_entry(
    entry: LedgerEntryCreate, body: ExtractionRequest
) -> tuple[LedgerEntryCreate | None, EntryRejection | None]:
    segments_by_id = {segment.segment_id: segment for segment in body.segments}
    normalized_evidence: list[dict[str, Any]] = []
    cited_text: list[str] = []

    for evidence in entry.evidence:
        if evidence.transcript_revision_id != body.transcript_revision_id:
            return None, EntryRejection(
                "revision_mismatch",
                entry.topic,
                evidence.segment_ids,
            )
        cited_segments = []
        for segment_id in evidence.segment_ids:
            segment = segments_by_id.get(segment_id)
            if segment is None:
                return None, EntryRejection(
                    "unknown_segment_id",
                    entry.topic,
                    evidence.segment_ids,
                )
            cited_segments.append(segment)
            cited_text.append(segment.text)

        if any(
            evidence.start_ms >= segment.end_ms or evidence.end_ms <= segment.start_ms
            for segment in cited_segments
        ):
            return None, EntryRejection(
                "range_mismatch",
                entry.topic,
                evidence.segment_ids,
            )

        normalized_evidence.append(
            {
                "transcript_revision_id": body.transcript_revision_id,
                "start_ms": min(segment.start_ms for segment in cited_segments),
                "end_ms": max(segment.end_ms for segment in cited_segments),
                "segment_ids": evidence.segment_ids,
            }
        )

    evidence_text = "\n".join(cited_text)
    data = entry.model_dump(mode="json")
    data["evidence"] = normalized_evidence
    if not _is_verbatim_quote(entry.exact_coach_feedback, cited_text):
        # The model paraphrased rather than quoted. Storing a paraphrase in a
        # field that means "what the coach actually said" would fabricate a
        # quote, and evidence-api rejects the entire extraction over one such
        # entry. Drop the quote and keep the cited entry.
        data["exact_coach_feedback"] = None
    if not _supported_by_evidence(
        entry.applies_to,
        evidence_text,
        allowed_short_values=_SUPPORTED_APPLIES_TO_SHORT_VALUES,
    ):
        data["applies_to"] = None
    if not _supported_by_evidence(entry.observed_result, evidence_text):
        data["observed_result"] = None
    return LedgerEntryCreate.model_validate(data), None


def _coerce_entries(payload: Any, body: ExtractionRequest) -> GatewayExtractionResponse:
    try:
        response = ModelExtractionResponse.model_validate(payload)
    except ValidationError as exc:
        logger.warning("model response failed ledger validation errors=%s", exc.errors()[:3])
        raise _http_error(
            "invalid_model_response",
            f"model response did not match the ledger schema: {exc.errors()[0]['msg']}",
            status.HTTP_502_BAD_GATEWAY,
        ) from exc

    entries: list[LedgerEntryCreate] = []
    rejected_count = 0
    for entry in response.entries:
        normalized, rejection = _normalize_entry(entry, body)
        if normalized is not None:
            entries.append(normalized)
            continue
        rejected_count += 1
        if rejection:
            logger.warning(
                "rejected model ledger entry reason=%s topic=%r segment_ids=%s",
                rejection.reason,
                rejection.topic,
                rejection.segment_ids,
            )
    if response.entries and not entries:
        logger.warning(
            "all model ledger entries were rejected model_entry_count=%s",
            len(response.entries),
        )

    metadata = {
        "gateway_model_entry_count": len(response.entries),
        "gateway_rejected_entry_count": rejected_count,
    }
    entries = [
        entry.model_copy(
            update={
                "extraction_metadata": {
                    **entry.extraction_metadata,
                    **metadata,
                }
            }
        )
        for entry in entries
    ]
    return GatewayExtractionResponse(
        entries=entries,
        model_entry_count=len(response.entries),
        rejected_entry_count=rejected_count,
    )


def create_app(
    settings: Settings | None = None, openai_client: OpenAIClient | None = None
) -> FastAPI:
    settings = settings or get_settings()
    openai_client = openai_client or OpenAIClient(settings)
    app = FastAPI(title="Coaching Extraction Gateway", version="0.1.0")
    app.state.settings = settings
    app.state.openai_client = openai_client

    def require_bearer(authorization: str | None = Header(default=None)) -> None:
        _authorize(settings, authorization)

    @app.exception_handler(OpenAIClientError)
    async def openai_error_handler(_, exc: OpenAIClientError):
        status_code = (
            status.HTTP_504_GATEWAY_TIMEOUT
            if isinstance(exc, OpenAITimeoutError)
            else status.HTTP_502_BAD_GATEWAY
        )
        logger.warning("extraction upstream failure code=%s detail=%s", exc.code, exc)
        return JSONResponse(
            status_code=status_code,
            content={"detail": {"code": exc.code, "message": str(exc)}},
        )

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "openai_configured": bool(settings.openai_api_key),
            "model": settings.openai_model,
        }

    @app.post("/", response_model=GatewayExtractionResponse)
    @app.post("/extract", response_model=GatewayExtractionResponse)
    def extract(body: ExtractionRequest, _: None = Depends(require_bearer)):
        schema = ModelExtractionResponse.model_json_schema()
        payload = openai_client.extract_json(
            messages=_build_messages(body),
            schema=schema,
        )
        return _coerce_entries(payload, body)

    return app


app = create_app()


def run() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    uvicorn.run("extraction_gateway.app:app", host=args.host, port=args.port)


if __name__ == "__main__":
    run()
