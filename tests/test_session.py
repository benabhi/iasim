"""Tests for the application-level game session."""

from __future__ import annotations

import unittest

from iasim.app.session import GameSession
from iasim.domain.geometry import Position
from iasim.domain.tiles import TileType, WorldMap
from iasim.world.layout import WorldLayout


def _layout(
    spawns: tuple[Position, ...] = (Position(2, 2),),
    *,
    blocked: Position | None = None,
) -> WorldLayout:
    tiles = [TileType.GRASS] * 25
    if blocked is not None:
        tiles[blocked.y * 5 + blocked.x] = TileType.DEEP_WATER
    return WorldLayout(
        seed=42,
        world=WorldMap(width=5, height=5, tiles=tuple(tiles)),
        spawn_points=spawns,
    )


def _session(layout: WorldLayout | None = None, **kwargs: object) -> GameSession:
    return GameSession(42, layout=layout if layout is not None else _layout(), **kwargs)


class GameSessionTests(unittest.TestCase):
    def test_join_and_observation_do_not_expose_the_map(self) -> None:
        session = _session()

        joined = session.join("Nia")
        observation = session.observe(joined["agent_id"])

        self.assertTrue(joined["ok"])
        self.assertEqual(joined["agent_id"], "ag_01")
        self.assertEqual(joined["spawn"], [2, 2])
        self.assertEqual(joined["tick"], 0)
        self.assertEqual(observation["tick"], 0)
        self.assertEqual(observation["agent"]["name"], "Nia")
        self.assertEqual(observation["agent"]["pos"], [2, 2])
        self.assertEqual(observation["time"]["day"], 1)
        self.assertEqual(observation["time"]["hour"], 6)
        self.assertEqual(observation["time"]["phase"], "dawn")
        self.assertNotIn("world", observation)
        self.assertNotIn("seed", observation)
        self.assertNotIn("rng_state", observation)
        self.assertNotIn("tiles", observation)
        self.assertLessEqual(len(observation["perception"]["visible"]), 49)

    def test_move_advances_tick_and_updates_position(self) -> None:
        session = _session()
        agent_id = session.join("Nia")["agent_id"]

        result = session.move(agent_id, 0, 1, 0)
        observation = session.observe(agent_id)

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "queued")
        self.assertEqual(observation["tick"], 1)
        self.assertEqual(observation["agent"]["pos"], [3, 2])
        self.assertEqual(observation["last_action_result"]["status"], "success")
        self.assertEqual(observation["last_action_result"]["action"], "move")
        self.assertEqual(observation["last_action_result"]["outcome"], "moved")

    def test_wait_advances_tick_without_moving(self) -> None:
        session = _session()
        agent_id = session.join("Nia")["agent_id"]
        session.move(agent_id, 0, 1, 0)

        result = session.wait(agent_id, 1)
        observation = session.observe(agent_id)

        self.assertTrue(result["ok"])
        self.assertEqual(observation["tick"], 2)
        self.assertEqual(observation["agent"]["pos"], [3, 2])
        self.assertEqual(observation["last_action_result"]["action"], "wait")
        self.assertEqual(observation["last_action_result"]["outcome"], "waited")

    def test_blocked_move_is_reported_in_the_next_observation(self) -> None:
        session = _session(_layout(blocked=Position(3, 2)))
        agent_id = session.join("Nia")["agent_id"]

        result = session.move(agent_id, 0, 1, 0)
        observation = session.observe(agent_id)

        self.assertTrue(result["ok"])
        self.assertEqual(observation["tick"], 1)
        self.assertEqual(observation["agent"]["pos"], [2, 2])
        self.assertEqual(observation["last_action_result"]["status"], "rejected")
        self.assertEqual(observation["last_action_result"]["outcome"], "impassable")

    def test_duplicate_actions_are_rejected_until_all_agents_act(self) -> None:
        layout = _layout(spawns=(Position(1, 1), Position(3, 3)))
        session = _session(layout)
        first = session.join("Nia")["agent_id"]
        second = session.join("Kai")["agent_id"]

        first_move = session.move(first, 0, 1, 0)
        duplicate = session.move(first, 0, 0, 1)
        second_wait = session.wait(second, 0)

        self.assertTrue(first_move["ok"])
        self.assertFalse(duplicate["ok"])
        self.assertEqual(duplicate["error"]["code"], "ALREADY_ACTED")
        self.assertTrue(second_wait["ok"])
        self.assertEqual(session.observe(first)["tick"], 1)

    def test_stale_and_invalid_actions_are_rejected(self) -> None:
        session = _session()
        agent_id = session.join("Nia")["agent_id"]

        future = session.move(agent_id, 1, 1, 0)
        unknown = session.move("ag_99", 0, 1, 0)
        invalid = session.move("bad", 0, 1, 0)
        negative = session.move(agent_id, -1, 1, 0)
        session.move(agent_id, 0, 1, 0)
        stale = session.move(agent_id, 0, 0, 1)

        self.assertEqual(future["error"]["code"], "INVALID_TICK")
        self.assertEqual(unknown["error"]["code"], "NOT_YOUR_TURN")
        self.assertEqual(invalid["error"]["code"], "NOT_YOUR_TURN")
        self.assertEqual(negative["error"]["code"], "INVALID_TICK")
        self.assertEqual(stale["error"]["code"], "STALE_TICK")

    def test_wait_for_tick_returns_new_tick_and_times_out(self) -> None:
        session = _session()
        agent_id = session.join("Nia")["agent_id"]
        session.move(agent_id, 0, 1, 0)

        fresh = session.wait_for_tick(agent_id, 0, 100)
        timed_out = session.wait_for_tick(agent_id, 1, 10)
        future = session.wait_for_tick(agent_id, 2, 10)

        self.assertEqual(fresh["tick"], 1)
        self.assertFalse(timed_out["ok"])
        self.assertEqual(timed_out["error"]["code"], "NO_NEW_TICK")
        self.assertFalse(future["ok"])
        self.assertEqual(future["error"]["code"], "INVALID_TICK")

    def test_join_rejects_invalid_names_and_full_sessions(self) -> None:
        session = _session()

        empty = session.join("  ")
        control = session.join("bad\nname")
        long_name = session.join("x" * 41)
        joined = session.join("Nia")
        full = session.join("Kai")

        self.assertEqual(empty["error"]["code"], "INVALID_NAME")
        self.assertEqual(control["error"]["code"], "INVALID_NAME")
        self.assertEqual(long_name["error"]["code"], "INVALID_NAME")
        self.assertTrue(joined["ok"])
        self.assertEqual(full["error"]["code"], "SESSION_FULL")

    def test_late_join_is_rejected_by_default_and_allowed_when_enabled(self) -> None:
        layout = _layout(spawns=(Position(1, 1), Position(3, 3)))
        session = _session(layout)
        first = session.join("Nia")["agent_id"]
        session.move(first, 0, 1, 0)

        late = session.join("Kai")
        self.assertEqual(late["error"]["code"], "LATE_JOIN_DISABLED")

        allowed = _session(layout, allow_late_join=True)
        first = allowed.join("Nia")["agent_id"]
        allowed.move(first, 0, 1, 0)
        joined = allowed.join("Kai")

        self.assertTrue(joined["ok"])
        self.assertEqual(joined["tick"], 1)

    def test_health_has_no_session_secrets(self) -> None:
        session = _session()
        session.join("Nia")

        health = session.health()

        self.assertEqual(health["status"], "ok")
        self.assertEqual(health["agents"], 1)
        self.assertNotIn("world", health)
        self.assertNotIn("seed", health)
        self.assertNotIn("rng_state", health)

    def test_observing_unknown_agent_is_rejected(self) -> None:
        session = _session()

        observation = session.observe("ag_99")

        self.assertFalse(observation["ok"])
        self.assertEqual(observation["error"]["code"], "NOT_YOUR_TURN")


if __name__ == "__main__":
    unittest.main()
