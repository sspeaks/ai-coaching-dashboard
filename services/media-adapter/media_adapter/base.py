from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol


class AdapterError(RuntimeError):
    code = "adapter_error"


class AdapterConfigurationError(AdapterError):
    code = "adapter_not_configured"


class AdapterResponseError(AdapterError):
    code = "adapter_response_error"


class TranscriptionSubmissionMode(StrEnum):
    ON_UPLOAD = "on_upload"
    EXPLICIT = "explicit"


@dataclass(frozen=True)
class SpeakrRecording:
    recording_id: str
    status: str
    duration_seconds: float | None = None


class MediaAdapter(Protocol):
    transcription_submission_mode: TranscriptionSubmissionMode
    # Whether the provider can deduplicate a repeated upload_recording (or,
    # for EXPLICIT-mode providers, queue_transcription) call that reuses
    # the same client_operation_id -- e.g. via a provider-native
    # idempotency key. Speakr's documented v1 API has neither an
    # idempotency key parameter nor any endpoint to look up a recording by
    # a client-supplied identifier, so SpeakrHttpAdapter declares False:
    # a repeated call after an ambiguous crash cannot be trusted not to
    # create a second recording and must instead be blocked for operator
    # reconciliation (see evidence_api.services.AMBIGUOUS_OPERATION_ERROR_CODE).
    supports_upload_idempotency: bool
    # Whether the provider can look up the durable result of a write by
    # client_operation_id. If true, find_operation_recording must return
    # the created/affected recording, or None when the operation provably
    # did not take effect.
    supports_operation_lookup: bool

    def upload_recording(
        self,
        path: Path,
        *,
        title: str,
        file_last_modified_ms: int | None = None,
        client_operation_id: str | None = None,
    ) -> SpeakrRecording: ...

    def queue_transcription(
        self,
        recording_id: str,
        *,
        client_operation_id: str | None = None,
    ) -> str: ...

    def get_recording(self, recording_id: str) -> SpeakrRecording: ...

    def find_operation_recording(
        self,
        operation_kind: str,
        client_operation_id: str,
    ) -> SpeakrRecording | None: ...

    def get_transcript(self, recording_id: str) -> list[dict]: ...

    def delete_recording(self, recording_id: str) -> None: ...
