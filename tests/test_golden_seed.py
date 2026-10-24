"""Golden-seed determinism and replay regression test.

Artifact contract for this test:

- seed: ``20261023``; two agents (``Nia`` = ag_01, ``Kai`` = ag_02); 12 ticks;
  both agents submit ``wait`` on every tick, and ag_01 reports one mind at tick 0.
- canonical state hashes after every resolved tick are the committed constants
  below. They change only when an SRS-approved change to the canonical state
  schema (or to seeded generation/turn ordering) is intentional; update them in
  the same commit that documents that change.
- a run directory contains ``session.json``, ``agents.json``, ``events.jsonl``,
  ``actions.jsonl``, ``thoughts.jsonl``, ``replay.json``, ``summary.json`` and
  ``metrics.csv`` (plus ``snapshots/`` when the cadence triggers).
- replaying that ``replay.json`` must reproduce every tick, the final hash, the
  same action count, and the same reported mind data.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from iasim.app.replay import replay_frames, replay_saved_run
from iasim.app.session import GameSession
from iasim.domain.hashing import canonical_state_hash

GOLDEN_SEED = 20261023
GOLDEN_TICKS = 12
GOLDEN_FINAL_HASH = "8536573d0bcad79a2c976ee53eb1dac5250b0583f0fc5e91d0ff118fe206a300"
GOLDEN_HASHES: tuple[str, ...] = (
    "55267c3a04578c912645b07cb744f8b216040c3e90ceb3f3c8fa4553b082ee47",
    "ddcae4dacd8304e25bf26d3d15ba7156addea3f2e76365209713f720df82da6a",
    "f5f041b4f0ab7f19e343c52b185d7f9e1bde31a5b8e18bdcc719856b90faa895",
    "7d4790e06d0aace742df2ec1fd3d2a4f30c7028b5fb939e3abdce5a0925ea158",
    "2db43ce25742eb1659546c649bae1416c496b7bcf3c51ad0b7271efdd8d93930",
    "7c9ee9490fc6d9842c8d063d21b447ddeff0dd9426fa01105d56062237701154",
    "18ecdffabf7064d22f07e293bc3f63a2fb318d9ced05f6624cdd35961de92d88",
    "e2b8e926bf848c057be8ad2c622901c75190771d64003926968acee8da52ae1a",
    "2e4fe3303d48a24125233ecc535d5377f78a44bd5a7b1b805939719e1c20875f",
    "e9447310e1220823280f7510c1ceab88243bceb4423a6f6f435c3a4158ca200e",
    "0b4932c7c3003b14f070dc0583c6b1f6f4b0a9df3fafac3d100ee2059b740df9",
    GOLDEN_FINAL_HASH,
)
ARTIFACT_NAMES = frozenset(
    {
        "session.json",
        "agents.json",
        "events.jsonl",
        "actions.jsonl",
        "thoughts.jsonl",
        "replay.json",
        "summary.json",
        "metrics.csv",
    }
)


def _run(directory: Path, *, seed: int = GOLDEN_SEED) -> tuple[GameSession, list[str]]:
    session = GameSession(
        seed,
        max_agents=2,
        log_dir=directory,
        snapshot_every_ticks=4,
        token_path=directory / "agents.json",
    )
    first = session.join("Nia", session.tokens[0])["agent_id"]
    second = session.join("Kai", session.tokens[1])["agent_id"]
    session.report_mind(
        first,
        0,
        intent="Explorar",
        thought="La isla parece tranquila.",
        plan="Esperar",
        confidence=70,
    )
    hashes: list[str] = []
    for tick in range(GOLDEN_TICKS):
        session.wait(first, tick)
        session.wait(second, tick)
        hashes.append(session.state_hash)
    session.finish()
    return session, hashes


class GoldenSeedTests(unittest.TestCase):
    def test_two_independent_runs_match_every_golden_hash(self) -> None:
        with (
            tempfile.TemporaryDirectory() as first_directory,
            tempfile.TemporaryDirectory() as second_directory,
        ):
            first_path = Path(first_directory)
            second_path = Path(second_directory)
            first_session, first_hashes = _run(first_path)
            second_session, second_hashes = _run(second_path)

            self.assertEqual(first_hashes, list(GOLDEN_HASHES))
            self.assertEqual(second_hashes, list(GOLDEN_HASHES))
            self.assertEqual(first_hashes, second_hashes)
            self.assertEqual(first_session.final_state_hash, GOLDEN_FINAL_HASH)
            self.assertEqual(second_session.final_state_hash, GOLDEN_FINAL_HASH)
            first_summary = json.loads((first_path / "summary.json").read_text(encoding="utf-8"))
            second_summary = json.loads((second_path / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(first_summary["final_state_hash"], GOLDEN_FINAL_HASH)
            self.assertEqual(second_summary["final_state_hash"], GOLDEN_FINAL_HASH)
            self.assertEqual(first_summary["session"], second_summary["session"])

    def test_artifacts_are_complete_and_documented(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            session, hashes = _run(path)

            self.assertEqual(hashes, list(GOLDEN_HASHES))
            names = {entry.name for entry in path.iterdir()}
            self.assertTrue(names.issuperset(ARTIFACT_NAMES), names)
            self.assertEqual(
                len((path / "thoughts.jsonl").read_text(encoding="utf-8").splitlines()),
                1,
            )
            replay = json.loads((path / "replay.json").read_text(encoding="utf-8"))
            self.assertEqual(replay["seed"], session.state.seed)
            self.assertEqual(len(replay["turns"]), GOLDEN_TICKS)
            self.assertEqual(
                [turn["state_hash"] for turn in replay["turns"]],
                list(GOLDEN_HASHES),
            )
            self.assertEqual(session.state_hash, GOLDEN_FINAL_HASH)

    def test_replay_reproduces_every_tick_and_the_final_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            session, hashes = _run(path)

            report = replay_saved_run(path / "replay.json")
            frames = replay_frames(path / "replay.json")

            self.assertTrue(report.matched, report.detail)
            self.assertEqual(report.ticks_replayed, GOLDEN_TICKS)
            self.assertEqual(report.actions_replayed, GOLDEN_TICKS * 2)
            self.assertEqual(report.final_hash, GOLDEN_FINAL_HASH)
            self.assertEqual(
                [canonical_state_hash(frame.state) for frame in frames[1:]],
                hashes,
            )
            self.assertEqual(canonical_state_hash(frames[-1].state), GOLDEN_FINAL_HASH)
            self.assertEqual(
                [report.intent for report in frames[1].minds],
                ["Explorar"],
            )
            self.assertEqual(
                session.final_state_hash,
                GOLDEN_FINAL_HASH,
            )

    def test_a_different_seed_changes_the_hash_sequence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _session, hashes = _run(Path(directory), seed=GOLDEN_SEED + 1)

        self.assertNotEqual(hashes, list(GOLDEN_HASHES))
        self.assertNotEqual(hashes[0], GOLDEN_HASHES[0])
        self.assertNotEqual(hashes[-1], GOLDEN_FINAL_HASH)


if __name__ == "__main__":
    unittest.main()
