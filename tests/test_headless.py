"""Tests for the headless runner and the headless CLI path."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from iasim import cli as cli_module
from iasim.app.headless import HeadlessReport, run_headless
from iasim.app.session import GameSession
from iasim.domain.actions import Action, ActionKind
from iasim.domain.geometry import Position
from iasim.domain.tiles import TileType, WorldMap
from iasim.errors import ExitCode
from iasim.world.layout import WorldLayout


def _layout() -> WorldLayout:
    return WorldLayout(
        seed=6,
        world=WorldMap(width=6, height=6, tiles=(TileType.GRASS,) * 36),
        spawn_points=(Position(2, 2), Position(3, 2)),
    )


def _session(directory: Path | None = None) -> tuple[GameSession, str, str]:
    session = GameSession(
        6,
        layout=_layout(),
        log_dir=directory,
        snapshot_every_ticks=1000,
    )
    return (
        session,
        session.join("Nia", session.tokens[0])["agent_id"],
        session.join("Kai", session.tokens[1])["agent_id"],
    )


class HeadlessRunnerTests(unittest.TestCase):
    def test_headless_run_matches_an_equivalent_direct_run(self) -> None:
        with (
            tempfile.TemporaryDirectory() as headless_directory,
            tempfile.TemporaryDirectory() as direct_directory,
        ):
            headless_path = Path(headless_directory)
            direct_path = Path(direct_directory)
            headless_session, _, _ = _session(headless_path)
            direct_session, first, second = _session(direct_path)

            report = run_headless(headless_session, ticks=4, finish=True)
            direct_hashes = []
            for tick in range(4):
                direct_session.wait(first, tick)
                direct_session.wait(second, tick)
                direct_hashes.append(direct_session.state_hash)
            direct_session.finish()

            self.assertIsInstance(report, HeadlessReport)
            self.assertEqual(list(report.state_hashes), direct_hashes)
            self.assertEqual(report.final_hash, direct_session.final_state_hash)
            self.assertEqual(report.ticks, 4)
            self.assertEqual(report.actions_submitted, 8)
            self.assertEqual(
                (headless_path / "summary.json").read_text(encoding="utf-8"),
                (direct_path / "summary.json").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                (headless_path / "metrics.csv").read_text(encoding="utf-8"),
                (direct_path / "metrics.csv").read_text(encoding="utf-8"),
            )

    def test_a_headless_run_writes_the_same_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            session, _, _ = _session(path)

            report = run_headless(session, ticks=3, finish=True)

            names = {entry.name for entry in path.iterdir()}
            self.assertTrue(
                {
                    "session.json",
                    "events.jsonl",
                    "actions.jsonl",
                    "replay.json",
                    "summary.json",
                    "metrics.csv",
                }
                <= names
            )
            summary = json.loads((path / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["final_state_hash"], report.final_hash)
            self.assertTrue(session.is_finished)

    def test_a_custom_script_changes_the_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session, first, _ = _session(Path(directory))

            def script(tick: int, agent_id: str) -> Action:
                if agent_id == first:
                    return Action(agent_id, tick, ActionKind.MOVE, (("dx", 0), ("dy", 1)))
                return Action(agent_id, tick, ActionKind.WAIT)

            report = run_headless(session, ticks=2, script=script)

            self.assertEqual(report.actions_submitted, 4)
            self.assertEqual(len(report.state_hashes), 2)
            moved = session.state.agents[0]
            self.assertEqual((moved.position.x, moved.position.y), (2, 4))

    def test_invalid_input_fails_loudly(self) -> None:
        session, first, second = _session()

        with self.assertRaises(ValueError):
            run_headless(session, ticks=0)

        stale = Action(first, 5, ActionKind.WAIT)

        with self.assertRaises(RuntimeError):
            run_headless(session, ticks=2, script=lambda tick, agent: stale)

        empty = GameSession(6, layout=_layout())
        with self.assertRaises(RuntimeError):
            run_headless(empty, ticks=1)
        self.assertIsNotNone(second)


class HeadlessCliTests(unittest.TestCase):
    def test_headless_serve_starts_the_simulation_without_a_window(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch("iasim.cli.run_server") as run_server:
                code = cli_module.main(
                    [
                        "serve",
                        "--headless",
                        "--seed",
                        "7",
                        "--log-dir",
                        directory,
                    ]
                )

            self.assertEqual(code, int(ExitCode.SUCCESS))
            run_server.assert_called_once()
            session = run_server.call_args.args[0]
            self.assertIsInstance(session, GameSession)
            self.assertFalse(session.is_finished)

    def test_gui_mode_still_requires_the_window(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            patch("iasim.cli.run_server") as run_server,
        ):
            code = cli_module.main(["serve", "--seed", "7", "--log-dir", directory])

        self.assertEqual(code, int(ExitCode.CONFIGURATION))
        run_server.assert_not_called()

    def test_headless_load_uses_the_saved_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            session = GameSession(7, max_agents=2, log_dir=path)
            first = session.join("Nia", session.tokens[0])["agent_id"]
            session.wait(first, 0)
            saved = session.save()

            with patch("iasim.cli.run_server") as run_server:
                code = cli_module.main(
                    [
                        "serve",
                        "--headless",
                        "--load",
                        str(saved),
                        "--log-dir",
                        str(path / "resumed"),
                    ]
                )

            self.assertEqual(code, int(ExitCode.SUCCESS))
            loaded = run_server.call_args.args[0]
            self.assertEqual(loaded.state.tick, session.state.tick)

    def test_a_missing_load_file_returns_the_persistence_exit_code(self) -> None:
        code = cli_module.main(["serve", "--headless", "--load", "missing.json"])

        self.assertEqual(code, int(ExitCode.PERSISTENCE))


if __name__ == "__main__":
    unittest.main()
