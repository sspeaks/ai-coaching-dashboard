from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from coaching_contracts import (
    JobStatus,
    SessionState,
    VerificationStatus,
)

from .db import Base


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid4())


class SessionRecord(Base):
    __tablename__ = "coaching_session"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(300))
    state: Mapped[str] = mapped_column(
        String(32), default=SessionState.CREATED.value, index=True
    )
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)
    notes: Mapped[str | None] = mapped_column(Text)
    original_filename: Mapped[str | None] = mapped_column(String(500))
    media_path: Mapped[str | None] = mapped_column(Text)
    media_sha256: Mapped[str | None] = mapped_column(String(64))
    media_size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    speakr_recording_id: Mapped[str | None] = mapped_column(
        String(100), unique=True, index=True
    )
    transcription_submitted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    # Durable idempotency/operation marker persisted (in its own committed
    # transaction) immediately *before* a non-idempotent provider write call
    # (Speakr upload, or an EXPLICIT-mode provider's queue_transcription)
    # and cleared only in the same commit that durably records that call's
    # outcome. If a worker process crashes after the provider accepts the
    # call but before that clearing commit, this marker survives and lets
    # recovery recognize the operation as ambiguous (the remote call may or
    # may not have been accepted) instead of blindly retrying it -- Speakr's
    # upload API has no idempotency key or lookup-by-key endpoint, so a
    # blind retry here could create a second, undiscoverable recording.
    pending_operation_kind: Mapped[str | None] = mapped_column(String(32))
    pending_operation_id: Mapped[str | None] = mapped_column(String(36))
    pending_operation_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    current_transcript_revision_id: Mapped[str | None] = mapped_column(String(36))
    last_reconciled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    # Optimistic concurrency: every ORM-level UPDATE conditions itself on
    # this value (`WHERE ... AND version = :version`) and SQLAlchemy raises
    # StaleDataError if a concurrent transaction already changed the row
    # (e.g. a deletion tombstone + DELETE_PENDING transition committed by
    # request_deletion while a worker was mid-reconcile/extract). This is
    # what makes the worker's `_safe_commit` StaleDataError handling real
    # instead of dead code, and works identically on SQLite and PostgreSQL
    # since SQLAlchemy implements it as an application-level conditional
    # UPDATE plus a rowcount check, not a database-native locking feature.
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )

    __mapper_args__ = {"version_id_col": version}


class JobRecord(Base):
    __tablename__ = "evidence_job"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("coaching_session.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(
        String(32), default=JobStatus.QUEUED.value, index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    ambiguous_operation_id: Mapped[str | None] = mapped_column(String(36))
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
    # Optimistic concurrency for job ownership: guards against, e.g., an
    # admin's `POST /jobs/{id}/cancel` and the worker's own result commit
    # racing on the same job row. The lease-heartbeat renewal in
    # evidence_worker.worker._renew_job_lease deliberately uses a raw Core
    # `update()` statement instead of the ORM, so it does NOT participate in
    # this version check and keeps behaving as a lightweight, best-effort
    # liveness signal exactly as before.
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )

    __mapper_args__ = {"version_id_col": version}


class TranscriptRevisionRecord(Base):
    __tablename__ = "transcript_revision"
    __table_args__ = (
        UniqueConstraint("session_id", "sha256", name="uq_transcript_revision_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("coaching_session.id", ondelete="CASCADE"), index=True
    )
    sha256: Mapped[str] = mapped_column(String(64))
    segments: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(100), default="speakr")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class LedgerEntryRecord(Base):
    __tablename__ = "ledger_entry"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("coaching_session.id", ondelete="CASCADE"), index=True
    )
    transcript_revision_id: Mapped[str] = mapped_column(
        ForeignKey("transcript_revision.id", ondelete="CASCADE"), index=True
    )
    topic: Mapped[str] = mapped_column(String(300))
    exact_coach_feedback: Mapped[str | None] = mapped_column(Text)
    interpretation: Mapped[str | None] = mapped_column(Text)
    applies_to: Mapped[str | None] = mapped_column(Text)
    song_passage_measure: Mapped[str | None] = mapped_column(Text)
    problem_heard_before: Mapped[str | None] = mapped_column(Text)
    exercise_or_requested_change: Mapped[str | None] = mapped_column(Text)
    observed_result: Mapped[str | None] = mapped_column(Text)
    next_action_and_owner: Mapped[str | None] = mapped_column(Text)
    unresolved_question: Mapped[str | None] = mapped_column(Text)
    confidence_millis: Mapped[int] = mapped_column(Integer)
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    extraction_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    verification_status: Mapped[str] = mapped_column(
        String(32), default=VerificationStatus.UNVERIFIED.value
    )
    verified_by: Mapped[str | None] = mapped_column(String(320))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class SessionSummaryRecord(Base):
    """The headline view of a session, derived from its ledger entries."""

    __tablename__ = "session_summary"
    __table_args__ = (
        UniqueConstraint("session_id", name="uq_session_summary_session"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("coaching_session.id", ondelete="CASCADE"), index=True
    )
    transcript_revision_id: Mapped[str] = mapped_column(
        ForeignKey("transcript_revision.id", ondelete="CASCADE"), index=True
    )
    themes: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    # The ledger the summary was built from. Compared against the ledger on read
    # to tell the reviewer their edits are not reflected here yet.
    entry_count: Mapped[int] = mapped_column(Integer)
    source_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class VerificationRecord(Base):
    __tablename__ = "ledger_verification"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    ledger_entry_id: Mapped[str] = mapped_column(
        ForeignKey("ledger_entry.id", ondelete="CASCADE"), index=True
    )
    reviewer: Mapped[str] = mapped_column(String(320))
    status: Mapped[str] = mapped_column(String(32))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class DeletionTombstoneRecord(Base):
    """Marks that deletion of a session has been requested.

    Deliberately has NO foreign key to coaching_session: this row must
    survive the session (and cascade-deleted job) rows being deleted so
    that an in-flight worker, mid-way through a separate transaction that
    started before deletion was requested, can still discover -- purely by
    session_id, after those rows are gone -- that it must not persist any
    further provider state and must compensate for anything it already
    created.
    """

    __tablename__ = "deletion_tombstone"

    session_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    compensated_recording_id: Mapped[str | None] = mapped_column(String(100))
    compensated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DeletionCompensationRecord(Base):
    """Durable provider cleanup work that survives session deletion."""

    __tablename__ = "deletion_compensation"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "recording_id",
            name="uq_deletion_compensation_recording",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    recording_id: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(32), default="PENDING", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class ProviderOperationResolutionRecord(Base):
    """Audit trail for manually resolved ambiguous provider operations."""

    __tablename__ = "provider_operation_resolution"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    job_id: Mapped[str] = mapped_column(String(36), index=True)
    operation_id: Mapped[str] = mapped_column(String(36), index=True)
    operation_kind: Mapped[str] = mapped_column(String(32))
    outcome: Mapped[str] = mapped_column(String(32))
    remote_recording_id: Mapped[str | None] = mapped_column(String(100))
    verification_method: Mapped[str] = mapped_column(String(64))
    override_reason: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[str] = mapped_column(String(320))
    resolved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class WebhookDeliveryRecord(Base):
    __tablename__ = "webhook_delivery"

    delivery_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    session_id: Mapped[str | None] = mapped_column(
        ForeignKey("coaching_session.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    payload_sha256: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
