"""Tests for the three-day two-agent MVP scenario."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from iasim.scenario import (
    SCENARIO_TICKS,
    ScenarioReport,
    run_three_day_scenario,
    write_scenario_report,
)

GOLDEN_FINAL_HASH = "8256d8aab6bf1a801124c80e2b01971ff84955473f32ad06fef32ff997a09855"


class ThreeDayScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._directory = tempfile.TemporaryDirectory()
        cls.report = run_three_day_scenario(Path(cls._directory.name))

    @classmethod
    def tearDownClass(cls) -> None:
        cls._directory.cleanup()

    def test_the_scenario_reaches_a_valid_end_state(self) -> None:
        report = self.report

        self.assertIsInstance(report, ScenarioReport)
        self.assertEqual(report.ticks, SCENARIO_TICKS)
        self.assertEqual(report.days, 3)
        self.assertEqual(report.survivor, "ag_01")
        self.assertEqual(report.casualty, "ag_02")
        self.assertIsNotNone(report.death_tick)
        assert report.death_tick is not None
        self.assertGreater(report.death_tick, 2 * 288)
        self.assertEqual(report.death_cause, "attack")
        self.assertEqual(report.killer, "ag_01")
        self.assertTrue(report.alliance_formed)
        self.assertTrue(report.looted)
        self.assertGreaterEqual(report.messages, 1)
        self.assertGreater(report.mind_reports, 0)

    def test_metrics_and_artifacts_are_recorded(self) -> None:
        report = self.report
        session = report.metrics["session"]
        casualty = report.metrics["casualty"]

        self.assertEqual(session["kills"], 1)
        self.assertEqual(session["alliances_formed"], 1)
        self.assertGreaterEqual(session["attacks_made"], 1)
        self.assertGreaterEqual(casualty["survival_ticks"], 1)
        self.assertEqual(casualty["cause_of_death"], "attack")
        self.assertEqual(casualty["killed_by"], "ag_01")
        required = {
            "session.json",
            "agents.json",
            "events.jsonl",
            "actions.jsonl",
            "thoughts.jsonl",
            "replay.json",
            "summary.json",
            "metrics.csv",
            "initial_snapshot.json",
        }
        self.assertTrue(required <= set(report.artifacts))

    def test_replay_matches_every_recorded_tick_and_the_final_hash(self) -> None:
        report = self.report

        self.assertTrue(report.replay_matched)
        self.assertEqual(report.final_hash, GOLDEN_FINAL_HASH)

    def test_the_report_records_the_outcome_and_replay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = write_scenario_report(
                self.report,
                Path(directory) / "scenario.md",
            )
            text = path.read_text(encoding="utf-8")

        self.assertIn("# Three-day two-agent scenario", text)
        self.assertIn("Replay: MATCH", text)
        self.assertIn("Survivor: `ag_01`", text)
        self.assertIn("Casualty: `ag_02` at tick", text)
        self.assertIn(GOLDEN_FINAL_HASH, text)


if __name__ == "__main__":
    unittest.main()
