#!/usr/bin/env python3
"""Score a generated summary against a gold-summary fixture.

Checks:
- Theme recall: every gold entry appears in at least one theme.
- No orphan entries: no entry assigned to zero themes.
- Merge accuracy: known merge pairs share a theme; known distinct pairs do not.

Distinct-pair handling:
  By default the fixture lists a subset of ``known_distinct_pairs`` that must
  stay separate, and any unlisted pair is unconstrained (allowing undetected
  over-merges).  When the fixture sets ``invert_distinct_default: true`` the
  scorer instead generates the *full* distinct-pair matrix from all entry IDs,
  then subtracts pairs that are explicitly permitted by ``known_merge_pairs``.
  This inverts the default: merging is a failure unless permitted.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def score_summary(
    gold_summary: dict[str, Any],
    predicted_summary: dict[str, Any],
    gold_ledger: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate predicted summary themes against gold expectations."""
    themes = predicted_summary.get("themes", [])
    all_entry_ids = {entry["id"] for entry in gold_ledger.get("entries", [])}

    # Build a map of entry_id -> set of theme indices it appears in
    entry_to_themes: dict[str, set[int]] = {eid: set() for eid in all_entry_ids}
    for idx, theme in enumerate(themes):
        for eid in theme.get("ledger_entry_ids", []):
            if eid in entry_to_themes:
                entry_to_themes[eid].add(idx)

    # Theme recall: fraction of gold entries covered by at least one theme
    covered = sum(1 for eids in entry_to_themes.values() if eids)
    theme_recall = covered / len(all_entry_ids) if all_entry_ids else 1.0

    # Orphan entries: entries in no theme
    orphan_ids = [eid for eid, t in entry_to_themes.items() if not t]

    # Merge accuracy: known merge pairs must share a theme
    merge_pairs = gold_summary.get("known_merge_pairs", [])
    merge_correct = 0
    merge_total = len(merge_pairs)
    for pair in merge_pairs:
        ids = pair["entry_ids"]
        if len(ids) < 2:
            merge_correct += 1
            continue
        # All entries in the pair should share at least one common theme
        theme_sets = [entry_to_themes.get(eid, set()) for eid in ids]
        common = set.intersection(*theme_sets) if theme_sets else set()
        if common:
            merge_correct += 1

    # Distinct accuracy: known distinct pairs must NOT share a theme.
    # If invert_distinct_default is true, generate the full pair matrix from all
    # entry IDs and subtract pairs that are explicitly permitted by known_merge_pairs.
    # This inverts the default from "unlisted pairs are unconstrained" to
    # "unlisted pairs are forbidden unless in a known merge group".
    if gold_summary.get("invert_distinct_default", False):
        permitted_merge_pairs: set[frozenset[str]] = set()
        for mp in merge_pairs:
            mp_ids = mp["entry_ids"]
            for _i in range(len(mp_ids)):
                for _j in range(_i + 1, len(mp_ids)):
                    permitted_merge_pairs.add(frozenset([mp_ids[_i], mp_ids[_j]]))
        all_ids_sorted = sorted(all_entry_ids)
        distinct_pairs = [
            {"entry_ids": [a, b]}
            for _i, a in enumerate(all_ids_sorted)
            for _j, b in enumerate(all_ids_sorted)
            if _i < _j and frozenset([a, b]) not in permitted_merge_pairs
        ]
    else:
        distinct_pairs = gold_summary.get("known_distinct_pairs", [])
    distinct_correct = 0
    distinct_total = len(distinct_pairs)
    for pair in distinct_pairs:
        ids = pair["entry_ids"]
        if len(ids) < 2:
            distinct_correct += 1
            continue
        theme_sets = [entry_to_themes.get(eid, set()) for eid in ids]
        common = set.intersection(*theme_sets) if theme_sets else set()
        if not common:
            distinct_correct += 1

    # Theme count in expected range
    expected_range = gold_summary.get("expected_theme_count_range", [5, 15])
    theme_count = len(themes)
    count_in_range = expected_range[0] <= theme_count <= expected_range[1]

    metrics = {
        "theme_count": theme_count,
        "expected_theme_count_range": expected_range,
        "count_in_range": count_in_range,
        "theme_recall": theme_recall,
        "orphan_entry_count": len(orphan_ids),
        "orphan_entry_ids": orphan_ids,
        "merge_accuracy": merge_correct / merge_total if merge_total else 1.0,
        "merge_correct": merge_correct,
        "merge_total": merge_total,
        "distinct_accuracy": distinct_correct / distinct_total if distinct_total else 1.0,
        "distinct_correct": distinct_correct,
        "distinct_total": distinct_total,
    }

    passed = (
        theme_recall >= 0.90
        and len(orphan_ids) == 0
        and (merge_correct == merge_total)
        and (distinct_correct == distinct_total)
        and count_in_range
    )

    return {
        "passed": passed,
        "metrics": metrics,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold-summary", required=True, help="Path to gold-summary.json")
    parser.add_argument("--predicted-summary", required=True, help="Path to predicted summary JSON")
    parser.add_argument("--gold-ledger", required=True, help="Path to gold-ledger.json")
    parser.add_argument("--output")
    args = parser.parse_args(argv)

    result = score_summary(
        load_json(args.gold_summary),
        load_json(args.predicted_summary),
        load_json(args.gold_ledger),
    )
    rendered = json.dumps(result, indent=2, sort_keys=True, allow_nan=False)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
