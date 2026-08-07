from coaching_contracts import SessionState, VerificationStatus
from evidence_api.models import (
    LedgerEntryRecord,
    SessionRecord,
    TranscriptRevisionRecord,
)
from evidence_api.services import reconcile_transcript


class FakeAdapter:
    def get_transcript(self, recording_id):
        assert recording_id == "42"
        return [
            {
                "id": "corrected-0",
                "start_time": 0.5,
                "end_time": 1.5,
                "sentence": "Corrected coach feedback.",
                "speaker": "SPEAKER_00",
            }
        ]

    def delete_recording(self, recording_id):
        raise NotImplementedError


def test_changed_transcript_revision_reopens_human_review(app, client):
    with app.state.session_factory() as db:
        session = SessionRecord(
            title="Revision test",
            state=SessionState.COMPLETE.value,
            speakr_recording_id="42",
            duration_ms=5_000,
        )
        db.add(session)
        db.flush()
        old = TranscriptRevisionRecord(
            session_id=session.id,
            sha256="c" * 64,
            source="speakr",
            segments=[
                {
                    "segment_id": "old-0",
                    "start_ms": 500,
                    "end_ms": 1500,
                    "text": "Old coach feedback.",
                    "provider_speaker_label": "SPEAKER_00",
                }
            ],
        )
        db.add(old)
        db.flush()
        session.current_transcript_revision_id = old.id
        entry = LedgerEntryRecord(
            session_id=session.id,
            transcript_revision_id=old.id,
            topic="Old entry",
            confidence_millis=900,
            evidence=[
                {
                    "transcript_revision_id": old.id,
                    "start_ms": 500,
                    "end_ms": 1500,
                    "segment_ids": ["old-0"],
                }
            ],
            extraction_metadata={},
            verification_status=VerificationStatus.VERIFIED.value,
            verified_by="reviewer@example.com",
        )
        db.add(entry)
        db.commit()

        revision, changed = reconcile_transcript(db, session, FakeAdapter())
        db.commit()
        assert changed is True
        assert revision.id != old.id
        assert session.current_transcript_revision_id == revision.id
        assert session.state == SessionState.AWAITING_REVIEW.value
        assert entry.verification_status == VerificationStatus.NEEDS_REVIEW.value
        assert entry.verified_by is None
