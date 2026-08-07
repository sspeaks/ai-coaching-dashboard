from evidence_api.transcripts import (
    normalize_speakr_segments,
    seconds_to_ms,
    transcript_sha256,
)


def test_speakr_seconds_are_normalized_to_explicit_milliseconds():
    segments = normalize_speakr_segments(
        [
            {
                "speaker": "SPEAKER_00",
                "sentence": "Do not infer identity.",
                "start_time": 1.2345,
                "end_time": 2.0,
            }
        ]
    )
    assert seconds_to_ms("1.2345") == 1235
    assert segments[0].start_ms == 1235
    assert segments[0].end_ms == 2000
    assert transcript_sha256(segments) == transcript_sha256(segments)
