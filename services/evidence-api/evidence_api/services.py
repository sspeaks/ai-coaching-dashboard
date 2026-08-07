import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from coaching_contracts import (
    EvidenceReference,
    JobResponse,
    JobStatus,
    JobType,
    LedgerEntryCreate,
    LedgerEntryResponse,
    SessionResponse,
    SessionState,
    TranscriptRevisionResponse,
    TranscriptSegment,
    VerificationStatus,
)
from media_adapter import MediaAdapter

from .models import (
    DeletionCompensationRecord,
    DeletionTombstoneRecord,
    JobRecord,
    LedgerEntryRecord,
    SessionRecord,
    TranscriptRevisionRecord,
)
from .state import transition
from .transcripts import normalize_speakr_segments, transcript_sha256

# Distinctive, non-retryable job/session error code used whenever a
# worker crash (or expired lease) leaves it unable to tell whether a
# non-idempotent provider write (Speakr upload, or an EXPLICIT-mode
# provider's queue_transcription) was actually accepted upstream before
# the crash. Never auto-retried -- see begin_pending_operation below.
AMBIGUOUS_OPERATION_ERROR_CODE = "ambiguous_provider_operation"


class EvidenceValidationError(ValueError):
    pass


def session_response(db: Session, record: SessionRecord) -> SessionResponse:
    ledger_filter = [
        LedgerEntryRecord.session_id == record.id,
        LedgerEntryRecord.transcript_revision_id
        == record.current_transcript_revision_id,
    ]
    ledger_entry_count = (
        db.scalar(select(func.count(LedgerEntryRecord.id)).where(*ledger_filter)) or 0
    )
    reviewed_ledger_entry_count = (
        db.scalar(
            select(func.count(LedgerEntryRecord.id)).where(
                *ledger_filter,
                LedgerEntryRecord.verification_status.in_(
                    [
                        VerificationStatus.VERIFIED.value,
                        VerificationStatus.REJECTED.value,
                    ]
                ),
            )
        )
        or 0
    )
    return SessionResponse(
        id=record.id,
        title=record.title,
        state=record.state,
        recorded_at=record.recorded_at,
        duration_ms=record.duration_ms,
        original_filename=record.original_filename,
        media_sha256=record.media_sha256,
        speakr_recording_id=record.speakr_recording_id,
        current_transcript_revision_id=record.current_transcript_revision_id,
        last_reconciled_at=record.last_reconciled_at,
        last_error=record.last_error,
        playback_url=(
            f"/api/sessions/{record.id}/media" if record.media_path else None
        ),
        ledger_entry_count=ledger_entry_count,
        reviewed_ledger_entry_count=reviewed_ledger_entry_count,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def job_response(record: JobRecord) -> JobResponse:
    return JobResponse(
        id=record.id,
        session_id=record.session_id,
        type=record.type,
        status=record.status,
        attempts=record.attempts,
        max_attempts=record.max_attempts,
        error_code=record.error_code,
        error_message=record.error_message,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def revision_response(record: TranscriptRevisionRecord) -> TranscriptRevisionResponse:
    return TranscriptRevisionResponse(
        id=record.id,
        session_id=record.session_id,
        sha256=record.sha256,
        segments=[TranscriptSegment.model_validate(item) for item in record.segments],
        source=record.source,
        created_at=record.created_at,
    )


def ledger_response(record: LedgerEntryRecord) -> LedgerEntryResponse:
    return LedgerEntryResponse(
        id=record.id,
        session_id=record.session_id,
        transcript_revision_id=record.transcript_revision_id,
        topic=record.topic,
        exact_coach_feedback=record.exact_coach_feedback,
        interpretation=record.interpretation,
        applies_to=record.applies_to,
        song_passage_measure=record.song_passage_measure,
        problem_heard_before=record.problem_heard_before,
        exercise_or_requested_change=record.exercise_or_requested_change,
        observed_result=record.observed_result,
        next_action_and_owner=record.next_action_and_owner,
        unresolved_question=record.unresolved_question,
        confidence=record.confidence_millis / 1000,
        evidence=[EvidenceReference.model_validate(item) for item in record.evidence],
        extraction_metadata=record.extraction_metadata or {},
        verification_status=record.verification_status,
        verified_by=record.verified_by,
        verified_at=record.verified_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def reconcile_transcript(
    db: Session,
    session_record: SessionRecord,
    adapter: MediaAdapter,
) -> tuple[TranscriptRevisionRecord, bool]:
    if not session_record.speakr_recording_id:
        raise EvidenceValidationError("session has no Speakr recording id")
    raw = adapter.get_transcript(session_record.speakr_recording_id)
    return reconcile_transcript_data(db, session_record, raw)


def reconcile_transcript_data(
    db: Session,
    session_record: SessionRecord,
    raw_segments: list[dict],
) -> tuple[TranscriptRevisionRecord, bool]:
    """Reconcile already-fetched provider data inside the caller's transaction."""

    segments = normalize_speakr_segments(raw_segments)
    digest = transcript_sha256(segments)
    existing = db.scalar(
        select(TranscriptRevisionRecord).where(
            TranscriptRevisionRecord.session_id == session_record.id,
            TranscriptRevisionRecord.sha256 == digest,
        )
    )
    session_record.last_reconciled_at = datetime.now(UTC)
    if existing:
        if SessionState(session_record.state) == SessionState.RECONCILING:
            statuses = set(
                db.scalars(
                    select(LedgerEntryRecord.verification_status).where(
                        LedgerEntryRecord.session_id == session_record.id,
                        LedgerEntryRecord.transcript_revision_id == existing.id,
                    )
                )
            )
            if not statuses:
                transition(session_record, SessionState.TRANSCRIPT_READY)
            elif statuses <= {
                VerificationStatus.VERIFIED.value,
                VerificationStatus.REJECTED.value,
            }:
                transition(session_record, SessionState.COMPLETE)
            else:
                transition(session_record, SessionState.AWAITING_REVIEW)
        return existing, False

    revision = TranscriptRevisionRecord(
        session_id=session_record.id,
        sha256=digest,
        segments=[segment.model_dump(mode="json") for segment in segments],
        source="speakr",
    )
    db.add(revision)
    db.flush()
    previous_revision_id = session_record.current_transcript_revision_id
    had_revision = previous_revision_id is not None
    session_record.current_transcript_revision_id = revision.id

    if SessionState(session_record.state) in {
        SessionState.TRANSCRIBING,
        SessionState.RECONCILING,
    }:
        transition(session_record, SessionState.TRANSCRIPT_READY)
    elif had_revision and SessionState(session_record.state) in {
        SessionState.AWAITING_REVIEW,
        SessionState.COMPLETE,
    }:
        if SessionState(session_record.state) == SessionState.COMPLETE:
            transition(session_record, SessionState.AWAITING_REVIEW)
    if had_revision:
        entries = db.scalars(
            select(LedgerEntryRecord).where(
                LedgerEntryRecord.session_id == session_record.id,
                LedgerEntryRecord.transcript_revision_id
                == previous_revision_id,
            )
        )
        for entry in entries:
            entry.verification_status = VerificationStatus.NEEDS_REVIEW.value
            entry.verified_by = None
            entry.verified_at = None
    return revision, True


def validate_evidence(
    db: Session,
    session_record: SessionRecord,
    entry: LedgerEntryCreate,
) -> None:
    referenced_text: list[str] = []
    revision_ids = {
        reference.transcript_revision_id for reference in entry.evidence
    }
    if len(revision_ids) != 1:
        raise EvidenceValidationError(
            "all evidence references in an entry must use one transcript revision"
        )
    if revision_ids != {session_record.current_transcript_revision_id}:
        raise EvidenceValidationError(
            "new ledger entries must reference the current transcript revision"
        )
    for reference in entry.evidence:
        revision = db.get(TranscriptRevisionRecord, reference.transcript_revision_id)
        if not revision or revision.session_id != session_record.id:
            raise EvidenceValidationError(
                "evidence transcript revision does not belong to the session"
            )
        if (
            session_record.duration_ms is not None
            and reference.end_ms > session_record.duration_ms
        ):
            raise EvidenceValidationError("evidence exceeds the recording duration")
        by_id = {
            segment["segment_id"]: TranscriptSegment.model_validate(segment)
            for segment in revision.segments
        }
        try:
            chosen = [by_id[segment_id] for segment_id in reference.segment_ids]
        except KeyError as exc:
            raise EvidenceValidationError(
                f"unknown evidence segment id: {exc.args[0]}"
            ) from exc
        if not all(
            segment.start_ms < reference.end_ms
            and segment.end_ms > reference.start_ms
            for segment in chosen
        ):
            raise EvidenceValidationError(
                "every referenced segment must overlap the evidence time range"
            )
        if reference.start_ms < min(item.start_ms for item in chosen):
            raise EvidenceValidationError(
                "evidence starts before its earliest referenced segment"
            )
        if reference.end_ms > max(item.end_ms for item in chosen):
            raise EvidenceValidationError(
                "evidence ends after its latest referenced segment"
            )
        # An evidence reference must cover the *entire* span of every
        # segment it cites, not merely overlap it. Without independently
        # validated word-level timestamps (not currently supported anywhere
        # in the contracts/backend), a sub-range like "9000-10000ms of a
        # 0-10000ms segment" cannot be trusted to represent what was
        # actually said in the full segment, and would let a reviewer's
        # quote be "anchored" against a misleadingly narrow slice of audio.
        if reference.start_ms > min(item.start_ms for item in chosen):
            raise EvidenceValidationError(
                "evidence must start at the beginning of its earliest "
                "referenced segment unless independently validated "
                "word-level timestamps are used"
            )
        if reference.end_ms < max(item.end_ms for item in chosen):
            raise EvidenceValidationError(
                "evidence must end at the end of its latest referenced "
                "segment unless independently validated word-level "
                "timestamps are used"
            )
        referenced_text.extend(segment.text for segment in chosen)

    if entry.exact_coach_feedback:
        quote = _normalize_text(entry.exact_coach_feedback)
        transcript = _normalize_text(" ".join(referenced_text))
        if quote not in transcript:
            raise EvidenceValidationError(
                "exact_coach_feedback is not present in referenced transcript text"
            )


def create_ledger_entry(
    db: Session,
    session_record: SessionRecord,
    entry: LedgerEntryCreate,
) -> LedgerEntryRecord:
    validate_evidence(db, session_record, entry)
    record = LedgerEntryRecord(
        session_id=session_record.id,
        transcript_revision_id=session_record.current_transcript_revision_id,
        topic=entry.topic,
        exact_coach_feedback=entry.exact_coach_feedback,
        interpretation=entry.interpretation,
        applies_to=entry.applies_to,
        song_passage_measure=entry.song_passage_measure,
        problem_heard_before=entry.problem_heard_before,
        exercise_or_requested_change=entry.exercise_or_requested_change,
        observed_result=entry.observed_result,
        next_action_and_owner=entry.next_action_and_owner,
        unresolved_question=entry.unresolved_question,
        confidence_millis=round(entry.confidence * 1000),
        evidence=[item.model_dump(mode="json") for item in entry.evidence],
        extraction_metadata=entry.extraction_metadata,
    )
    db.add(record)
    db.flush()
    return record


def ensure_job(
    db: Session,
    *,
    session_id: str,
    job_type: JobType,
    max_attempts: int,
) -> tuple[JobRecord, bool]:
    active = db.scalar(
        select(JobRecord).where(
            JobRecord.session_id == session_id,
            JobRecord.type == job_type.value,
            JobRecord.status.in_(
                [JobStatus.QUEUED.value, JobStatus.RUNNING.value]
            ),
        )
    )
    if active:
        return active, False
    job = JobRecord(
        session_id=session_id,
        type=job_type.value,
        max_attempts=max_attempts,
    )
    db.add(job)
    return job, True


def begin_pending_operation(session_record: SessionRecord, kind: str) -> str:
    """Persist a durable idempotency/operation marker on the session
    *before* a non-idempotent provider write call (Speakr upload, or an
    EXPLICIT-mode provider's queue_transcription). The caller must commit
    this in its own transaction before invoking the remote call, and clear
    it (see `clear_pending_operation`) only in the same commit that
    durably records that call's outcome (e.g. `speakr_recording_id` or
    `transcription_submitted_at`).

    If a worker process crashes after the provider accepts the call but
    before that clearing commit, this marker survives and lets recovery
    (`evidence_worker.worker.Worker.recover_abandoned_jobs`) recognize the
    operation as ambiguous instead of blindly retrying it -- Speakr's
    upload API has no idempotency key or lookup-by-key endpoint, so a
    blind retry could create a second, undiscoverable recording.
    """
    operation_id = str(uuid4())
    session_record.pending_operation_kind = kind
    session_record.pending_operation_id = operation_id
    session_record.pending_operation_started_at = datetime.now(UTC)
    return operation_id


def clear_pending_operation(session_record: SessionRecord) -> None:
    """Clear a pending-operation marker once its outcome has been durably
    recorded (success) or an operator has manually reconciled it."""
    session_record.pending_operation_kind = None
    session_record.pending_operation_id = None
    session_record.pending_operation_started_at = None


def record_deletion_intent(db: Session, session_id: str) -> DeletionTombstoneRecord:
    """Idempotently persist a tombstone marking `session_id` as pending
    deletion. Safe to call more than once -- both `request_deletion` and
    `confirm_deletion` call this so the tombstone always exists no later
    than the moment a session first enters DELETE_PENDING.

    The tombstone has no foreign key to the session row, so it remains
    queryable by session_id even after the session (and its cascade-linked
    jobs) have actually been deleted, which is what lets an in-flight
    worker in a separate transaction detect cancellation purely by
    session_id without depending on any row that might already be gone.
    """
    tombstone = db.get(DeletionTombstoneRecord, session_id)
    if tombstone is None:
        tombstone = DeletionTombstoneRecord(session_id=session_id)
        db.add(tombstone)
    return tombstone


def deletion_requested(db: Session, session_id: str) -> bool:
    """Cheap, dedicated existence check a worker can perform immediately
    before and after any remote provider call that creates state (e.g.
    uploading a recording), independent of whatever session/job objects it
    already holds in memory (which may be stale by the time a slow remote
    call returns)."""
    return (
        db.scalar(
            select(DeletionTombstoneRecord.session_id).where(
                DeletionTombstoneRecord.session_id == session_id
            )
        )
        is not None
    )


def ensure_deletion_compensation(
    db: Session,
    session_id: str,
    recording_id: str,
) -> DeletionCompensationRecord:
    """Persist provider cleanup before attempting it so remote IDs are never lost."""

    record_deletion_intent(db, session_id)
    compensation = db.scalar(
        select(DeletionCompensationRecord).where(
            DeletionCompensationRecord.session_id == session_id,
            DeletionCompensationRecord.recording_id == recording_id,
        )
    )
    if compensation is None:
        compensation = DeletionCompensationRecord(
            session_id=session_id,
            recording_id=recording_id,
        )
        db.add(compensation)
    return compensation


def has_pending_deletion_compensation(db: Session, session_id: str) -> bool:
    return (
        db.scalar(
            select(DeletionCompensationRecord.id).where(
                DeletionCompensationRecord.session_id == session_id,
                DeletionCompensationRecord.status != "SUCCEEDED",
            )
        )
        is not None
    )


def provider_deletion_not_found(exc: BaseException) -> bool:
    code = str(getattr(exc, "code", "")).casefold()
    message = str(exc).casefold()
    return code in {
        "not_found",
        "recording_not_found",
        "provider_not_found",
        "http_404",
    } or bool(re.search(r"\b404\b|not[_ -]found", f"{code} {message}"))


def record_deletion_compensation(
    db: Session, session_id: str, recording_id: str
) -> None:
    """Record that a provider recording created after cancellation was
    already requested has been compensated for (deleted from the
    provider), for audit/troubleshooting. Always succeeds even after the
    session row itself is gone, since the tombstone has no FK to it."""
    tombstone = db.get(DeletionTombstoneRecord, session_id)
    if tombstone is None:
        tombstone = DeletionTombstoneRecord(session_id=session_id)
        db.add(tombstone)
    tombstone.compensated_recording_id = recording_id
    tombstone.compensated_at = datetime.now(UTC)


def has_active_job(
    db: Session,
    session_id: str,
    lease_seconds: int,
    *,
    job_type: JobType | None = None,
) -> bool:
    """True if a job for this session is RUNNING and its lease (based on
    `updated_at`) has not yet expired -- i.e. a worker is presumed to
    still be actively holding it and may be mid-way through a remote call.
    Jobs whose lease has expired are treated as abandoned (the worker's own
    `recover_abandoned_jobs` sweep will requeue them), so deletion is
    allowed to proceed rather than waiting indefinitely on a dead worker.
    """
    cutoff = datetime.now(UTC) - timedelta(seconds=lease_seconds)
    query = select(JobRecord.id).where(
        JobRecord.session_id == session_id,
        JobRecord.status == JobStatus.RUNNING.value,
        JobRecord.updated_at >= cutoff,
    )
    if job_type is not None:
        query = query.where(JobRecord.type == job_type.value)
    return db.scalar(query) is not None


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()
