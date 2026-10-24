"""Release documentation and metadata consistency tests."""

from __future__ import annotations

import re
import tomllib
import unittest
from pathlib import Path

from iasim import __version__
from iasim.config import IasimConfig
from iasim.protocol import PROTOCOL_VERSION

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
RELEASE_NOTES = ROOT / "docs" / "release-notes.md"
CONFIGURATION = ROOT / "docs" / "configuration.md"
SRS = ROOT / "docs" / "SRS.md"


class ReleaseMetadataTests(unittest.TestCase):
    def test_package_version_is_the_release_version(self) -> None:
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        version = project["project"]["version"]

        self.assertEqual(version, "0.1.0")
        self.assertEqual(__version__, version)
        self.assertEqual(PROTOCOL_VERSION, "iasim-mcp/1.0")

    def test_release_documents_exist_and_link_each_other(self) -> None:
        for path in (README, RELEASE_NOTES, CONFIGURATION, SRS):
            self.assertTrue(path.is_file(), path)
        readme = README.read_text(encoding="utf-8")
        notes = RELEASE_NOTES.read_text(encoding="utf-8")
        configuration = CONFIGURATION.read_text(encoding="utf-8")

        self.assertIn("docs/SRS.md", readme)
        self.assertIn("docs/release-notes.md", readme)
        self.assertIn("docs/configuration.md", readme)
        self.assertIn("0.1.0", notes)
        self.assertIn("iasim-mcp/1.0", notes)
        self.assertIn("SRS.md", notes)
        self.assertIn("SRS.md", configuration)

    def test_readme_and_notes_do_not_claim_f2_f3_features(self) -> None:
        readme = README.read_text(encoding="utf-8").lower()
        notes = RELEASE_NOTES.read_text(encoding="utf-8").lower()

        for text in (readme, notes):
            normalized = " ".join(text.split())
            self.assertIn("f2", normalized)
            self.assertIn("f3", normalized)
            self.assertIn("not delivered", normalized)
        for forbidden in ("snow is implemented", "fishing is implemented", "llm agent is included"):
            self.assertNotIn(forbidden, " ".join(readme.split()))
            self.assertNotIn(forbidden, " ".join(notes.split()))

    def test_startup_commands_and_protocol_are_documented(self) -> None:
        readme = README.read_text(encoding="utf-8")

        for expected in (
            "uv run iasim",
            "iasim serve --headless",
            "python -m iasim",
            "iasim-mcp/1.0",
            "agents.json",
            "0.0.0.0",
        ):
            self.assertIn(expected, readme)

    def test_configuration_doc_matches_the_pydantic_defaults(self) -> None:
        text = CONFIGURATION.read_text(encoding="utf-8")
        defaults = IasimConfig()

        expected_rows = {
            "`tick_minutes`": str(defaults.game.tick_minutes),
            "`turn_timeout_ms`": str(defaults.game.turn_timeout_ms),
            "`max_agents`": str(defaults.game.max_agents),
            "`autosave_every_ticks`": str(defaults.game.autosave_every_ticks),
            "`weather_min_ticks`": str(defaults.weather.weather_min_ticks),
            "`weather_max_ticks`": str(defaults.weather.weather_max_ticks),
            "`port`": str(defaults.mcp.port),
            "`snapshot_every_ticks`": str(defaults.logs.snapshot_every_ticks),
        }
        for label, value in expected_rows.items():
            with self.subTest(label=label):
                line = next(
                    (row for row in text.splitlines() if label in row),
                    None,
                )
                self.assertIsNotNone(line, label)
                self.assertIn(f"`{value}`", line or "", label)

    def test_headless_and_dev_open_limits_are_documented(self) -> None:
        readme = README.read_text(encoding="utf-8")
        configuration = CONFIGURATION.read_text(encoding="utf-8")

        for text in (readme, configuration):
            self.assertIn("loopback", text.lower())
            self.assertIn("headless", text.lower())
        self.assertRegex(
            configuration,
            re.compile(r"`0\.0\.0\.0`.*plaintext|plaintext.*`0\.0\.0\.0`"),
        )
