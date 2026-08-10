import argparse
import hmac
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Literal

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, ValidationError

from coaching_contracts import (
    LedgerEntryCreate,
    SessionSummaryCreate,
    SummaryThemeCreate,
    TranscriptSegment,
)

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


class SummaryLedgerEntry(StrictModel):
    id: str
    topic: str
    exact_coach_feedback: str | None = None
    interpretation: str | None = None
    applies_to: str | None = None
    exercise_or_requested_change: str | None = None
    next_action_and_owner: str | None = None
    start_ms: int
    end_ms: int


class SummaryRequest(StrictModel):
    schema_version: Literal["coaching-ledger-v1"]
    session: ExtractionSession
    transcript_revision_id: str
    theme_count: int = 5
    entries: list[SummaryLedgerEntry]


class ModelSummaryResponse(StrictModel):
    themes: list[SummaryThemeCreate]


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


def _build_messages(
    body: ExtractionRequest, segments: list[TranscriptSegment]
) -> list[dict[str, str]]:
    payload = {
        "schema_version": body.schema_version,
        "session": body.session.model_dump(mode="json"),
        "transcript_revision_id": body.transcript_revision_id,
        "timestamp_unit": body.timestamp_unit,
        "instructions": body.instructions,
        "segments": [segment.model_dump(mode="json") for segment in segments],
    }
    return [
        {
            "role": "system",
            "content": (
                "Extract source-grounded coaching ledger entries from transcript "
                "segments. Return only JSON matching the supplied schema. Treat "
                "segment IDs and timestamps as evidence constraints. "
                "The segments are one window of a longer session; cover this "
                "window thoroughly and do not summarize it into a few entries. "
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


def _split_windows(
    segments: list[TranscriptSegment], *, size: int, overlap: int
) -> list[list[TranscriptSegment]]:
    """Split a transcript into overlapping windows.

    A whole session in a single request makes the model return a handful of
    entries covering a few minutes and silently ignore the rest, so the
    transcript is extracted a window at a time. Windows overlap so a coaching
    moment that straddles a boundary is still seen whole by one of them.
    """
    if len(segments) <= size:
        return [segments]
    step = size - overlap
    windows = []
    for start in range(0, len(segments), step):
        windows.append(segments[start : start + size])
        if start + size >= len(segments):
            break
    return windows


def _entry_identity(entry: LedgerEntryCreate) -> tuple[str, frozenset[str]]:
    # Overlapping windows see the same moment twice. Two entries are treated as
    # the same observation when they are about the same topic and rest on the
    # same segments; the quote is deliberately excluded because one window may
    # have quoted it and the other paraphrased.
    segment_ids = frozenset(
        segment_id
        for evidence in entry.evidence
        for segment_id in evidence.segment_ids
    )
    return _normalize_quote_text(entry.topic), segment_ids


def _coerce_entries(
    payloads: list[Any], body: ExtractionRequest
) -> GatewayExtractionResponse:
    entries: list[LedgerEntryCreate] = []
    seen: set[tuple[str, frozenset[str]]] = set()
    model_entry_count = 0
    rejected_count = 0
    duplicate_count = 0

    for payload in payloads:
        try:
            response = ModelExtractionResponse.model_validate(payload)
        except ValidationError as exc:
            logger.warning(
                "model response failed ledger validation errors=%s", exc.errors()[:3]
            )
            raise _http_error(
                "invalid_model_response",
                f"model response did not match the ledger schema: {exc.errors()[0]['msg']}",
                status.HTTP_502_BAD_GATEWAY,
            ) from exc

        model_entry_count += len(response.entries)
        for entry in response.entries:
            normalized, rejection = _normalize_entry(entry, body)
            if normalized is None:
                rejected_count += 1
                if rejection:
                    logger.warning(
                        "rejected model ledger entry reason=%s topic=%r segment_ids=%s",
                        rejection.reason,
                        rejection.topic,
                        rejection.segment_ids,
                    )
                continue
            identity = _entry_identity(normalized)
            if identity in seen:
                duplicate_count += 1
                continue
            seen.add(identity)
            entries.append(normalized)

    if model_entry_count and not entries:
        logger.warning(
            "all model ledger entries were rejected model_entry_count=%s",
            model_entry_count,
        )
    logger.info(
        "extraction complete windows=%s model_entries=%s kept=%s rejected=%s duplicates=%s",
        len(payloads),
        model_entry_count,
        len(entries),
        rejected_count,
        duplicate_count,
    )

    metadata = {
        "gateway_model_entry_count": model_entry_count,
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
        model_entry_count=model_entry_count,
        rejected_entry_count=rejected_count,
    )


def _build_summary_messages(body: SummaryRequest) -> list[dict[str, str]]:
    payload = {
        "session": body.session.model_dump(mode="json"),
        "theme_count": body.theme_count,
        "entries": [entry.model_dump(mode="json") for entry in body.entries],
    }
    return [
        {
            "role": "system",
            "content": (
                "You are summarizing one coaching session for the singers who "
                f"were in it. Group the supplied ledger entries into at most "
                f"{body.theme_count} themes, ordered with the most substantial "
                "first, so a reader can see at a glance what the coach actually "
                "worked on. Each theme needs a short specific title (name the "
                "actual vocal or musical issue, never a generic label like "
                "'Vocal Technique') and a few sentences describing what the "
                "coach asked for and why. Use only the supplied entries: every "
                "theme must list the ids of the entries it covers, every id "
                "must be one you were given, and each entry belongs to at most "
                "one theme. Prefer covering the whole session over describing "
                "any one theme exhaustively; it is fine to leave minor entries "
                "out of every theme."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        },
    ]


def _coerce_summary(payload: Any, body: SummaryRequest) -> SessionSummaryCreate:
    try:
        response = ModelSummaryResponse.model_validate(payload)
    except ValidationError as exc:
        logger.warning(
            "model summary failed validation errors=%s", exc.errors()[:3]
        )
        raise _http_error(
            "invalid_model_response",
            f"model response did not match the summary schema: {exc.errors()[0]['msg']}",
            status.HTTP_502_BAD_GATEWAY,
        ) from exc

    known_ids = {entry.id for entry in body.entries}
    themes: list[SummaryThemeCreate] = []
    claimed: set[str] = set()
    for theme in response.themes:
        # An id we did not supply is an invented citation, and the whole point
        # of summarizing the ledger rather than the transcript is that every
        # headline stays traceable to a verified entry.
        entry_ids = [
            entry_id
            for entry_id in theme.ledger_entry_ids
            if entry_id in known_ids and entry_id not in claimed
        ]
        dropped = len(theme.ledger_entry_ids) - len(entry_ids)
        if dropped:
            logger.warning(
                "dropped %s unusable entry ids from summary theme title=%r",
                dropped,
                theme.title,
            )
        if not entry_ids:
            logger.warning("discarded summary theme with no usable entries title=%r", theme.title)
            continue
        claimed.update(entry_ids)
        themes.append(theme.model_copy(update={"ledger_entry_ids": entry_ids}))

    themes = themes[: body.theme_count]
    logger.info(
        "summary complete session=%s entries=%s themes=%s covered_entries=%s",
        body.session.id,
        len(body.entries),
        len(themes),
        len(claimed),
    )
    return SessionSummaryCreate(themes=themes)


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
        windows = _split_windows(
            body.segments,
            size=settings.window_segment_count,
            overlap=settings.window_overlap_segments,
        )
        logger.info(
            "extracting session=%s segments=%s windows=%s",
            body.session.id,
            len(body.segments),
            len(windows),
        )

        def run_window(window: list[TranscriptSegment]) -> Any:
            return openai_client.extract_json(
                messages=_build_messages(body, window),
                schema=schema,
            )

        if len(windows) == 1:
            return _coerce_entries([run_window(windows[0])], body)

        # A window that fails is a silently missing stretch of the session,
        # which is the failure this windowing exists to prevent. Let the error
        # out of the pool so the job fails and can be retried whole.
        with ThreadPoolExecutor(max_workers=settings.window_concurrency) as pool:
            payloads = list(pool.map(run_window, windows))
        return _coerce_entries(payloads, body)

    @app.post("/summarize", response_model=SessionSummaryCreate)
    def summarize(body: SummaryRequest, _: None = Depends(require_bearer)):
        if not body.entries:
            return SessionSummaryCreate(themes=[])
        payload = openai_client.extract_json(
            messages=_build_summary_messages(body),
            schema=ModelSummaryResponse.model_json_schema(),
        )
        return _coerce_summary(payload, body)

    return app


app = create_app()


def run() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    # Without this the module logger has no handler above WARNING, so the
    # per-session coverage counts never reach the container log.
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    uvicorn.run("extraction_gateway.app:app", host=args.host, port=args.port)


if __name__ == "__main__":
    run()
