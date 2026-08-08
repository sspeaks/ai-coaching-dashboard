import json
import platform
import shutil
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS = json.loads(
    (ROOT / "fixtures" / "contracts" / "nixos-quality-requirements.json").read_text(
        encoding="utf-8"
    )
)


@unittest.skipUnless((ROOT / "flake.nix").exists(), "NixOS implementation not present yet")
class NixOsQualityTests(unittest.TestCase):
    def test_module_mentions_operational_requirements(self):
        sources = [ROOT / "flake.nix", *sorted((ROOT / "nix").rglob("*.nix"))]
        text = "\n".join(path.read_text(encoding="utf-8").lower() for path in sources)
        for concept in REQUIREMENTS["required_configuration_concepts"]:
            self.assertTrue(concept in text, f"Nix configuration omits {concept}")

    @unittest.skipUnless(shutil.which("nix"), "nix command is unavailable")
    def test_flake_exports_module_and_acceptance_checks(self):
        completed = subprocess.run(
            ["nix", "flake", "show", "path:.", "--json"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=300,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        outputs = json.loads(completed.stdout)
        # Newer Nix versions may wrap flake-show results under an "outputs" key.
        flake_outputs = outputs.get("outputs", outputs)
        missing_outputs = [
            output
            for output in REQUIREMENTS["required_flake_outputs"]
            if output not in flake_outputs
        ]
        self.assertFalse(missing_outputs, f"flake outputs omit {missing_outputs}")
        system = f"{platform.machine().replace('amd64', 'x86_64')}-linux"
        system_checks = flake_outputs.get("checks", {}).get(system, {})
        missing_checks = [
            check
            for check in REQUIREMENTS["required_vm_checks"]
            if check not in system_checks
        ]
        self.assertFalse(
            missing_checks,
            f"flake checks for {system} omit {missing_checks}; "
            f"available checks: {sorted(system_checks)}",
        )


if __name__ == "__main__":
    unittest.main()
