"""Tests for the F7 metrics and session summary view."""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from iasim.app.session import GameSession
from iasim.ui.controls import UiState, UiView, handle_key
from iasim.ui.layout import render_metrics_screen


def _session(
    directory: Path,
    *,
    finish: bool = True,
    report_mind: bool = True,
) -> tuple[GameSession, str, str]:
    session = GameSession(
        seed=7,
        max_agents=2,
        log_dir=directory,
        token_path=directory / "agents.json",
    )
    first = session.join("Nia", session.tokens[0])["agent_id"]
    second = session.join("Kai", session.tokens[1])["agent_id"]
    if report_mind:
        session.report_mind(
            first,
            0,
            intent="Buscar agua",
            thought="Tengo sed",
            plan="Ir al río",
        )
    session.move(first, 0, 0, 1)
    session.wait(second, 0)
    session.wait(first, 1)
    session.wait(second, 1)
    if finish:
        session.finish()
    return session, first, second


class MetricsScreenTests(unittest.TestCase):
    def test_the_view_renders_the_same_values_as_the_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            session, first, second = _session(path)
            snapshot = session.metrics_snapshot()

            screen = render_metrics_screen(snapshot, final=True)
            text = screen.to_text()

            self.assertEqual((screen.width, screen.height), (160, 45))
            self.assertTrue(all(len(screen.row_text(y)) == 160 for y in range(45)))
            summary = json.loads((path / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["session"], snapshot["session"])
            with (path / "metrics.csv").open(encoding="utf-8", newline="") as handle:
                csv_rows = list(csv.DictReader(handle))
                rows = {row["scope"]: row for row in csv_rows}

            session_row = screen.row_text(4)
            for column in (
                "survival_ticks",
                "days_survived",
                "critical_need_ratio",
                "exploration_pct",
                "distance_traveled",
                "actions_total",
                "actions_failed",
                "messages_sent",
                "alliances_formed",
                "attacks_made",
                "kills",
                "mind_reports",
                "decision_latency_p50_ms",
            ):
                expected = rows["session"][column]
                self.assertIn(
                    expected if expected else "—",
                    session_row,
                    f"session column {column}",
                )

            agent_rows = [screen.row_text(y) for y in range(5, 7)]
            for agent_id, name in ((first, "Nia"), (second, "Kai")):
                csv_row = next(row for row in csv_rows if row["agent_id"] == agent_id)
                row = next(
                    candidate for candidate in agent_rows if candidate.strip().startswith(name)
                )
                self.assertIn(csv_row["actions_total"], row)
                self.assertIn(csv_row["survival_ticks"], row)

            for expected in (
                "F7 · MÉTRICAS",
                "RESUMEN FINAL",
                "hash ",
                "AGENTE",
                "SUP",
                "ACC",
                "P50",
                "SESIÓN",
                "Nia",
                "Kai",
                "Causa:",
                "Componentes:",
                "Recursos:",
                "[F7] Cerrar métricas",
            ):
                self.assertIn(expected, text)

    def test_missing_values_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            session, _, _ = _session(path, finish=False, report_mind=False)
            snapshot = session.metrics_snapshot()

            screen = render_metrics_screen(snapshot, final=False)
            text = screen.to_text()

            self.assertIn("SESIÓN EN CURSO", text)
            self.assertIn("— = sin dato", text)
            self.assertIn("Causa: —", text)
            self.assertIn("Autor: —", text)
            self.assertIn("P50/P95: —/—", text)
            self.assertIn("—", screen.row_text(4))

    def test_the_view_can_compare_the_current_state_with_the_start(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            session, _, _ = _session(path, finish=False)
            snapshot = session.metrics_snapshot()

            screen = render_metrics_screen(
                snapshot,
                initial={
                    "survival_ticks": 0,
                    "actions_total": 0,
                    "exploration_pct": 0.0,
                },
            )
            text = screen.to_text()
            current = snapshot["session"]

            self.assertIn(
                "Inicio: supervivencia 0 · acciones 0 · exploración 0.0",
                text,
            )
            self.assertIn(
                f"Δ: supervivencia +{current['survival_ticks']}",
                text,
            )
            self.assertIn(
                f"acciones +{current['actions_total']}",
                text,
            )

    def test_ascii_mode_keeps_the_footer_safe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            session, _, _ = _session(path, finish=False)
            snapshot = session.metrics_snapshot()

            screen = render_metrics_screen(snapshot, ascii_mode=True)

            self.assertIn("[F7] Cerrar métricas", screen.to_text())
            self.assertTrue(all(len(screen.row_text(y)) == 160 for y in range(45)))


class MetricsControlTests(unittest.TestCase):
    def test_f7_toggles_the_metrics_view(self) -> None:
        state = handle_key(UiState(), "f7", ())

        self.assertEqual(state.view, UiView.METRICS)
        self.assertEqual(handle_key(state, "f7", ()).view, UiView.NONE)
        self.assertEqual(handle_key(state, "esc", ()).view, UiView.NONE)


if __name__ == "__main__":
    unittest.main()
