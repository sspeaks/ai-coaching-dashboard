from pathlib import Path
from typing import Any

import httpx

from .base import (
    AdapterConfigurationError,
    AdapterResponseError,
    SpeakrRecording,
    TranscriptionSubmissionMode,
)


class SpeakrHttpAdapter:
    """Server-side adapter for Speakr's documented v1 REST API."""

    transcription_submission_mode = TranscriptionSubmissionMode.ON_UPLOAD
    # Upstream limitation: Speakr's v1 upload endpoint accepts no
    # idempotency key and Speakr exposes no endpoint to look up a
    # recording by a client-supplied identifier, so a repeated
    # upload_recording call can never be proven safe after an ambiguous
    # crash. `client_operation_id` is still accepted below (for interface
    # conformity with providers that do support it) but is intentionally
    # not sent to Speakr, since inventing an undocumented request field
    # would be relying on unverified provider behavior.
    supports_upload_idempotency = False
    supports_operation_lookup = False

    def __init__(
        self,
        base_url: str | None,
        api_token: str | None,
        *,
        timeout_seconds: float = 60,
        verify_tls: bool = True,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.api_token = api_token
        self.timeout_seconds = timeout_seconds
        self.verify_tls = verify_tls

    def _client(self) -> httpx.Client:
        if not self.base_url or not self.api_token:
            raise AdapterConfigurationError(
                "Speakr requires EVIDENCE_SPEAKR_BASE_URL and "
                "EVIDENCE_SPEAKR_API_TOKEN"
            )
        return httpx.Client(
            base_url=self.base_url,
            headers={"X-API-Token": self.api_token},
            timeout=self.timeout_seconds,
            verify=self.verify_tls,
            follow_redirects=False,
        )

    @staticmethod
    def _raise(response: httpx.Response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text[:500]
            raise AdapterResponseError(
                f"Speakr returned HTTP {response.status_code}: {detail}"
            ) from exc

    def upload_recording(
        self,
        path: Path,
        *,
        title: str,
        file_last_modified_ms: int | None = None,
        client_operation_id: str | None = None,
    ) -> SpeakrRecording:
        if not path.is_file():
            raise AdapterResponseError(f"media file does not exist: {path}")
        data: dict[str, str] = {"title": title}
        if file_last_modified_ms is not None:
            data["file_last_modified"] = str(file_last_modified_ms)
        with path.open("rb") as media, self._client() as client:
            response = client.post(
                "/api/v1/recordings/upload",
                data=data,
                files={"file": (path.name, media, "application/octet-stream")},
            )
        self._raise(response)
        payload = self._json(response)
        return SpeakrRecording(
            recording_id=str(payload["id"]),
            status=str(payload.get("status", "PENDING")),
            duration_seconds=self._number(payload.get("audio_duration")),
        )

    def queue_transcription(
        self,
        recording_id: str,
        *,
        client_operation_id: str | None = None,
    ) -> str:
        raise AdapterResponseError(
            "Speakr queues transcription as part of a successful recording upload"
        )

    def get_recording(self, recording_id: str) -> SpeakrRecording:
        with self._client() as client:
            response = client.get(
                f"/api/v1/recordings/{recording_id}", params={"format": "minimal"}
            )
        self._raise(response)
        payload = self._json(response)
        return SpeakrRecording(
            recording_id=str(payload["id"]),
            status=str(payload.get("status", "UNKNOWN")),
            duration_seconds=self._number(payload.get("audio_duration")),
        )

    def find_operation_recording(
        self,
        operation_kind: str,
        client_operation_id: str,
    ) -> SpeakrRecording | None:
        raise AdapterResponseError(
            "Speakr cannot look up provider writes by client operation id"
        )

    def get_transcript(self, recording_id: str) -> list[dict]:
        with self._client() as client:
            response = client.get(
                f"/api/v1/recordings/{recording_id}/transcript",
                params={"format": "json"},
            )
        self._raise(response)
        payload = self._json(response)
        segments = payload.get("segments")
        if not isinstance(segments, list):
            raise AdapterResponseError("Speakr transcript omitted a segments list")
        if not segments:
            # Speakr returns an empty list -- and a plain-text `raw` blob -- when
            # the transcription model produced no timestamps. Accepting it would
            # store an empty transcript revision, which reads downstream as "the
            # session contained nothing" rather than "the transcript was lost".
            raise AdapterResponseError(
                "Speakr returned a transcript with no timestamped segments; "
                "the recording must be transcribed with a model that emits "
                "segment timestamps"
            )
        return [self._segment(item, index) for index, item in enumerate(segments)]

    @classmethod
    def _segment(cls, item: Any, index: int) -> dict:
        if not isinstance(item, dict):
            raise AdapterResponseError("Speakr transcript segment was not an object")

        start_ms = cls._timestamp_ms(item, ("start_time", "start"), index)
        end_ms = cls._timestamp_ms(item, ("end_time", "end"), index)
        if end_ms <= start_ms:
            raise AdapterResponseError(
                f"Speakr transcript segment {index} ends at or before it starts"
            )

        text = item.get("sentence")
        if not isinstance(text, str):
            text = item.get("text")
        if not isinstance(text, str):
            raise AdapterResponseError(
                f"Speakr transcript segment {index} carried no text"
            )

        speaker = item.get("speaker")
        segment_id = item.get("id")

        return {
            "segment_id": str(segment_id) if segment_id is not None else f"speakr-{index}",
            "start_ms": start_ms,
            "end_ms": end_ms,
            "text": text,
            "provider_speaker_label": str(speaker) if speaker not in (None, "") else None,
        }

    @staticmethod
    def _timestamp_ms(item: dict, keys: tuple[str, ...], index: int) -> int:
        for key in keys:
            value = item.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            if value < 0:
                raise AdapterResponseError(
                    f"Speakr transcript segment {index} had a negative {key}"
                )
            # Speakr reports segment boundaries in seconds.
            return round(value * 1000)
        raise AdapterResponseError(
            f"Speakr transcript segment {index} omitted {keys[0]}"
        )

    def delete_recording(self, recording_id: str) -> None:
        with self._client() as client:
            response = client.delete(f"/api/v1/recordings/{recording_id}")
        if response.status_code == 404:
            return
        self._raise(response)

    @staticmethod
    def _json(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise AdapterResponseError("Speakr returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise AdapterResponseError("Speakr returned a non-object JSON response")
        return payload

    @staticmethod
    def _number(value: Any) -> float | None:
        return float(value) if isinstance(value, (int, float)) else None
