"""Tests for per-agent session token authentication."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from iasim.app.session import GameSession
from iasim.errors import PersistenceError


class TokenRegistryTests(unittest.TestCase):
    def test_token_file_contains_unique_slots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agents.json"
            session = GameSession(42, token_path=path)
            data = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(data["schema_version"], "1.0")
        self.assertEqual(len(data["agents"]), 8)
        tokens = [entry["token"] for entry in data["agents"]]
        self.assertEqual(len(tokens), len(set(tokens)))
        self.assertEqual(tuple(tokens), session.tokens)
        self.assertEqual(
            [entry["agent_id"] for entry in data["agents"]],
            [f"ag_{index:02d}" for index in range(1, 9)],
        )
        self.assertTrue(all(len(token) >= 32 for token in tokens))

    @unittest.skipIf(os.name == "nt", "POSIX permissions are not enforced on Windows")
    def test_token_file_is_private(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "agents.json"
            GameSession(42, token_path=path)

            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_join_binds_the_token_to_its_slot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = GameSession(42, token_path=Path(directory) / "agents.json")
            token = session.tokens[0]
            joined = session.join("Nia", token)

            self.assertTrue(joined["ok"])
            self.assertEqual(joined["agent_id"], "ag_01")
            self.assertEqual(session.agent_for_token(token), "ag_01")
            self.assertEqual(session.agent_id_for_token(token), "ag_01")
            self.assertIsNone(session.agent_for_token("bad-token"))
            self.assertIsNone(session.agent_id_for_token("bad-token"))
            self.assertEqual(
                session.join("Kai", token)["error"]["code"],
                "ALREADY_JOINED",
            )
            self.assertEqual(
                session.join("Kai", "bad-token")["error"]["code"],
                "UNAUTHORIZED",
            )

    def test_tokens_are_not_exposed_in_observations_or_health(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            session = GameSession(42, token_path=Path(directory) / "agents.json")
            token = session.tokens[0]
            joined = session.join("Nia", token)
            observation = session.observe("ag_01")
            health = session.health()

        self.assertNotIn(token, json.dumps(joined))
        self.assertNotIn(token, json.dumps(observation))
        self.assertNotIn(token, json.dumps(health))

    def test_token_file_write_failure_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            blocker = Path(directory) / "not-a-directory"
            blocker.write_text("x", encoding="utf-8")
            path = blocker / "agents.json"

            with self.assertRaises(PersistenceError):
                GameSession(42, token_path=path)


if __name__ == "__main__":
    unittest.main()
