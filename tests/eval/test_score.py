import copy
import json
import unittest
from pathlib import Path

from eval.score import score


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures" / "synthetic" / "quartet-coaching-01"


def load(name):
    return json.loads((FIXTURE / name).read_text(encoding="utf-8"))


class CoachingLedgerScoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gold = load("gold-ledger.json")
        cls.transcript = load("transcript.json")

    def test_gold_scores_as_release_ready(self):
        result = score(self.gold, self.gold, self.transcript)
        self.assertTrue(result["passed"], result)
        self.assertEqual(result["metrics"]["intervention_recall"], 1.0)
        self.assertEqual(result["metrics"]["unsupported_claim_rate"], 0.0)
        self.assertLessEqual(result["metrics"]["median_seek_error_seconds"], 2.0)

    def test_ten_of_eleven_interventions_meets_ninety_percent_recall(self):
        predicted = copy.deepcopy(self.gold)
        predicted["entries"].pop()
        result = score(self.gold, predicted, self.transcript)
        self.assertGreaterEqual(result["metrics"]["intervention_recall"], 0.90)
        self.assertTrue(result["checks"]["intervention_recall"])

    def test_invented_critical_claim_fails_even_with_high_confidence(self):
        predicted = load("adversarial-ledger.json")
        result = score(self.gold, predicted, self.transcript)
        self.assertFalse(result["passed"])
        self.assertGreater(result["metrics"]["invented_critical_claim_count"], 0)
        self.assertFalse(result["checks"]["invented_critical_claims"])

    def test_reversed_negative_instruction_fails(self):
        predicted = copy.deepcopy(self.gold)
        entry = predicted["entries"][0]
        entry["action"] = {
            "normalized": "encourage_scoop",
            "polarity": "positive",
            "critical": True,
        }
        entry["exact_feedback"] = "Bass, scoop into the first note."
        result = score(self.gold, predicted, self.transcript)
        self.assertEqual(result["metrics"]["reversed_instruction_count"], 1)
        self.assertFalse(result["checks"]["reversed_instructions"])

    def test_wrong_attribution_and_irrelevant_timestamp_fail(self):
        predicted = copy.deepcopy(self.gold)
        predicted["entries"][0]["subject"] = "tenor"
        predicted["entries"][0]["evidence"]["feedback"] = {
            "segment_id": "s025",
            "timestamp": 141.0,
        }
        predicted["entries"][0]["evidence"]["before"] = {
            "segment_id": "s025",
            "timestamp": 141.0,
        }
        result = score(self.gold, predicted, self.transcript)
        self.assertFalse(result["passed"])
        self.assertLess(result["metrics"]["attribution_accuracy"], 0.95)
        self.assertLess(result["metrics"]["evidence_relevance"], 0.95)

    def test_uncertain_overlap_cannot_be_asserted_verified(self):
        predicted = copy.deepcopy(self.gold)
        uncertain = next(entry for entry in predicted["entries"] if entry["id"] == "i05")
        uncertain["uncertainty"] = None
        uncertain["verification_state"] = "VERIFIED"
        result = score(self.gold, predicted, self.transcript)
        self.assertEqual(result["metrics"]["uncertainty_compliance"], 0.0)
        self.assertFalse(result["checks"]["uncertainty_compliance"])

    def test_transcript_revision_must_match(self):
        predicted = copy.deepcopy(self.gold)
        predicted["transcript_revision"] = 2
        result = score(self.gold, predicted, self.transcript)
        self.assertFalse(result["checks"]["transcript_revision_accuracy"])


if __name__ == "__main__":
    unittest.main()
