"""Tests for local chat delivery, targeting, and text sanitization."""

from __future__ import annotations

import unittest

from iasim.app.session import GameSession
from iasim.domain.chat import (
    MAX_CHAT_MESSAGE_LENGTH,
    sanitize_chat_text,
    within_chat_radius,
)
from iasim.domain.geometry import Position
from iasim.domain.tiles import TileType, WorldMap
from iasim.world.layout import WorldLayout


def _layout() -> WorldLayout:
    tiles = [TileType.GRASS] * (21 * 3)
    return WorldLayout(
        seed=42,
        world=WorldMap(width=21, height=3, tiles=tuple(tiles)),
        spawn_points=(Position(1, 1), Position(9, 1), Position(18, 1)),
    )


def _session() -> tuple[GameSession, tuple[str, str, str]]:
    session = GameSession(42, layout=_layout(), max_agents=3)
    agents = tuple(
        session.join(name, session.tokens[index])["agent_id"]
        for index, name in enumerate(("Nia", "Kai", "Luma"))
    )
    return session, agents


def _advance(session: GameSession, agents: tuple[str, str, str]) -> None:
    tick = session.tick
    for agent_id in agents:
        self_result = session.wait(agent_id, tick)
        if not self_result["ok"]:
            raise AssertionError(self_result)


class ChatSanitizationTests(unittest.TestCase):
    def test_sanitizer_removes_ansi_and_control_sequences(self) -> None:
        text = "\x1b[31mHola\x1b[0m\nmundo\x00\tcompleto"

        self.assertEqual(sanitize_chat_text(text), "Hola mundo completo")

    def test_chat_radius_is_chebyshev_and_inclusive(self) -> None:
        origin = Position(1, 1)

        self.assertTrue(within_chat_radius(origin, Position(9, 1)))
        self.assertTrue(within_chat_radius(origin, Position(9, 9)))
        self.assertFalse(within_chat_radius(origin, Position(10, 1)))


class SessionChatTests(unittest.TestCase):
    def test_say_is_delivered_next_tick_only_to_agents_in_range(self) -> None:
        session, agents = _session()

        said = session.say(agents[0], "Hola a todos")
        self.assertTrue(said["ok"])
        self.assertEqual(said["status"], "queued")
        self.assertEqual(session.observe(agents[1])["perception"]["messages"], [])

        _advance(session, agents)

        first = session.observe(agents[0])["perception"]["messages"]
        second = session.observe(agents[1])["perception"]["messages"]
        third = session.observe(agents[2])["perception"]["messages"]
        self.assertEqual(first, [])
        self.assertEqual(
            second,
            [{"from": agents[0], "tick": 0, "text": "Hola a todos"}],
        )
        self.assertEqual(third, [])

    def test_say_is_free_but_only_once_per_tick_and_can_target(self) -> None:
        session, agents = _session()

        self.assertTrue(session.say(agents[0], "Uno")["ok"])
        duplicate = session.say(agents[0], "Dos")
        self.assertEqual(duplicate["error"]["code"], "ALREADY_SAID")

        tick = session.tick
        for agent_id in agents:
            self.assertTrue(session.wait(agent_id, tick)["ok"])

        targeted = session.say(agents[0], "Solo Kai", agents[1])
        self.assertTrue(targeted["ok"])
        tick = session.tick
        for agent_id in agents:
            self.assertTrue(session.wait(agent_id, tick)["ok"])

        self.assertEqual(
            session.observe(agents[1])["perception"]["messages"],
            [{"from": agents[0], "tick": 1, "text": "Solo Kai"}],
        )
        self.assertEqual(session.observe(agents[2])["perception"]["messages"], [])

    def test_say_rejects_out_of_range_targets_and_sanitizes_text(self) -> None:
        session, agents = _session()

        out_of_range = session.say(agents[0], "Lejos", agents[2])
        unknown = session.say(agents[0], "Nadie", "ag_99")
        self_target = session.say(agents[0], "Yo", agents[0])
        self.assertEqual(out_of_range["error"]["code"], "NOT_IN_RANGE")
        self.assertEqual(unknown["error"]["code"], "INVALID_TARGET")
        self.assertEqual(self_target["error"]["code"], "INVALID_TARGET")
        self.assertTrue(session.say(agents[0], "\x1b[31mHola\x1b[0m\nmundo")["ok"])

        tick = session.tick
        for agent_id in agents:
            self.assertTrue(session.wait(agent_id, tick)["ok"])

        self.assertEqual(
            session.observe(agents[1])["perception"]["messages"],
            [{"from": agents[0], "tick": 0, "text": "Hola mundo"}],
        )

    def test_say_rejects_oversized_and_empty_messages_without_consuming_the_tick(self) -> None:
        session, agents = _session()

        too_long = session.say(agents[0], "x" * (MAX_CHAT_MESSAGE_LENGTH + 1))
        empty = session.say(agents[0], "\x00\x01")
        valid = session.say(agents[0], "x" * MAX_CHAT_MESSAGE_LENGTH)

        self.assertEqual(too_long["error"]["code"], "MESSAGE_TOO_LONG")
        self.assertEqual(empty["error"]["code"], "INVALID_MESSAGE")
        self.assertTrue(valid["ok"])

    def test_say_does_not_consume_the_primary_action(self) -> None:
        session, agents = _session()

        self.assertTrue(session.say(agents[0], "Voy")["ok"])
        _advance(session, agents)
        self.assertEqual(session.tick, 1)


if __name__ == "__main__":
    unittest.main()
