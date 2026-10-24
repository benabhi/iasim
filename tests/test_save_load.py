"""Tests for atomic session save and load."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from iasim.app.session import GameSession
from iasim.domain.agents import AgentProfile
from iasim.domain.geometry import Position
from iasim.domain.tiles import TileType, WorldMap
from iasim.errors import PersistenceError
from iasim.persistence.state import SnapshotError
from iasim.world.layout import WorldLayout


def _layout() -> WorldLayout:
    return WorldLayout(
        seed=3,
        world=WorldMap(width=6, height=6, tiles=(TileType.GRASS,) * 36),
        spawn_points=(Position(2, 2), Position(3, 2)),
    )


def _session(
    directory: Path,
    *,
    token_file: bool = True,
    profiles: tuple[AgentProfile, AgentProfile] | None = None,
) -> tuple[GameSession, str, str]:
    session = GameSession(
        3,
        layout=_layout(),
        profiles=profiles,
        log_dir=directory,
        snapshot_every_ticks=1000,
        token_path=(directory / "agents.json") if token_file else None,
    )
    return (
        session,
        session.join("Nia", session.tokens[0])["agent_id"],
        session.join("Kai", session.tokens[1])["agent_id"],
    )


def _records(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


class SaveLoadTests(unittest.TestCase):
    def test_save_and_load_restore_the_same_state_hash(self) -> None:
        with (
            tempfile.TemporaryDirectory() as source_directory,
            tempfile.TemporaryDirectory() as target_directory,
        ):
            source_path = Path(source_directory)
            session, first, second = _session(source_path)
            for tick in range(2):
                session.wait(first, tick)
                session.wait(second, tick)
            saved_hash = session.state_hash

            path = session.save()
            loaded = GameSession.load(
                path,
                token_path=source_path / "agents.json",
                log_dir=Path(target_directory),
            )

            self.assertEqual(loaded.state_hash, saved_hash)
            self.assertEqual(loaded.agent_id_for_token(session.tokens[0]), first)
            self.assertEqual(loaded.observe(first)["agent"]["id"], first)
            summary = loaded.finish()
            self.assertEqual(
                [agent["name"] for agent in summary["agents"]],
                ["Nia", "Kai"],
            )

    def test_a_loaded_session_resumes_like_an_uninterrupted_run(self) -> None:
        with (
            tempfile.TemporaryDirectory() as source_directory,
            tempfile.TemporaryDirectory() as resumed_directory,
            tempfile.TemporaryDirectory() as control_directory,
        ):
            source_path = Path(source_directory)
            source, first, second = _session(source_path)
            control, control_first, control_second = _session(Path(control_directory))

            for tick in range(2):
                source.wait(first, tick)
                source.wait(second, tick)
                control.wait(control_first, tick)
                control.wait(control_second, tick)
            path = source.save()
            resumed = GameSession.load(
                path,
                token_path=source_path / "agents.json",
                log_dir=Path(resumed_directory),
            )
            resumed_first = resumed.agent_id_for_token(source.tokens[0])
            resumed_second = resumed.agent_id_for_token(source.tokens[1])
            assert resumed_first is not None and resumed_second is not None

            for tick in range(2, 4):
                control.wait(control_first, tick)
                control.wait(control_second, tick)
                resumed.wait(resumed_first, tick)
                resumed.wait(resumed_second, tick)
                with self.subTest(tick=tick + 1):
                    self.assertEqual(resumed.state_hash, control.state_hash)

    def test_a_mid_turn_save_preserves_the_pending_queue(self) -> None:
        with (
            tempfile.TemporaryDirectory() as source_directory,
            tempfile.TemporaryDirectory() as resumed_directory,
        ):
            source_path = Path(source_directory)
            source, first, second = _session(source_path)
            self.assertTrue(source.move(first, 0, 0, 1)["ok"])
            path = source.save()

            resumed = GameSession.load(
                path,
                token_path=source_path / "agents.json",
                log_dir=Path(resumed_directory),
            )
            resumed_first = resumed.agent_id_for_token(source.tokens[0])
            resumed_second = resumed.agent_id_for_token(source.tokens[1])
            assert resumed_first is not None and resumed_second is not None

            self.assertTrue(source.wait(second, 0)["ok"])
            self.assertTrue(resumed.wait(resumed_second, 0)["ok"])

            self.assertEqual(resumed.state_hash, source.state_hash)
            actions = _records(Path(resumed_directory) / "actions.jsonl")
            moves = [
                record
                for record in actions
                if record["action"] == "move" and record["agent_id"] == resumed_first
            ]
            self.assertEqual(len(moves), 1)
            self.assertEqual(moves[0]["arguments"], {"dx": 0, "dy": 1})

    def test_save_records_the_last_save_in_the_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            session, first, _ = _session(path)

            session.wait(first, 0)
            session.save()

            metadata = json.loads((path / "session.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["last_saved_file"], "tick_000000.json")
            self.assertEqual(metadata["last_saved_tick"], 0)

    def test_save_is_atomic_when_the_replace_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            session, _, _ = _session(path)
            target = path / "manual.json"

            with (
                patch(
                    "iasim.persistence.state.Path.replace",
                    side_effect=OSError("disk full"),
                ),
                self.assertRaises(SnapshotError),
            ):
                session.save(target)

            self.assertFalse(target.exists())
            self.assertEqual(list(path.glob("*.tmp")), [])

    def test_an_incompatible_save_version_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            session, _, _ = _session(path)
            save_path = session.save()
            data = json.loads(save_path.read_text(encoding="utf-8"))
            data["schema_version"] = "9.9"
            save_path.write_text(json.dumps(data), encoding="utf-8")

            with self.assertRaises(SnapshotError):
                GameSession.load(save_path)

    def test_loading_a_missing_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(SnapshotError):
            GameSession.load(Path(directory) / "missing.json")

    def test_a_finished_session_stays_finished_after_loading(self) -> None:
        with (
            tempfile.TemporaryDirectory() as source_directory,
            tempfile.TemporaryDirectory() as target_directory,
        ):
            source_path = Path(source_directory)
            session, _, _ = _session(source_path)
            summary = session.finish()
            path = session.save()

            loaded = GameSession.load(
                path,
                token_path=source_path / "agents.json",
                log_dir=Path(target_directory),
            )

            self.assertTrue(loaded.is_finished)
            self.assertEqual(loaded.final_state_hash, summary["state_hash"])


class SaveContentTests(unittest.TestCase):
    def test_a_save_contains_the_session_names_and_queue(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            session, first, second = _session(path)
            session.move(first, 0, 1, 0)

            save_path = session.save()
            data = json.loads(save_path.read_text(encoding="utf-8"))

            self.assertEqual(data["session"]["max_agents"], 2)
            self.assertEqual(
                data["session"]["names"],
                {first: "Nia", second: "Kai"},
            )
            self.assertEqual(len(data["session"]["pending_actions"]), 1)
            self.assertEqual(
                data["session"]["pending_actions"][0]["agent_id"],
                first,
            )

    def test_saving_without_a_location_requires_a_path(self) -> None:
        session = GameSession(3, layout=_layout())
        first = session.join("Nia", session.tokens[0])["agent_id"]
        session.wait(first, 0)

        with self.assertRaises(PersistenceError) as raised:
            session.save()

        self.assertIn("pass an explicit path", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
