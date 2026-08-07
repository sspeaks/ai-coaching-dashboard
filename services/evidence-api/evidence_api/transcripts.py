import hashlib
import json
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from coaching_contracts import TranscriptSegment


def seconds_to_ms(value: Any) -> int:
    try:
        seconds = Decimal(str(value))
    except Exception as exc:
        raise ValueError(f"invalid timestamp seconds: {value!r}") from exc
    if seconds < 0:
        raise ValueError("timestamp seconds cannot be negative")
    return int((seconds * 1000).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def normalize_speakr_segments(raw_segments: list[dict]) -> list[TranscriptSegment]:
    normalized: list[TranscriptSegment] = []
    segment_ids: set[str] = set()
    for index, raw in enumerate(raw_segments):
        if not isinstance(raw, dict):
            raise ValueError(f"segment {index} is not an object")
        start = raw.get("start_time", raw.get("start"))
        end = raw.get("end_time", raw.get("end"))
        if start is None or end is None:
            raise ValueError(f"segment {index} omits start/end timestamps")
        segment_id = str(raw.get("id", index))
        if segment_id in segment_ids:
            raise ValueError(f"duplicate segment id: {segment_id}")
        segment_ids.add(segment_id)
        normalized.append(
            TranscriptSegment(
                segment_id=segment_id,
                start_ms=seconds_to_ms(start),
                end_ms=seconds_to_ms(end),
                text=str(raw.get("sentence", raw.get("text", ""))),
                provider_speaker_label=(
                    str(raw["speaker"]) if raw.get("speaker") is not None else None
                ),
            )
        )
    return normalized


def transcript_sha256(segments: list[TranscriptSegment]) -> str:
    canonical = json.dumps(
        [segment.model_dump(mode="json") for segment in segments],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
