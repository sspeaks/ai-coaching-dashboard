import hashlib
import hmac
import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from coaching_contracts import JobStatus, JobType, SessionState
from fastapi.testclient import TestClient
from evidence_api.app import create_app
from evidence_api.config import Settings
from evidence_api.models import (
    JobRecord,
    LedgerEntryRecord,
    ProviderOperationResolutionRecord,
    SessionRecord,
    TranscriptRevisionRecord,
)
from evidence_api.services import (
    AMBIGUOUS_OPERATION_ERROR_CODE,
    begin_pending_operation,
)
from media_adapter import AdapterResponseError, SpeakrRecording


def create_session(client, title="Coaching session"):
    response = client.post(
        "/api/sessions", json={"title": title, "duration_ms": 10_000}
    )
    assert response.status_code == 201
    return response.json()


class RecordingLookupAdapter:
    supports_operation_lookup = False

    def __init__(self, recordings=()):
        self.recordings = set(recordings)

    def get_recording(self, recording_id):
        if recording_id not in self.recordings:
            raise AdapterResponseError("provider recording not found")
        return SpeakrRecording(recording_id, "COMPLETED", 1.0)


class OperationLookupAdapter(RecordingLookupAdapter):
    supports_operation_lookup = True

    def __init__(self, operation_recording=None):
        super().__init__()
        self.operation_recording = operation_recording

    def find_operation_recording(self, operation_kind, client_operation_id):
        assert operation_kind == "upload"
        assert client_operation_id
        return self.operation_recording


def create_ambiguous_upload(app):
    with app.state.session_factory() as db:
        session = SessionRecord(
            title="Ambiguous provider operation",
            state=SessionState.FAILED.value,
        )
        db.add(session)
        db.flush()
        operation_id = begin_pending_operation(session, "upload")
        job = JobRecord(
            session_id=session.id,
            type=JobType.TRANSCRIBE.value,
            status=JobStatus.FAILED.value,
            error_code=AMBIGUOUS_OPERATION_ERROR_CODE,
            ambiguous_operation_id=operation_id,
            error_message=f"ambiguous operation {operation_id}",
            max_attempts=3,
        )
        db.add(job)
        db.commit()
        return session.id, job.id, operation_id


def test_session_upload_and_transcription_job(client, app):
    created = create_session(client)
    uploaded = client.post(
        f"/api/sessions/{created['id']}/media",
        files={"media": ("session.wav", b"original-audio", "audio/wav")},
    )
    assert uploaded.status_code == 200
    assert uploaded.json()["state"] == "TRANSCRIBING"
    assert uploaded.json()["media_sha256"] == hashlib.sha256(
        b"original-audio"
    ).hexdigest()

    playback = client.get(uploaded.json()["playback_url"])
    assert playback.status_code == 200
    assert playback.content == b"original-audio"
    session = client.get(f"/api/sessions/{created['id']}").json()
    assert session["state"] == "TRANSCRIBING"
    with app.state.session_factory() as db:
        jobs = list(db.query(JobRecord).filter_by(session_id=created["id"]))
        assert [job.type for job in jobs] == ["TRANSCRIBE"]


def test_ledger_evidence_and_human_verification_complete_session(client, app):
    created = create_session(client)
    with app.state.session_factory() as db:
        session = db.get(SessionRecord, created["id"])
        revision = TranscriptRevisionRecord(
            session_id=session.id,
            sha256="a" * 64,
            source="test",
            segments=[
                {
                    "segment_id": "0",
                    "start_ms": 1000,
                    "end_ms": 3000,
                    "text": "Coach: Release the sound instead of pushing.",
                    "provider_speaker_label": "SPEAKER_00",
                }
            ],
        )
        db.add(revision)
        db.flush()
        session.current_transcript_revision_id = revision.id
        session.state = SessionState.TRANSCRIPT_READY.value
        db.commit()
        revision_id = revision.id

    entry = client.post(
        f"/api/sessions/{created['id']}/ledger",
        json={
            "topic": "Release",
            "exact_coach_feedback": "Release the sound instead of pushing.",
            "confidence": 0.8,
            "evidence": [
                {
                    "transcript_revision_id": revision_id,
                    "start_ms": 1000,
                    "end_ms": 3000,
                    "segment_ids": ["0"],
                }
            ],
        },
    )
    assert entry.status_code == 201
    assert entry.json()["verification_status"] == "UNVERIFIED"

    verified = client.put(
        f"/api/ledger/{entry.json()['id']}/verification",
        json={"status": "VERIFIED", "note": "Checked against audio."},
    )
    assert verified.status_code == 200
    assert verified.json()["verified_by"] == "local-developer@example.invalid"
    session = client.get(f"/api/sessions/{created['id']}").json()
    assert session["state"] == "COMPLETE"


def test_rejects_unanchored_exact_quote(client, app):
    created = create_session(client)
    with app.state.session_factory() as db:
        session = db.get(SessionRecord, created["id"])
        revision = TranscriptRevisionRecord(
            session_id=session.id,
            sha256="b" * 64,
            source="test",
            segments=[
                {
                    "segment_id": "0",
                    "start_ms": 0,
                    "end_ms": 1000,
                    "text": "Try that again.",
                    "provider_speaker_label": None,
                }
            ],
        )
        db.add(revision)
        db.flush()
        session.current_transcript_revision_id = revision.id
        session.state = SessionState.TRANSCRIPT_READY.value
        db.commit()
        revision_id = revision.id
    response = client.post(
        f"/api/sessions/{created['id']}/ledger",
        json={
            "topic": "Unsupported quote",
            "exact_coach_feedback": "You improved.",
            "confidence": 0.4,
            "evidence": [
                {
                    "transcript_revision_id": revision_id,
                    "start_ms": 0,
                    "end_ms": 1000,
                    "segment_ids": ["0"],
                }
            ],
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_evidence_reference"


def test_rejects_evidence_subrange_not_covering_full_segment(client, app):
    """A 9000-10000ms reference against a 0-10000ms segment must be
    rejected: without independently validated word-level timestamps, an
    evidence reference must cover the complete referenced segment."""
    created = create_session(client)
    with app.state.session_factory() as db:
        session = db.get(SessionRecord, created["id"])
        revision = TranscriptRevisionRecord(
            session_id=session.id,
            sha256="e" * 64,
            source="test",
            segments=[
                {
                    "segment_id": "0",
                    "start_ms": 0,
                    "end_ms": 10_000,
                    "text": "This is a full ten second segment of speech.",
                    "provider_speaker_label": None,
                }
            ],
        )
        db.add(revision)
        db.flush()
        session.current_transcript_revision_id = revision.id
        session.state = SessionState.TRANSCRIPT_READY.value
        db.commit()
        revision_id = revision.id
    response = client.post(
        f"/api/sessions/{created['id']}/ledger",
        json={
            "topic": "Subrange",
            "confidence": 0.4,
            "evidence": [
                {
                    "transcript_revision_id": revision_id,
                    "start_ms": 9_000,
                    "end_ms": 10_000,
                    "segment_ids": ["0"],
                }
            ],
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_evidence_reference"


def test_accepts_evidence_covering_full_segment(client, app):
    created = create_session(client)
    with app.state.session_factory() as db:
        session = db.get(SessionRecord, created["id"])
        revision = TranscriptRevisionRecord(
            session_id=session.id,
            sha256="f" * 64,
            source="test",
            segments=[
                {
                    "segment_id": "0",
                    "start_ms": 0,
                    "end_ms": 10_000,
                    "text": "This is a full ten second segment of speech.",
                    "provider_speaker_label": None,
                }
            ],
        )
        db.add(revision)
        db.flush()
        session.current_transcript_revision_id = revision.id
        session.state = SessionState.TRANSCRIPT_READY.value
        db.commit()
        revision_id = revision.id
    response = client.post(
        f"/api/sessions/{created['id']}/ledger",
        json={
            "topic": "Full segment",
            "confidence": 0.4,
            "evidence": [
                {
                    "transcript_revision_id": revision_id,
                    "start_ms": 0,
                    "end_ms": 10_000,
                    "segment_ids": ["0"],
                }
            ],
        },
    )
    assert response.status_code == 201


def test_webhook_hmac_freshness_and_idempotency(client, app):
    created = create_session(client)
    with app.state.session_factory() as db:
        session = db.get(SessionRecord, created["id"])
        session.speakr_recording_id = "9173"
        session.state = SessionState.TRANSCRIBING.value
        db.commit()

    delivery_id = "f4e6a4e1-3b9b-4a04-9d4f-0e7a5d8b3c10"
    timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    body = json.dumps(
        {
            "id": delivery_id,
            "type": "recording.transcription.completed",
            "timestamp": timestamp,
            "user_id": 42,
            "data": {
                "recording_id": 9173,
                "title": "Coaching session",
                "audio_duration_seconds": 12.345,
            },
        },
        separators=(",", ":"),
    ).encode()
    signature = hmac.new(
        b"test-webhook-secret", body, hashlib.sha256
    ).hexdigest()
    headers = {
        "Content-Type": "application/json",
        "Speakr-Event": "recording.transcription.completed",
        "Speakr-Delivery-Id": delivery_id,
        "Speakr-Timestamp": timestamp,
        "Speakr-Signature": f"sha256={signature}",
    }
    first = client.post("/api/webhooks/speakr", content=body, headers=headers)
    second = client.post("/api/webhooks/speakr", content=body, headers=headers)
    assert first.json() == {"accepted": True, "duplicate": False}
    assert second.json() == {"accepted": True, "duplicate": True}

    with app.state.session_factory() as db:
        session = db.get(SessionRecord, created["id"])
        assert session.state == SessionState.TRANSCRIBING.value
        assert session.duration_ms == 12_345
        jobs = list(db.query(JobRecord).filter_by(session_id=session.id))
        assert len(jobs) == 1
        assert jobs[0].status == JobStatus.QUEUED.value


def test_webhook_rejects_modified_raw_body(client):
    timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    body = json.dumps(
        {
            "id": "delivery",
            "type": "webhook.test",
            "timestamp": timestamp,
            "data": {},
        },
        separators=(",", ":"),
    ).encode()
    signature = hmac.new(
        b"test-webhook-secret", body + b" ", hashlib.sha256
    ).hexdigest()
    response = client.post(
        "/api/webhooks/speakr",
        content=body,
        headers={
            "Content-Type": "application/json",
            "Speakr-Event": "webhook.test",
            "Speakr-Delivery-Id": "delivery",
            "Speakr-Timestamp": timestamp,
            "Speakr-Signature": f"sha256={signature}",
        },
    )
    assert response.status_code == 401


def test_webhook_rejects_replay_with_fresh_unsigned_header(client):
    old_timestamp = (datetime.now(UTC) - timedelta(hours=1)).isoformat().replace(
        "+00:00", "Z"
    )
    fresh_timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    body = json.dumps(
        {
            "id": "old-delivery",
            "type": "webhook.test",
            "timestamp": old_timestamp,
            "data": {},
        },
        separators=(",", ":"),
    ).encode()
    signature = hmac.new(
        b"test-webhook-secret", body, hashlib.sha256
    ).hexdigest()
    response = client.post(
        "/api/webhooks/speakr",
        content=body,
        headers={
            "Content-Type": "application/json",
            "Speakr-Event": "webhook.test",
            "Speakr-Delivery-Id": "old-delivery",
            "Speakr-Timestamp": fresh_timestamp,
            "Speakr-Signature": f"sha256={signature}",
        },
    )
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "webhook_timestamp_mismatch"


def test_cancel_refresh_and_confirmed_deletion(client, app):
    created = create_session(client)
    client.post(
        f"/api/sessions/{created['id']}/media",
        files={"media": ("session.wav", b"audio", "audio/wav")},
    )
    with app.state.session_factory() as db:
        session = db.get(SessionRecord, created["id"])
        media_path = Path(session.media_path)

    cancelled = client.post(f"/api/sessions/{created['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["state"] == "CANCELLED"

    refreshed = client.post(f"/api/sessions/{created['id']}/refresh")
    repeated = client.post(f"/api/sessions/{created['id']}/refresh")
    assert refreshed.status_code == 202
    assert repeated.status_code == 202
    with app.state.session_factory() as db:
        active = list(
            db.query(JobRecord).filter(
                JobRecord.session_id == created["id"],
                JobRecord.status.in_(["QUEUED", "RUNNING"]),
            )
        )
        assert len(active) == 1

    pending = client.delete(f"/api/sessions/{created['id']}")
    assert pending.status_code == 200
    assert pending.json()["state"] == "DELETE_PENDING"
    mismatch = client.post(
        f"/api/sessions/{created['id']}/deletion/confirm",
        json={"confirm_session_id": "wrong"},
    )
    assert mismatch.status_code == 400
    confirmed = client.post(
        f"/api/sessions/{created['id']}/deletion/confirm",
        json={"confirm_session_id": created["id"]},
    )
    assert confirmed.status_code == 204
    assert not media_path.exists()
    assert client.get(f"/api/sessions/{created['id']}").status_code == 404


def test_manual_speakr_refresh_is_idempotent_and_pollable(client, app):
    created = create_session(client)
    with app.state.session_factory() as db:
        session = db.get(SessionRecord, created["id"])
        session.state = SessionState.COMPLETE.value
        session.speakr_recording_id = "recording-edited"
        revision = TranscriptRevisionRecord(
            session_id=session.id,
            sha256="e" * 64,
            source="speakr",
            segments=[
                {
                    "segment_id": "0",
                    "start_ms": 0,
                    "end_ms": 1000,
                    "text": "Original.",
                    "provider_speaker_label": None,
                }
            ],
        )
        db.add(revision)
        db.flush()
        session.current_transcript_revision_id = revision.id
        db.commit()

    first = client.post(f"/api/sessions/{created['id']}/refresh")
    second = client.post(f"/api/sessions/{created['id']}/refresh")
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["state"] == "RECONCILING"
    with app.state.session_factory() as db:
        active = list(
            db.query(JobRecord).filter(
                JobRecord.session_id == created["id"],
                JobRecord.type == "RECONCILE",
                JobRecord.status.in_(["QUEUED", "RUNNING"]),
            )
        )
        assert len(active) == 1


def test_ambiguity_resolution_rejects_active_operation(client, app):
    session_id, _, operation_id = create_ambiguous_upload(app)
    with app.state.session_factory() as db:
        db.add(
            JobRecord(
                session_id=session_id,
                type=JobType.TRANSCRIBE.value,
                status=JobStatus.RUNNING.value,
                max_attempts=3,
            )
        )
        db.commit()
    app.state.speakr_adapter = RecordingLookupAdapter({"reachable-recording"})

    response = client.post(
        f"/api/sessions/{session_id}/upload-operation/resolve",
        json={
            "confirm_operation_id": operation_id,
            "outcome": "adopt_existing",
            "speakr_recording_id": "reachable-recording",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "provider_operation_active"
    with app.state.session_factory() as db:
        session = db.get(SessionRecord, session_id)
        assert session.pending_operation_id == operation_id
        assert db.query(ProviderOperationResolutionRecord).count() == 0


def test_ambiguity_resolution_requires_matching_terminal_job(client, app):
    session_id, _, operation_id = create_ambiguous_upload(app)
    with app.state.session_factory() as db:
        job = db.query(JobRecord).filter_by(session_id=session_id).one()
        job.ambiguous_operation_id = "different-operation"
        db.commit()

    response = client.post(
        f"/api/sessions/{session_id}/upload-operation/resolve",
        json={
            "confirm_operation_id": operation_id,
            "outcome": "not_created",
            "allow_unverified_absence": True,
            "override_reason": "Terminal job does not match this operation.",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "ambiguous_job_required"
    with app.state.session_factory() as db:
        assert db.get(SessionRecord, session_id).pending_operation_id == operation_id


def test_ambiguity_resolution_rejects_unreachable_adopted_recording(client, app):
    session_id, _, operation_id = create_ambiguous_upload(app)
    app.state.speakr_adapter = RecordingLookupAdapter()

    response = client.post(
        f"/api/sessions/{session_id}/upload-operation/resolve",
        json={
            "confirm_operation_id": operation_id,
            "outcome": "adopt_existing",
            "speakr_recording_id": "arbitrary-recording-id",
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "adopted_recording_unreachable"
    with app.state.session_factory() as db:
        session = db.get(SessionRecord, session_id)
        assert session.pending_operation_id == operation_id
        assert session.speakr_recording_id is None
        assert db.query(ProviderOperationResolutionRecord).count() == 0


def test_ambiguity_resolution_validates_and_audits_adoption(client, app):
    session_id, job_id, operation_id = create_ambiguous_upload(app)
    app.state.speakr_adapter = RecordingLookupAdapter({"reachable-recording"})

    response = client.post(
        f"/api/sessions/{session_id}/upload-operation/resolve",
        json={
            "confirm_operation_id": operation_id,
            "outcome": "adopt_existing",
            "speakr_recording_id": "reachable-recording",
        },
    )

    assert response.status_code == 200
    assert response.json()["speakr_recording_id"] == "reachable-recording"
    with app.state.session_factory() as db:
        session = db.get(SessionRecord, session_id)
        resolution = db.query(ProviderOperationResolutionRecord).one()
        assert session.pending_operation_id is None
        assert resolution.job_id == job_id
        assert resolution.operation_id == operation_id
        assert resolution.remote_recording_id == "reachable-recording"
        assert resolution.verification_method == "provider_recording_lookup"
        assert resolution.resolved_by == "local-developer@example.invalid"


def test_not_created_requires_audited_override_without_provider_lookup(
    client, app
):
    session_id, _, operation_id = create_ambiguous_upload(app)
    app.state.speakr_adapter = RecordingLookupAdapter()

    rejected = client.post(
        f"/api/sessions/{session_id}/upload-operation/resolve",
        json={
            "confirm_operation_id": operation_id,
            "outcome": "not_created",
        },
    )
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["code"] == "absence_override_required"

    resolved = client.post(
        f"/api/sessions/{session_id}/upload-operation/resolve",
        json={
            "confirm_operation_id": operation_id,
            "outcome": "not_created",
            "allow_unverified_absence": True,
            "override_reason": (
                "Operator checked the integration account and found no recording."
            ),
        },
    )
    assert resolved.status_code == 200
    with app.state.session_factory() as db:
        resolution = db.query(ProviderOperationResolutionRecord).one()
        assert resolution.outcome == "not_created"
        assert resolution.verification_method == "explicit_operator_override"
        assert "Operator checked" in resolution.override_reason


def test_not_created_uses_provider_absence_lookup_when_supported(client, app):
    session_id, _, operation_id = create_ambiguous_upload(app)
    app.state.speakr_adapter = OperationLookupAdapter(
        SpeakrRecording("provider-created-recording", "COMPLETED", 1.0)
    )

    found = client.post(
        f"/api/sessions/{session_id}/upload-operation/resolve",
        json={
            "confirm_operation_id": operation_id,
            "outcome": "not_created",
        },
    )
    assert found.status_code == 409
    assert found.json()["detail"]["code"] == "provider_operation_was_created"

    app.state.speakr_adapter = OperationLookupAdapter()
    response = client.post(
        f"/api/sessions/{session_id}/upload-operation/resolve",
        json={
            "confirm_operation_id": operation_id,
            "outcome": "not_created",
        },
    )
    assert response.status_code == 200
    with app.state.session_factory() as db:
        resolution = db.query(ProviderOperationResolutionRecord).one()
        assert resolution.verification_method == "provider_operation_lookup"
        assert resolution.override_reason is None


def test_trusted_proxy_rbac_enforces_viewer_editor_and_admin():
    root = Path("services/evidence-api/tests/.runtime-rbac")
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    proxy_secret = "s" * 40
    settings = Settings(
        environment="test",
        auth_mode="trusted_proxy",
        trusted_proxy_networks="127.0.0.0/8",
        trusted_proxy_shared_secret=proxy_secret,
        database_url=f"sqlite:///{root / 'evidence.db'}",
        media_root=root / "media",
    )
    app = create_app(settings)
    with TestClient(app, client=("127.0.0.1", 50000)) as proxy_client:
        secret_header = {settings.trusted_proxy_secret_header: proxy_secret}
        viewer = {**secret_header, "X-Auth-Request-Email": "viewer@example.com"}
        editor = {
            **secret_header,
            "X-Auth-Request-Email": "editor@example.com",
            "X-Auth-Request-Groups": "evidence-editors",
        }
        admin = {
            **secret_header,
            "X-Auth-Request-Email": "admin@example.com",
            "X-Auth-Request-Groups": "evidence-admins",
        }
        assert proxy_client.get("/api/sessions", headers=viewer).status_code == 200
        assert (
            proxy_client.post(
                "/api/sessions", json={"title": "Denied"}, headers=viewer
            ).status_code
            == 403
        )
        created = proxy_client.post(
            "/api/sessions", json={"title": "Allowed"}, headers=editor
        )
        assert created.status_code == 201
        session_id = created.json()["id"]
        with app.state.session_factory() as db:
            session = db.get(SessionRecord, session_id)
            revision = TranscriptRevisionRecord(
                session_id=session_id,
                sha256="d" * 64,
                source="test",
                segments=[
                    {
                        "segment_id": "0",
                        "start_ms": 0,
                        "end_ms": 1000,
                        "text": "Review me.",
                        "provider_speaker_label": None,
                    }
                ],
            )
            db.add(revision)
            db.flush()
            session.current_transcript_revision_id = revision.id
            session.state = SessionState.AWAITING_REVIEW.value
            entry = LedgerEntryRecord(
                session_id=session_id,
                transcript_revision_id=revision.id,
                topic="Review",
                confidence_millis=500,
                evidence=[
                    {
                        "transcript_revision_id": revision.id,
                        "start_ms": 0,
                        "end_ms": 1000,
                        "segment_ids": ["0"],
                    }
                ],
                extraction_metadata={},
            )
            db.add(entry)
            db.commit()
            entry_id = entry.id
        assert (
            proxy_client.put(
                f"/api/ledger/{entry_id}/verification",
                json={"status": "VERIFIED"},
                headers=viewer,
            ).status_code
            == 403
        )
        assert (
            proxy_client.put(
                f"/api/ledger/{entry_id}/verification",
                json={"status": "VERIFIED"},
                headers=editor,
            ).status_code
            == 200
        )
        with app.state.session_factory() as db:
            session = db.get(SessionRecord, session_id)
            operation_id = begin_pending_operation(session, "upload")
            db.add(
                JobRecord(
                    session_id=session_id,
                    type=JobType.TRANSCRIBE.value,
                    status=JobStatus.FAILED.value,
                    error_code=AMBIGUOUS_OPERATION_ERROR_CODE,
                    ambiguous_operation_id=operation_id,
                    max_attempts=3,
                )
            )
            db.commit()
        assert (
            proxy_client.post(
                f"/api/sessions/{session_id}/upload-operation/resolve",
                json={
                    "confirm_operation_id": operation_id,
                    "outcome": "not_created",
                    "allow_unverified_absence": True,
                    "override_reason": "Editor must not resolve provider ambiguity.",
                },
                headers=editor,
            ).status_code
            == 403
        )
        assert (
            proxy_client.delete(
                f"/api/sessions/{session_id}", headers=editor
            ).status_code
            == 403
        )
        assert (
            proxy_client.delete(
                f"/api/sessions/{session_id}", headers=admin
            ).status_code
            == 200
        )


def test_trusted_proxy_rejects_peer_container_spoofing_without_shared_secret():
    """A peer container on the trusted network that forges identity headers
    but does not hold the shared secret must be rejected, even though it
    satisfies both the IP-allowlist and identity-header checks."""
    root = Path("services/evidence-api/tests/.runtime-rbac-spoof")
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    proxy_secret = "s" * 40
    settings = Settings(
        environment="test",
        auth_mode="trusted_proxy",
        trusted_proxy_networks="127.0.0.0/8",
        trusted_proxy_shared_secret=proxy_secret,
        database_url=f"sqlite:///{root / 'evidence.db'}",
        media_root=root / "media",
    )
    app = create_app(settings)
    with TestClient(app, client=("127.0.0.1", 50000)) as proxy_client:
        forged_admin_headers = {
            "X-Auth-Request-Email": "admin@example.com",
            "X-Auth-Request-Groups": "evidence-admins",
        }
        # No secret header at all.
        response = proxy_client.get("/api/sessions", headers=forged_admin_headers)
        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "proxy_secret_required"

        # Wrong secret value.
        response = proxy_client.get(
            "/api/sessions",
            headers={
                **forged_admin_headers,
                settings.trusted_proxy_secret_header: "wrong-secret-value",
            },
        )
        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "proxy_secret_required"

        # Correct secret restores access.
        response = proxy_client.get(
            "/api/sessions",
            headers={
                **forged_admin_headers,
                settings.trusted_proxy_secret_header: proxy_secret,
            },
        )
        assert response.status_code == 200


def test_trusted_proxy_fails_closed_when_secret_not_configured():
    """If a deployment forgets to configure the shared secret, every
    request must be rejected rather than silently trusting identity
    headers -- fail closed, not fail open."""
    root = Path("services/evidence-api/tests/.runtime-rbac-unconfigured")
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    settings = Settings(
        environment="test",
        auth_mode="trusted_proxy",
        trusted_proxy_networks="127.0.0.0/8",
        database_url=f"sqlite:///{root / 'evidence.db'}",
        media_root=root / "media",
    )
    assert settings.trusted_proxy_shared_secret is None
    app = create_app(settings)
    with TestClient(app, client=("127.0.0.1", 50000)) as proxy_client:
        response = proxy_client.get(
            "/api/sessions",
            headers={
                "X-Auth-Request-Email": "admin@example.com",
                "X-Auth-Request-Groups": "evidence-admins",
                settings.trusted_proxy_secret_header: "anything",
            },
        )
        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "proxy_secret_required"


def test_development_auth_rejects_non_loopback_connections():
    root = Path("services/evidence-api/tests/.runtime-dev-non-loopback")
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    settings = Settings(
        environment="test",
        auth_mode="development",
        database_url=f"sqlite:///{root / 'evidence.db'}",
        media_root=root / "media",
    )
    app = create_app(settings)
    # Default TestClient host ("testclient") is not loopback.
    with TestClient(app) as non_loopback_client:
        response = non_loopback_client.get("/api/sessions")
        assert response.status_code == 401
        assert (
            response.json()["detail"]["code"] == "development_auth_requires_loopback"
        )
    with TestClient(app, client=("127.0.0.1", 50000)) as loopback_client:
        assert loopback_client.get("/api/sessions").status_code == 200


def test_confirm_deletion_defers_while_worker_holds_active_lease(client, app):
    """Reproduces the second-review finding directly at the API layer:
    confirm_deletion must not delete a session (and truthfully must not
    report success) while a job for that session is RUNNING with a fresh
    lease, since a worker may still be mid-upload to the provider. Once
    the job is no longer active (simulating the worker having observed
    the deletion tombstone and self-cancelled), confirmation proceeds and
    genuinely deletes the session."""
    created = create_session(client)
    with app.state.session_factory() as db:
        job = JobRecord(
            session_id=created["id"],
            type=JobType.TRANSCRIBE.value,
            status=JobStatus.RUNNING.value,
            max_attempts=3,
        )
        db.add(job)
        db.commit()
        job_id = job.id

    pending = client.delete(f"/api/sessions/{created['id']}")
    assert pending.status_code == 200
    assert pending.json()["state"] == "DELETE_PENDING"
    with app.state.session_factory() as db:
        job = db.get(JobRecord, job_id)
        # request_deletion must leave a RUNNING job's status untouched --
        # cancelling it here would make the has_active_job lease check
        # below meaningless, defeating the very race protection it exists
        # to provide.
        assert job.status == JobStatus.RUNNING.value

    deferred = client.post(
        f"/api/sessions/{created['id']}/deletion/confirm",
        json={"confirm_session_id": created["id"]},
    )
    assert deferred.status_code == 202
    assert deferred.json()["code"] == "deletion_pending_active_job"
    # The session must genuinely still exist -- confirm_deletion must not
    # have deleted anything while reporting this truthful pending state.
    assert client.get(f"/api/sessions/{created['id']}").status_code == 200

    with app.state.session_factory() as db:
        job = db.get(JobRecord, job_id)
        job.status = JobStatus.CANCELLED.value
        db.commit()

    confirmed = client.post(
        f"/api/sessions/{created['id']}/deletion/confirm",
        json={"confirm_session_id": created["id"]},
    )
    assert confirmed.status_code == 204
    assert client.get(f"/api/sessions/{created['id']}").status_code == 404


def _summarized_session(client, settings):
    from datetime import UTC, datetime

    from evidence_api.db import create_db_engine, create_session_factory
    from evidence_api.models import (
        LedgerEntryRecord,
        SessionRecord,
        SessionSummaryRecord,
        TranscriptRevisionRecord,
    )

    factory = create_session_factory(create_db_engine(settings))
    with factory() as db:
        session = SessionRecord(title="Rehearsal", state="AWAITING_REVIEW")
        db.add(session)
        db.flush()
        revision = TranscriptRevisionRecord(
            session_id=session.id, sha256="a" * 64, segments=[]
        )
        db.add(revision)
        db.flush()
        session.current_transcript_revision_id = revision.id
        entry = LedgerEntryRecord(
            session_id=session.id,
            transcript_revision_id=revision.id,
            topic="Release",
            confidence_millis=900,
            evidence=[
                {
                    "transcript_revision_id": revision.id,
                    "start_ms": 1000,
                    "end_ms": 2500,
                    "segment_ids": ["seg-1"],
                }
            ],
            extraction_metadata={},
        )
        db.add(entry)
        db.flush()
        db.add(
            SessionSummaryRecord(
                session_id=session.id,
                transcript_revision_id=revision.id,
                themes=[
                    {
                        "rank": 1,
                        "title": "Releasing the sound",
                        "summary": "The coach worked on release.",
                        "ledger_entry_ids": [entry.id],
                        "moments": [
                            {
                                "ledger_entry_id": entry.id,
                                "start_ms": 1000,
                                "end_ms": 2500,
                            }
                        ],
                        "start_ms": 1000,
                        "end_ms": 2500,
                    }
                ],
                entry_count=1,
                source_updated_at=entry.updated_at,
                generated_at=datetime.now(UTC),
            )
        )
        db.commit()
        return session.id, entry.id


def test_summary_reports_where_each_theme_happened(client, settings):
    session_id, entry_id = _summarized_session(client, settings)

    body = client.get(f"/api/sessions/{session_id}/summary").json()

    assert body["stale"] is False
    theme = body["themes"][0]
    assert theme["rank"] == 1
    assert theme["start_ms"] == 1000
    assert theme["end_ms"] == 2500
    assert theme["moments"] == [
        {"ledger_entry_id": entry_id, "start_ms": 1000, "end_ms": 2500}
    ]
    assert theme["ledger_entry_ids"] == [entry_id]


def test_summary_is_marked_stale_once_the_ledger_changes(client, settings):
    session_id, entry_id = _summarized_session(client, settings)

    # Reviewing an entry must not silently leave a summary that no longer
    # describes the ledger looking authoritative.
    response = client.put(
        f"/api/ledger/{entry_id}/verification", json={"status": "VERIFIED"}
    )
    assert response.status_code in (200, 201)

    body = client.get(f"/api/sessions/{session_id}/summary").json()
    assert body["stale"] is True


def test_a_session_without_a_summary_says_so(client):
    created = client.post("/api/sessions", json={"title": "No summary"}).json()

    response = client.get(f"/api/sessions/{created['id']}/summary")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "summary_not_found"
