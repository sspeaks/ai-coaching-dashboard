from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SessionState(StrEnum):
    CREATED = "CREATED"
    UPLOADING = "UPLOADING"
    UPLOADED = "UPLOADED"
    TRANSCRIBING = "TRANSCRIBING"
    RECONCILING = "RECONCILING"
    TRANSCRIPT_READY = "TRANSCRIPT_READY"
    EXTRACTING = "EXTRACTING"
    AWAITING_REVIEW = "AWAITING_REVIEW"
    COMPLETE = "COMPLETE"
    RETRY_PENDING = "RETRY_PENDING"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    DELETE_PENDING = "DELETE_PENDING"
    DELETED = "DELETED"


class JobType(StrEnum):
    TRANSCRIBE = "TRANSCRIBE"
    RECONCILE = "RECONCILE"
    EXTRACT = "EXTRACT"
    SUMMARIZE = "SUMMARIZE"


class JobStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class VerificationStatus(StrEnum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class CreateSessionRequest(StrictModel):
    title: str = Field(min_length=1, max_length=300)
    recorded_at: datetime | None = None
    duration_ms: int | None = Field(default=None, ge=1)
    notes: str | None = Field(default=None, max_length=10_000)


class SessionResponse(StrictModel):
    id: str
    title: str
    state: SessionState
    recorded_at: datetime | None
    duration_ms: int | None
    original_filename: str | None
    media_sha256: str | None
    speakr_recording_id: str | None
    current_transcript_revision_id: str | None
    last_reconciled_at: datetime | None
    last_error: str | None
    playback_url: str | None
    ledger_entry_count: int
    reviewed_ledger_entry_count: int
    created_at: datetime
    updated_at: datetime


class CreateJobRequest(StrictModel):
    type: JobType


class JobResponse(StrictModel):
    id: str
    session_id: str
    type: JobType
    status: JobStatus
    attempts: int
    max_attempts: int
    error_code: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class TranscriptSegment(StrictModel):
    segment_id: str
    start_ms: int = Field(ge=0, description="Inclusive start in milliseconds.")
    end_ms: int = Field(gt=0, description="Exclusive end in milliseconds.")
    text: str
    provider_speaker_label: str | None = Field(
        default=None,
        description="Unverified provider label; never treated as singer identity.",
    )

    @model_validator(mode="after")
    def validate_range(self) -> "TranscriptSegment":
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        return self


class TranscriptRevisionResponse(StrictModel):
    id: str
    session_id: str
    sha256: str
    segments: list[TranscriptSegment]
    source: str
    created_at: datetime


class EvidenceReference(StrictModel):
    transcript_revision_id: str
    start_ms: int = Field(ge=0, description="Inclusive start in milliseconds.")
    end_ms: int = Field(gt=0, description="Exclusive end in milliseconds.")
    segment_ids: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_range(self) -> "EvidenceReference":
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        if len(set(self.segment_ids)) != len(self.segment_ids):
            raise ValueError("segment_ids must be unique")
        return self


class LedgerEntryCreate(StrictModel):
    topic: str = Field(min_length=1, max_length=300)
    exact_coach_feedback: str | None = None
    interpretation: str | None = None
    applies_to: str | None = Field(
        default=None,
        description="Must be null unless explicitly supported by evidence.",
    )
    song_passage_measure: str | None = None
    problem_heard_before: str | None = None
    exercise_or_requested_change: str | None = None
    observed_result: str | None = Field(
        default=None,
        description="Must be null unless a result was explicitly evaluated.",
    )
    next_action_and_owner: str | None = None
    unresolved_question: str | None = None
    confidence: float = Field(ge=0, le=1)
    evidence: list[EvidenceReference] = Field(min_length=1)
    extraction_metadata: dict[str, Any] = Field(default_factory=dict)


class LedgerEntryResponse(LedgerEntryCreate):
    id: str
    session_id: str
    transcript_revision_id: str
    verification_status: VerificationStatus
    verified_by: str | None
    verified_at: datetime | None
    created_at: datetime
    updated_at: datetime


class SummaryThemeCreate(StrictModel):
    """One headline item, as produced by the summarizer."""

    title: str = Field(min_length=1, max_length=200)
    summary: str = Field(min_length=1, max_length=4_000)
    ledger_entry_ids: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_entry_ids(self) -> "SummaryThemeCreate":
        if len(set(self.ledger_entry_ids)) != len(self.ledger_entry_ids):
            raise ValueError("ledger_entry_ids must be unique")
        return self


class SessionSummaryCreate(StrictModel):
    themes: list[SummaryThemeCreate]


class SummaryTheme(SummaryThemeCreate):
    rank: int = Field(ge=1)
    # Derived from the cited entries rather than asked of the model, so "where
    # this happened" is always a real transcript position.
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)


class SessionSummaryResponse(StrictModel):
    id: str
    session_id: str
    transcript_revision_id: str
    themes: list[SummaryTheme]
    entry_count: int
    stale: bool = Field(
        description=(
            "True when ledger entries changed after this summary was generated, "
            "so it no longer reflects the reviewed ledger."
        )
    )
    generated_at: datetime


class VerificationRequest(StrictModel):
    status: VerificationStatus
    note: str | None = Field(default=None, max_length=5_000)

    @model_validator(mode="after")
    def reject_system_status_write(self) -> "VerificationRequest":
        if self.status in {
            VerificationStatus.UNVERIFIED,
            VerificationStatus.NEEDS_REVIEW,
        }:
            raise ValueError(
                f"{self.status} is a system state, not a review decision"
            )
        return self
