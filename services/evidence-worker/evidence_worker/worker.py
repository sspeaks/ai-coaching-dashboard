import argparse
import time
from datetime import UTC, datetime, timedelta
from enum import Enum, auto
from pathlib import Path
from threading import Event, Thread
from typing import Callable, TypeVar

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.orm.exc import StaleDataError

from coaching_contracts import JobStatus, JobType, SessionState, TranscriptSegment
from media_adapter import (
    AdapterError,
    MediaAdapter,
    SpeakrHttpAdapter,
    TranscriptionSubmissionMode,
)

from evidence_api.config import Settings, get_settings
from evidence_api.db import (
    create_db_engine,
    create_session_factory,
    init_schema,
)
from evidence_api.extraction import (
    ExtractionError,
    ExtractionProvider,
    create_extraction_provider,
)
from evidence_api.summaries import (
    SummaryError,
    SummaryProvider,
    create_summary_provider,
)
from evidence_api.models import (
    DeletionCompensationRecord,
    JobRecord,
    LedgerEntryRecord,
    SessionRecord,
    SessionSummaryRecord,
    TranscriptRevisionRecord,
)
from evidence_api.services import (
    AMBIGUOUS_OPERATION_ERROR_CODE,
    begin_pending_operation,
    clear_pending_operation,
    create_ledger_entry,
    deletion_requested,
    ensure_job,
    ensure_deletion_compensation,
    provider_deletion_not_found,
    reconcile_transcript_data,
    record_deletion_compensation,
)
from evidence_api.state import transition


class TranscriptionPending(RuntimeError):
    code = "transcription_pending"


class TranscriptionFailed(RuntimeError):
    code = "transcription_failed"


class JobCancelled(RuntimeError):
    pass


class ProcessOutcome(Enum):
    """Explicit signal from `_process` telling `run_once` how (or
    whether) to finalize the job, so completion never depends on
    inferring intent from the job's row status after the fact.

    STEP_COMPLETED: `_process` finished this step's work without
        putting the job into a terminal state itself; `run_once` must
        still call `_complete_job` to mark it SUCCEEDED (which itself
        re-checks for a concurrent cancellation/deletion before doing
        so).
    ALREADY_FINALIZED: `_process` already left the job in a terminal
        state itself -- cancelled, or FAILED with
        `ambiguous_provider_operation` pending operator resolution --
        and `run_once` must not call `_complete_job` (or anything else
        that would finalize the job again), since doing so could
        overwrite that terminal state (e.g. clobbering an ambiguous
        FAILED job back to CANCELLED or SUCCEEDED).
    """

    STEP_COMPLETED = auto()
    ALREADY_FINALIZED = auto()


T = TypeVar("T")


class Worker:
    def __init__(
        self,
        settings: Settings,
        factory: sessionmaker[Session],
        *,
        adapter: MediaAdapter | None = None,
        extraction_provider: ExtractionProvider | None = None,
        summary_provider: SummaryProvider | None = None,
    ) -> None:
        self.settings = settings
        self.factory = factory
        self.adapter = adapter or SpeakrHttpAdapter(
            settings.speakr_base_url,
            settings.speakr_api_token,
            timeout_seconds=settings.speakr_timeout_seconds,
            verify_tls=settings.speakr_verify_tls,
        )
        self.extraction_provider = (
            extraction_provider or create_extraction_provider(settings)
        )
        self.summary_provider = summary_provider or create_summary_provider(settings)

    def run_once(self) -> bool:
        if self.retry_deletion_compensation():
            return True
        self.recover_abandoned_jobs()
        self.enqueue_scheduled_reconciliation()
        with self.factory() as db:
            now = datetime.now(UTC)
            job = db.scalar(
                select(JobRecord)
                .where(
                    JobRecord.status == JobStatus.QUEUED.value,
                    JobRecord.available_at <= now,
                )
                .order_by(JobRecord.created_at)
                .with_for_update(skip_locked=True)
            )
            if not job:
                return False
            job.status = JobStatus.RUNNING.value
            job.attempts += 1
            try:
                db.commit()
            except StaleDataError:
                db.rollback()
                return True
            job_id = job.id
            session_id = job.session_id

        with self.factory() as db:
            current = self._reload_current(db, job_id, session_id)
            if current is None:
                return True
            job, session_record = current
            if (
                deletion_requested(db, session_id)
                or job.status == JobStatus.CANCELLED.value
                or SessionState(session_record.state)
                in {SessionState.CANCELLED, SessionState.DELETE_PENDING}
            ):
                self._cancel_job(db, job_id)
                return True
            try:
                try:
                    outcome = self._process(db, job_id, session_id)
                    if outcome is ProcessOutcome.STEP_COMPLETED:
                        self._complete_job(db, job_id, session_id)
                    # ProcessOutcome.ALREADY_FINALIZED: `_process` already
                    # left the job in its correct terminal state (e.g.
                    # cancelled, or FAILED with
                    # ambiguous_provider_operation pending operator
                    # resolution) -- calling `_complete_job` here would
                    # incorrectly overwrite that state.
                except JobCancelled:
                    self._cancel_job(db, job_id)
                except TranscriptionPending as exc:
                    self._requeue_pending(
                        db,
                        job_id,
                        session_id,
                        exc.code,
                        str(exc),
                    )
                except (
                    TranscriptionFailed,
                    AdapterError,
                    ExtractionError,
                    SummaryError,
                    ValueError,
                    OSError,
                ) as exc:
                    code = getattr(exc, "code", "worker_error")
                    self._fail_job(db, job_id, session_id, code, str(exc))
            except StaleDataError:
                db.rollback()
                self._resolve_stale_processing(job_id, session_id)
            return True

    def _process(
        self, db: Session, job_id: str, session_id: str
    ) -> ProcessOutcome:
        current = self._checkpoint(db, job_id, session_id)
        if current is None:
            self._cancel_job(db, job_id)
            return ProcessOutcome.ALREADY_FINALIZED
        job, session_record = current
        job_type = JobType(job.type)
        if job_type == JobType.TRANSCRIBE:
            if SessionState(session_record.state) == SessionState.RETRY_PENDING:
                transition(session_record, SessionState.TRANSCRIBING)
                self._safe_commit(db)
            if not session_record.media_path:
                raise ValueError("session has no retained original media")
            if not session_record.speakr_recording_id:
                if session_record.pending_operation_kind == "upload" and not getattr(
                    self.adapter, "supports_upload_idempotency", False
                ):
                    # A previous attempt may have crashed after Speakr
                    # accepted the upload but before we recorded the
                    # result. Speakr has no idempotency key or
                    # lookup-by-key endpoint, so a blind retry here could
                    # create a second, undiscoverable recording -- this
                    # must be resolved by an operator, not auto-retried.
                    self._fail_ambiguous_operation(
                        db, job_id, session_id, session_record
                    )
                    return ProcessOutcome.ALREADY_FINALIZED
                media_path = Path(session_record.media_path)
                title = session_record.title
                if session_record.pending_operation_kind != "upload":
                    begin_pending_operation(session_record, "upload")
                    self._safe_commit(db)
                operation_id = session_record.pending_operation_id
                uploaded, job, session_record, cancelled = self._leased_provider_call(
                    db,
                    job_id,
                    session_id,
                    lambda: self.adapter.upload_recording(
                        media_path, title=title, client_operation_id=operation_id
                    ),
                )
                if cancelled:
                    self._compensate_orphan_recording(
                        session_id, uploaded.recording_id
                    )
                    self._cancel_job(db, job_id)
                    return ProcessOutcome.ALREADY_FINALIZED
                assert job is not None and session_record is not None
                session_record.speakr_recording_id = uploaded.recording_id
                clear_pending_operation(session_record)
                if (
                    uploaded.duration_seconds is not None
                    and session_record.duration_ms is None
                ):
                    session_record.duration_ms = round(
                        uploaded.duration_seconds * 1000
                    )
                self._safe_commit(db)
            current = self._checkpoint(db, job_id, session_id)
            if current is None:
                self._cancel_job(db, job_id)
                return ProcessOutcome.ALREADY_FINALIZED
            _, session_record = current
            if session_record.transcription_submitted_at is None:
                submission_mode = self.adapter.transcription_submission_mode
                if submission_mode == TranscriptionSubmissionMode.EXPLICIT:
                    no_idempotency = not getattr(
                        self.adapter, "supports_upload_idempotency", False
                    )
                    if (
                        session_record.pending_operation_kind
                        == "queue_transcription"
                        and no_idempotency
                    ):
                        self._fail_ambiguous_operation(
                            db, job_id, session_id, session_record
                        )
                        return ProcessOutcome.ALREADY_FINALIZED
                    recording_id = session_record.speakr_recording_id
                    if not recording_id:
                        raise ValueError("session has no Speakr recording id")
                    if (
                        session_record.pending_operation_kind
                        != "queue_transcription"
                    ):
                        begin_pending_operation(
                            session_record, "queue_transcription"
                        )
                        self._safe_commit(db)
                    operation_id = session_record.pending_operation_id
                    _, job, session_record, cancelled = (
                        self._leased_provider_call(
                            db,
                            job_id,
                            session_id,
                            lambda: self.adapter.queue_transcription(
                                recording_id, client_operation_id=operation_id
                            ),
                        )
                    )
                    if cancelled:
                        self._cancel_job(db, job_id)
                        return ProcessOutcome.ALREADY_FINALIZED
                    assert job is not None and session_record is not None
                    clear_pending_operation(session_record)
                elif submission_mode != TranscriptionSubmissionMode.ON_UPLOAD:
                    raise ValueError(
                        "adapter returned an unsupported transcription "
                        f"submission mode: {submission_mode}"
                    )
                session_record.transcription_submitted_at = datetime.now(UTC)
                self._safe_commit(db)
            current = self._checkpoint(db, job_id, session_id)
            if current is None:
                self._cancel_job(db, job_id)
                return ProcessOutcome.ALREADY_FINALIZED
            ensure_job(
                db,
                session_id=session_id,
                job_type=JobType.RECONCILE,
                max_attempts=self.settings.worker_max_attempts,
            )
            self._safe_commit(db)
            return ProcessOutcome.STEP_COMPLETED
        elif job_type == JobType.RECONCILE:
            if SessionState(session_record.state) in {
                SessionState.TRANSCRIBING,
                SessionState.TRANSCRIPT_READY,
                SessionState.AWAITING_REVIEW,
                SessionState.COMPLETE,
                SessionState.RETRY_PENDING,
            }:
                transition(session_record, SessionState.RECONCILING)
                self._safe_commit(db)
                current = self._checkpoint(db, job_id, session_id)
                if current is None:
                    self._cancel_job(db, job_id)
                    return ProcessOutcome.ALREADY_FINALIZED
                _, session_record = current
            if not session_record.speakr_recording_id:
                raise ValueError("session has no Speakr recording id")
            recording_id = session_record.speakr_recording_id
            recording, job, session_record, cancelled = self._leased_provider_call(
                db,
                job_id,
                session_id,
                lambda: self.adapter.get_recording(recording_id),
            )
            if cancelled:
                self._cancel_job(db, job_id)
                return ProcessOutcome.ALREADY_FINALIZED
            assert job is not None and session_record is not None
            status = recording.status.strip().upper()
            if recording.duration_seconds is not None:
                session_record.duration_ms = round(
                    recording.duration_seconds * 1000
                )
                self._safe_commit(db)
            if status in {"FAILED", "ERROR", "CANCELLED"}:
                raise TranscriptionFailed(
                    f"Speakr transcription ended with status {status}"
                )
            if status not in {
                "COMPLETED",
                "COMPLETE",
                "TRANSCRIBED",
                "READY",
                "DONE",
            }:
                raise TranscriptionPending(
                    f"Speakr transcription status is {status or 'UNKNOWN'}"
                )
            raw_segments, job, session_record, cancelled = (
                self._leased_provider_call(
                    db,
                    job_id,
                    session_id,
                    lambda: self.adapter.get_transcript(recording_id),
                )
            )
            if cancelled:
                self._cancel_job(db, job_id)
                return ProcessOutcome.ALREADY_FINALIZED
            assert job is not None and session_record is not None
            revision, _ = reconcile_transcript_data(
                db, session_record, raw_segments
            )
            current_entries = db.scalar(
                select(LedgerEntryRecord.id).where(
                    LedgerEntryRecord.session_id == session_id,
                    LedgerEntryRecord.transcript_revision_id == revision.id,
                )
            )
            if current_entries is None:
                ensure_job(
                    db,
                    session_id=session_id,
                    job_type=JobType.EXTRACT,
                    max_attempts=self.settings.worker_max_attempts,
                )
            self._safe_commit(db)
            return ProcessOutcome.STEP_COMPLETED
        elif job_type == JobType.EXTRACT:
            if SessionState(session_record.state) == SessionState.RETRY_PENDING:
                transition(session_record, SessionState.EXTRACTING)
            elif SessionState(session_record.state) in {
                SessionState.TRANSCRIPT_READY,
                SessionState.AWAITING_REVIEW,
            }:
                transition(session_record, SessionState.EXTRACTING)
            self._safe_commit(db)
            current = self._checkpoint(db, job_id, session_id)
            if current is None:
                self._cancel_job(db, job_id)
                return ProcessOutcome.ALREADY_FINALIZED
            _, session_record = current
            revision = db.get(
                TranscriptRevisionRecord,
                session_record.current_transcript_revision_id,
            )
            if not revision or revision.session_id != session_record.id:
                raise ValueError("current transcript revision is missing")
            existing = db.scalar(
                select(LedgerEntryRecord.id).where(
                    LedgerEntryRecord.session_id == session_record.id,
                    LedgerEntryRecord.transcript_revision_id == revision.id,
                )
            )
            if existing is not None:
                transition(session_record, SessionState.AWAITING_REVIEW)
                self._safe_commit(db)
                return ProcessOutcome.STEP_COMPLETED
            title = session_record.title
            revision_id = revision.id
            segments = [
                TranscriptSegment.model_validate(item) for item in revision.segments
            ]
            entries, job, session_record, cancelled = self._leased_provider_call(
                db,
                job_id,
                session_id,
                lambda: self.extraction_provider.extract(
                    session_id=session_id,
                    title=title,
                    transcript_revision_id=revision_id,
                    segments=segments,
                ),
            )
            if cancelled:
                self._cancel_job(db, job_id)
                return ProcessOutcome.ALREADY_FINALIZED
            assert job is not None and session_record is not None
            transition(session_record, SessionState.AWAITING_REVIEW)
            for entry in entries:
                create_ledger_entry(db, session_record, entry)
            if entries:
                ensure_job(
                    db,
                    session_id=session_id,
                    job_type=JobType.SUMMARIZE,
                    max_attempts=self.settings.worker_max_attempts,
                )
            self._safe_commit(db)
            return ProcessOutcome.STEP_COMPLETED
        elif job_type == JobType.SUMMARIZE:
            revision = db.get(
                TranscriptRevisionRecord,
                session_record.current_transcript_revision_id,
            )
            if not revision or revision.session_id != session_record.id:
                raise ValueError("current transcript revision is missing")
            records = list(
                db.scalars(
                    select(LedgerEntryRecord)
                    .where(
                        LedgerEntryRecord.session_id == session_record.id,
                        LedgerEntryRecord.transcript_revision_id == revision.id,
                    )
                    .order_by(LedgerEntryRecord.created_at)
                )
            )
            if not records:
                # Nothing to summarize is a no-op, not a failure: the session
                # simply has no ledger yet.
                return ProcessOutcome.STEP_COMPLETED
            spans = {record.id: _entry_span(record) for record in records}
            title = session_record.title
            revision_id = revision.id
            source_updated_at = max(record.updated_at for record in records)
            entry_payload = [
                {
                    "id": record.id,
                    "topic": record.topic,
                    "exact_coach_feedback": record.exact_coach_feedback,
                    "interpretation": record.interpretation,
                    "applies_to": record.applies_to,
                    "exercise_or_requested_change": record.exercise_or_requested_change,
                    "next_action_and_owner": record.next_action_and_owner,
                    "start_ms": spans[record.id][0],
                    "end_ms": spans[record.id][1],
                }
                for record in records
            ]
            summary, job, session_record, cancelled = self._leased_provider_call(
                db,
                job_id,
                session_id,
                lambda: self.summary_provider.summarize(
                    session_id=session_id,
                    title=title,
                    transcript_revision_id=revision_id,
                    theme_count=self.settings.summary_theme_count,
                    entries=entry_payload,
                ),
            )
            if cancelled:
                self._cancel_job(db, job_id)
                return ProcessOutcome.ALREADY_FINALIZED
            assert session_record is not None
            themes = []
            for rank, theme in enumerate(summary.themes, start=1):
                covered = [spans[entry_id] for entry_id in theme.ledger_entry_ids]
                themes.append(
                    {
                        **theme.model_dump(mode="json"),
                        "rank": rank,
                        # Where the theme happened is taken from its entries, so
                        # it always points at real transcript positions.
                        "start_ms": min(span[0] for span in covered),
                        "end_ms": max(span[1] for span in covered),
                    }
                )
            _store_summary(
                db,
                session_id=session_record.id,
                transcript_revision_id=revision_id,
                themes=themes,
                entry_count=len(records),
                source_updated_at=source_updated_at,
            )
            # The summary is derived from the ledger, not a step towards review,
            # so it deliberately leaves session state alone.
            self._safe_commit(db)
            return ProcessOutcome.STEP_COMPLETED
        # Unrecognized job types cannot happen (JobType(job.type) above
        # would already have raised), but keep the return type honest for
        # static analysis rather than implicitly returning None.
        raise AssertionError(f"unhandled job type: {job_type}")

    def _reload_current(
        self,
        db: Session,
        job_id: str,
        session_id: str,
    ) -> tuple[JobRecord, SessionRecord] | None:
        db.rollback()
        job = db.get(JobRecord, job_id, populate_existing=True)
        session_record = db.get(SessionRecord, session_id, populate_existing=True)
        if job is None or session_record is None:
            db.rollback()
            return None
        return job, session_record

    def _checkpoint(
        self,
        db: Session,
        job_id: str,
        session_id: str,
    ) -> tuple[JobRecord, SessionRecord] | None:
        current = self._reload_current(db, job_id, session_id)
        if current is None or deletion_requested(db, session_id):
            db.rollback()
            return None
        job, session_record = current
        if (
            job.status != JobStatus.RUNNING.value
            or SessionState(session_record.state)
            in {
                SessionState.CANCELLED,
                SessionState.DELETE_PENDING,
                SessionState.DELETED,
            }
        ):
            db.rollback()
            return None
        job.updated_at = datetime.now(UTC)
        if not self._safe_commit(db):
            return None
        current = self._reload_current(db, job_id, session_id)
        if current is None or deletion_requested(db, session_id):
            db.rollback()
            return None
        return current

    def _reload_after_remote(
        self,
        db: Session,
        job_id: str,
        session_id: str,
    ) -> tuple[JobRecord | None, SessionRecord | None, bool]:
        db.rollback()
        tombstoned = deletion_requested(db, session_id)
        job = db.get(JobRecord, job_id, populate_existing=True)
        session_record = db.get(SessionRecord, session_id, populate_existing=True)
        cancelled = (
            tombstoned
            or job is None
            or session_record is None
            or job.status != JobStatus.RUNNING.value
            or (
                session_record is not None
                and SessionState(session_record.state)
                in {
                    SessionState.CANCELLED,
                    SessionState.DELETE_PENDING,
                    SessionState.DELETED,
                }
            )
        )
        return job, session_record, cancelled

    def _leased_provider_call(
        self,
        db: Session,
        job_id: str,
        session_id: str,
        call: Callable[[], T],
    ) -> tuple[T, JobRecord | None, SessionRecord | None, bool]:
        if self._checkpoint(db, job_id, session_id) is None:
            raise JobCancelled
        stop = Event()
        heartbeat = Thread(
            target=self._heartbeat_job_lease,
            args=(job_id, stop),
            name=f"job-lease-{job_id}",
            daemon=True,
        )
        heartbeat.start()
        try:
            result = call()
        except Exception:
            stop.set()
            heartbeat.join()
            self._reload_after_remote(db, job_id, session_id)
            raise
        stop.set()
        heartbeat.join()
        job, session_record, cancelled = self._reload_after_remote(
            db, job_id, session_id
        )
        return result, job, session_record, cancelled

    def _heartbeat_job_lease(self, job_id: str, stop: Event) -> None:
        interval = min(
            max(self.settings.worker_job_lease_seconds / 3, 0.05),
            5.0,
        )
        while not stop.wait(interval):
            if not self._renew_job_lease(job_id):
                return

    def _renew_job_lease(self, job_id: str) -> bool:
        try:
            with self.factory() as lease_db:
                result = lease_db.execute(
                    update(JobRecord)
                    .where(
                        JobRecord.id == job_id,
                        JobRecord.status == JobStatus.RUNNING.value,
                    )
                    .values(updated_at=datetime.now(UTC))
                )
                lease_db.commit()
                return result.rowcount > 0
        except Exception:
            return True

    def _safe_commit(self, db: Session) -> bool:
        try:
            db.commit()
            return True
        except StaleDataError:
            db.rollback()
            raise

    def _resolve_stale_processing(self, job_id: str, session_id: str) -> None:
        """Recover a processing transaction that lost an optimistic race."""

        for _ in range(3):
            with self.factory() as recovery_db:
                tombstoned = deletion_requested(recovery_db, session_id)
                job = recovery_db.get(JobRecord, job_id, populate_existing=True)
                session_record = recovery_db.get(
                    SessionRecord, session_id, populate_existing=True
                )
                if job is None or job.status != JobStatus.RUNNING.value:
                    return
                cancelled = tombstoned or session_record is None or (
                    SessionState(session_record.state)
                    in {
                        SessionState.CANCELLED,
                        SessionState.DELETE_PENDING,
                        SessionState.DELETED,
                    }
                )
                if cancelled:
                    job.status = JobStatus.CANCELLED.value
                else:
                    message = (
                        "processing lost an optimistic concurrency race; "
                        "the transaction was rolled back before retry"
                    )
                    ambiguous = (
                        JobType(job.type) == JobType.TRANSCRIBE
                        and session_record.pending_operation_kind is not None
                        and not getattr(
                            self.adapter,
                            "supports_upload_idempotency",
                            False,
                        )
                    )
                    if ambiguous:
                        operation_id = session_record.pending_operation_id
                        job.status = JobStatus.FAILED.value
                        job.error_code = AMBIGUOUS_OPERATION_ERROR_CODE
                        job.ambiguous_operation_id = operation_id
                        job.error_message = (
                            "processing lost a concurrency race while a "
                            "non-idempotent provider operation was pending; "
                            f"operation {operation_id} requires manual "
                            "reconciliation"
                        )
                        if SessionState(session_record.state) in {
                            SessionState.TRANSCRIBING,
                            SessionState.RETRY_PENDING,
                        }:
                            transition(session_record, SessionState.FAILED)
                        session_record.last_error = (
                            f"{AMBIGUOUS_OPERATION_ERROR_CODE}: operation "
                            f"{operation_id} requires manual reconciliation"
                        )
                    elif job.attempts < job.max_attempts:
                        job.status = JobStatus.QUEUED.value
                        job.error_code = "concurrent_update"
                        job.error_message = message
                        job.available_at = datetime.now(UTC) + timedelta(
                            seconds=self.settings.worker_transcription_poll_seconds
                        )
                        if SessionState(session_record.state) in {
                            SessionState.TRANSCRIBING,
                            SessionState.RECONCILING,
                            SessionState.EXTRACTING,
                        }:
                            transition(session_record, SessionState.RETRY_PENDING)
                    else:
                        job.status = JobStatus.FAILED.value
                        job.error_code = "concurrent_update"
                        job.error_message = message
                        if SessionState(session_record.state) in {
                            SessionState.TRANSCRIBING,
                            SessionState.RECONCILING,
                            SessionState.EXTRACTING,
                            SessionState.RETRY_PENDING,
                        }:
                            transition(session_record, SessionState.FAILED)
                        session_record.last_error = (
                            f"concurrent_update: {message}"
                        )
                try:
                    recovery_db.commit()
                    return
                except StaleDataError:
                    recovery_db.rollback()

        with self.factory() as recovery_db:
            tombstoned = deletion_requested(recovery_db, session_id)
            job = recovery_db.get(JobRecord, job_id)
            session_record = recovery_db.get(SessionRecord, session_id)
            if job is None or job.status != JobStatus.RUNNING.value:
                return
            cancelled = tombstoned or session_record is None or (
                SessionState(session_record.state)
                in {
                    SessionState.CANCELLED,
                    SessionState.DELETE_PENDING,
                    SessionState.DELETED,
                }
            )
            ambiguous = (
                not cancelled
                and JobType(job.type) == JobType.TRANSCRIBE
                and session_record.pending_operation_kind is not None
                and not getattr(
                    self.adapter,
                    "supports_upload_idempotency",
                    False,
                )
            )
            target = (
                JobStatus.CANCELLED.value
                if cancelled
                else JobStatus.FAILED.value
                if ambiguous
                else (
                    JobStatus.QUEUED.value
                    if job.attempts < job.max_attempts
                    else JobStatus.FAILED.value
                )
            )
            values = {
                "status": target,
                "error_code": (
                    AMBIGUOUS_OPERATION_ERROR_CODE
                    if ambiguous
                    else "concurrent_update"
                ),
                "error_message": (
                    "a non-idempotent provider operation requires manual "
                    "reconciliation"
                    if ambiguous
                    else (
                        "processing repeatedly lost an optimistic concurrency "
                        "race; transaction rolled back"
                    )
                ),
            }
            if ambiguous:
                values["ambiguous_operation_id"] = (
                    session_record.pending_operation_id
                )
            if target == JobStatus.QUEUED.value:
                values["available_at"] = datetime.now(UTC) + timedelta(
                    seconds=self.settings.worker_transcription_poll_seconds
                )
            recovery_db.execute(
                update(JobRecord)
                .where(
                    JobRecord.id == job_id,
                    JobRecord.status == JobStatus.RUNNING.value,
                )
                .values(**values)
            )
            recovery_db.commit()

    def _cancel_job(self, db: Session, job_id: str) -> None:
        db.rollback()
        fresh = db.get(JobRecord, job_id, populate_existing=True)
        if fresh is None:
            db.rollback()
            return
        fresh.status = JobStatus.CANCELLED.value
        self._safe_commit(db)

    def _complete_job(self, db: Session, job_id: str, session_id: str) -> None:
        job, session_record, cancelled = self._reload_after_remote(
            db, job_id, session_id
        )
        if cancelled or job is None or session_record is None:
            self._cancel_job(db, job_id)
            return
        job.status = JobStatus.SUCCEEDED.value
        job.error_code = None
        job.error_message = None
        session_record.last_error = None
        self._safe_commit(db)

    def _requeue_pending(
        self,
        db: Session,
        job_id: str,
        session_id: str,
        code: str,
        message: str,
    ) -> None:
        job, session_record, cancelled = self._reload_after_remote(
            db, job_id, session_id
        )
        if cancelled or job is None or session_record is None:
            self._cancel_job(db, job_id)
            return
        job.status = JobStatus.QUEUED.value
        job.attempts = max(0, job.attempts - 1)
        job.error_code = code
        job.error_message = message[:4000]
        job.available_at = datetime.now(UTC) + timedelta(
            seconds=self.settings.worker_transcription_poll_seconds
        )
        self._safe_commit(db)

    def _compensate_orphan_recording(
        self,
        session_id: str,
        recording_id: str,
    ) -> bool:
        with self.factory() as compensation_db:
            compensation = ensure_deletion_compensation(
                compensation_db,
                session_id,
                recording_id,
            )
            try:
                compensation_db.commit()
            except IntegrityError:
                compensation_db.rollback()
                compensation = compensation_db.scalar(
                    select(DeletionCompensationRecord).where(
                        DeletionCompensationRecord.session_id == session_id,
                        DeletionCompensationRecord.recording_id == recording_id,
                    )
                )
                if compensation is None:
                    raise
            compensation_id = compensation.id
        return self._attempt_deletion_compensation(compensation_id)

    def retry_deletion_compensation(self) -> bool:
        with self.factory() as db:
            compensation = db.scalar(
                select(DeletionCompensationRecord)
                .where(
                    DeletionCompensationRecord.status.in_(["PENDING", "FAILED"]),
                    DeletionCompensationRecord.available_at <= datetime.now(UTC),
                )
                .order_by(DeletionCompensationRecord.created_at)
                .with_for_update(skip_locked=True)
            )
            if compensation is None:
                return False
            compensation_id = compensation.id
        self._attempt_deletion_compensation(compensation_id)
        return True

    def _attempt_deletion_compensation(self, compensation_id: str) -> bool:
        with self.factory() as db:
            compensation = db.get(DeletionCompensationRecord, compensation_id)
            if compensation is None:
                return True
            if compensation.status == "SUCCEEDED":
                return True
            compensation.status = "PENDING"
            compensation.attempts += 1
            recording_id = compensation.recording_id
            session_id = compensation.session_id
            attempts = compensation.attempts
            db.commit()
        try:
            self.adapter.delete_recording(recording_id)
        except Exception as exc:
            if not provider_deletion_not_found(exc):
                with self.factory() as db:
                    compensation = db.get(
                        DeletionCompensationRecord, compensation_id
                    )
                    if compensation is not None:
                        compensation.status = "FAILED"
                        compensation.error_code = getattr(
                            exc, "code", "compensation_error"
                        )
                        compensation.error_message = str(exc)[:4000]
                        compensation.available_at = datetime.now(UTC) + timedelta(
                            seconds=min(
                                self.settings.worker_transcription_poll_seconds
                                * (2 ** max(0, attempts - 1)),
                                300,
                            )
                        )
                        db.commit()
                return False
        with self.factory() as db:
            compensation = db.get(DeletionCompensationRecord, compensation_id)
            if compensation is not None:
                compensation.status = "SUCCEEDED"
                compensation.error_code = None
                compensation.error_message = None
                compensation.completed_at = datetime.now(UTC)
                record_deletion_compensation(db, session_id, recording_id)
                db.commit()
        return True

    def _fail_job(
        self,
        db: Session,
        job_id: str,
        session_id: str,
        code: str,
        message: str,
    ) -> None:
        job, session_record, cancelled = self._reload_after_remote(
            db, job_id, session_id
        )
        if cancelled or job is None or session_record is None:
            self._cancel_job(db, job_id)
            return
        job.error_code = code
        job.error_message = message[:4000]
        retryable = job.attempts < job.max_attempts and code not in {
            "adapter_not_configured",
            "extraction_not_configured",
            "transcription_failed",
            AMBIGUOUS_OPERATION_ERROR_CODE,
        }
        if retryable:
            job.status = JobStatus.QUEUED.value
            job.available_at = datetime.now(UTC) + timedelta(
                seconds=min(
                    self.settings.worker_transcription_poll_seconds
                    * (2 ** max(0, job.attempts - 1)),
                    300,
                )
            )
            if SessionState(session_record.state) in {
                SessionState.TRANSCRIBING,
                SessionState.RECONCILING,
                SessionState.EXTRACTING,
            }:
                transition(session_record, SessionState.RETRY_PENDING)
        else:
            job.status = JobStatus.FAILED.value
            if SessionState(session_record.state) in {
                SessionState.TRANSCRIBING,
                SessionState.RECONCILING,
                SessionState.EXTRACTING,
                SessionState.RETRY_PENDING,
            }:
                transition(session_record, SessionState.FAILED)
            if JobType(job.type) != JobType.SUMMARIZE:
                # The summary is a derived convenience over an already-good
                # ledger. Recording its failure on the session would show the
                # reviewer an error banner for a session that is perfectly fine.
                session_record.last_error = f"{code}: {message}"[:4000]
        self._safe_commit(db)

    def _fail_ambiguous_operation(
        self,
        db: Session,
        job_id: str,
        session_id: str,
        session_record: SessionRecord,
    ) -> None:
        """Fail a job whose session has a pending, non-idempotent
        provider-write marker (see `begin_pending_operation`) instead of
        letting it be auto-retried. This is the last line of defense
        against a blind duplicate upload/queue_transcription call; the
        primary detection point is `recover_abandoned_jobs`, which
        converts an abandoned job in this state to FAILED before it is
        ever requeued, but this guard also covers a job manually
        recreated (e.g. via the retry API) while the marker is still set.
        """
        job = db.get(JobRecord, job_id, populate_existing=True)
        if job is None:
            return
        kind = session_record.pending_operation_kind
        operation_id = session_record.pending_operation_id
        started_at = session_record.pending_operation_started_at
        job.status = JobStatus.FAILED.value
        job.error_code = AMBIGUOUS_OPERATION_ERROR_CODE
        job.ambiguous_operation_id = operation_id
        job.error_message = (
            f"a previous {kind} attempt to the media provider (operation "
            f"{operation_id}, started "
            f"{started_at.isoformat() if started_at else 'unknown'}) may "
            "have been accepted upstream before this worker crashed or its "
            "lease expired; the provider has no idempotency key or "
            "lookup-by-key endpoint, so this cannot be safely auto-retried. "
            "An operator must check the provider for a stray recording and "
            "resolve via POST /api/sessions/{id}/upload-operation/resolve "
            "before retrying."
        )[:4000]
        if SessionState(session_record.state) in {
            SessionState.TRANSCRIBING,
            SessionState.RETRY_PENDING,
        }:
            transition(session_record, SessionState.FAILED)
        session_record.last_error = (
            f"{AMBIGUOUS_OPERATION_ERROR_CODE}: operation {operation_id} "
            "requires manual reconciliation before retrying"
        )[:4000]
        self._safe_commit(db)

    def enqueue_scheduled_reconciliation(self) -> int:
        now = datetime.now(UTC)
        queued = 0
        with self.factory() as db:
            sessions = db.scalars(
                select(SessionRecord).where(
                    SessionRecord.speakr_recording_id.is_not(None),
                    SessionRecord.state.in_(
                        [
                            SessionState.TRANSCRIPT_READY.value,
                            SessionState.AWAITING_REVIEW.value,
                            SessionState.COMPLETE.value,
                        ]
                    ),
                )
            )
            for session_record in sessions:
                last = session_record.last_reconciled_at
                if last is not None:
                    if last.tzinfo is None:
                        last = last.replace(tzinfo=UTC)
                    if (
                        now - last.astimezone(UTC)
                    ).total_seconds() < self.settings.reconciliation_interval_seconds:
                        continue
                _, created = ensure_job(
                    db,
                    session_id=session_record.id,
                    job_type=JobType.RECONCILE,
                    max_attempts=self.settings.worker_max_attempts,
                )
                if created:
                    queued += 1
            db.commit()
        return queued

    def recover_abandoned_jobs(self) -> int:
        """Requeue jobs whose worker lease has expired -- except where a
        session's pending-operation marker (see `begin_pending_operation`)
        shows a non-idempotent provider write (Speakr upload, or an
        EXPLICIT-mode provider's queue_transcription) may have been
        in-flight when the lease expired. Those cannot be distinguished
        from "completed upstream" without provider support neither Speakr
        nor a generic EXPLICIT provider is assumed to have, so -- unless
        the adapter declares `supports_upload_idempotency` -- they are
        failed as ambiguous rather than blindly requeued for auto-retry,
        which could otherwise create a second, undiscoverable recording.

        Each abandoned job is recovered in its own isolated transaction
        (see `_recover_one_abandoned_job`) rather than batching every
        abandoned job into a single commit, so an optimistic-concurrency
        conflict on one job's (or its session's) row -- e.g. an operator
        cancelling/resolving it concurrently -- cannot abort recovery of
        every other abandoned job in the same sweep, and cannot raise out
        of this method and crash the worker's poll loop.
        """
        cutoff = datetime.now(UTC) - timedelta(
            seconds=self.settings.worker_job_lease_seconds
        )
        with self.factory() as db:
            job_ids = list(
                db.scalars(
                    select(JobRecord.id)
                    .where(
                        JobRecord.status == JobStatus.RUNNING.value,
                        JobRecord.updated_at < cutoff,
                    )
                    .order_by(JobRecord.created_at)
                )
            )
        recovered = 0
        for job_id in job_ids:
            if self._recover_one_abandoned_job(job_id, cutoff):
                recovered += 1
        return recovered

    def _recover_one_abandoned_job(self, job_id: str, cutoff: datetime) -> bool:
        """Recover a single abandoned job in its own transaction, retrying
        on `StaleDataError` (an optimistic-concurrency conflict on the
        job's or its session's row -- e.g. a concurrent admin cancel or
        resolve) by rolling back, reloading the row's current state, and
        re-evaluating from scratch rather than blindly retrying stale
        in-memory data. Returns True only if this call actually recovered
        (requeued or ambiguous-failed) the job; returns False if it was
        skipped because a concurrent change already made it ineligible
        (e.g. no longer RUNNING, or its lease was renewed/already
        recovered) -- without ever raising, so one persistently-contested
        row cannot terminate the recovery sweep or the worker loop.
        """
        for _ in range(3):
            with self.factory() as db:
                job = db.get(JobRecord, job_id, populate_existing=True)
                if job is None or job.status != JobStatus.RUNNING.value:
                    # Already handled by someone/something else since it
                    # was listed as abandoned (completed, cancelled, or
                    # retried) -- nothing left for this sweep to do.
                    return False
                updated_at = job.updated_at
                if updated_at.tzinfo is None:
                    # sqlite (used in tests) round-trips DateTime(timezone=True)
                    # columns as naive UTC; normalize before comparing.
                    updated_at = updated_at.replace(tzinfo=UTC)
                if updated_at >= cutoff:
                    # The lease was renewed (heartbeat) since this job was
                    # listed as abandoned; it is no longer stale.
                    return False
                session_record = db.get(
                    SessionRecord, job.session_id, populate_existing=True
                )
                ambiguous = (
                    session_record is not None
                    and session_record.pending_operation_kind is not None
                    and JobType(job.type) == JobType.TRANSCRIBE
                    and not getattr(
                        self.adapter, "supports_upload_idempotency", False
                    )
                )
                if ambiguous:
                    kind = session_record.pending_operation_kind
                    operation_id = session_record.pending_operation_id
                    job.status = JobStatus.FAILED.value
                    job.error_code = AMBIGUOUS_OPERATION_ERROR_CODE
                    job.ambiguous_operation_id = operation_id
                    job.error_message = (
                        "worker lease expired while a non-idempotent "
                        f"provider call ({kind}, operation {operation_id}) "
                        "may still have been in flight; safe auto-retry is "
                        "not possible without upstream idempotency "
                        "support, so this job requires operator "
                        "reconciliation instead of being requeued"
                    )[:4000]
                    if SessionState(session_record.state) in {
                        SessionState.TRANSCRIBING,
                        SessionState.RETRY_PENDING,
                    }:
                        transition(session_record, SessionState.FAILED)
                    session_record.last_error = (
                        f"{AMBIGUOUS_OPERATION_ERROR_CODE}: operation "
                        f"{operation_id} requires manual reconciliation "
                        "before retrying"
                    )[:4000]
                else:
                    job.status = JobStatus.QUEUED.value
                    job.available_at = datetime.now(UTC)
                    job.error_code = "worker_lease_expired"
                    job.error_message = "worker lease expired; job safely re-queued"
                try:
                    db.commit()
                    return True
                except StaleDataError:
                    db.rollback()
                    continue
        return False


def _entry_span(record: LedgerEntryRecord) -> tuple[int, int]:
    """Where in the recording an entry's evidence sits."""

    starts = [reference["start_ms"] for reference in record.evidence]
    ends = [reference["end_ms"] for reference in record.evidence]
    return min(starts), max(ends)


def _store_summary(
    db: Session,
    *,
    session_id: str,
    transcript_revision_id: str,
    themes: list[dict],
    entry_count: int,
    source_updated_at: datetime,
) -> None:
    existing = db.scalar(
        select(SessionSummaryRecord).where(
            SessionSummaryRecord.session_id == session_id
        )
    )
    if existing is None:
        db.add(
            SessionSummaryRecord(
                session_id=session_id,
                transcript_revision_id=transcript_revision_id,
                themes=themes,
                entry_count=entry_count,
                source_updated_at=source_updated_at,
                generated_at=datetime.now(UTC),
            )
        )
        return
    # A session keeps one current summary; regenerating replaces it rather than
    # accumulating versions the reviewer would have to choose between.
    existing.transcript_revision_id = transcript_revision_id
    existing.themes = themes
    existing.entry_count = entry_count
    existing.source_updated_at = source_updated_at
    existing.generated_at = datetime.now(UTC)


def run() -> None:
    parser = argparse.ArgumentParser(description="Coaching evidence worker")
    parser.add_argument("--once", action="store_true", help="process at most one job")
    args = parser.parse_args()
    settings = get_settings()
    engine = create_db_engine(settings)
    init_schema(engine)
    worker = Worker(settings, create_session_factory(engine))
    if args.once:
        worker.run_once()
        return
    while True:
        worked = worker.run_once()
        if not worked:
            time.sleep(settings.worker_poll_seconds)
