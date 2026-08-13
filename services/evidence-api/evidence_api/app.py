import hashlib
import hmac
import json
import mimetypes
import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import (
    APIRouter,
    Depends,
    FastAPI,
    File,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError

from coaching_contracts import (
    CreateJobRequest,
    CreateSessionRequest,
    JobResponse,
    JobStatus,
    JobType,
    LedgerEntryCreate,
    LedgerEntryResponse,
    SessionResponse,
    SessionState,
    SessionSummaryResponse,
    SummaryTheme,
    TranscriptRevisionResponse,
    VerificationRequest,
    VerificationStatus,
)
from media_adapter import AdapterError, SpeakrHttpAdapter

from .auth import Principal, require_admin, require_editor, require_principal
from .config import Settings, get_settings
from .db import (
    create_db_engine,
    create_session_factory,
    init_schema,
    session_dependency,
)
from .models import (
    JobRecord,
    LedgerEntryRecord,
    ProviderOperationResolutionRecord,
    SessionRecord,
    SessionSummaryRecord,
    TranscriptRevisionRecord,
    VerificationRecord,
    WebhookDeliveryRecord,
)
from .services import (
    AMBIGUOUS_OPERATION_ERROR_CODE,
    EvidenceValidationError,
    clear_pending_operation,
    create_ledger_entry,
    ensure_job,
    has_active_job,
    has_pending_deletion_compensation,
    has_running_pending_provider_operation,
    job_response,
    ledger_response,
    provider_deletion_not_found,
    record_deletion_intent,
    revision_response,
    session_response,
)
from .state import InvalidStateTransition, transition


class DeleteConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm_session_id: str


class ResolveUploadOperationRequest(BaseModel):
    """Operator-submitted resolution for a session stuck in the
    `ambiguous_provider_operation` state (see
    `evidence_worker.worker.Worker._fail_ambiguous_operation`). The
    operator is expected to have checked the media provider out-of-band
    (Speakr has no lookup-by-key endpoint, so this cannot be automated)
    and to report one of two outcomes:

    - "not_created": the previous provider call never took effect (e.g. it
      failed before reaching Speakr, or the operator confirmed no stray
      recording exists) -- the marker is cleared and a plain retry is safe.
    - "adopt_existing": the previous call *did* create a recording
      upstream; `speakr_recording_id` identifies it so the session can
      adopt it instead of uploading a duplicate.

    `confirm_operation_id` must match the session's current
    `pending_operation_id` to guard against an operator resolving a
    different (e.g. already-superseded) operation by mistake.
    """

    model_config = ConfigDict(extra="forbid")
    confirm_operation_id: str
    outcome: Literal["not_created", "adopt_existing"]
    speakr_recording_id: str | None = None
    allow_unverified_absence: bool = False
    override_reason: str | None = Field(default=None, max_length=2000)


class CurrentUserResponse(BaseModel):
    username: str


def _http_error(code: str, message: str, status_code: int = 400) -> HTTPException:
    return HTTPException(
        status_code=status_code, detail={"code": code, "message": message}
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = create_db_engine(settings)
    session_factory = create_session_factory(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.media_root.mkdir(parents=True, exist_ok=True)
        init_schema(engine)
        yield
        engine.dispose()

    app = FastAPI(
        title="Coaching Evidence API",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.speakr_adapter = SpeakrHttpAdapter(
        settings.speakr_base_url,
        settings.speakr_api_token,
        timeout_seconds=settings.speakr_timeout_seconds,
        verify_tls=settings.speakr_verify_tls,
    )
    router = APIRouter(prefix="/api")

    @app.exception_handler(InvalidStateTransition)
    async def invalid_state_handler(_, exc: InvalidStateTransition):
        return JSONResponse(
            status_code=409,
            content={
                "detail": {"code": "invalid_state_transition", "message": str(exc)}
            },
        )

    @app.exception_handler(StaleDataError)
    async def stale_data_handler(_, exc: StaleDataError):
        # Raised by SQLAlchemy's optimistic `version_id_col` check when a
        # commit's WHERE ... AND version = :version updates zero rows --
        # i.e. a concurrent transaction (typically the worker completing a
        # RECONCILE/EXTRACT job, or the reverse: an API-level deletion)
        # already advanced the row's version since this request read it.
        # The request's premise is stale; the client should re-fetch the
        # current session/job state and decide whether to retry.
        return JSONResponse(
            status_code=409,
            content={
                "detail": {
                    "code": "concurrent_update",
                    "message": (
                        "the session or job was modified concurrently; "
                        "re-fetch its current state before retrying"
                    ),
                }
            },
        )

    @router.get("/health")
    def health(db: Session = Depends(session_dependency)):
        db.execute(select(1))
        return {
            "status": "ok",
            "database": "ok",
            "timestamp_unit": "milliseconds",
            "speakr_configured": bool(
                settings.speakr_base_url and settings.speakr_api_token
            ),
            "extraction_provider": settings.extraction_provider,
        }

    @router.get("/me", response_model=CurrentUserResponse)
    def current_user(principal: Principal = Depends(require_principal)):
        return CurrentUserResponse(username=principal.username)

    @router.post(
        "/sessions",
        response_model=SessionResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_session(
        body: CreateSessionRequest,
        _: Principal = Depends(require_editor),
        db: Session = Depends(session_dependency),
    ):
        record = SessionRecord(**body.model_dump())
        db.add(record)
        db.commit()
        return session_response(db, record)

    @router.get("/sessions", response_model=list[SessionResponse])
    def list_sessions(
        _: Principal = Depends(require_principal),
        db: Session = Depends(session_dependency),
    ):
        records = db.scalars(
            select(SessionRecord)
            .where(SessionRecord.state != SessionState.DELETED.value)
            .order_by(SessionRecord.created_at.desc())
        )
        return [session_response(db, item) for item in records]

    @router.get("/sessions/{session_id}", response_model=SessionResponse)
    def get_session(
        session_id: str,
        _: Principal = Depends(require_principal),
        db: Session = Depends(session_dependency),
    ):
        return session_response(db, _session_or_404(db, session_id))

    @router.post("/sessions/{session_id}/media", response_model=SessionResponse)
    async def upload_media(
        session_id: str,
        media: UploadFile = File(...),
        _: Principal = Depends(require_editor),
        db: Session = Depends(session_dependency),
    ):
        record = _session_or_404(db, session_id)
        if record.media_path and SessionState(record.state) in {
            SessionState.UPLOADED,
            SessionState.TRANSCRIBING,
            SessionState.RECONCILING,
            SessionState.TRANSCRIPT_READY,
            SessionState.EXTRACTING,
            SessionState.AWAITING_REVIEW,
            SessionState.COMPLETE,
            SessionState.RETRY_PENDING,
        }:
            if SessionState(record.state) == SessionState.UPLOADED:
                ensure_job(
                    db,
                    session_id=record.id,
                    job_type=JobType.TRANSCRIBE,
                    max_attempts=settings.worker_max_attempts,
                )
                transition(record, SessionState.TRANSCRIBING)
                db.commit()
            elif SessionState(record.state) == SessionState.TRANSCRIBING:
                ensure_job(
                    db,
                    session_id=record.id,
                    job_type=(
                        JobType.RECONCILE
                        if record.speakr_recording_id
                        else JobType.TRANSCRIBE
                    ),
                    max_attempts=settings.worker_max_attempts,
                )
                db.commit()
            elif SessionState(record.state) == SessionState.RECONCILING:
                ensure_job(
                    db,
                    session_id=record.id,
                    job_type=JobType.RECONCILE,
                    max_attempts=settings.worker_max_attempts,
                )
                db.commit()
            return session_response(db, record)
        transition(record, SessionState.UPLOADING)
        db.commit()

        safe_name = _safe_filename(media.filename or "recording.bin")
        directory = settings.media_root / record.id
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / f"original{Path(safe_name).suffix.lower()}"
        staging = directory / ".uploading"
        digest = hashlib.sha256()
        size = 0
        try:
            staging.unlink(missing_ok=True)
            with staging.open("xb") as output:
                while chunk := await media.read(1024 * 1024):
                    size += len(chunk)
                    if size > settings.max_upload_bytes:
                        raise _http_error(
                            "upload_too_large",
                            f"upload exceeds {settings.max_upload_bytes} bytes",
                            413,
                        )
                    output.write(chunk)
                    digest.update(chunk)
            if size == 0:
                raise _http_error(
                    "empty_upload", "recording upload cannot be empty", 422
                )
            staging.replace(destination)
            record.original_filename = media.filename or safe_name
            record.media_path = str(destination)
            record.media_sha256 = digest.hexdigest()
            record.media_size_bytes = size
            transition(record, SessionState.UPLOADED)
            ensure_job(
                db,
                session_id=record.id,
                job_type=JobType.TRANSCRIBE,
                max_attempts=settings.worker_max_attempts,
            )
            transition(record, SessionState.TRANSCRIBING)
            db.commit()
        except Exception as exc:
            staging.unlink(missing_ok=True)
            record.state = SessionState.FAILED.value
            record.last_error = f"media upload failed: {exc}"[:4000]
            db.commit()
            raise
        return session_response(db, record)

    @router.get("/sessions/{session_id}/media")
    def play_media(
        session_id: str,
        _: Principal = Depends(require_principal),
        db: Session = Depends(session_dependency),
    ):
        record = _session_or_404(db, session_id)
        if not record.media_path or not Path(record.media_path).is_file():
            raise _http_error("media_not_found", "recording media is unavailable", 404)
        media_type = (
            mimetypes.guess_type(record.original_filename or "")[0]
            or "application/octet-stream"
        )
        return FileResponse(
            record.media_path,
            media_type=media_type,
            headers={"Cache-Control": "private, no-store"},
        )

    @router.post(
        "/sessions/{session_id}/jobs",
        response_model=JobResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def create_job(
        session_id: str,
        body: CreateJobRequest,
        _: Principal = Depends(require_editor),
        db: Session = Depends(session_dependency),
    ):
        record = _session_or_404(db, session_id)
        job, created = ensure_job(
            db,
            session_id=session_id,
            job_type=body.type,
            max_attempts=settings.worker_max_attempts,
        )
        if created:
            _prepare_state_for_job(record, body.type)
        db.commit()
        return job_response(job)

    @router.get("/sessions/{session_id}/jobs", response_model=list[JobResponse])
    def list_jobs(
        session_id: str,
        _: Principal = Depends(require_principal),
        db: Session = Depends(session_dependency),
    ):
        _session_or_404(db, session_id)
        records = db.scalars(
            select(JobRecord)
            .where(JobRecord.session_id == session_id)
            .order_by(JobRecord.created_at.desc())
        )
        return [job_response(item) for item in records]

    @router.post("/jobs/{job_id}/cancel", response_model=JobResponse)
    def cancel_job(
        job_id: str,
        _: Principal = Depends(require_editor),
        db: Session = Depends(session_dependency),
    ):
        job = _job_or_404(db, job_id)
        if job.status not in {JobStatus.QUEUED.value, JobStatus.RUNNING.value}:
            raise _http_error("job_not_cancellable", "job is not active", 409)
        job.status = JobStatus.CANCELLED.value
        session_record = _session_or_404(db, job.session_id)
        if SessionState(session_record.state) in {
            SessionState.TRANSCRIBING,
            SessionState.EXTRACTING,
            SessionState.RETRY_PENDING,
        }:
            transition(session_record, SessionState.CANCELLED)
        db.commit()
        return job_response(job)

    @router.post("/jobs/{job_id}/retry", response_model=JobResponse)
    def retry_job(
        job_id: str,
        _: Principal = Depends(require_editor),
        db: Session = Depends(session_dependency),
    ):
        old = _job_or_404(db, job_id)
        if old.status not in {
            JobStatus.FAILED.value,
            JobStatus.CANCELLED.value,
        }:
            raise _http_error("job_not_retryable", "job has not failed or cancelled", 409)
        session_record = _session_or_404(db, old.session_id)
        if SessionState(session_record.state) in {
            SessionState.FAILED,
            SessionState.CANCELLED,
        }:
            transition(session_record, SessionState.RETRY_PENDING)
        _prepare_state_for_job(session_record, JobType(old.type))
        retry = JobRecord(
            session_id=old.session_id,
            type=old.type,
            max_attempts=old.max_attempts,
        )
        db.add(retry)
        db.commit()
        return job_response(retry)

    @router.post(
        "/sessions/{session_id}/refresh",
        response_model=SessionResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    def refresh_from_speakr(
        session_id: str,
        _: Principal = Depends(require_editor),
        db: Session = Depends(session_dependency),
    ):
        record = _session_or_404(db, session_id)
        if SessionState(record.state) in {
            SessionState.DELETE_PENDING,
            SessionState.DELETED,
        }:
            raise _http_error(
                "refresh_not_allowed", "deleted sessions cannot be refreshed", 409
            )
        if record.pending_operation_kind:
            # A prior upload or queue_transcription call may have reached
            # Speakr before a crash/lease expiry prevented us from
            # recording its outcome. Refreshing here would infer a job
            # type (TRANSCRIBE or RECONCILE) from possibly-stale local
            # state and could resubmit the same non-idempotent provider
            # call. Require operator resolution first (see
            # ResolveUploadOperationRequest).
            raise _http_error(
                AMBIGUOUS_OPERATION_ERROR_CODE,
                (
                    "a previous provider operation for this session has "
                    "not been confirmed complete; resolve via POST "
                    "/sessions/{session_id}/upload-operation/resolve "
                    "before refreshing"
                ),
                409,
            )
        if not record.speakr_recording_id:
            if not record.media_path:
                raise _http_error(
                    "refresh_not_allowed",
                    "session has neither retained media nor a Speakr recording",
                    409,
                )
            if SessionState(record.state) in {
                SessionState.FAILED,
                SessionState.CANCELLED,
            }:
                transition(record, SessionState.RETRY_PENDING)
            job_type = JobType.TRANSCRIBE
        else:
            if SessionState(record.state) in {
                SessionState.FAILED,
                SessionState.CANCELLED,
            }:
                transition(record, SessionState.RETRY_PENDING)
            job_type = JobType.RECONCILE
            transition(record, SessionState.RECONCILING)
        ensure_job(
            db,
            session_id=record.id,
            job_type=job_type,
            max_attempts=settings.worker_max_attempts,
        )
        db.commit()
        return session_response(db, record)

    @router.post(
        "/sessions/{session_id}/upload-operation/resolve",
        response_model=SessionResponse,
    )
    def resolve_upload_operation(
        session_id: str,
        body: ResolveUploadOperationRequest,
        request: Request,
        principal: Principal = Depends(require_admin),
        db: Session = Depends(session_dependency),
    ):
        """Manually resolve a session left in the
        `ambiguous_provider_operation` state after a worker crashed (or
        its lease expired) between a non-idempotent Speakr call
        (upload_recording / queue_transcription) succeeding and this
        service durably recording that outcome. Adoption is validated
        through the configured provider integration. A not-created
        outcome is verified through provider lookup when supported, or
        requires an explicit audited operator override.

        This endpoint only clears the local ambiguity marker (and
        optionally adopts a recording id the operator confirms exists);
        it does not itself requeue a job. Follow up with the existing
        POST /jobs/{job_id}/retry (or /sessions/{id}/refresh) to resume
        processing once resolved.
        """
        record = _session_or_404(db, session_id)
        if not record.pending_operation_kind:
            raise _http_error(
                "no_pending_operation",
                "session has no pending provider operation to resolve",
                409,
            )
        if body.confirm_operation_id != record.pending_operation_id:
            raise _http_error(
                "operation_id_mismatch",
                "confirm_operation_id does not match the session's "
                "current pending operation id",
                409,
            )
        active_job = db.scalar(
            select(JobRecord).where(
                JobRecord.session_id == session_id,
                JobRecord.type == JobType.TRANSCRIBE.value,
                JobRecord.status.in_(
                    [JobStatus.QUEUED.value, JobStatus.RUNNING.value]
                ),
            )
        )
        if active_job is not None:
            raise _http_error(
                "provider_operation_active",
                "the ambiguity marker cannot be cleared while a "
                "transcription job is queued or running",
                409,
            )
        ambiguous_job = db.scalar(
            select(JobRecord)
            .where(
                JobRecord.session_id == session_id,
                JobRecord.type == JobType.TRANSCRIBE.value,
                JobRecord.status == JobStatus.FAILED.value,
                JobRecord.error_code == AMBIGUOUS_OPERATION_ERROR_CODE,
                JobRecord.ambiguous_operation_id
                == record.pending_operation_id,
            )
            .order_by(JobRecord.updated_at.desc())
        )
        if ambiguous_job is None:
            raise _http_error(
                "ambiguous_job_required",
                "resolution requires the terminal failed job for this "
                "specific ambiguous provider operation",
                409,
            )
        kind = record.pending_operation_kind
        if kind not in {"upload", "queue_transcription"}:
            raise _http_error(
                "unknown_pending_operation_kind",
                f"unrecognized pending operation kind: {kind}",
                500,
            )
        adapter = request.app.state.speakr_adapter
        remote_recording_id: str | None = None
        verification_method: str
        if body.outcome == "adopt_existing":
            if body.allow_unverified_absence or body.override_reason:
                raise _http_error(
                    "absence_override_not_applicable",
                    "absence override fields apply only to not_created",
                    422,
                )
            if kind == "upload":
                # The ambiguity here is whether upload_recording created a
                # new recording upstream; the operator supplies its id so
                # a retried TRANSCRIBE job can adopt it instead of
                # uploading a duplicate.
                if not body.speakr_recording_id:
                    raise _http_error(
                        "speakr_recording_id_required",
                        "speakr_recording_id is required when adopting "
                        "an existing recording created by an ambiguous "
                        "upload",
                        409,
                    )
                remote_recording_id = body.speakr_recording_id
                linked_session = db.scalar(
                    select(SessionRecord.id).where(
                        SessionRecord.speakr_recording_id
                        == remote_recording_id,
                        SessionRecord.id != session_id,
                    )
                )
                if linked_session is not None:
                    raise _http_error(
                        "recording_already_linked",
                        "the provider recording is already linked to "
                        "another coaching session",
                        409,
                    )
            elif kind == "queue_transcription":
                # The recording id was already known before this
                # operation began; the ambiguity is only whether Speakr
                # accepted the transcription submission. There is
                # nothing to adopt by id -- the operator is confirming
                # the submission itself succeeded.
                if body.speakr_recording_id:
                    raise _http_error(
                        "speakr_recording_id_not_applicable",
                        "speakr_recording_id must not be supplied when "
                        "resolving a queue_transcription operation; "
                        "confirm the submission outcome instead",
                        409,
                    )
                remote_recording_id = record.speakr_recording_id
                if not remote_recording_id:
                    raise _http_error(
                        "speakr_recording_id_required",
                        "the session has no recording to validate for the "
                        "ambiguous transcription submission",
                        409,
                    )
            try:
                provider_recording = adapter.get_recording(
                    remote_recording_id
                )
            except AdapterError as exc:
                raise _http_error(
                    "adopted_recording_unreachable",
                    "the configured integration account could not access "
                    "the proposed provider recording",
                    503 if exc.code == "adapter_not_configured" else 422,
                ) from exc
            if provider_recording.recording_id != remote_recording_id:
                raise _http_error(
                    "adopted_recording_mismatch",
                    "the provider returned a different recording identity",
                    422,
                )
            verification_method = "provider_recording_lookup"
            if kind == "upload":
                record.speakr_recording_id = remote_recording_id
            else:
                record.transcription_submitted_at = datetime.now(UTC)
        else:
            if body.speakr_recording_id:
                raise _http_error(
                    "speakr_recording_id_not_applicable",
                    "speakr_recording_id applies only to adopt_existing",
                    422,
                )
            supports_lookup = bool(
                getattr(adapter, "supports_operation_lookup", False)
            )
            lookup = getattr(adapter, "find_operation_recording", None)
            if supports_lookup and callable(lookup):
                try:
                    provider_recording = lookup(
                        kind,
                        record.pending_operation_id,
                    )
                except AdapterError as exc:
                    raise _http_error(
                        "absence_verification_failed",
                        "the configured integration account could not "
                        "verify whether the provider operation took effect",
                        502,
                    ) from exc
                if provider_recording is not None:
                    raise _http_error(
                        "provider_operation_was_created",
                        "provider lookup found a recording for this "
                        "operation; adopt it instead of clearing as absent",
                        409,
                    )
                verification_method = "provider_operation_lookup"
            else:
                reason = (body.override_reason or "").strip()
                if not body.allow_unverified_absence or len(reason) < 10:
                    raise _http_error(
                        "absence_override_required",
                        "this provider cannot verify operation absence; "
                        "set allow_unverified_absence=true and provide an "
                        "auditable override_reason of at least 10 characters",
                        409,
                    )
                verification_method = "explicit_operator_override"
        db.add(
            ProviderOperationResolutionRecord(
                session_id=session_id,
                job_id=ambiguous_job.id,
                operation_id=record.pending_operation_id,
                operation_kind=kind,
                outcome=body.outcome,
                remote_recording_id=remote_recording_id,
                verification_method=verification_method,
                override_reason=(
                    body.override_reason.strip()
                    if body.override_reason
                    else None
                ),
                resolved_by=principal.subject,
            )
        )
        clear_pending_operation(record)
        db.commit()
        return session_response(db, record)

    @router.post("/sessions/{session_id}/cancel", response_model=SessionResponse)
    def cancel_session(
        session_id: str,
        _: Principal = Depends(require_editor),
        db: Session = Depends(session_dependency),
    ):
        record = _session_or_404(db, session_id)
        if SessionState(record.state) not in {
            SessionState.CREATED,
            SessionState.UPLOADING,
            SessionState.UPLOADED,
            SessionState.TRANSCRIBING,
            SessionState.RECONCILING,
            SessionState.TRANSCRIPT_READY,
            SessionState.EXTRACTING,
            SessionState.RETRY_PENDING,
        }:
            raise _http_error(
                "session_not_cancellable", "session is not processing", 409
            )
        jobs = db.scalars(
            select(JobRecord).where(
                JobRecord.session_id == session_id,
                JobRecord.status.in_(
                    [JobStatus.QUEUED.value, JobStatus.RUNNING.value]
                ),
            )
        )
        for job in jobs:
            job.status = JobStatus.CANCELLED.value
        transition(record, SessionState.CANCELLED)
        db.commit()
        return session_response(db, record)

    @router.get(
        "/sessions/{session_id}/transcript-revisions",
        response_model=list[TranscriptRevisionResponse],
    )
    def list_revisions(
        session_id: str,
        _: Principal = Depends(require_principal),
        db: Session = Depends(session_dependency),
    ):
        _session_or_404(db, session_id)
        records = db.scalars(
            select(TranscriptRevisionRecord)
            .where(TranscriptRevisionRecord.session_id == session_id)
            .order_by(TranscriptRevisionRecord.created_at.desc())
        )
        return [revision_response(item) for item in records]

    @router.post(
        "/sessions/{session_id}/ledger",
        response_model=LedgerEntryResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def add_ledger_entry(
        session_id: str,
        body: LedgerEntryCreate,
        _: Principal = Depends(require_editor),
        db: Session = Depends(session_dependency),
    ):
        session_record = _session_or_404(db, session_id)
        if SessionState(session_record.state) not in {
            SessionState.TRANSCRIPT_READY,
            SessionState.AWAITING_REVIEW,
            SessionState.COMPLETE,
        }:
            raise _http_error(
                "ledger_not_allowed",
                "ledger entries require a transcript-ready session",
                409,
            )
        try:
            record = create_ledger_entry(db, session_record, body)
        except EvidenceValidationError as exc:
            raise _http_error("invalid_evidence_reference", str(exc), 422) from exc
        if SessionState(session_record.state) == SessionState.TRANSCRIPT_READY:
            transition(session_record, SessionState.AWAITING_REVIEW)
        elif SessionState(session_record.state) == SessionState.COMPLETE:
            transition(session_record, SessionState.AWAITING_REVIEW)
        db.commit()
        return ledger_response(record)

    @router.get(
        "/sessions/{session_id}/ledger", response_model=list[LedgerEntryResponse]
    )
    def list_ledger(
        session_id: str,
        transcript_revision_id: str | None = None,
        _: Principal = Depends(require_principal),
        db: Session = Depends(session_dependency),
    ):
        session_record = _session_or_404(db, session_id)
        revision_id = (
            transcript_revision_id
            if transcript_revision_id is not None
            else session_record.current_transcript_revision_id
        )
        if revision_id is None:
            return []
        records = db.scalars(
            select(LedgerEntryRecord)
            .where(
                LedgerEntryRecord.session_id == session_id,
                LedgerEntryRecord.transcript_revision_id == revision_id,
            )
            .order_by(LedgerEntryRecord.created_at)
        )
        return [ledger_response(item) for item in records]

    @router.get(
        "/sessions/{session_id}/summary", response_model=SessionSummaryResponse
    )
    def get_summary(
        session_id: str,
        _: Principal = Depends(require_principal),
        db: Session = Depends(session_dependency),
    ):
        _session_or_404(db, session_id)
        record = db.scalar(
            select(SessionSummaryRecord).where(
                SessionSummaryRecord.session_id == session_id
            )
        )
        if record is None:
            raise _http_error(
                "summary_not_found",
                "this session has no summary yet",
                404,
            )
        current = db.execute(
            select(
                func.count(LedgerEntryRecord.id),
                func.max(LedgerEntryRecord.updated_at),
            ).where(
                LedgerEntryRecord.session_id == session_id,
                LedgerEntryRecord.transcript_revision_id
                == record.transcript_revision_id,
            )
        ).one()
        entry_count, latest_update = current
        # Summaries are regenerated on request, so the reviewer has to be able
        # to see when their edits are not reflected in what they are reading.
        stale = entry_count != record.entry_count or (
            latest_update is not None
            and _as_utc(latest_update) > _as_utc(record.source_updated_at)
        )
        return SessionSummaryResponse(
            id=record.id,
            session_id=record.session_id,
            transcript_revision_id=record.transcript_revision_id,
            themes=[SummaryTheme.model_validate(theme) for theme in record.themes],
            entry_count=record.entry_count,
            stale=stale,
            generated_at=_as_utc(record.generated_at),
        )

    @router.put("/ledger/{entry_id}/verification", response_model=LedgerEntryResponse)
    def verify_ledger_entry(
        entry_id: str,
        body: VerificationRequest,
        principal: Principal = Depends(require_editor),
        db: Session = Depends(session_dependency),
    ):
        entry = db.get(LedgerEntryRecord, entry_id)
        if not entry:
            raise _http_error("ledger_entry_not_found", "ledger entry not found", 404)
        session_record = _session_or_404(db, entry.session_id)
        if entry.transcript_revision_id != session_record.current_transcript_revision_id:
            raise _http_error(
                "stale_ledger_entry",
                "historical ledger entries cannot be verified as current",
                409,
            )
        now = datetime.now(UTC)
        entry.verification_status = body.status.value
        entry.verified_by = principal.subject
        entry.verified_at = now
        db.add(
            VerificationRecord(
                ledger_entry_id=entry.id,
                reviewer=principal.subject,
                status=body.status.value,
                note=body.note,
            )
        )
        db.flush()
        statuses = set(
            db.scalars(
                select(LedgerEntryRecord.verification_status).where(
                    LedgerEntryRecord.session_id == entry.session_id,
                    LedgerEntryRecord.transcript_revision_id
                    == session_record.current_transcript_revision_id,
                )
            )
        )
        if statuses and statuses <= {
            VerificationStatus.VERIFIED.value,
            VerificationStatus.REJECTED.value,
        }:
            if SessionState(session_record.state) == SessionState.AWAITING_REVIEW:
                transition(session_record, SessionState.COMPLETE)
        elif SessionState(session_record.state) == SessionState.COMPLETE:
            transition(session_record, SessionState.AWAITING_REVIEW)
        db.commit()
        return ledger_response(entry)

    @router.delete("/sessions/{session_id}", response_model=SessionResponse)
    def request_deletion(
        session_id: str,
        _: Principal = Depends(require_admin),
        db: Session = Depends(session_dependency),
    ):
        record = _session_or_404(db, session_id)
        # Persist the cancellation/deletion intent immediately, before
        # touching any job. This tombstone is what an in-flight worker (in
        # a separate transaction, possibly already past the point of
        # checking in-memory job/session state, e.g. mid-upload to the
        # provider) relies on to detect -- purely by session_id -- that it
        # must not persist further provider state and must compensate for
        # anything it already created.
        record_deletion_intent(db, session_id)
        jobs = db.scalars(
            select(JobRecord).where(
                JobRecord.session_id == session_id,
                JobRecord.status == JobStatus.QUEUED.value,
            )
        )
        for job in jobs:
            # Only QUEUED jobs -- ones no worker has started yet -- are
            # safe to cancel immediately here. A RUNNING job's status is
            # deliberately left untouched so it keeps truthfully reflecting
            # that a worker may still be actively processing it; the
            # worker itself observes the tombstone above and transitions
            # its own job to CANCELLED once it reaches a safe checkpoint
            # (see evidence_worker.worker.Worker._process /
            # has_active_job below, which relies on this being accurate).
            job.status = JobStatus.CANCELLED.value
        transition(record, SessionState.DELETE_PENDING)
        db.commit()
        return session_response(db, record)

    @router.post(
        "/sessions/{session_id}/deletion/confirm",
        status_code=status.HTTP_204_NO_CONTENT,
        response_class=Response,
    )
    def confirm_deletion(
        session_id: str,
        body: DeleteConfirmation,
        request: Request,
        _: Principal = Depends(require_admin),
        db: Session = Depends(session_dependency),
    ):
        record = _session_or_404(db, session_id)
        if body.confirm_session_id != session_id:
            raise _http_error("deletion_confirmation_mismatch", "confirmation mismatch")
        if SessionState(record.state) != SessionState.DELETE_PENDING:
            raise _http_error(
                "deletion_not_pending", "session is not pending deletion", 409
            )
        record_deletion_intent(db, session_id)
        if has_active_job(
            db, session_id, settings.worker_job_lease_seconds
        ) or has_running_pending_provider_operation(db, session_id):
            # A worker still holds an active lease on a job for this
            # session -- or is inside a durable pending provider-write
            # section whose heartbeat may be momentarily stale. It has not
            # yet had a chance to observe the tombstone and self-cancel at
            # a safe checkpoint. Deleting the row now would race its
            # in-flight work (e.g. it could still be mid-upload to the
            # provider). Report truthfully that deletion has not completed
            # rather than claiming success while that race is still
            # possible.
            db.commit()
            return JSONResponse(
                status_code=status.HTTP_202_ACCEPTED,
                content={
                    "code": "deletion_pending_active_job",
                    "message": (
                        "an in-flight job is still processing this "
                        "session; retry deletion confirmation shortly"
                    ),
                },
            )
        if has_pending_deletion_compensation(db, session_id):
            db.commit()
            return JSONResponse(
                status_code=status.HTTP_202_ACCEPTED,
                content={
                    "code": "deletion_pending_compensation",
                    "message": (
                        "provider cleanup is still pending; retry deletion "
                        "confirmation after the worker completes compensation"
                    ),
                },
            )
        if record.speakr_recording_id:
            try:
                request.app.state.speakr_adapter.delete_recording(
                    record.speakr_recording_id
                )
            except AdapterError as exc:
                if provider_deletion_not_found(exc):
                    record.speakr_recording_id = None
                else:
                    record.last_error = f"{exc.code}: {exc}"
                    db.commit()
                    raise _http_error(
                        "speakr_deletion_failed",
                        "Speakr copy was not deleted; retained original was not touched",
                        502,
                    ) from exc
            record.speakr_recording_id = None
        if record.media_path:
            path = Path(record.media_path)
            if path.exists():
                path.unlink()
            try:
                path.parent.rmdir()
            except OSError:
                pass
        record.media_path = None
        db.delete(record)
        db.commit()
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @router.post("/webhooks/speakr")
    async def receive_speakr_webhook(
        request: Request,
        db: Session = Depends(session_dependency),
    ):
        raw_body = await request.body()
        _verify_webhook(request, raw_body, settings)
        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError as exc:
            raise _http_error("invalid_webhook_json", "body is not valid JSON", 400) from exc
        _verify_payload_timestamp(
            payload, request.headers["Speakr-Timestamp"], settings
        )
        delivery_id = request.headers["Speakr-Delivery-Id"]
        if payload.get("id") != delivery_id:
            raise _http_error(
                "delivery_id_mismatch", "header and payload delivery ids differ", 400
            )
        existing = db.get(WebhookDeliveryRecord, delivery_id)
        if existing:
            return {"accepted": True, "duplicate": True}
        event_type = str(payload.get("type", ""))
        header_event = request.headers.get("Speakr-Event")
        if header_event != event_type:
            raise _http_error(
                "event_type_mismatch", "header and payload event types differ", 400
            )
        delivery = WebhookDeliveryRecord(
            delivery_id=delivery_id,
            event_type=event_type,
            payload_sha256=hashlib.sha256(raw_body).hexdigest(),
            payload=payload,
        )
        db.add(delivery)
        delivery.session_id = _apply_webhook_event(db, payload, settings)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return {"accepted": True, "duplicate": True}
        return {"accepted": True, "duplicate": False}

    app.include_router(router)
    return app


def _session_or_404(db: Session, session_id: str) -> SessionRecord:
    record = db.get(SessionRecord, session_id)
    if not record:
        raise _http_error("session_not_found", "session not found", 404)
    return record


def _job_or_404(db: Session, job_id: str) -> JobRecord:
    record = db.get(JobRecord, job_id)
    if not record:
        raise _http_error("job_not_found", "job not found", 404)
    return record


def _safe_filename(filename: str) -> str:
    base = Path(filename).name
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")
    return safe[:240] or "recording.bin"


def _prepare_state_for_job(record: SessionRecord, job_type: JobType) -> None:
    current = SessionState(record.state)
    if current in {SessionState.DELETE_PENDING, SessionState.DELETED}:
        raise _http_error(
            "job_not_allowed", "jobs cannot run for a deleted session", 409
        )
    if job_type == JobType.TRANSCRIBE and record.pending_operation_kind:
        # A prior upload/queue_transcription attempt may have been
        # accepted by the provider before this worker process crashed or
        # its lease expired (see
        # evidence_worker.worker.Worker._fail_ambiguous_operation /
        # recover_abandoned_jobs). Blindly creating a new TRANSCRIBE job
        # here would let the worker attempt the same non-idempotent
        # provider call again. Require the operator to resolve it first.
        raise _http_error(
            AMBIGUOUS_OPERATION_ERROR_CODE,
            (
                "a previous provider operation for this session has not "
                "been confirmed complete; resolve via POST "
                "/sessions/{session_id}/upload-operation/resolve before "
                "creating a new transcription job"
            ),
            409,
        )
    if job_type == JobType.TRANSCRIBE:
        if current not in {SessionState.UPLOADED, SessionState.RETRY_PENDING}:
            raise _http_error(
                "transcription_not_allowed",
                "transcription requires UPLOADED or RETRY_PENDING",
                409,
            )
        transition(record, SessionState.TRANSCRIBING)
    elif job_type == JobType.RECONCILE:
        if not record.speakr_recording_id:
            raise _http_error(
                "reconciliation_not_allowed", "session has no Speakr recording id", 409
            )
        if current not in {
            SessionState.TRANSCRIBING,
            SessionState.RECONCILING,
            SessionState.TRANSCRIPT_READY,
            SessionState.AWAITING_REVIEW,
            SessionState.COMPLETE,
            SessionState.RETRY_PENDING,
        }:
            raise _http_error(
                "reconciliation_not_allowed",
                "session is not in a refreshable state",
                409,
            )
        transition(record, SessionState.RECONCILING)
    elif job_type == JobType.EXTRACT:
        if not record.current_transcript_revision_id:
            raise _http_error(
                "extraction_not_allowed", "session has no transcript revision", 409
            )
        if current not in {
            SessionState.TRANSCRIPT_READY,
            SessionState.AWAITING_REVIEW,
            SessionState.RETRY_PENDING,
        }:
            raise _http_error(
                "extraction_not_allowed",
                "extraction requires transcript-ready, review, or retry state",
                409,
            )
        transition(record, SessionState.EXTRACTING)
    elif job_type == JobType.SUMMARIZE:
        if not record.current_transcript_revision_id:
            raise _http_error(
                "summary_not_allowed", "session has no transcript revision", 409
            )
        # Summarizing only reads the ledger, so it needs no state change and
        # must not disturb a session that is mid-review.


def _as_utc(value: datetime) -> datetime:
    """Some drivers hand back naive datetimes for timestamptz columns."""

    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _verify_webhook(request: Request, raw_body: bytes, settings: Settings) -> None:
    if not settings.speakr_webhook_secret:
        raise _http_error(
            "webhook_not_configured",
            "EVIDENCE_SPEAKR_WEBHOOK_SECRET is not configured",
            503,
        )
    signature = request.headers.get("Speakr-Signature", "")
    if not signature.startswith("sha256="):
        raise _http_error("invalid_webhook_signature", "signature is missing", 401)
    expected = hmac.new(
        settings.speakr_webhook_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(signature[7:], expected):
        raise _http_error("invalid_webhook_signature", "signature is invalid", 401)
    delivery_id = request.headers.get("Speakr-Delivery-Id")
    timestamp = request.headers.get("Speakr-Timestamp")
    if not delivery_id or not timestamp:
        raise _http_error(
            "invalid_webhook_headers", "delivery id and timestamp are required", 400
        )
    try:
        dispatched_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if dispatched_at.tzinfo is None:
            raise ValueError("timezone required")
    except ValueError as exc:
        raise _http_error("invalid_webhook_timestamp", "invalid timestamp", 400) from exc
    age = abs((datetime.now(UTC) - dispatched_at.astimezone(UTC)).total_seconds())
    if age > settings.webhook_freshness_seconds:
        raise _http_error("stale_webhook", "webhook timestamp is outside freshness window", 401)


def _verify_payload_timestamp(
    payload: dict, header_timestamp: str, settings: Settings
) -> None:
    payload_timestamp = payload.get("timestamp")
    if not isinstance(payload_timestamp, str):
        raise _http_error(
            "invalid_webhook_timestamp", "signed payload timestamp is required", 400
        )
    try:
        signed_at = datetime.fromisoformat(
            payload_timestamp.replace("Z", "+00:00")
        )
        dispatched_at = datetime.fromisoformat(
            header_timestamp.replace("Z", "+00:00")
        )
        if signed_at.tzinfo is None or dispatched_at.tzinfo is None:
            raise ValueError("timezone required")
    except ValueError as exc:
        raise _http_error("invalid_webhook_timestamp", "invalid timestamp", 400) from exc
    signed_at = signed_at.astimezone(UTC)
    dispatched_at = dispatched_at.astimezone(UTC)
    if abs((signed_at - dispatched_at).total_seconds()) > 1:
        raise _http_error(
            "webhook_timestamp_mismatch",
            "header and signed payload timestamps differ",
            401,
        )
    age = abs((datetime.now(UTC) - signed_at).total_seconds())
    if age > settings.webhook_freshness_seconds:
        raise _http_error(
            "stale_webhook", "signed payload timestamp is outside freshness window", 401
        )


def _apply_webhook_event(
    db: Session, payload: dict, settings: Settings
) -> str | None:
    data = payload.get("data")
    if not isinstance(data, dict) or data.get("recording_id") is None:
        return None
    recording_id = str(data["recording_id"])
    record = db.scalar(
        select(SessionRecord).where(
            SessionRecord.speakr_recording_id == recording_id
        )
    )
    if not record:
        return None
    event_type = payload.get("type")
    if event_type == "recording.transcription.completed":
        duration = data.get("audio_duration_seconds")
        if isinstance(duration, (int, float)):
            record.duration_ms = round(float(duration) * 1000)
        ensure_job(
            db,
            session_id=record.id,
            job_type=JobType.RECONCILE,
            max_attempts=settings.worker_max_attempts,
        )
    elif event_type == "recording.transcription.failed":
        if SessionState(record.state) == SessionState.TRANSCRIBING:
            transition(record, SessionState.FAILED)
        record.last_error = str(data.get("error", "Speakr transcription failed"))
        active_jobs = db.scalars(
            select(JobRecord).where(
                JobRecord.session_id == record.id,
                JobRecord.status.in_(
                    [JobStatus.QUEUED.value, JobStatus.RUNNING.value]
                ),
            )
        )
        for job in active_jobs:
            job.status = JobStatus.CANCELLED.value
    elif event_type == "recording.deleted":
        record.speakr_recording_id = None
        record.last_error = "Speakr copy deleted; project recording retained"
    return record.id


app = create_app()


def run() -> None:
    import uvicorn

    uvicorn.run("evidence_api.app:app", host="0.0.0.0", port=8000)
