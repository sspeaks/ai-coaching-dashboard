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
from pydantic import BaseModel, ConfigDict, Field, ValidationError

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
    theme_count: int | None = None
    pre_groups: list[dict[str, Any]] | None = None
    entries: list[SummaryLedgerEntry]


class ModelSummaryResponse(StrictModel):
    themes: list[SummaryThemeCreate]


class ConsolidationGroup(StrictModel):
    """A group of entry IDs that represent the same coaching point."""

    canonical_topic: str = Field(min_length=1, max_length=200)
    entry_ids: list[str] = Field(min_length=1)


class ModelConsolidationResponse(StrictModel):
    groups: list[ConsolidationGroup]


class ConsolidationRequest(StrictModel):
    schema_version: Literal["coaching-ledger-v1"]
    session: ExtractionSession
    entries: list[SummaryLedgerEntry]


class ConsolidationResponse(StrictModel):
    groups: list[ConsolidationGroup]
    ungrouped_entry_ids: list[str]


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


def _build_consolidation_messages(body: ConsolidationRequest) -> list[dict[str, str]]:
    payload = {
        "session": body.session.model_dump(mode="json"),
        "entries": [entry.model_dump(mode="json") for entry in body.entries],
    }
    return [
        {
            "role": "system",
            "content": (
                "You are grouping coaching ledger entries from one session. "
                "Two entries belong in the same group ONLY when they address "
                "the exact same technique for the same singer for the same "
                "reason — meaning the coach returned to the same correction "
                "later in the session.\n"
                "When in doubt whether two entries are the same point, keep "
                "them in SEPARATE groups. An extra group is acceptable; "
                "silently merging two distinct coaching corrections is not.\n"
                "Every entry must appear in exactly one group. A group may "
                "contain a single entry if that point was only addressed once.\n"
                "For each group, provide a short canonical_topic that names "
                "the specific coaching point in the coach's terms."
            ),
        },
        {
            "role": "user",
            "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        },
    ]


def _coerce_consolidation(
    payload: Any, body: ConsolidationRequest
) -> ConsolidationResponse:
    try:
        response = ModelConsolidationResponse.model_validate(payload)
    except ValidationError as exc:
        logger.warning(
            "model consolidation failed validation errors=%s", exc.errors()[:3]
        )
        raise _http_error(
            "invalid_model_response",
            f"model response did not match the consolidation schema: {exc.errors()[0]['msg']}",
            status.HTTP_502_BAD_GATEWAY,
        ) from exc

    known_ids = {entry.id for entry in body.entries}
    claimed: set[str] = set()
    groups: list[ConsolidationGroup] = []

    for group in response.groups:
        valid_ids = [eid for eid in group.entry_ids if eid in known_ids and eid not in claimed]
        if not valid_ids:
            continue
        claimed.update(valid_ids)
        groups.append(
            ConsolidationGroup(
                canonical_topic=group.canonical_topic,
                entry_ids=valid_ids,
            )
        )

    # Any entries the model forgot get their own singleton group
    ungrouped = [eid for eid in known_ids if eid not in claimed]
    for eid in ungrouped:
        entry = next(e for e in body.entries if e.id == eid)
        groups.append(
            ConsolidationGroup(canonical_topic=entry.topic, entry_ids=[eid])
        )

    logger.info(
        "consolidation complete session=%s entries=%s groups=%s ungrouped=%s",
        body.session.id,
        len(body.entries),
        len(groups),
        len(ungrouped),
    )
    return ConsolidationResponse(groups=groups, ungrouped_entry_ids=ungrouped)


def _build_summary_messages(body: SummaryRequest) -> list[dict[str, str]]:
    payload: dict[str, Any] = {
        "session": body.session.model_dump(mode="json"),
        "entries": [entry.model_dump(mode="json") for entry in body.entries],
    }
    if body.pre_groups:
        payload["pre_groups"] = body.pre_groups
    cap_instruction = (
        f"Return at most {body.theme_count} themes. "
        if body.theme_count
        else ""
    )
    grouping_instruction = (
        "A prior analysis has grouped the entries into clusters of "
        "related coaching points (provided in pre_groups). Use these "
        "clusters as your theme structure — one theme per group. You "
        "may split a group further if it clearly contains distinct "
        "points, but do not merge groups together.\n"
        if body.pre_groups
        else ""
    )
    return [
        {
            "role": "system",
            "content": (
                "You are summarizing one coaching session for the singers who "
                "were in it. Group the supplied ledger entries into themes — "
                "one theme per genuinely distinct coaching point. "
                + cap_instruction
                + grouping_instruction +
                "Order themes so the theme the coach "
                "spent the most of the session on comes first.\n"
                "Merge entries into the same theme ONLY when they address the "
                "same technique for the same singer for the same reason. When "
                "two mentions of the same correction appear at different times "
                "(coach returned to the same issue), include them in one theme "
                "with all their entry IDs. When in doubt whether two entries "
                "are the same point, keep them as separate themes — an extra "
                "theme is acceptable, a silently dropped coaching point is not.\n"
                "Titles must name the specific thing the coach worked on, in "
                "the coach's own terms: 'Disengaging the glottis on da-da' or "
                "'Aligning the E vowel in fill', never a filing-cabinet label "
                "like 'Vocal Technique', 'Performance Feedback' or 'Tempo and "
                "Dynamics'. If a title would fit any coaching session ever, it "
                "is the wrong title.\n"
                "The summary of each theme should say what the coach asked for, "
                "what it was meant to fix, and how it developed over the "
                "session.\n"
                "Assign every entry that records real coaching to exactly one "
                "theme. Leave an entry out only when it is pure logistics or "
                "chatter; a related entry belongs in the closest theme rather "
                "than nowhere. Themes may be large, and covering the whole "
                "session matters more than keeping them tidy.\n"
                "Use only the supplied entries: every id you cite must be one "
                "you were given."
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

    if body.theme_count:
        themes = themes[: body.theme_count]
    if len(themes) > 25:
        logger.warning(
            "summary returned %s themes (sanity max 25); truncating session=%s",
            len(themes),
            body.session.id,
        )
        themes = themes[:25]
    logger.info(
        "summary complete session=%s entries=%s themes=%s covered_entries=%s uncovered=%s",
        body.session.id,
        len(body.entries),
        len(themes),
        len(claimed),
        len(known_ids - claimed),
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

    @app.post("/consolidate", response_model=ConsolidationResponse)
    def consolidate(body: ConsolidationRequest, _: None = Depends(require_bearer)):
        if not body.entries:
            return ConsolidationResponse(groups=[], ungrouped_entry_ids=[])
        payload = openai_client.extract_json(
            messages=_build_consolidation_messages(body),
            schema=ModelConsolidationResponse.model_json_schema(),
        )
        return _coerce_consolidation(payload, body)

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
