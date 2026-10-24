"""Tests for deterministic replay from seed and snapshots."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from iasim.app.replay import replay_saved_run
from iasim.app.session import GameSession
from iasim.persistence.replay import ReplayError, read_replay


def _session(
    directory: Path,
    *,
    seed: int = 5,
    snapshot_every_ticks: int = 1000,
    turn_timeout_ms: int = 60_000,
    wall_clock=None,
) -> tuple[GameSession, str, str]:
    kwargs = {}
    if wall_clock is not None:
        kwargs["wall_clock"] = wall_clock
    session = GameSession(
        seed,
        max_agents=2,
        log_dir=directory,
        snapshot_every_ticks=snapshot_every_ticks,
        turn_timeout_ms=turn_timeout_ms,
        token_path=directory / "agents.json",
        **kwargs,
    )
    return (
        session,
        session.join("Nia", session.tokens[0])["agent_id"],
        session.join("Kai", session.tokens[1])["agent_id"],
    )


class ReplayTests(unittest.TestCase):
    def test_full_replay_matches_every_recorded_tick(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            session, first, second = _session(path)
            session.move(first, 0, 0, 1)
            session.wait(second, 0)
            session.wait(first, 1)
            session.wait(second, 1)
            summary = session.finish()

            report = replay_saved_run(path / "replay.json")

            self.assertTrue(report.matched, report.detail)
            self.assertEqual(report.ticks_replayed, 2)
            self.assertEqual(report.actions_replayed, 4)
            self.assertEqual(report.action_offset, 0)
            self.assertEqual(report.start_tick, 0)
            self.assertEqual(report.final_hash, summary["state_hash"])

    def test_replay_from_a_snapshot_skips_earlier_ticks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            session, first, second = _session(path, snapshot_every_ticks=1)
            for tick in range(3):
                session.wait(first, tick)
                session.wait(second, tick)
            summary = session.finish()
            snapshot = path / "snapshots" / "tick_000002.json"

            full = replay_saved_run(path / "replay.json")
            partial = replay_saved_run(
                path / "replay.json",
                from_snapshot=snapshot,
            )

            self.assertTrue(full.matched, full.detail)
            self.assertTrue(partial.matched, partial.detail)
            self.assertEqual(partial.start_tick, 2)
            self.assertEqual(partial.ticks_replayed, 1)
            self.assertEqual(partial.actions_replayed, 2)
            self.assertEqual(partial.action_offset, 4)
            self.assertEqual(full.action_offset, 0)
            self.assertEqual(partial.final_hash, summary["state_hash"])
            self.assertEqual(partial.final_hash, full.final_hash)

    def test_a_changed_action_reports_the_first_divergent_tick(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            session, first, second = _session(path)
            session.move(first, 0, 0, 1)
            session.wait(second, 0)
            session.wait(first, 1)
            session.wait(second, 1)
            session.finish()
            replay_path = path / "replay.json"
            data = json.loads(replay_path.read_text(encoding="utf-8"))
            moved = next(
                action for action in data["turns"][0]["actions"] if action["kind"] == "move"
            )
            moved["payload"] = [["dx", 0], ["dy", -1]]
            replay_path.write_text(json.dumps(data), encoding="utf-8")

            report = replay_saved_run(replay_path)

            self.assertFalse(report.matched)
            self.assertEqual(report.first_divergence_tick, 1)
            self.assertIsNotNone(report.expected_hash)
            self.assertIsNotNone(report.actual_hash)
            self.assertIn("diverged", report.detail)

    def test_a_deadline_turn_is_replayed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            clock = [0.0]
            session, first, _ = _session(
                path,
                turn_timeout_ms=1_000,
                wall_clock=lambda: clock[0],
            )
            for tick in range(2):
                session.wait(first, tick)
                clock[0] += 2.0
                session.observe(first)
            summary = session.finish()

            report = replay_saved_run(path / "replay.json")

            self.assertTrue(report.matched, report.detail)
            self.assertEqual(report.ticks_replayed, 2)
            self.assertEqual(report.final_hash, summary["state_hash"])


class ReplayRecordTests(unittest.TestCase):
    def test_the_record_is_written_and_readable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            session, first, second = _session(path)
            session.wait(first, 0)
            session.wait(second, 0)
            session.finish()

            record = read_replay(path / "replay.json")

            self.assertEqual(record.seed, 5)
            self.assertEqual(record.max_agents, 2)
            self.assertEqual(record.start_tick, 0)
            self.assertEqual(len(record.turns), 1)
            self.assertEqual(len(record.turns[0].actions), 2)
            self.assertEqual([agent[0] for agent in record.agents], ["ag_01", "ag_02"])

    def test_an_incompatible_version_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            session, first, _ = _session(path)
            session.wait(first, 0)
            session.finish()
            replay_path = path / "replay.json"
            data = json.loads(replay_path.read_text(encoding="utf-8"))
            data["schema_version"] = "9.9"
            replay_path.write_text(json.dumps(data), encoding="utf-8")

            with self.assertRaises(ReplayError):
                read_replay(replay_path)

    def test_a_missing_record_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ReplayError):
            read_replay(Path(directory) / "missing.json")

    def test_a_continuation_record_requires_its_start_snapshot(self) -> None:
        with (
            tempfile.TemporaryDirectory() as source_directory,
            tempfile.TemporaryDirectory() as resumed_directory,
        ):
            source_path = Path(source_directory)
            session, first, second = _session(source_path)
            session.wait(first, 0)
            session.wait(second, 0)
            save_path = session.save()

            loaded = GameSession.load(
                save_path,
                token_path=source_path / "agents.json",
                log_dir=Path(resumed_directory),
            )
            loaded_first = loaded.agent_id_for_token(session.tokens[0])
            loaded_second = loaded.agent_id_for_token(session.tokens[1])
            assert loaded_first is not None and loaded_second is not None
            loaded.wait(loaded_first, 1)
            loaded.wait(loaded_second, 1)
            summary = loaded.finish()
            replay_path = Path(resumed_directory) / "replay.json"
            record = read_replay(replay_path)
            self.assertEqual(record.start_tick, 1)

            with self.assertRaises(ReplayError):
                replay_saved_run(replay_path)

            report = replay_saved_run(replay_path, from_snapshot=save_path)

            self.assertTrue(report.matched, report.detail)
            self.assertEqual(report.start_tick, 1)
            self.assertEqual(report.ticks_replayed, 1)
            self.assertEqual(report.final_hash, summary["state_hash"])


if __name__ == "__main__":
    unittest.main()
