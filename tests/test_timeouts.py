"""Tests for the action deadline, skipped turns, and the absent state."""

from __future__ import annotations

import unittest

from iasim.app.session import GameSession
from iasim.domain.agents import AgentStatus
from iasim.domain.geometry import Position
from iasim.domain.tiles import TileType, WorldMap
from iasim.world.layout import WorldLayout

TIMEOUT_MS = 1000


def _layout() -> WorldLayout:
    return WorldLayout(
        seed=7,
        world=WorldMap(width=6, height=6, tiles=(TileType.GRASS,) * 36),
        spawn_points=(Position(2, 2), Position(3, 2)),
    )


def _session(
    *,
    timeout_disconnects: int = 3,
) -> tuple[GameSession, list[float], str, str]:
    clock = [0.0]
    session = GameSession(
        7,
        layout=_layout(),
        turn_timeout_ms=TIMEOUT_MS,
        timeout_disconnects=timeout_disconnects,
        wall_clock=lambda: clock[0],
    )
    first = session.join("Nia", session.tokens[0])["agent_id"]
    second = session.join("Kai", session.tokens[1])["agent_id"]
    return session, clock, first, second


def _status(session: GameSession, agent_id: str) -> AgentStatus:
    return next(agent for agent in session.state.agents if agent.agent_id == agent_id).status


class DeadlineTests(unittest.TestCase):
    def test_missing_action_is_skipped_after_the_deadline(self) -> None:
        session, clock, first, second = _session()
        self.assertTrue(session.wait(first, 0)["ok"])
        self.assertEqual(session.tick, 0)

        clock[0] += TIMEOUT_MS / 1000.0
        observation = session.observe(first)

        self.assertEqual(observation["tick"], 1)
        self.assertEqual(observation["last_action_result"]["outcome"], "waited")
        self.assertEqual(_status(session, second), AgentStatus.ACTIVE)

    def test_the_deadline_is_not_applied_early(self) -> None:
        session, clock, first, _ = _session()
        self.assertTrue(session.wait(first, 0)["ok"])

        clock[0] += TIMEOUT_MS / 2000.0
        observation = session.observe(first)

        self.assertEqual(observation["tick"], 0)

    def test_no_deadline_runs_without_pending_actions(self) -> None:
        session, clock, first, _ = _session()

        clock[0] += 10.0
        observation = session.observe(first)

        self.assertEqual(observation["tick"], 0)

    def test_three_consecutive_timeouts_mark_the_agent_absent(self) -> None:
        session, clock, first, second = _session()

        for tick in range(3):
            self.assertTrue(session.wait(first, tick)["ok"])
            clock[0] += TIMEOUT_MS / 1000.0
            self.assertEqual(session.observe(first)["tick"], tick + 1)

        self.assertEqual(session.tick, 3)
        self.assertEqual(_status(session, second), AgentStatus.ABSENT)

    def test_an_absent_agent_cannot_act_until_it_responds(self) -> None:
        session, clock, first, second = _session()
        for tick in range(3):
            self.assertTrue(session.wait(first, tick)["ok"])
            clock[0] += TIMEOUT_MS / 1000.0
            session.observe(first)

        blocked = session.wait(second, 3)
        self.assertFalse(blocked["ok"])
        self.assertEqual(blocked["error"]["code"], "AGENT_ABSENT")

        session.observe(second)
        self.assertEqual(_status(session, second), AgentStatus.ACTIVE)
        self.assertTrue(session.wait(second, 3)["ok"])

    def test_an_absent_agent_does_not_block_the_turn(self) -> None:
        session, clock, first, second = _session()
        for tick in range(3):
            self.assertTrue(session.wait(first, tick)["ok"])
            clock[0] += TIMEOUT_MS / 1000.0
            session.observe(first)
        self.assertEqual(_status(session, second), AgentStatus.ABSENT)

        self.assertTrue(session.wait(first, 3)["ok"])

        self.assertEqual(session.tick, 4)

    def test_responding_resets_the_consecutive_timeout_counter(self) -> None:
        session, clock, first, second = _session()

        self.assertTrue(session.wait(first, 0)["ok"])
        clock[0] += TIMEOUT_MS / 1000.0
        session.observe(first)
        self.assertTrue(session.wait(first, 1)["ok"])
        self.assertTrue(session.wait(second, 1)["ok"])

        for tick in (2, 3):
            self.assertTrue(session.wait(first, tick)["ok"])
            clock[0] += TIMEOUT_MS / 1000.0
            session.observe(first)

        self.assertEqual(session.tick, 4)
        self.assertEqual(_status(session, second), AgentStatus.ACTIVE)

    def test_sleeping_and_absent_agents_are_not_awaited(self) -> None:
        session, _, first, second = _session()
        self.assertTrue(session.sleep(second, 0, "energy_full")["ok"])
        self.assertTrue(session.wait(first, 0)["ok"])

        self.assertEqual(session.tick, 1)


if __name__ == "__main__":
    unittest.main()
