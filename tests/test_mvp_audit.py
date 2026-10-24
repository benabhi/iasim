"""Consistency checks for the MVP closure audit."""

from __future__ import annotations

import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "docs" / "mvp-audit.md"


class MvpAuditTests(unittest.TestCase):
    def test_the_audit_names_every_mvp_epic_and_the_release(self) -> None:
        text = AUDIT.read_text(encoding="utf-8")

        for epic in (
            "iasim-tek",
            "iasim-6kr",
            "iasim-7a4",
            "iasim-591",
            "iasim-9i2",
            "iasim-sv5",
            "iasim-qul",
        ):
            self.assertIn(epic, text)
        self.assertIn("v0.1.0", text)
        self.assertIn("7b8da11", text)

    def test_the_audit_records_gaps_and_follow_ups_honestly(self) -> None:
        text = AUDIT.read_text(encoding="utf-8")

        self.assertIn("iasim-145", text)
        self.assertIn("iasim-59d", text)
        self.assertIn("AC-26", text)
        self.assertIn("GAP", text)
        self.assertIn("NOT APPLICABLE", text)
        self.assertIn("no f2/f3 issues were created", text.lower())

    def test_the_audit_matches_the_package_version(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        text = AUDIT.read_text(encoding="utf-8")

        self.assertEqual(project["project"]["version"], "0.1.0")
        self.assertIn(f"Version: `{project['project']['version']}`", text)


if __name__ == "__main__":
    unittest.main()
