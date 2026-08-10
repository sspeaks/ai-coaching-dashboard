import httpx
import logging
import time
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm.exc import StaleDataError

import pytest
from coaching_contracts import (
    EvidenceReference,
    JobStatus,
    JobType,
    LedgerEntryCreate,
    SessionState,
    SessionSummaryCreate,
    SummaryThemeCreate,
    TranscriptSegment,
)
from evidence_api.app import create_app
from evidence_api.db import (
    create_db_engine,
    create_session_factory,
    init_schema,
)
from evidence_api.models import (
    DeletionCompensationRecord,
    DeletionTombstoneRecord,
    JobRecord,
    LedgerEntryRecord,
    SessionRecord,
    TranscriptRevisionRecord,
)
from evidence_api.services import (
    AMBIGUOUS_OPERATION_ERROR_CODE,
    begin_pending_operation,
    record_deletion_intent,
)
from evidence_api.state import transition
from evidence_worker.worker import Worker
from media_adapter import (
    AdapterResponseError,
    SpeakrHttpAdapter,
    SpeakrRecording,
    TranscriptionSubmissionMode,
)


def test_worker_reports_unconfigured_speakr_without_fake_success(settings):
    engine = create_db_engine(settings)
    init_schema(engine)
    factory = create_session_factory(engine)
    media = settings.media_root / "retained.wav"
    media.parent.mkdir(parents=True, exist_ok=True)
    media.write_bytes(b"audio")
    with factory() as db:
        session = SessionRecord(
            title="Test",
            state=SessionState.TRANSCRIBING.value,
            media_path=str(media),
        )
        db.add(session)
        db.flush()
        job = JobRecord(
            session_id=session.id,
            type=JobType.TRANSCRIBE.value,
            max_attempts=3,
        )
        db.add(job)
        db.commit()
        job_id = job.id
        session_id = session.id

    assert Worker(settings, factory).run_once() is True
    with factory() as db:
        job = db.get(JobRecord, job_id)
        session = db.get(SessionRecord, session_id)
        assert job.status == JobStatus.FAILED.value
        assert job.error_code == "adapter_not_configured"
        assert session.state == SessionState.FAILED.value
        assert "EVIDENCE_SPEAKR_BASE_URL" in session.last_error


def test_speakr_upload_is_the_only_transcription_submission(settings, monkeypatch):
    engine = create_db_engine(settings)
    init_schema(engine)
    factory = create_session_factory(engine)
    media = settings.media_root / "retained.wav"
    media.parent.mkdir(parents=True, exist_ok=True)
    media.write_bytes(b"audio")
    with factory() as db:
        session = SessionRecord(
            title="Speakr single submission",
            state=SessionState.TRANSCRIBING.value,
            media_path=str(media),
        )
        db.add(session)
        db.flush()
        db.add(
            JobRecord(
                session_id=session.id,
                type=JobType.TRANSCRIBE.value,
                max_attempts=3,
            )
        )
        db.commit()
        session_id = session.id

    requests: list[tuple[str, str]] = []

    def handle_request(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        return httpx.Response(
            202,
            json={
                "id": "recording-1",
                "status": "PENDING",
                "audio_duration": 2.0,
            },
        )

    transport = httpx.MockTransport(handle_request)
    adapter = SpeakrHttpAdapter("https://speakr.invalid", "test-token")
    monkeypatch.setattr(
        adapter,
        "_client",
        lambda: httpx.Client(
            base_url=adapter.base_url,
            headers={"X-API-Token": adapter.api_token},
            transport=transport,
        ),
    )

    assert Worker(settings, factory, adapter=adapter).run_once() is True

    assert requests == [("POST", "/api/v1/recordings/upload")]
    with factory() as db:
        session = db.get(SessionRecord, session_id)
        assert session.speakr_recording_id == "recording-1"
        assert session.transcription_submitted_at is not None


class FakeSpeakrAdapter:
    transcription_submission_mode = TranscriptionSubmissionMode.ON_UPLOAD

    def __init__(self):
        self.uploads = 0
        self.submissions = 0
        self.explicit_submission_calls = 0

    def upload_recording(
        self, path, *, title, file_last_modified_ms=None, client_operation_id=None
    ):
        assert path.read_bytes() == b"audio"
        assert title == "Automatic chain"
        self.uploads += 1
        self.submissions += 1
        return SpeakrRecording("recording-1", "PENDING", 2.0)

    def queue_transcription(self, recording_id, *, client_operation_id=None):
        self.explicit_submission_calls += 1
        raise AssertionError("Speakr upload already queued transcription")

    def get_recording(self, recording_id):
        assert recording_id == "recording-1"
        return SpeakrRecording("recording-1", "COMPLETED", 2.0)

    def get_transcript(self, recording_id):
        assert recording_id == "recording-1"
        return [
            {
                "id": "segment-1",
                "start_time": 0.25,
                "end_time": 1.25,
                "sentence": "Release the sound.",
                "speaker": "SPEAKER_00",
            }
        ]

    def delete_recording(self, recording_id):
        raise NotImplementedError


class FakeExtractionProvider:
    def extract(
        self,
        *,
        session_id,
        title,
        transcript_revision_id,
        segments,
    ):
        assert title == "Automatic chain"
        assert segments[0].start_ms == 250
        return [
            LedgerEntryCreate(
                topic="Release",
                exact_coach_feedback="Release the sound.",
                confidence=0.9,
                evidence=[
                    EvidenceReference(
                        transcript_revision_id=transcript_revision_id,
                        start_ms=250,
                        end_ms=1250,
                        segment_ids=["segment-1"],
                    )
                ],
            )
        ]


class FakeSummaryProvider:
    def __init__(self):
        self.calls = []

    def summarize(self, *, session_id, title, transcript_revision_id, theme_count, entries):
        self.calls.append(entries)
        return SessionSummaryCreate(
            themes=[
                SummaryThemeCreate(
                    title="Releasing the sound",
                    summary="The coach worked on releasing tension.",
                    ledger_entry_ids=[entry["id"] for entry in entries],
                )
            ]
        )


def test_worker_runs_upload_to_ledger_chain_without_manual_jobs(settings):
    engine = create_db_engine(settings)
    init_schema(engine)
    factory = create_session_factory(engine)
    media = settings.media_root / "retained.wav"
    media.parent.mkdir(parents=True, exist_ok=True)
    media.write_bytes(b"audio")
    with factory() as db:
        session = SessionRecord(
            title="Automatic chain",
            state=SessionState.TRANSCRIBING.value,
            media_path=str(media),
        )
        db.add(session)
        db.flush()
        db.add(
            JobRecord(
                session_id=session.id,
                type=JobType.TRANSCRIBE.value,
                max_attempts=3,
            )
        )
        db.commit()
        session_id = session.id

    adapter = FakeSpeakrAdapter()
    summaries = FakeSummaryProvider()
    worker = Worker(
        settings,
        factory,
        adapter=adapter,
        extraction_provider=FakeExtractionProvider(),
        summary_provider=summaries,
    )
    assert worker.run_once() is True
    assert worker.run_once() is True
    assert worker.run_once() is True
    assert worker.run_once() is True
    assert worker.run_once() is False

    with factory() as db:
        session = db.get(SessionRecord, session_id)
        jobs = list(
            db.query(JobRecord)
            .filter_by(session_id=session_id)
            .order_by(JobRecord.created_at)
        )
        revisions = list(
            db.query(TranscriptRevisionRecord).filter_by(session_id=session_id)
        )
        entries = list(
            db.query(LedgerEntryRecord).filter_by(session_id=session_id)
        )
        assert [job.type for job in jobs] == [
            JobType.TRANSCRIBE.value,
            JobType.RECONCILE.value,
            JobType.EXTRACT.value,
            JobType.SUMMARIZE.value,
        ]
        assert all(job.status == JobStatus.SUCCEEDED.value for job in jobs)
        assert session.state == SessionState.AWAITING_REVIEW.value
        assert session.duration_ms == 2_000
        assert len(revisions) == 1
        assert len(entries) == 1
        assert entries[0].transcript_revision_id == revisions[0].id
    assert adapter.uploads == 1
    assert adapter.submissions == 1
    assert adapter.explicit_submission_calls == 0


def test_worker_explicitly_submits_when_adapter_declares_that_capability(settings):
    class FakeExplicitSubmissionAdapter(FakeSpeakrAdapter):
        transcription_submission_mode = TranscriptionSubmissionMode.EXPLICIT

        def upload_recording(
            self,
            path,
            *,
            title,
            file_last_modified_ms=None,
            client_operation_id=None,
        ):
            assert path.read_bytes() == b"audio"
            self.uploads += 1
            return SpeakrRecording("recording-1", "PENDING", 2.0)

        def queue_transcription(self, recording_id, *, client_operation_id=None):
            assert recording_id == "recording-1"
            self.explicit_submission_calls += 1
            self.submissions += 1
            return "provider-job-1"

    engine = create_db_engine(settings)
    init_schema(engine)
    factory = create_session_factory(engine)
    media = settings.media_root / "retained.wav"
    media.parent.mkdir(parents=True, exist_ok=True)
    media.write_bytes(b"audio")
    with factory() as db:
        session = SessionRecord(
            title="Automatic chain",
            state=SessionState.TRANSCRIBING.value,
            media_path=str(media),
        )
        db.add(session)
        db.flush()
        db.add(
            JobRecord(
                session_id=session.id,
                type=JobType.TRANSCRIBE.value,
                max_attempts=3,
            )
        )
        db.commit()
        session_id = session.id

    adapter = FakeExplicitSubmissionAdapter()
    assert Worker(settings, factory, adapter=adapter).run_once() is True

    assert adapter.uploads == 1
    assert adapter.submissions == 1
    assert adapter.explicit_submission_calls == 1
    with factory() as db:
        session = db.get(SessionRecord, session_id)
        assert session.transcription_submitted_at is not None


def test_worker_reports_unconfigured_extraction_after_transcript(settings):
    engine = create_db_engine(settings)
    init_schema(engine)
    factory = create_session_factory(engine)
    media = settings.media_root / "retained.wav"
    media.parent.mkdir(parents=True, exist_ok=True)
    media.write_bytes(b"audio")
    with factory() as db:
        session = SessionRecord(
            title="Automatic chain",
            state=SessionState.TRANSCRIBING.value,
            media_path=str(media),
        )
        db.add(session)
        db.flush()
        db.add(
            JobRecord(
                session_id=session.id,
                type=JobType.TRANSCRIBE.value,
                max_attempts=3,
            )
        )
        db.commit()
        session_id = session.id

    worker = Worker(settings, factory, adapter=FakeSpeakrAdapter())
    assert worker.run_once() is True
    assert worker.run_once() is True
    assert worker.run_once() is True

    with factory() as db:
        session = db.get(SessionRecord, session_id)
        extract_job = db.query(JobRecord).filter_by(
            session_id=session_id, type=JobType.EXTRACT.value
        ).one()
        assert extract_job.status == JobStatus.FAILED.value
        assert extract_job.error_code == "extraction_not_configured"
        assert session.state == SessionState.FAILED.value
        assert session.current_transcript_revision_id is not None


class RaceInducingSpeakrAdapter:
    """A fake adapter whose upload_recording call deterministically
    reproduces a concurrent deletion request arriving mid-upload, without
    real threads: it persists a deletion tombstone (via a separate DB
    session from the same factory, exactly as
    evidence_api.services.record_deletion_intent -- which
    evidence_api.app.request_deletion calls -- would do concurrently)
    before the fake "slow" provider call returns."""

    transcription_submission_mode = TranscriptionSubmissionMode.ON_UPLOAD

    def __init__(self, factory, session_id, recording_id="orphan-recording-1"):
        self.factory = factory
        self.session_id = session_id
        self.recording_id = recording_id
        self.uploads = 0
        self.deleted_recording_ids: list[str] = []

    def upload_recording(
        self, path, *, title, file_last_modified_ms=None, client_operation_id=None
    ):
        self.uploads += 1
        with self.factory() as concurrent_db:
            record_deletion_intent(concurrent_db, self.session_id)
            concurrent_db.commit()
        return SpeakrRecording(self.recording_id, "PENDING", 3.0)

    def queue_transcription(self, recording_id, *, client_operation_id=None):
        raise AssertionError("must not queue transcription after cancellation")

    def get_recording(self, recording_id):
        raise AssertionError("not used in this test")

    def get_transcript(self, recording_id):
        raise AssertionError("not used in this test")

    def delete_recording(self, recording_id):
        self.deleted_recording_ids.append(recording_id)


def test_deletion_race_compensates_orphaned_recording_created_during_upload(settings):
    """Reproduces the confirmed-deletion-vs-in-flight-upload race: the
    deletion tombstone appears while adapter.upload_recording() is still
    running. The worker must notice on its very next check, delete the
    just-created provider recording instead of orphaning it, never persist
    speakr_recording_id, and end the job CANCELLED rather than SUCCEEDED."""
    engine = create_db_engine(settings)
    init_schema(engine)
    factory = create_session_factory(engine)
    media = settings.media_root / "retained.wav"
    media.parent.mkdir(parents=True, exist_ok=True)
    media.write_bytes(b"audio")
    with factory() as db:
        session = SessionRecord(
            title="Race",
            state=SessionState.TRANSCRIBING.value,
            media_path=str(media),
        )
        db.add(session)
        db.flush()
        job = JobRecord(
            session_id=session.id,
            type=JobType.TRANSCRIBE.value,
            max_attempts=3,
        )
        db.add(job)
        db.commit()
        session_id = session.id
        job_id = job.id

    adapter = RaceInducingSpeakrAdapter(factory, session_id)
    worker = Worker(settings, factory, adapter=adapter)
    assert worker.run_once() is True

    assert adapter.uploads == 1
    assert adapter.deleted_recording_ids == ["orphan-recording-1"]

    with factory() as db:
        job = db.get(JobRecord, job_id)
        session = db.get(SessionRecord, session_id)
        assert job.status == JobStatus.CANCELLED.value
        assert session.speakr_recording_id is None
        tombstone = db.get(DeletionTombstoneRecord, session_id)
        assert tombstone.compensated_recording_id == "orphan-recording-1"
        assert tombstone.compensated_at is not None


def test_run_once_does_not_crash_when_deletion_completes_during_in_flight_upload(
    settings,
):
    """A stricter version of the race: deletion is not merely requested
    but fully *confirmed* (the session row, and its job via cascade, are
    actually deleted) while upload_recording() is still in flight -- e.g.
    because the job's lease had already appeared expired to
    confirm_deletion. Before the fix, run_once() used db.refresh(job),
    which raises InvalidRequestError once the row is gone, crashing the
    worker loop. The safe re-fetch (db.get(..., populate_existing=True))
    must instead return None and let run_once complete gracefully."""
    engine = create_db_engine(settings)
    init_schema(engine)
    factory = create_session_factory(engine)
    media = settings.media_root / "retained.wav"
    media.parent.mkdir(parents=True, exist_ok=True)
    media.write_bytes(b"audio")
    with factory() as db:
        session = SessionRecord(
            title="Race",
            state=SessionState.TRANSCRIBING.value,
            media_path=str(media),
        )
        db.add(session)
        db.flush()
        job = JobRecord(
            session_id=session.id,
            type=JobType.TRANSCRIBE.value,
            max_attempts=3,
        )
        db.add(job)
        db.commit()
        session_id = session.id

    class ConfirmedDeletionDuringUploadAdapter:
        transcription_submission_mode = TranscriptionSubmissionMode.ON_UPLOAD

        def __init__(self):
            self.deleted_recording_ids: list[str] = []

        def upload_recording(
            self,
            path,
            *,
            title,
            file_last_modified_ms=None,
            client_operation_id=None,
        ):
            with factory() as concurrent_db:
                record_deletion_intent(concurrent_db, session_id)
                record = concurrent_db.get(SessionRecord, session_id)
                concurrent_db.delete(record)
                concurrent_db.commit()
            return SpeakrRecording("orphan-recording-2", "PENDING", 3.0)

        def queue_transcription(self, recording_id, *, client_operation_id=None):
            raise AssertionError("must not queue transcription after cancellation")

        def get_recording(self, recording_id):
            raise AssertionError("not used in this test")

        def get_transcript(self, recording_id):
            raise AssertionError("not used in this test")

        def delete_recording(self, recording_id):
            self.deleted_recording_ids.append(recording_id)

    adapter = ConfirmedDeletionDuringUploadAdapter()
    worker = Worker(settings, factory, adapter=adapter)

    # This must not raise -- reproduces the exact prior crash bug.
    assert worker.run_once() is True

    assert adapter.deleted_recording_ids == ["orphan-recording-2"]
    with factory() as db:
        assert db.get(SessionRecord, session_id) is None
        remaining_jobs = list(
            db.query(JobRecord).filter_by(session_id=session_id)
        )
        assert remaining_jobs == []
        tombstone = db.get(DeletionTombstoneRecord, session_id)
        assert tombstone.compensated_recording_id == "orphan-recording-2"


def test_confirm_deletion_has_active_job_reflects_worker_lease(settings):
    """Unit-level check of the has_active_job lease helper confirm_deletion
    relies on: a RUNNING job with a fresh updated_at is considered active
    (deletion must defer), while one whose updated_at is older than the
    configured lease is considered abandoned (deletion may proceed)."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import update

    from evidence_api.services import has_active_job

    engine = create_db_engine(settings)
    init_schema(engine)
    factory = create_session_factory(engine)
    with factory() as db:
        session = SessionRecord(title="Lease", state=SessionState.TRANSCRIBING.value)
        db.add(session)
        db.flush()
        job = JobRecord(
            session_id=session.id,
            type=JobType.TRANSCRIBE.value,
            status=JobStatus.RUNNING.value,
            max_attempts=3,
        )
        db.add(job)
        db.commit()
        session_id = session.id
        job_id = job.id

    with factory() as db:
        assert has_active_job(db, session_id, settings.worker_job_lease_seconds) is True

    stale = datetime.now(UTC) - timedelta(seconds=settings.worker_job_lease_seconds + 60)
    with factory() as db:
        # A Core-style bulk update (rather than mutating and committing an
        # ORM instance) is required here: the column's Python-side
        # onupdate=utcnow default unconditionally overwrites any
        # instance-level assignment on every ORM flush, so a normal
        # `job.updated_at = stale; db.commit()` would silently reset it
        # back to "now" instead of actually going stale.
        db.execute(update(JobRecord).where(JobRecord.id == job_id).values(updated_at=stale))
        db.commit()

    with factory() as db:
        assert has_active_job(db, session_id, settings.worker_job_lease_seconds) is False


def test_queue_call_heartbeats_expired_lease_until_safe_cancellation(settings):
    settings = settings.model_copy(update={"worker_job_lease_seconds": 1})
    app = create_app(settings)
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        factory = app.state.session_factory
        media = settings.media_root / "heartbeat.wav"
        media.parent.mkdir(parents=True, exist_ok=True)
        media.write_bytes(b"audio")
        with factory() as db:
            session = SessionRecord(
                title="Heartbeat",
                state=SessionState.TRANSCRIBING.value,
                media_path=str(media),
                speakr_recording_id="recording-heartbeat",
            )
            db.add(session)
            db.flush()
            job = JobRecord(
                session_id=session.id,
                type=JobType.TRANSCRIBE.value,
                max_attempts=3,
            )
            db.add(job)
            db.commit()
            session_id = session.id
            job_id = job.id

        class ExpiringQueueAdapter:
            transcription_submission_mode = TranscriptionSubmissionMode.EXPLICIT

            def __init__(self):
                self.remote_recordings = {"recording-heartbeat"}
                self.confirm_status = None
                self.confirm_body = None

            def upload_recording(self, *args, **kwargs):
                raise AssertionError("recording is already uploaded")

            def queue_transcription(self, recording_id, *, client_operation_id=None):
                assert recording_id == "recording-heartbeat"
                stale = datetime.now(UTC) - timedelta(seconds=30)
                with factory() as concurrent_db:
                    concurrent_db.execute(
                        update(JobRecord)
                        .where(JobRecord.id == job_id)
                        .values(updated_at=stale)
                    )
                    concurrent_db.commit()

                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    with factory() as concurrent_db:
                        renewed_at = concurrent_db.get(
                            JobRecord, job_id
                        ).updated_at
                    if renewed_at.tzinfo is None:
                        renewed_at = renewed_at.replace(tzinfo=UTC)
                    if renewed_at > datetime.now(UTC) - timedelta(seconds=1):
                        break
                    time.sleep(0.02)
                else:
                    raise AssertionError("worker did not renew the expired lease")

                pending = client.delete(f"/api/sessions/{session_id}")
                assert pending.status_code == 200
                confirmed = client.post(
                    f"/api/sessions/{session_id}/deletion/confirm",
                    json={"confirm_session_id": session_id},
                )
                self.confirm_status = confirmed.status_code
                self.confirm_body = confirmed.json()
                return "provider-job-heartbeat"

            def get_recording(self, recording_id):
                raise AssertionError("not used")

            def get_transcript(self, recording_id):
                raise AssertionError("not used")

            def delete_recording(self, recording_id):
                self.remote_recordings.discard(recording_id)

        adapter = ExpiringQueueAdapter()
        app.state.speakr_adapter = adapter
        worker = Worker(settings, factory, adapter=adapter)

        assert worker.run_once() is True
        assert adapter.confirm_status == 202
        assert adapter.confirm_body["code"] == "deletion_pending_active_job"
        assert client.get(f"/api/sessions/{session_id}").status_code == 200

        confirmed = client.post(
            f"/api/sessions/{session_id}/deletion/confirm",
            json={"confirm_session_id": session_id},
        )
        assert confirmed.status_code == 204
        assert adapter.remote_recordings == set()
        assert client.get(f"/api/sessions/{session_id}").status_code == 404


def test_failed_orphan_compensation_retries_durably_before_confirmation(settings):
    settings = settings.model_copy(
        update={"worker_transcription_poll_seconds": 0}
    )
    app = create_app(settings)
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        factory = app.state.session_factory
        media = settings.media_root / "compensation.wav"
        media.parent.mkdir(parents=True, exist_ok=True)
        media.write_bytes(b"audio")
        with factory() as db:
            session = SessionRecord(
                title="Compensation",
                state=SessionState.TRANSCRIBING.value,
                media_path=str(media),
            )
            db.add(session)
            db.flush()
            job = JobRecord(
                session_id=session.id,
                type=JobType.TRANSCRIBE.value,
                max_attempts=3,
            )
            db.add(job)
            db.commit()
            session_id = session.id

        class FailingThenSuccessfulCompensationAdapter:
            transcription_submission_mode = TranscriptionSubmissionMode.ON_UPLOAD

            def __init__(self):
                self.remote_recordings: set[str] = set()
                self.deletion_attempts = 0

            def upload_recording(
                self,
                path,
                *,
                title,
                file_last_modified_ms=None,
                client_operation_id=None,
            ):
                self.remote_recordings.add("orphan-retry")
                pending = client.delete(f"/api/sessions/{session_id}")
                assert pending.status_code == 200
                return SpeakrRecording("orphan-retry", "PENDING", 1.0)

            def queue_transcription(self, recording_id, *, client_operation_id=None):
                raise AssertionError("upload submits transcription")

            def get_recording(self, recording_id):
                raise AssertionError("not used")

            def get_transcript(self, recording_id):
                raise AssertionError("not used")

            def delete_recording(self, recording_id):
                self.deletion_attempts += 1
                if self.deletion_attempts == 1:
                    raise AdapterResponseError("forced provider deletion failure")
                self.remote_recordings.discard(recording_id)

        adapter = FailingThenSuccessfulCompensationAdapter()
        app.state.speakr_adapter = adapter
        first_worker = Worker(settings, factory, adapter=adapter)

        assert first_worker.run_once() is True
        assert adapter.remote_recordings == {"orphan-retry"}
        with factory() as db:
            compensation = db.query(DeletionCompensationRecord).one()
            assert compensation.session_id == session_id
            assert compensation.recording_id == "orphan-retry"
            assert compensation.status == "FAILED"
            assert compensation.attempts == 1
            assert compensation.error_code == "adapter_response_error"
            assert "forced provider deletion failure" in compensation.error_message
            assert compensation.completed_at is None
            tombstone = db.get(DeletionTombstoneRecord, session_id)
            assert tombstone.compensated_at is None

        pending_confirmation = client.post(
            f"/api/sessions/{session_id}/deletion/confirm",
            json={"confirm_session_id": session_id},
        )
        assert pending_confirmation.status_code == 202
        assert (
            pending_confirmation.json()["code"]
            == "deletion_pending_compensation"
        )
        assert client.get(f"/api/sessions/{session_id}").status_code == 200

        restarted_worker = Worker(settings, factory, adapter=adapter)
        assert restarted_worker.run_once() is True
        assert adapter.remote_recordings == set()
        with factory() as db:
            compensation = db.query(DeletionCompensationRecord).one()
            assert compensation.status == "SUCCEEDED"
            assert compensation.attempts == 2
            assert compensation.error_code is None
            assert compensation.completed_at is not None
            tombstone = db.get(DeletionTombstoneRecord, session_id)
            assert tombstone.compensated_recording_id == "orphan-retry"
            assert tombstone.compensated_at is not None

        confirmed = client.post(
            f"/api/sessions/{session_id}/deletion/confirm",
            json={"confirm_session_id": session_id},
        )
        assert confirmed.status_code == 204
        assert client.get(f"/api/sessions/{session_id}").status_code == 404


def test_recover_abandoned_upload_fails_ambiguous_and_resolve_unblocks_retry(settings):
    """FIX #2/#3 crash test: reproduces a worker crashing after Speakr's
    upload_recording() call has (deterministically, per this test's setup)
    already succeeded upstream but before the local commit that would have
    recorded speakr_recording_id and cleared the pending-operation marker.
    Speakr has no idempotency key or lookup-by-key endpoint, so
    recover_abandoned_jobs() must not blindly requeue this job -- it must
    fail it as ambiguous, leave the marker intact for inspection, and must
    never call upload_recording() again. An operator can then resolve the
    ambiguity via the upload-operation/resolve endpoint, after which a
    normal retry completes without re-uploading."""
    engine = create_db_engine(settings)
    init_schema(engine)
    factory = create_session_factory(engine)
    media = settings.media_root / "retained.wav"
    media.parent.mkdir(parents=True, exist_ok=True)
    media.write_bytes(b"audio")
    with factory() as db:
        session = SessionRecord(
            title="Ambiguous upload",
            state=SessionState.TRANSCRIBING.value,
            media_path=str(media),
        )
        db.add(session)
        db.flush()
        job = JobRecord(
            session_id=session.id,
            type=JobType.TRANSCRIBE.value,
            status=JobStatus.RUNNING.value,
            max_attempts=3,
        )
        db.add(job)
        db.commit()
        session_id = session.id
        job_id = job.id

    # Deterministically reproduce "crashed after provider success, before
    # local commit": persist the pending-operation marker (as
    # begin_pending_operation does immediately before the real upload
    # call) but never record speakr_recording_id or clear it -- exactly
    # the state a real crash between those two points would leave behind.
    # Then make the job's lease look abandoned, as recover_abandoned_jobs
    # requires.
    with factory() as db:
        session = db.get(SessionRecord, session_id)
        operation_id = begin_pending_operation(session, "upload")
        db.commit()
    stale = datetime.now(UTC) - timedelta(
        seconds=settings.worker_job_lease_seconds + 60
    )
    with factory() as db:
        db.execute(
            update(JobRecord).where(JobRecord.id == job_id).values(updated_at=stale)
        )
        db.commit()

    class NoReuploadAdapter:
        transcription_submission_mode = TranscriptionSubmissionMode.ON_UPLOAD
        supports_upload_idempotency = False

        def __init__(self):
            self.upload_calls = 0

        def upload_recording(self, *args, **kwargs):
            self.upload_calls += 1
            raise AssertionError(
                "must not re-upload after an ambiguous crashed operation"
            )

        def queue_transcription(self, *args, **kwargs):
            raise AssertionError("not used in this test")

        def get_recording(self, recording_id):
            assert recording_id == "recovered-recording-1"
            return SpeakrRecording(recording_id, "COMPLETED", 1.0)

        def get_transcript(self, recording_id):
            raise AssertionError("not used in this test")

        def delete_recording(self, recording_id):
            raise AssertionError("not used in this test")

    adapter = NoReuploadAdapter()
    worker = Worker(settings, factory, adapter=adapter)

    recovered = worker.recover_abandoned_jobs()
    assert recovered == 1
    assert adapter.upload_calls == 0

    with factory() as db:
        job = db.get(JobRecord, job_id)
        session = db.get(SessionRecord, session_id)
        assert job.status == JobStatus.FAILED.value
        assert job.error_code == AMBIGUOUS_OPERATION_ERROR_CODE
        assert session.state == SessionState.FAILED.value
        # The marker must survive the failure -- it is the operator's
        # only evidence of which operation needs reconciling.
        assert session.pending_operation_kind == "upload"
        assert session.pending_operation_id == operation_id

    # A plain run_once() (e.g. a poll loop tick) must not touch the failed
    # job or call upload_recording again either.
    assert worker.run_once() is False
    assert adapter.upload_calls == 0

    app = create_app(settings)
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        app.state.session_factory = factory
        app.state.speakr_adapter = adapter
        resolve = client.post(
            f"/api/sessions/{session_id}/upload-operation/resolve",
            json={
                "confirm_operation_id": operation_id,
                "outcome": "adopt_existing",
                "speakr_recording_id": "recovered-recording-1",
            },
        )
        assert resolve.status_code == 200
        assert resolve.json()["speakr_recording_id"] == "recovered-recording-1"

        with factory() as db:
            session = db.get(SessionRecord, session_id)
            assert session.pending_operation_kind is None
            assert session.pending_operation_id is None

        retried = client.post(f"/api/jobs/{job_id}/retry")
        assert retried.status_code == 200
        retried_job_id = retried.json()["id"]

    # The retried TRANSCRIBE job must adopt the resolved recording id
    # rather than uploading a duplicate, then proceed straight to
    # enqueuing the follow-on RECONCILE job (ON_UPLOAD mode has no
    # separate submission call).
    assert worker.run_once() is True
    assert adapter.upload_calls == 0
    with factory() as db:
        session = db.get(SessionRecord, session_id)
        jobs = list(
            db.query(JobRecord).filter_by(session_id=session_id).order_by(
                JobRecord.created_at
            )
        )
        retried_job = db.get(JobRecord, retried_job_id)
        assert session.speakr_recording_id == "recovered-recording-1"
        assert session.pending_operation_kind is None
        assert retried_job.type == JobType.TRANSCRIBE.value
        assert retried_job.status == JobStatus.SUCCEEDED.value
        assert any(job.type == JobType.RECONCILE.value for job in jobs)


def test_run_once_preserves_ambiguous_failure_after_fail_ambiguous_operation(
    settings,
):
    """FIX #1 regression test: reproduces a worker crash/timeout that left
    a session's non-idempotent "upload" provider-operation marker set
    (see begin_pending_operation) without speakr_recording_id ever being
    recorded, then a fresh TRANSCRIBE job (e.g. one manually recreated via
    the retry API while the marker is still set) is picked up by a normal
    run_once() tick -- not via recover_abandoned_jobs' stale-lease sweep
    -- and hits the `_process`-level `_fail_ambiguous_operation` guard.

    Before this fix, run_once() unconditionally called `_complete_job`
    immediately after `_process` returned (whenever `_process` didn't
    raise), which reloads the job/session and -- since
    `_reload_after_remote` treats *any* non-RUNNING job status as
    "cancelled" -- fell into `_cancel_job` and silently overwrote the
    FAILED + ambiguous_provider_operation terminal state with CANCELLED,
    losing the only evidence an operator has that manual reconciliation
    is required. This test asserts the FAILED + ambiguous marker survive
    run_once()'s own completion handling, that a subsequent worker tick
    and recovery sweep leave it alone, and that admin resolution followed
    by a safe retry still completes normally afterward."""
    engine = create_db_engine(settings)
    init_schema(engine)
    factory = create_session_factory(engine)
    media = settings.media_root / "retained.wav"
    media.parent.mkdir(parents=True, exist_ok=True)
    media.write_bytes(b"audio")
    with factory() as db:
        session = SessionRecord(
            title="Crash before commit",
            state=SessionState.TRANSCRIBING.value,
            media_path=str(media),
        )
        db.add(session)
        db.flush()
        # Simulate a worker that crashed (or the provider call timed out)
        # after calling begin_pending_operation but before the provider
        # call and its local commit ever completed -- exactly what a
        # fresh job manually recreated (e.g. via the retry API) while the
        # marker is still set would see on its very first run_once tick.
        operation_id = begin_pending_operation(session, "upload")
        db.commit()
        session_id = session.id

    with factory() as db:
        job = JobRecord(
            session_id=session_id,
            type=JobType.TRANSCRIBE.value,
            status=JobStatus.QUEUED.value,
            max_attempts=3,
        )
        db.add(job)
        db.commit()
        job_id = job.id

    class NoReuploadAdapter:
        transcription_submission_mode = TranscriptionSubmissionMode.ON_UPLOAD
        supports_upload_idempotency = False

        def __init__(self):
            self.upload_calls = 0

        def upload_recording(self, *args, **kwargs):
            self.upload_calls += 1
            raise AssertionError(
                "must not upload while an ambiguous provider operation "
                "marker is pending resolution"
            )

        def queue_transcription(self, *args, **kwargs):
            raise AssertionError("not used in this test")

        def get_recording(self, recording_id):
            assert recording_id == "adopted-recording-1"
            return SpeakrRecording(recording_id, "COMPLETED", 1.0)

        def get_transcript(self, recording_id):
            raise AssertionError("not used in this test")

        def delete_recording(self, recording_id):
            raise AssertionError("not used in this test")

    adapter = NoReuploadAdapter()
    worker = Worker(settings, factory, adapter=adapter)

    assert worker.run_once() is True
    assert adapter.upload_calls == 0

    with factory() as db:
        job = db.get(JobRecord, job_id)
        session = db.get(SessionRecord, session_id)
        # The FAILED + ambiguous_provider_operation terminal state set by
        # _fail_ambiguous_operation must survive run_once()'s subsequent
        # completion handling -- it must NOT have been overwritten to
        # CANCELLED (the pre-fix bug) or SUCCEEDED.
        assert job.status == JobStatus.FAILED.value
        assert job.error_code == AMBIGUOUS_OPERATION_ERROR_CODE
        assert job.ambiguous_operation_id == operation_id
        assert session.state == SessionState.FAILED.value
        assert session.pending_operation_kind == "upload"
        assert session.pending_operation_id == operation_id

    # A subsequent worker tick (poll loop, and its abandoned-job recovery
    # sweep) must leave the terminal ambiguous failure alone rather than
    # reprocessing or re-recovering it.
    assert worker.recover_abandoned_jobs() == 0
    assert worker.run_once() is False
    assert adapter.upload_calls == 0

    app = create_app(settings)
    with TestClient(app, client=("127.0.0.1", 50000)) as client:
        app.state.session_factory = factory
        app.state.speakr_adapter = adapter
        resolve = client.post(
            f"/api/sessions/{session_id}/upload-operation/resolve",
            json={
                "confirm_operation_id": operation_id,
                "outcome": "adopt_existing",
                "speakr_recording_id": "adopted-recording-1",
            },
        )
        assert resolve.status_code == 200
        assert resolve.json()["speakr_recording_id"] == "adopted-recording-1"

        with factory() as db:
            session = db.get(SessionRecord, session_id)
            assert session.pending_operation_kind is None
            assert session.pending_operation_id is None

        retried = client.post(f"/api/jobs/{job_id}/retry")
        assert retried.status_code == 200
        retried_job_id = retried.json()["id"]

    # The safely-retried job must adopt the resolved recording id instead
    # of re-uploading, and proceed to completion.
    assert worker.run_once() is True
    assert adapter.upload_calls == 0
    with factory() as db:
        retried_job = db.get(JobRecord, retried_job_id)
        session = db.get(SessionRecord, session_id)
        jobs = list(
            db.query(JobRecord).filter_by(session_id=session_id).order_by(
                JobRecord.created_at
            )
        )
        assert retried_job.status == JobStatus.SUCCEEDED.value
        assert session.speakr_recording_id == "adopted-recording-1"
        assert any(job.type == JobType.RECONCILE.value for job in jobs)


def test_reconcile_final_commit_does_not_overwrite_concurrent_deletion(
    settings, monkeypatch
):
    """FIX #1 crash-consistency test: a concurrent deletion request commits
    (tombstone + DELETE_PENDING transition, bumping the session row's
    optimistic-concurrency version) in the narrow window between the
    RECONCILE job's last provider call -- after which the existing
    tombstone re-check inside _leased_provider_call/_reload_after_remote
    has already run and passed -- and this job's own final result commit.
    The version_id_col added to SessionRecord must make that final commit
    raise StaleDataError (caught by _safe_commit), so the reconciled
    transcript/state changes are never persisted; the immediately
    following _complete_job checkpoint (which reloads fresh state) must
    then observe the concurrent tombstone and mark the job CANCELLED
    instead of SUCCEEDED, and must never revert the session's
    DELETE_PENDING state back to a reconciliation outcome."""
    engine = create_db_engine(settings)
    init_schema(engine)
    factory = create_session_factory(engine)
    with factory() as db:
        session = SessionRecord(
            title="Reconcile commit race",
            state=SessionState.TRANSCRIBING.value,
            speakr_recording_id="recording-commit-race-1",
        )
        db.add(session)
        db.flush()
        job = JobRecord(
            session_id=session.id,
            type=JobType.RECONCILE.value,
            max_attempts=3,
        )
        db.add(job)
        db.commit()
        session_id = session.id
        job_id = job.id

    class ReconcileOnlyAdapter:
        transcription_submission_mode = TranscriptionSubmissionMode.ON_UPLOAD

        def get_recording(self, recording_id):
            return SpeakrRecording(recording_id, "COMPLETED", 5.0)

        def get_transcript(self, recording_id):
            return [
                {
                    "id": "segment-1",
                    "start_time": 0,
                    "end_time": 1,
                    "sentence": "hello world",
                }
            ]

        def upload_recording(self, *args, **kwargs):
            raise AssertionError("not used in this test")

        def queue_transcription(self, *args, **kwargs):
            raise AssertionError("not used in this test")

        def delete_recording(self, recording_id):
            raise AssertionError("not used in this test")

    import evidence_worker.worker as worker_module

    real_reconcile = worker_module.reconcile_transcript_data
    calls = {"count": 0, "stale_flush": 0}

    def racing_reconcile(db, session_record, raw_segments):
        calls["count"] += 1
        # Simulate evidence_api.app.request_deletion committing in a
        # separate transaction right after this job's last provider call
        # returned but before this job's own final commit.
        with factory() as concurrent_db:
            record_deletion_intent(concurrent_db, session_record.id)
            concurrent_record = concurrent_db.get(SessionRecord, session_record.id)
            transition(concurrent_record, SessionState.DELETE_PENDING)
            concurrent_db.commit()
        try:
            return real_reconcile(db, session_record, raw_segments)
        except StaleDataError:
            calls["stale_flush"] += 1
            raise

    monkeypatch.setattr(worker_module, "reconcile_transcript_data", racing_reconcile)

    worker = Worker(settings, factory, adapter=ReconcileOnlyAdapter())
    assert worker.run_once() is True
    assert calls["count"] == 1
    assert calls["stale_flush"] == 1

    with factory() as db:
        job = db.get(JobRecord, job_id)
        session = db.get(SessionRecord, session_id)
        assert job.status == JobStatus.CANCELLED.value
        assert session.state == SessionState.DELETE_PENDING.value
        # The reconciliation outcome must not have been persisted onto a
        # session that is now pending deletion.
        assert session.current_transcript_revision_id is None
        assert (
            db.query(TranscriptRevisionRecord)
            .filter_by(session_id=session_id)
            .count()
            == 0
        )
        tombstone = db.get(DeletionTombstoneRecord, session_id)
        assert tombstone is not None


def test_reconcile_stale_flush_requeues_without_leaving_job_running(
    settings, monkeypatch
):
    engine = create_db_engine(settings)
    init_schema(engine)
    factory = create_session_factory(engine)
    with factory() as db:
        session = SessionRecord(
            title="Reconcile benign race",
            state=SessionState.TRANSCRIBING.value,
            speakr_recording_id="recording-benign-race",
        )
        db.add(session)
        db.flush()
        job = JobRecord(
            session_id=session.id,
            type=JobType.RECONCILE.value,
            max_attempts=3,
        )
        db.add(job)
        db.commit()
        session_id = session.id
        job_id = job.id

    class ReconcileAdapter:
        transcription_submission_mode = TranscriptionSubmissionMode.ON_UPLOAD

        def get_recording(self, recording_id):
            return SpeakrRecording(recording_id, "COMPLETED", 1.0)

        def get_transcript(self, recording_id):
            return [
                {
                    "id": "segment-1",
                    "start_time": 0,
                    "end_time": 1,
                    "sentence": "Valid transcript payload.",
                }
            ]

        def upload_recording(self, *args, **kwargs):
            raise AssertionError("not used")

        def queue_transcription(self, *args, **kwargs):
            raise AssertionError("not used")

        def delete_recording(self, recording_id):
            raise AssertionError("not used")

    import evidence_worker.worker as worker_module

    real_reconcile = worker_module.reconcile_transcript_data
    stale_flushes = {"count": 0}

    def racing_reconcile(db, session_record, raw_segments):
        with factory() as concurrent_db:
            concurrent_record = concurrent_db.get(
                SessionRecord, session_record.id
            )
            concurrent_record.notes = "concurrent metadata edit"
            concurrent_db.commit()
        try:
            return real_reconcile(db, session_record, raw_segments)
        except StaleDataError:
            stale_flushes["count"] += 1
            raise

    monkeypatch.setattr(worker_module, "reconcile_transcript_data", racing_reconcile)

    worker = Worker(settings, factory, adapter=ReconcileAdapter())
    assert worker.run_once() is True
    assert stale_flushes["count"] == 1

    with factory() as db:
        job = db.get(JobRecord, job_id)
        session = db.get(SessionRecord, session_id)
        assert job.status == JobStatus.QUEUED.value
        assert job.error_code == "concurrent_update"
        assert session.state == SessionState.RETRY_PENDING.value
        assert session.notes == "concurrent metadata edit"
        assert (
            db.query(TranscriptRevisionRecord)
            .filter_by(session_id=session_id)
            .count()
            == 0
        )


def test_extract_final_commit_does_not_overwrite_concurrent_deletion(
    settings, monkeypatch
):
    """FIX #1 crash-consistency test: the EXTRACT-job analogue of the
    RECONCILE race above. A concurrent deletion request commits (tombstone
    + DELETE_PENDING transition, bumping the session row's version) in the
    window between the extraction provider call returning (already past
    the existing tombstone re-check in _leased_provider_call) and this
    job's own final `transition(...AWAITING_REVIEW); _safe_commit(db)`.
    That final commit must be rejected by the version check, and the
    ledger entries produced by the (now-orphaned) extraction call must
    never be persisted onto a session pending deletion; the job must end
    CANCELLED, not SUCCEEDED."""
    engine = create_db_engine(settings)
    init_schema(engine)
    factory = create_session_factory(engine)
    with factory() as db:
        session = SessionRecord(
            title="Extract commit race",
            state=SessionState.TRANSCRIPT_READY.value,
            speakr_recording_id="recording-extract-race-1",
        )
        db.add(session)
        db.flush()
        revision = TranscriptRevisionRecord(
            session_id=session.id,
            sha256="0" * 64,
            segments=[
                {
                    "segment_id": "segment-1",
                    "start_ms": 0,
                    "end_ms": 1000,
                    "text": "Release the sound.",
                }
            ],
            source="speakr",
        )
        db.add(revision)
        db.flush()
        session.current_transcript_revision_id = revision.id
        job = JobRecord(
            session_id=session.id,
            type=JobType.EXTRACT.value,
            max_attempts=3,
        )
        db.add(job)
        db.commit()
        session_id = session.id
        job_id = job.id

    class FakeExtractOnlyProvider:
        def extract(self, *, session_id, title, transcript_revision_id, segments):
            return [
                LedgerEntryCreate(
                    topic="Release",
                    exact_coach_feedback="Release the sound.",
                    confidence=0.9,
                    evidence=[
                        EvidenceReference(
                            transcript_revision_id=transcript_revision_id,
                            start_ms=0,
                            end_ms=1000,
                            segment_ids=["segment-1"],
                        )
                    ],
                )
            ]

    import evidence_worker.worker as worker_module

    real_create_ledger_entry = worker_module.create_ledger_entry
    calls = {"count": 0, "stale_flush": 0}

    def racing_create_ledger_entry(db, session_record, entry):
        calls["count"] += 1
        # Simulate a concurrent deletion request committing right after
        # the extraction provider call returned but before this job's own
        # final transition-to-AWAITING_REVIEW commit.
        with factory() as concurrent_db:
            record_deletion_intent(concurrent_db, session_record.id)
            concurrent_record = concurrent_db.get(SessionRecord, session_record.id)
            transition(concurrent_record, SessionState.DELETE_PENDING)
            concurrent_db.commit()
        try:
            return real_create_ledger_entry(db, session_record, entry)
        except StaleDataError:
            calls["stale_flush"] += 1
            raise

    monkeypatch.setattr(
        worker_module, "create_ledger_entry", racing_create_ledger_entry
    )

    worker = Worker(
        settings, factory, adapter=None, extraction_provider=FakeExtractOnlyProvider()
    )
    # Extraction never touches Speakr, but Worker() requires an adapter if
    # none is given it constructs a real SpeakrHttpAdapter -- harmless
    # here since it is never called.
    assert worker.run_once() is True
    assert calls["count"] == 1
    assert calls["stale_flush"] == 1

    with factory() as db:
        job = db.get(JobRecord, job_id)
        session = db.get(SessionRecord, session_id)
        assert job.status == JobStatus.CANCELLED.value
        assert session.state == SessionState.DELETE_PENDING.value
        assert (
            db.query(LedgerEntryRecord).filter_by(session_id=session_id).count() == 0
        )
        tombstone = db.get(DeletionTombstoneRecord, session_id)
        assert tombstone is not None


def test_recover_abandoned_queue_transcription_fails_ambiguous(settings):
    """FIX #2/#3 crash test, EXPLICIT-submission-mode variant: reproduces a
    worker crashing after an EXPLICIT-mode adapter's queue_transcription()
    call has already succeeded upstream but before the local commit that
    would have recorded transcription_submitted_at and cleared the
    pending-operation marker. Unlike the upload case, speakr_recording_id
    is already durably known here -- the ambiguity is specifically about
    whether the submission itself was accepted -- so recovery must still
    treat it as ambiguous rather than resubmitting."""
    engine = create_db_engine(settings)
    init_schema(engine)
    factory = create_session_factory(engine)
    with factory() as db:
        session = SessionRecord(
            title="Ambiguous submission",
            state=SessionState.TRANSCRIBING.value,
            speakr_recording_id="recording-explicit-1",
        )
        db.add(session)
        db.flush()
        job = JobRecord(
            session_id=session.id,
            type=JobType.TRANSCRIBE.value,
            status=JobStatus.RUNNING.value,
            max_attempts=3,
        )
        db.add(job)
        db.commit()
        session_id = session.id
        job_id = job.id

    with factory() as db:
        session = db.get(SessionRecord, session_id)
        operation_id = begin_pending_operation(session, "queue_transcription")
        db.commit()
    stale = datetime.now(UTC) - timedelta(
        seconds=settings.worker_job_lease_seconds + 60
    )
    with factory() as db:
        db.execute(
            update(JobRecord).where(JobRecord.id == job_id).values(updated_at=stale)
        )
        db.commit()

    class NoResubmitAdapter:
        transcription_submission_mode = TranscriptionSubmissionMode.EXPLICIT
        supports_upload_idempotency = False

        def __init__(self):
            self.submission_calls = 0

        def upload_recording(self, *args, **kwargs):
            raise AssertionError("recording is already uploaded")

        def queue_transcription(self, *args, **kwargs):
            self.submission_calls += 1
            raise AssertionError(
                "must not resubmit after an ambiguous crashed operation"
            )

        def get_recording(self, recording_id):
            raise AssertionError("not used in this test")

        def get_transcript(self, recording_id):
            raise AssertionError("not used in this test")

        def delete_recording(self, recording_id):
            raise AssertionError("not used in this test")

    adapter = NoResubmitAdapter()
    worker = Worker(settings, factory, adapter=adapter)

    recovered = worker.recover_abandoned_jobs()
    assert recovered == 1
    assert adapter.submission_calls == 0

    with factory() as db:
        job = db.get(JobRecord, job_id)
        session = db.get(SessionRecord, session_id)
        assert job.status == JobStatus.FAILED.value
        assert job.error_code == AMBIGUOUS_OPERATION_ERROR_CODE
        assert session.state == SessionState.FAILED.value
        assert session.pending_operation_kind == "queue_transcription"
        assert session.pending_operation_id == operation_id
        # The recording id from the (uncontested) upload is untouched --
        # only the submission outcome is ambiguous.
        assert session.speakr_recording_id == "recording-explicit-1"

    assert worker.run_once() is False
    assert adapter.submission_calls == 0


def test_recover_abandoned_jobs_handles_concurrent_version_conflict_without_aborting_sweep(
    settings, monkeypatch
):
    """FIX #3 regression test: recover_abandoned_jobs() must isolate each
    abandoned job's recovery in its own transaction so a genuine
    StaleDataError optimistic-concurrency conflict on ONE job's (or its
    session's) row cannot abort recovery of every other abandoned job in
    the same sweep and cannot raise out of recover_abandoned_jobs() and
    crash the worker's poll loop. This reproduces a realistic race: an
    operator's POST /jobs/{id}/cancel (evidence_api.app.cancel_job, which
    sets job.status=CANCELLED and transitions the session to CANCELLED,
    bumping both rows' optimistic-concurrency versions) lands in between
    this sweep's read of an ambiguous, abandoned job and its own commit
    of that job as FAILED/ambiguous_provider_operation. The conflicted
    job must be safely rolled back, reloaded, and skipped -- respecting
    the concurrent cancellation rather than clobbering it back to
    FAILED -- while a second, unrelated abandoned job in the same sweep
    must still be recovered normally."""
    engine = create_db_engine(settings)
    init_schema(engine)
    factory = create_session_factory(engine)

    with factory() as db:
        ambiguous_session = SessionRecord(
            title="Concurrently cancelled while ambiguous",
            state=SessionState.TRANSCRIBING.value,
        )
        db.add(ambiguous_session)
        db.flush()
        ambiguous_job = JobRecord(
            session_id=ambiguous_session.id,
            type=JobType.TRANSCRIBE.value,
            status=JobStatus.RUNNING.value,
            max_attempts=3,
        )
        db.add(ambiguous_job)
        db.flush()
        operation_id = begin_pending_operation(ambiguous_session, "upload")

        plain_session = SessionRecord(
            title="Plain abandoned job",
            state=SessionState.TRANSCRIBING.value,
        )
        db.add(plain_session)
        db.flush()
        plain_job = JobRecord(
            session_id=plain_session.id,
            type=JobType.TRANSCRIBE.value,
            status=JobStatus.RUNNING.value,
            max_attempts=3,
        )
        db.add(plain_job)
        db.commit()
        ambiguous_session_id = ambiguous_session.id
        ambiguous_job_id = ambiguous_job.id
        plain_session_id = plain_session.id
        plain_job_id = plain_job.id

    stale = datetime.now(UTC) - timedelta(
        seconds=settings.worker_job_lease_seconds + 60
    )
    with factory() as db:
        # The ambiguous job must be listed (and thus processed) before
        # the plain job so the injected race below -- which only fires
        # on the very first `transition()` call in the sweep -- lands on
        # the ambiguous job and not the plain one.
        db.execute(
            update(JobRecord)
            .where(JobRecord.id == ambiguous_job_id)
            .values(updated_at=stale, created_at=stale - timedelta(seconds=10))
        )
        db.execute(
            update(JobRecord)
            .where(JobRecord.id == plain_job_id)
            .values(updated_at=stale, created_at=stale)
        )
        db.commit()

    import evidence_worker.worker as worker_module

    real_transition = worker_module.transition
    calls = {"count": 0}

    def racing_transition(session_record, new_state):
        calls["count"] += 1
        if calls["count"] == 1:
            # Simulate an operator's POST /jobs/{id}/cancel landing
            # concurrently, in between this recovery attempt's initial
            # read of the ambiguous job/session and its own commit --
            # exactly what evidence_api.app.cancel_job does.
            with factory() as concurrent_db:
                concurrent_job = concurrent_db.get(JobRecord, ambiguous_job_id)
                concurrent_job.status = JobStatus.CANCELLED.value
                concurrent_session = concurrent_db.get(
                    SessionRecord, ambiguous_session_id
                )
                real_transition(concurrent_session, SessionState.CANCELLED)
                concurrent_db.commit()
        return real_transition(session_record, new_state)

    monkeypatch.setattr(worker_module, "transition", racing_transition)

    class NoOpAdapter:
        transcription_submission_mode = TranscriptionSubmissionMode.ON_UPLOAD
        supports_upload_idempotency = False

        def upload_recording(self, *args, **kwargs):
            raise AssertionError("not used in this test")

        def queue_transcription(self, *args, **kwargs):
            raise AssertionError("not used in this test")

        def get_recording(self, recording_id):
            raise AssertionError("not used in this test")

        def get_transcript(self, recording_id):
            raise AssertionError("not used in this test")

        def delete_recording(self, recording_id):
            raise AssertionError("not used in this test")

    worker = Worker(settings, factory, adapter=NoOpAdapter())

    recovered = worker.recover_abandoned_jobs()

    # Only the plain job was actually recovered by this sweep -- the
    # ambiguous job's own concurrent cancellation pre-empted it, and that
    # StaleDataError must not have aborted the whole sweep or propagated
    # out of recover_abandoned_jobs().
    assert recovered == 1
    assert calls["count"] == 1

    with factory() as db:
        ambiguous_job = db.get(JobRecord, ambiguous_job_id)
        ambiguous_session_record = db.get(SessionRecord, ambiguous_session_id)
        # The concurrent, legitimate cancellation must be respected --
        # not overwritten back to FAILED/ambiguous by a blind retry, and
        # the failed attempt's in-memory ambiguous-failure fields must
        # never have been partially persisted.
        assert ambiguous_job.status == JobStatus.CANCELLED.value
        assert ambiguous_job.error_code is None
        assert ambiguous_job.ambiguous_operation_id is None
        assert ambiguous_session_record.state == SessionState.CANCELLED.value
        assert ambiguous_session_record.pending_operation_id == operation_id

        plain_job = db.get(JobRecord, plain_job_id)
        plain_session_record = db.get(SessionRecord, plain_session_id)
        assert plain_job.status == JobStatus.QUEUED.value
        assert plain_job.error_code == "worker_lease_expired"
        assert plain_session_record.state == SessionState.TRANSCRIBING.value

    # The worker loop must keep functioning afterward -- no exception
    # should have escaped the sweep above, and a further tick must not
    # touch the (now legitimately cancelled) ambiguous job either.
    assert worker.run_once() in (True, False)
    with factory() as db:
        ambiguous_job = db.get(JobRecord, ambiguous_job_id)
        assert ambiguous_job.status == JobStatus.CANCELLED.value


def _speakr_transcript_adapter(monkeypatch, payload):
    def handle_request(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    adapter = SpeakrHttpAdapter("https://speakr.invalid", "test-token")
    monkeypatch.setattr(
        adapter,
        "_client",
        lambda: httpx.Client(
            base_url=adapter.base_url,
            headers={"X-API-Token": adapter.api_token},
            transport=httpx.MockTransport(handle_request),
        ),
    )
    return adapter


def test_speakr_transcript_without_segments_is_an_error_not_an_empty_transcript(
    monkeypatch,
):
    adapter = _speakr_transcript_adapter(
        monkeypatch,
        {"format": "json", "segments": [], "raw": "a transcript with no timestamps"},
    )

    with pytest.raises(AdapterResponseError):
        adapter.get_transcript("recording-1")


def test_summary_records_where_each_theme_happened(settings):
    from evidence_api.models import SessionSummaryRecord

    engine = create_db_engine(settings)
    init_schema(engine)
    factory = create_session_factory(engine)
    media = settings.media_root / "summary.wav"
    media.parent.mkdir(parents=True, exist_ok=True)
    media.write_bytes(b"audio")
    with factory() as db:
        session = SessionRecord(
            title="Automatic chain",
            state=SessionState.TRANSCRIBING.value,
            media_path=str(media),
        )
        db.add(session)
        db.flush()
        db.add(
            JobRecord(
                session_id=session.id,
                type=JobType.TRANSCRIBE.value,
                max_attempts=3,
            )
        )
        db.commit()
        session_id = session.id

    worker = Worker(
        settings,
        factory,
        adapter=FakeSpeakrAdapter(),
        extraction_provider=FakeExtractionProvider(),
        summary_provider=FakeSummaryProvider(),
    )
    while worker.run_once():
        pass

    with factory() as db:
        summary = db.query(SessionSummaryRecord).filter_by(session_id=session_id).one()
        theme = summary.themes[0]
        assert theme["rank"] == 1
        assert theme["title"] == "Releasing the sound"
        # The span comes from the cited entry's evidence, never from the model.
        assert theme["start_ms"] == 250
        assert theme["end_ms"] == 1250
        # Each cited entry becomes a jump point, so a theme the coach returned
        # to is not flattened into one misleading stretch of the recording.
        stored_entry = db.query(LedgerEntryRecord).one()
        assert theme["moments"] == [
            {"ledger_entry_id": stored_entry.id, "start_ms": 250, "end_ms": 1250}
        ]
        assert summary.entry_count == 1
        # A derived summary must not disturb the reviewable session.
        assert db.get(SessionRecord, session_id).state == SessionState.AWAITING_REVIEW.value


def test_a_failed_summary_does_not_make_a_good_session_look_broken(settings):
    from evidence_api.summaries import SummaryError

    class BrokenSummaryProvider:
        def summarize(self, **_):
            raise SummaryError("gateway exploded")

    engine = create_db_engine(settings)
    init_schema(engine)
    factory = create_session_factory(engine)
    media = settings.media_root / "broken-summary.wav"
    media.parent.mkdir(parents=True, exist_ok=True)
    media.write_bytes(b"audio")
    with factory() as db:
        session = SessionRecord(
            title="Automatic chain",
            state=SessionState.TRANSCRIBING.value,
            media_path=str(media),
        )
        db.add(session)
        db.flush()
        db.add(
            JobRecord(
                session_id=session.id,
                type=JobType.TRANSCRIBE.value,
                max_attempts=1,
            )
        )
        db.commit()
        session_id = session.id

    worker = Worker(
        settings,
        factory,
        adapter=FakeSpeakrAdapter(),
        extraction_provider=FakeExtractionProvider(),
        summary_provider=BrokenSummaryProvider(),
    )
    for _ in range(6):
        worker.run_once()

    with factory() as db:
        session = db.get(SessionRecord, session_id)
        assert session.state == SessionState.AWAITING_REVIEW.value
        assert session.last_error is None
        assert db.query(LedgerEntryRecord).filter_by(session_id=session_id).count() == 1
