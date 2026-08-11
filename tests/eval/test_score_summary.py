"""Tests for eval.score_summary."""

import unittest

from eval.score_summary import score_summary


class TestScoreSummary(unittest.TestCase):
    """Validate summary scoring logic against synthetic expectations."""

    GOLD_LEDGER = {
        "entries": [
            {"id": f"i{i:02d}"} for i in range(1, 12)
        ]
    }

    GOLD_SUMMARY = {
        "expected_theme_count_range": [8, 10],
        "known_merge_pairs": [
            {"entry_ids": ["i01", "i02"], "reason": "bass onset pair"}
        ],
        "known_distinct_pairs": [
            {"entry_ids": ["i03", "i04"], "reason": "different singers"},
            {"entry_ids": ["i07", "i08"], "reason": "different techniques"},
            {"entry_ids": ["i09", "i10"], "reason": "different points"},
            {"entry_ids": ["i02", "i11"], "reason": "onset exercise vs resonance instruction"},
            {"entry_ids": ["i05", "i06"], "reason": "dynamic correction vs rehearsal technique"},
        ],
    }

    def test_perfect_summary_passes(self):
        """A summary that merges i01+i02 and keeps everything else separate passes."""
        predicted = {
            "themes": [
                {"ledger_entry_ids": ["i01", "i02"]},
                {"ledger_entry_ids": ["i03"]},
                {"ledger_entry_ids": ["i04"]},
                {"ledger_entry_ids": ["i05"]},
                {"ledger_entry_ids": ["i06"]},
                {"ledger_entry_ids": ["i07"]},
                {"ledger_entry_ids": ["i08"]},
                {"ledger_entry_ids": ["i09"]},
                {"ledger_entry_ids": ["i10"]},
                {"ledger_entry_ids": ["i11"]},
            ]
        }
        result = score_summary(self.GOLD_SUMMARY, predicted, self.GOLD_LEDGER)
        self.assertTrue(result["passed"])
        self.assertEqual(result["metrics"]["merge_accuracy"], 1.0)
        self.assertEqual(result["metrics"]["distinct_accuracy"], 1.0)
        self.assertEqual(result["metrics"]["orphan_entry_count"], 0)

    def test_over_merged_fails_distinct_check(self):
        """Merging i03 and i04 into one theme violates distinct pair constraint."""
        predicted = {
            "themes": [
                {"ledger_entry_ids": ["i01", "i02"]},
                {"ledger_entry_ids": ["i03", "i04"]},  # BAD: should be separate
                {"ledger_entry_ids": ["i05"]},
                {"ledger_entry_ids": ["i06"]},
                {"ledger_entry_ids": ["i07"]},
                {"ledger_entry_ids": ["i08"]},
                {"ledger_entry_ids": ["i09"]},
                {"ledger_entry_ids": ["i10"]},
                {"ledger_entry_ids": ["i11"]},
            ]
        }
        result = score_summary(self.GOLD_SUMMARY, predicted, self.GOLD_LEDGER)
        self.assertFalse(result["passed"])
        self.assertLess(result["metrics"]["distinct_accuracy"], 1.0)

    def test_under_merged_fails_merge_check(self):
        """Keeping i01 and i02 separate violates merge pair constraint."""
        predicted = {
            "themes": [
                {"ledger_entry_ids": ["i01"]},
                {"ledger_entry_ids": ["i02"]},
                {"ledger_entry_ids": ["i03"]},
                {"ledger_entry_ids": ["i04"]},
                {"ledger_entry_ids": ["i05"]},
                {"ledger_entry_ids": ["i06"]},
                {"ledger_entry_ids": ["i07"]},
                {"ledger_entry_ids": ["i08"]},
                {"ledger_entry_ids": ["i09"]},
                {"ledger_entry_ids": ["i10"]},
                {"ledger_entry_ids": ["i11"]},
            ]
        }
        result = score_summary(self.GOLD_SUMMARY, predicted, self.GOLD_LEDGER)
        self.assertFalse(result["passed"])
        self.assertEqual(result["metrics"]["merge_accuracy"], 0.0)

    def test_orphan_entries_fail(self):
        """Missing entries from themes causes failure."""
        predicted = {
            "themes": [
                {"ledger_entry_ids": ["i01", "i02"]},
                {"ledger_entry_ids": ["i03"]},
                {"ledger_entry_ids": ["i04"]},
                {"ledger_entry_ids": ["i05"]},
                {"ledger_entry_ids": ["i06"]},
                {"ledger_entry_ids": ["i07"]},
                {"ledger_entry_ids": ["i08"]},
                {"ledger_entry_ids": ["i09"]},
                # i10 and i11 are missing
            ]
        }
        result = score_summary(self.GOLD_SUMMARY, predicted, self.GOLD_LEDGER)
        self.assertFalse(result["passed"])
        self.assertEqual(result["metrics"]["orphan_entry_count"], 2)

    def test_theme_count_out_of_range_fails(self):
        """Too few themes (below expected range) causes failure."""
        predicted = {
            "themes": [
                {"ledger_entry_ids": ["i01", "i02", "i03", "i04", "i05"]},
                {"ledger_entry_ids": ["i06", "i07", "i08", "i09", "i10", "i11"]},
            ]
        }
        result = score_summary(self.GOLD_SUMMARY, predicted, self.GOLD_LEDGER)
        self.assertFalse(result["passed"])
        self.assertFalse(result["metrics"]["count_in_range"])

    def test_merging_i11_into_bass_onset_fails(self):
        """Switch attack 5: merging i11 into bass-onset theme must now be caught."""
        predicted = {
            "themes": [
                {"ledger_entry_ids": ["i01", "i02", "i11"]},  # BAD: i02+i11 distinct
                {"ledger_entry_ids": ["i03"]},
                {"ledger_entry_ids": ["i04"]},
                {"ledger_entry_ids": ["i05"]},
                {"ledger_entry_ids": ["i06"]},
                {"ledger_entry_ids": ["i07"]},
                {"ledger_entry_ids": ["i08"]},
                {"ledger_entry_ids": ["i09"]},
                {"ledger_entry_ids": ["i10"]},
            ]
        }
        result = score_summary(self.GOLD_SUMMARY, predicted, self.GOLD_LEDGER)
        self.assertFalse(result["passed"])
        self.assertLess(result["metrics"]["distinct_accuracy"], 1.0)

    def test_merging_i05_i06_fails(self):
        """Switch attack 6: merging i05+i06 must now be caught."""
        predicted = {
            "themes": [
                {"ledger_entry_ids": ["i01", "i02"]},
                {"ledger_entry_ids": ["i03"]},
                {"ledger_entry_ids": ["i04"]},
                {"ledger_entry_ids": ["i05", "i06"]},  # BAD: distinct pair
                {"ledger_entry_ids": ["i07"]},
                {"ledger_entry_ids": ["i08"]},
                {"ledger_entry_ids": ["i09"]},
                {"ledger_entry_ids": ["i10"]},
                {"ledger_entry_ids": ["i11"]},
            ]
        }
        result = score_summary(self.GOLD_SUMMARY, predicted, self.GOLD_LEDGER)
        self.assertFalse(result["passed"])
        self.assertLess(result["metrics"]["distinct_accuracy"], 1.0)


if __name__ == "__main__":
    unittest.main()
