import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "fixtures" / "browser" / "evidence-ledger-scenarios.json"


class BrowserScenarioManifestTests(unittest.TestCase):
    """Validate scenario coverage only; this is not browser automation."""

    def test_scenarios_cover_critical_user_workflows(self):
        document = json.loads(MANIFEST.read_text(encoding="utf-8"))
        ids = {scenario["id"] for scenario in document["scenarios"]}
        self.assertTrue(
            {
                "seek-from-feedback",
                "uncertainty-not-asserted",
                "correct-transcript-preserve-history",
                "reject-critical-claim",
                "delete-session-copies",
                "cost-observability",
            }.issubset(ids)
        )
        for scenario in document["scenarios"]:
            self.assertTrue(scenario["steps"])
            self.assertTrue(scenario["assertions"])


if __name__ == "__main__":
    unittest.main()
