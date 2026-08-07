#!/usr/bin/env python3
"""Score a generated coaching ledger against a human-labelled fixture."""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from pathlib import Path
from typing import Any

DEFAULT_THRESHOLDS = {
    "intervention_recall": 0.90,
    "unsupported_claim_rate_max": 0.0,
    "reversed_instruction_count_max": 0,
    "invented_critical_claim_count_max": 0,
    "attribution_accuracy": 0.95,
    "evidence_relevance": 0.95,
    "median_seek_error_seconds_max": 2.0,
    "uncertainty_compliance": 1.0,
    "verification_state_accuracy": 0.95,
    "substantive_claim_evidence_rate": 1.0,
    "transcript_revision_accuracy": 1.0,
}

OPPOSITE_ACTIONS = {
    "avoid_scoop": {"encourage_scoop"},
    "delay_diphthong": {"advance_diphthong"},
    "align_release_with_lead": {"release_separately", "misalign_release"},
    "soften_third": {"strengthen_third", "increase_third"},
    "breathe_together": {"breathe_separately"},
    "avoid_acceleration": {"accelerate_tag"},
    "increase_ring_not_volume": {"increase_volume", "sing_louder"},
}


def load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.lower()))


def _similarity(predicted: dict[str, Any], gold: dict[str, Any]) -> float:
    predicted_text = " ".join(
        str(predicted.get(key, "")) for key in ("topic", "exact_feedback", "paraphrase")
    )
    gold_text = " ".join(
        str(gold.get(key, "")) for key in ("topic", "exact_feedback", "paraphrase")
    )
    left, right = _tokens(predicted_text), _tokens(gold_text)
    return len(left & right) / len(left | right) if left and right else 0.0


def _match_entries(
    predicted: list[dict[str, Any]], gold: list[dict[str, Any]]
) -> tuple[dict[int, int], set[int]]:
    gold_by_id = {entry.get("id"): index for index, entry in enumerate(gold)}
    matches: dict[int, int] = {}
    used_gold: set[int] = set()

    for pred_index, entry in enumerate(predicted):
        gold_index = gold_by_id.get(entry.get("id"))
        if gold_index is not None and gold_index not in used_gold:
            matches[pred_index] = gold_index
            used_gold.add(gold_index)

    candidates: list[tuple[float, int, int]] = []
    for pred_index, pred_entry in enumerate(predicted):
        if pred_index in matches:
            continue
        for gold_index, gold_entry in enumerate(gold):
            if gold_index not in used_gold:
                candidates.append((_similarity(pred_entry, gold_entry), pred_index, gold_index))

    for similarity, pred_index, gold_index in sorted(candidates, reverse=True):
        if similarity < 0.55 or pred_index in matches or gold_index in used_gold:
            continue
        matches[pred_index] = gold_index
        used_gold.add(gold_index)
    return matches, used_gold


def _valid_quote(entry: dict[str, Any], transcript_by_id: dict[str, dict[str, Any]]) -> bool:
    quote = str(entry.get("exact_feedback", "")).strip().lower()
    feedback = entry.get("evidence", {}).get("feedback", {})
    segment = transcript_by_id.get(feedback.get("segment_id"))
    if not quote or not segment:
        return False
    return quote in str(segment.get("text", "")).lower()


def _action(entry: dict[str, Any]) -> str:
    return str(entry.get("action", {}).get("normalized", ""))


def _is_reversed(predicted: dict[str, Any], gold: dict[str, Any]) -> bool:
    predicted_action, gold_action = _action(predicted), _action(gold)
    if predicted_action in OPPOSITE_ACTIONS.get(gold_action, set()):
        return True
    return (
        bool(gold.get("action", {}).get("critical"))
        and predicted_action != gold_action
        and predicted.get("action", {}).get("polarity")
        != gold.get("action", {}).get("polarity")
    )


def _entry_supported(
    predicted: dict[str, Any],
    gold: dict[str, Any],
    transcript_by_id: dict[str, dict[str, Any]],
) -> bool:
    result = predicted.get("observed_result", "not_evaluated")
    result_supported = result == gold.get("observed_result", "not_evaluated")
    if result not in (None, "not_evaluated"):
        result_supported = result_supported and "result" in predicted.get("evidence", {})
    return (
        _valid_quote(predicted, transcript_by_id)
        and predicted.get("subject") == gold.get("subject")
        and _action(predicted) == _action(gold)
        and bool(str(predicted.get("paraphrase", "")).strip())
        and predicted.get("paraphrase") != predicted.get("exact_feedback")
        and result_supported
    )


def _threshold_results(metrics: dict[str, Any], thresholds: dict[str, Any]) -> dict[str, bool]:
    return {
        "intervention_recall": metrics["intervention_recall"]
        >= thresholds["intervention_recall"],
        "unsupported_claim_rate": metrics["unsupported_claim_rate"]
        <= thresholds["unsupported_claim_rate_max"],
        "reversed_instructions": metrics["reversed_instruction_count"]
        <= thresholds["reversed_instruction_count_max"],
        "invented_critical_claims": metrics["invented_critical_claim_count"]
        <= thresholds["invented_critical_claim_count_max"],
        "attribution_accuracy": metrics["attribution_accuracy"]
        >= thresholds["attribution_accuracy"],
        "evidence_relevance": metrics["evidence_relevance"]
        >= thresholds["evidence_relevance"],
        "median_seek_error_seconds": metrics["median_seek_error_seconds"]
        <= thresholds["median_seek_error_seconds_max"],
        "uncertainty_compliance": metrics["uncertainty_compliance"]
        >= thresholds["uncertainty_compliance"],
        "verification_state_accuracy": metrics["verification_state_accuracy"]
        >= thresholds["verification_state_accuracy"],
        "substantive_claim_evidence_rate": metrics["substantive_claim_evidence_rate"]
        >= thresholds["substantive_claim_evidence_rate"],
        "transcript_revision_accuracy": metrics["transcript_revision_accuracy"]
        >= thresholds["transcript_revision_accuracy"],
    }


def score(
    gold_document: dict[str, Any],
    predicted_document: dict[str, Any],
    transcript_document: dict[str, Any],
    thresholds: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return deterministic metrics and a release-gate verdict."""
    thresholds = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    gold = gold_document.get("entries", [])
    predicted = predicted_document.get("entries", [])
    transcript_by_id = {
        segment["id"]: segment for segment in transcript_document.get("segments", [])
    }
    matches, used_gold = _match_entries(predicted, gold)

    unsupported = 0
    reversed_count = 0
    invented_critical = 0
    attribution_correct = 0
    verification_correct = 0
    relevant_links = 0
    total_links = 0
    seek_errors: list[float] = []
    entries_with_evidence = 0

    for pred_index, pred_entry in enumerate(predicted):
        evidence = pred_entry.get("evidence", {})
        if evidence:
            entries_with_evidence += 1
        gold_index = matches.get(pred_index)
        if gold_index is None:
            unsupported += 1
            if pred_entry.get("action", {}).get("critical"):
                invented_critical += 1
            total_links += len(evidence)
            continue

        gold_entry = gold[gold_index]
        if pred_entry.get("subject") == gold_entry.get("subject"):
            attribution_correct += 1
        if pred_entry.get("verification_state") == gold_entry.get("verification_state"):
            verification_correct += 1
        if _is_reversed(pred_entry, gold_entry):
            reversed_count += 1
        if not _entry_supported(pred_entry, gold_entry, transcript_by_id):
            unsupported += 1
            if pred_entry.get("action", {}).get("critical") and not _is_reversed(
                pred_entry, gold_entry
            ):
                invented_critical += 1

        for role, reference in evidence.items():
            total_links += 1
            segment = transcript_by_id.get(reference.get("segment_id"))
            expected = gold_entry.get("evidence", {}).get(role)
            timestamp = reference.get("timestamp")
            relevant = (
                segment is not None
                and expected is not None
                and reference.get("segment_id") == expected.get("segment_id")
                and isinstance(timestamp, (int, float))
                and segment["start"] <= timestamp <= segment["end"]
            )
            if relevant:
                relevant_links += 1
                seek_errors.append(abs(float(timestamp) - float(expected["timestamp"])))

    uncertain_gold = [
        (index, entry) for index, entry in enumerate(gold) if entry.get("uncertainty")
    ]
    uncertainty_correct = 0
    for gold_index, _ in uncertain_gold:
        matched_pred = next(
            (predicted[pred_index] for pred_index, match in matches.items() if match == gold_index),
            None,
        )
        if (
            matched_pred
            and matched_pred.get("uncertainty")
            and matched_pred.get("verification_state") in {"UNVERIFIED", "NEEDS_CORRECTION"}
        ):
            uncertainty_correct += 1

    matched_count = len(used_gold)
    metrics = {
        "intervention_recall": matched_count / len(gold) if gold else 1.0,
        "unsupported_claim_rate": unsupported / len(predicted) if predicted else 0.0,
        "unsupported_claim_count": unsupported,
        "reversed_instruction_count": reversed_count,
        "invented_critical_claim_count": invented_critical,
        "attribution_accuracy": attribution_correct / matched_count if matched_count else 0.0,
        "evidence_relevance": relevant_links / total_links if total_links else 0.0,
        "median_seek_error_seconds": statistics.median(seek_errors) if seek_errors else 1e9,
        "uncertainty_compliance": uncertainty_correct / len(uncertain_gold)
        if uncertain_gold
        else 1.0,
        "verification_state_accuracy": verification_correct / matched_count
        if matched_count
        else 0.0,
        "substantive_claim_evidence_rate": entries_with_evidence / len(predicted)
        if predicted
        else 0.0,
        "transcript_revision_accuracy": float(
            predicted_document.get("transcript_revision")
            == gold_document.get("transcript_revision")
        ),
        "matched_interventions": matched_count,
        "gold_interventions": len(gold),
        "predicted_interventions": len(predicted),
    }
    checks = _threshold_results(metrics, thresholds)
    return {
        "passed": all(checks.values()),
        "metrics": metrics,
        "checks": checks,
        "thresholds": thresholds,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", required=True)
    parser.add_argument("--predicted", required=True)
    parser.add_argument("--transcript", required=True)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    result = score(load_json(args.gold), load_json(args.predicted), load_json(args.transcript))
    rendered = json.dumps(result, indent=2, sort_keys=True, allow_nan=False)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
