import logging

import pytest

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


def test_zero_length_segments_are_dropped_without_renumbering_the_rest(caplog):
    with caplog.at_level(logging.WARNING):
        segments = normalize_speakr_segments(
            [
                {"start_time": 1.0, "end_time": 2.0, "sentence": "Kept."},
                {"start_time": 3.0, "end_time": 3.0, "sentence": "Let's"},
                {"start_time": 4.0, "end_time": 5.0, "sentence": "Also kept."},
            ]
        )

    assert [segment.segment_id for segment in segments] == ["0", "2"]
    assert [segment.text for segment in segments] == ["Kept.", "Also kept."]
    assert "zero-length" in caplog.text


def test_a_transcript_of_only_zero_length_segments_is_an_error():
    with pytest.raises(ValueError):
        normalize_speakr_segments([{"start_time": 1.0, "end_time": 1.0, "text": "And"}])


def test_an_empty_transcript_stays_empty():
    assert normalize_speakr_segments([]) == []


def test_a_segment_ending_before_it_starts_is_an_error():
    with pytest.raises(ValueError):
        normalize_speakr_segments(
            [{"start_time": 2.0, "end_time": 1.0, "sentence": "reversed"}]
        )
