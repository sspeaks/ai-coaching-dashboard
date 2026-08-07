import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "fixtures" / "synthetic" / "quartet-coaching-01"


def load(name):
    return json.loads((FIXTURE / name).read_text(encoding="utf-8"))


class SyntheticFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.metadata = load("metadata.json")
        cls.transcript = load("transcript.json")
        cls.gold = load("gold-ledger.json")
        cls.segments = {item["id"]: item for item in cls.transcript["segments"]}

    def test_fixture_is_redistributable_and_contains_no_recording(self):
        self.assertTrue(self.metadata["redistributable"])
        self.assertFalse(self.metadata["contains_real_people"])
        self.assertFalse(self.metadata["contains_copyrighted_recording"])
        self.assertFalse(self.metadata["media"]["included"])

    def test_every_gold_entry_has_grounded_evidence(self):
        for entry in self.gold["entries"]:
            self.assertNotEqual(entry["exact_feedback"], entry["paraphrase"])
            feedback = entry["evidence"]["feedback"]
            feedback_segment = self.segments[feedback["segment_id"]]
            self.assertIn(entry["exact_feedback"].lower(), feedback_segment["text"].lower())
            for reference in entry["evidence"].values():
                segment = self.segments[reference["segment_id"]]
                self.assertLessEqual(segment["start"], reference["timestamp"])
                self.assertLessEqual(reference["timestamp"], segment["end"])
            if entry["observed_result"] != "not_evaluated":
                self.assertIn("result", entry["evidence"])

    def test_uncertain_overlap_is_not_asserted_as_verified(self):
        uncertain = [entry for entry in self.gold["entries"] if entry["uncertainty"]]
        self.assertTrue(uncertain)
        for entry in uncertain:
            self.assertIn(entry["verification_state"], {"UNVERIFIED", "NEEDS_CORRECTION"})
            self.assertLess(entry["confidence"], 0.5)

    def test_machine_extracted_gold_expectations_start_unverified(self):
        self.assertTrue(
            all(entry["verification_state"] == "UNVERIFIED" for entry in self.gold["entries"])
        )

    def test_no_action_passages_do_not_generate_feedback_entries(self):
        feedback_segments = {
            entry["evidence"]["feedback"]["segment_id"] for entry in self.gold["entries"]
        }
        self.assertTrue(set(self.gold["no_action_segments"]).isdisjoint(feedback_segments))


if __name__ == "__main__":
    unittest.main()
