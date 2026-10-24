"""Tests for the automated iasim-qul.6 acceptance checklist."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from iasim.acceptance import (
    RESIDUAL_ITEMS,
    cli_checks,
    gui_checks,
    lan_checks,
    run_acceptance,
    server_checks,
    write_report,
)


class AcceptanceGuiTests(unittest.TestCase):
    def test_every_gui_view_renders_at_160x45(self) -> None:
        results = gui_checks()

        self.assertTrue(results)
        self.assertTrue(
            all(result.status == "PASS" for result in results),
            [(result.check_id, result.evidence) for result in results],
        )
        ids = {result.check_id for result in results}
        self.assertTrue(
            {
                "gui.base",
                "gui.help",
                "gui.agent_sheet",
                "gui.world",
                "gui.events",
                "gui.replay",
                "gui.map",
                "gui.metrics",
                "gui.settings",
                "gui.ascii",
                "gui.inspection",
                "gui.fullscreen_flag",
                "gui.keys",
            }
            <= ids
        )


class AcceptanceServerTests(unittest.TestCase):
    def test_loopback_server_checks_pass(self) -> None:
        results = server_checks()

        self.assertTrue(results)
        self.assertTrue(
            all(result.status == "PASS" for result in results),
            [(result.check_id, result.evidence) for result in results],
        )

    def test_lan_binding_checks_pass(self) -> None:
        results = lan_checks()

        self.assertTrue(results)
        self.assertTrue(
            all(result.status == "PASS" for result in results),
            [(result.check_id, result.evidence) for result in results],
        )


class AcceptanceReportTests(unittest.TestCase):
    def test_the_report_records_results_and_residual_items(self) -> None:
        results = gui_checks()
        with tempfile.TemporaryDirectory() as directory:
            path = write_report(results, Path(directory) / "acceptance.md")
            text = path.read_text(encoding="utf-8")

        self.assertIn("# Acceptance checklist", text)
        self.assertIn("**PASS**", text)
        self.assertIn("`gui.base`", text)
        for check_id, _description, _evidence in RESIDUAL_ITEMS:
            self.assertIn(check_id, text)

    def test_the_full_runner_includes_every_group(self) -> None:
        results = run_acceptance(include_cli=False)

        ids = {result.check_id for result in results}
        self.assertIn("gui.base", ids)
        self.assertIn("loopback.health", ids)
        self.assertIn("lan.warning", ids)
        self.assertNotIn("cli.startup", ids)
        self.assertTrue(
            all(result.status != "FAIL" for result in results),
            [(result.check_id, result.evidence) for result in results],
        )


class AcceptanceCliTests(unittest.TestCase):
    def test_the_real_cli_starts_and_accepts_an_agent(self) -> None:
        results = cli_checks()

        self.assertTrue(results)
        self.assertTrue(
            all(result.status == "PASS" for result in results),
            [(result.check_id, result.evidence) for result in results],
        )


if __name__ == "__main__":
    unittest.main()
