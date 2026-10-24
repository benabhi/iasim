"""Tests for session directories and JSONL session logs."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path

from iasim.app.session import GameSession
from iasim.domain.agents import AgentAttributes, AgentProfile
from iasim.domain.alliances import alliance_id_for
from iasim.domain.geometry import Position
from iasim.domain.identifiers import AgentId
from iasim.domain.tiles import TileType, WorldMap
from iasim.persistence.logs import SessionLogs
from iasim.world.layout import WorldLayout

TIMEOUT_MS = 1000


def _layout() -> WorldLayout:
    return WorldLayout(
        seed=1,
        world=WorldMap(width=6, height=6, tiles=(TileType.GRASS,) * 36),
        spawn_points=(Position(2, 2), Position(3, 2)),
    )


def _session(
    directory: Path | None = None,
    *,
    profiles: tuple[AgentProfile, AgentProfile] | None = None,
    timeout_disconnects: int = 3,
    turn_timeout_ms: int = 60_000,
    wall_clock=None,
) -> tuple[GameSession, str, str]:
    kwargs = {}
    if wall_clock is not None:
        kwargs["wall_clock"] = wall_clock
    session = GameSession(
        1,
        layout=_layout(),
        profiles=profiles,
        log_dir=directory,
        turn_timeout_ms=turn_timeout_ms,
        timeout_disconnects=timeout_disconnects,
        **kwargs,
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


class SessionMetadataTests(unittest.TestCase):
    def test_session_metadata_is_written_without_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            session, first, _ = _session(path)

            metadata = json.loads((path / "session.json").read_text(encoding="utf-8"))
            text = (path / "session.json").read_text(encoding="utf-8")

            self.assertEqual(metadata["schema_version"], "1.0")
            self.assertEqual(metadata["protocol_version"], "iasim-mcp/1.0")
            self.assertEqual(metadata["seed"], 1)
            self.assertEqual(metadata["max_agents"], 2)
            self.assertFalse(metadata["finished"])
            self.assertEqual(
                [agent["id"] for agent in metadata["agents"]],
                [first, "ag_02"],
            )
            self.assertNotIn(session.tokens[0], text)
            self.assertNotIn(session.tokens[1], text)

    def test_finish_updates_metadata_and_logs_the_end(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            session, _, _ = _session(path)

            session.finish()

            metadata = json.loads((path / "session.json").read_text(encoding="utf-8"))
            events = _records(path / "events.jsonl")
            self.assertTrue(metadata["finished"])
            self.assertEqual(metadata["end_reason"], "operator")
            self.assertEqual(metadata["final_state_hash"], session.final_state_hash)
            self.assertIn("session_end", [record["event"] for record in events])


class ConnectionEventTests(unittest.TestCase):
    def test_join_and_leave_are_logged_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            session, first, _ = _session(path)

            session.leave(first)

            events = _records(path / "events.jsonl")
            joins = [record for record in events if record["event"] == "join"]
            disconnects = [record for record in events if record["event"] == "disconnect"]
            self.assertEqual([record["agent_id"] for record in joins], ["ag_01", "ag_02"])
            self.assertEqual(len(disconnects), 1)
            self.assertEqual(disconnects[0]["agent_id"], first)
            self.assertEqual(disconnects[0]["cause"], "leave")

    def test_waiting_and_running_transitions_are_logged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            session, first, second = _session(path)

            session.leave(first)
            session.leave(second)

            events = _records(path / "events.jsonl")
            kinds = [record["event"] for record in events]
            waiting = [record for record in events if record["event"] == "waiting"]
            self.assertEqual(kinds.count("running"), 1)
            self.assertEqual(len(waiting), 1)
            self.assertEqual(waiting[0]["reason"], "no_agents")


class ActionLogTests(unittest.TestCase):
    def test_resolved_actions_are_logged_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            session, first, second = _session(path)

            session.wait(first, 0)
            session.wait(second, 0)

            actions = _records(path / "actions.jsonl")
            self.assertEqual(len(actions), 2)
            self.assertEqual({record["agent_id"] for record in actions}, {first, second})
            self.assertTrue(all(record["status"] == "success" for record in actions))
            self.assertTrue(all(record["outcome"] == "waited" for record in actions))
            self.assertEqual(actions[0]["tick"], 0)

    def test_action_arguments_are_logged_for_replay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            session, first, second = _session(path)

            session.move(first, 0, 0, 1)
            session.wait(second, 0)

            actions = _records(path / "actions.jsonl")
            move = next(record for record in actions if record["action"] == "move")
            self.assertEqual(move["arguments"], {"dx": 0, "dy": 1})
            self.assertIsNone(move["request_id"])
            self.assertEqual(move["outcome"], "moved")

    def test_queue_rejections_are_logged_with_the_error_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            session, first, second = _session(path)

            session.wait(first, 0)
            session.wait(second, 0)
            session.wait(first, 0)
            session.wait(first, 1)
            session.wait(first, 1)

            actions = _records(path / "actions.jsonl")
            rejected = [record for record in actions if record["status"] == "rejected"]
            self.assertEqual(
                [record["error"] for record in rejected], ["STALE_TICK", "ALREADY_ACTED"]
            )
            self.assertTrue(all(record["agent_id"] == first for record in rejected))

    def test_social_events_reach_the_event_log(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            session, first, second = _session(path)
            alliance_id = alliance_id_for(AgentId(first), AgentId(second))

            session.say(first, "Hola")
            session.offer_alliance(first, 0, second)
            session.wait(second, 0)
            session.accept_alliance(second, 1, alliance_id)
            session.wait(first, 1)

            kinds = [record["event"] for record in _records(path / "events.jsonl")]
            self.assertIn("message", kinds)
            self.assertIn("alliance_offered", kinds)
            self.assertIn("alliance_formed", kinds)


class SimulationEventTests(unittest.TestCase):
    def test_deaths_are_logged_with_cause_and_killer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            profiles = (
                AgentProfile(),
                AgentProfile(attributes=AgentAttributes(health_centi=100)),
            )
            session, first, second = _session(path, profiles=profiles)

            session.attack(first, 0, second)
            session.wait(second, 0)

            deaths = [
                record for record in _records(path / "events.jsonl") if record["event"] == "death"
            ]
            self.assertEqual(len(deaths), 1)
            self.assertEqual(deaths[0]["agent_id"], second)
            self.assertEqual(deaths[0]["cause"], "attack")
            self.assertEqual(deaths[0]["killer_id"], first)

    def test_timeouts_and_absence_are_logged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            clock = [0.0]
            session, first, second = _session(
                path,
                timeout_disconnects=3,
                turn_timeout_ms=TIMEOUT_MS,
                wall_clock=lambda: clock[0],
            )

            for tick in range(3):
                session.wait(first, tick)
                clock[0] += TIMEOUT_MS / 1000.0
                session.observe(first)

            events = _records(path / "events.jsonl")
            timeouts = [
                record
                for record in events
                if record["event"] == "timeout" and record["agent_id"] == second
            ]
            absent = [
                record
                for record in events
                if record["event"] == "absent" and record["agent_id"] == second
            ]
            self.assertEqual([record["consecutive"] for record in timeouts], [1, 2, 3])
            self.assertEqual(len(absent), 1)


class LogSafetyTests(unittest.TestCase):
    def test_no_token_appears_in_any_log_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            session, first, second = _session(path)

            session.wait(first, 0)
            session.wait(second, 0)
            session.report_mind(first, 1, intent="Beber", thought="Sed")
            session.leave(second)

            for filename in (
                "session.json",
                "events.jsonl",
                "actions.jsonl",
                "thoughts.jsonl",
            ):
                text = (path / filename).read_text(encoding="utf-8")
                with self.subTest(file=filename):
                    for token in session.tokens:
                        self.assertNotIn(token, text)

    def test_concurrent_appends_stay_well_formed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            logs = SessionLogs(path)

            def writer(worker: int) -> None:
                for index in range(25):
                    logs.event(
                        kind="probe",
                        tick=0,
                        agent_id=f"ag_{worker:02d}",
                        index=index,
                    )

            threads = [threading.Thread(target=writer, args=(worker,)) for worker in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            records = _records(path / "events.jsonl")
            self.assertEqual(len(records), 200)
            self.assertTrue(all(record["event"] == "probe" for record in records))
            self.assertTrue(all(record["schema_version"] == "1.0" for record in records))

    def test_the_same_session_sequence_produces_the_same_logs(self) -> None:
        with (
            tempfile.TemporaryDirectory() as first_directory,
            tempfile.TemporaryDirectory() as second_directory,
        ):
            first_path = Path(first_directory)
            second_path = Path(second_directory)
            first_session, first, second = _session(first_path)
            other_session, other_first, other_second = _session(second_path)

            for session, actor, partner in (
                (first_session, first, second),
                (other_session, other_first, other_second),
            ):
                session.say(actor, "Hola")
                session.wait(actor, 0)
                session.wait(partner, 0)
                session.report_mind(actor, 1, intent="Vivir", thought="Sigo aquí")

            for filename in ("events.jsonl", "actions.jsonl", "thoughts.jsonl"):
                with self.subTest(file=filename):
                    self.assertEqual(
                        (first_path / filename).read_text(encoding="utf-8"),
                        (second_path / filename).read_text(encoding="utf-8"),
                    )


if __name__ == "__main__":
    unittest.main()
