"""Tests for the summary.json and metrics.csv exports."""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from iasim.app.session import GameSession
from iasim.domain.geometry import Position
from iasim.domain.tiles import TileType, WorldMap
from iasim.persistence.export import (
    COMPONENT_COLUMNS,
    CSV_COLUMNS,
    DOCUMENTED_METRICS,
    METRIC_COLUMNS,
    write_metrics_csv,
    write_summary,
)
from iasim.world.layout import WorldLayout

SRS_METRICS = {
    "survival_ticks",
    "days_survived",
    "cause_of_death",
    "killed_by",
    "avg_hunger",
    "avg_thirst",
    "avg_energy",
    "critical_need_ratio",
    "exploration_pct",
    "distance_traveled",
    "resources_gathered",
    "items_crafted",
    "structures_built",
    "actions_total",
    "actions_failed",
    "invalid_action_rate",
    "timeouts",
    "messages_sent",
    "trades_offered",
    "trades_completed",
    "alliances_formed",
    "betrayals",
    "attacks_made",
    "damage_dealt",
    "damage_taken",
    "kills",
    "mind_reports",
    "mind_report_rate",
    "decision_latency_p50_ms",
    "decision_latency_p95_ms",
    "final_state_hash",
}


def _layout() -> WorldLayout:
    return WorldLayout(
        seed=4,
        world=WorldMap(width=6, height=6, tiles=(TileType.GRASS,) * 36),
        spawn_points=(Position(2, 2), Position(3, 2)),
    )


def _session(directory: Path) -> tuple[GameSession, str, str]:
    session = GameSession(4, layout=_layout(), log_dir=directory)
    return (
        session,
        session.join("Nia", session.tokens[0])["agent_id"],
        session.join("Kai", session.tokens[1])["agent_id"],
    )


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


class ExportTests(unittest.TestCase):
    def test_summary_and_csv_agree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            session, first, second = _session(path)
            session.observe(first)
            session.say(first, "Hola")
            session.report_mind(first, 0, intent="Seguir", thought="Vivo")
            session.move(first, 0, 1, 0)
            session.wait(second, 0)
            session.finish()

            summary = json.loads((path / "summary.json").read_text(encoding="utf-8"))
            rows = _csv_rows(path / "metrics.csv")

            self.assertEqual(rows[0]["scope"], "session")
            self.assertEqual(
                [(row["scope"], row["agent_id"]) for row in rows[1:]],
                [("agent", first), ("agent", second)],
            )
            self.assertEqual(rows[0]["name"], "")
            self.assertEqual(rows[1]["name"], "Nia")
            for column in METRIC_COLUMNS:
                with self.subTest(column=column):
                    self._assert_cell_matches(
                        rows[0][column],
                        summary["session"].get(column),
                    )
            for row in rows[1:]:
                agent = summary["agents"][row["agent_id"]]
                for column in METRIC_COLUMNS:
                    with self.subTest(agent=row["agent_id"], column=column):
                        self._assert_cell_matches(row[column], agent.get(column))
            self.assertEqual(
                rows[0]["final_state_hash"],
                summary["final_state_hash"],
            )

    def test_empty_values_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            session, _, _ = _session(path)
            session.finish()

            summary = json.loads((path / "summary.json").read_text(encoding="utf-8"))
            rows = _csv_rows(path / "metrics.csv")

            self.assertIsNone(summary["session"]["cause_of_death"])
            self.assertEqual(rows[0]["cause_of_death"], "")
            self.assertIsNone(summary["session"]["decision_latency_p50_ms"])
            self.assertEqual(rows[0]["decision_latency_p50_ms"], "")

    def test_the_csv_layout_is_stable_and_documented(self) -> None:
        self.assertEqual(CSV_COLUMNS[:3], ("scope", "agent_id", "name"))
        self.assertEqual(CSV_COLUMNS[3:], METRIC_COLUMNS)
        self.assertTrue(set(DOCUMENTED_METRICS) >= SRS_METRICS)
        self.assertEqual(
            METRIC_COLUMNS,
            (*DOCUMENTED_METRICS, *COMPONENT_COLUMNS),
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            session, _, _ = _session(path)
            session.finish()
            header = (path / "metrics.csv").read_text(encoding="utf-8").splitlines()[0]
            self.assertEqual(header.split(","), list(CSV_COLUMNS))

    def test_identical_sessions_produce_identical_artifacts(self) -> None:
        with (
            tempfile.TemporaryDirectory() as first_directory,
            tempfile.TemporaryDirectory() as second_directory,
        ):
            first_path = Path(first_directory)
            second_path = Path(second_directory)
            first_session, first, second = _session(first_path)
            second_session, other_first, other_second = _session(second_path)
            for session, actor, partner in (
                (first_session, first, second),
                (second_session, other_first, other_second),
            ):
                session.wait(actor, 0)
                session.wait(partner, 0)
                session.finish()

            self.assertEqual(
                (first_path / "summary.json").read_text(encoding="utf-8"),
                (second_path / "summary.json").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                (first_path / "metrics.csv").read_text(encoding="utf-8"),
                (second_path / "metrics.csv").read_text(encoding="utf-8"),
            )

    def test_writers_accept_a_snapshot_directly(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            session, first, _ = _session(path)
            session.wait(first, 0)
            snapshot = session.metrics_snapshot()

            summary_path = write_summary(path, snapshot)
            csv_path = write_metrics_csv(path, snapshot)

            self.assertEqual(
                json.loads(summary_path.read_text(encoding="utf-8"))["schema_version"],
                "1.0",
            )
            self.assertEqual(
                len(_csv_rows(csv_path)),
                len(snapshot["agents"]) + 1,
            )

    def test_no_export_without_a_run_directory(self) -> None:
        session = GameSession(4, layout=_layout())
        first = session.join("Nia", session.tokens[0])["agent_id"]
        session.wait(first, 0)

        summary = session.finish()

        self.assertIn("state_hash", summary)

    def _assert_cell_matches(self, cell: str, value: object) -> None:
        if value is None:
            self.assertEqual(cell, "")
        elif isinstance(value, dict):
            self.assertEqual(json.loads(cell), value)
        elif isinstance(value, bool):
            self.assertEqual(cell, "true" if value else "false")
        elif isinstance(value, float):
            self.assertEqual(float(cell), value)
        else:
            self.assertEqual(cell, str(value))


if __name__ == "__main__":
    unittest.main()
