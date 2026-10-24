"""Tests for canonical snapshots: serialization, versioning, and atomic writes."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from iasim.app.session import GameSession
from iasim.crafting import load_catalog
from iasim.domain.agents import Agent, AgentAttributes, AgentStatus
from iasim.domain.alliances import Alliance
from iasim.domain.corpse import Corpse
from iasim.domain.geometry import Position
from iasim.domain.hashing import canonical_state_hash
from iasim.domain.identifiers import AgentId, ItemId
from iasim.domain.items import Equipment, EquipSlot, GroundItem, Inventory, ItemStack
from iasim.domain.memory import AgentMemory, Memory, MemoryEntry
from iasim.domain.resources import ResourceNode
from iasim.domain.session import SessionState
from iasim.domain.tiles import TileType, WorldMap
from iasim.domain.trades import TradeOffer
from iasim.domain.weather import WeatherKind, WeatherState
from iasim.domain.world import Structure, StructureKind
from iasim.persistence.state import (
    SnapshotError,
    read_snapshot,
    state_from_payload,
    state_to_payload,
    write_snapshot,
)
from iasim.world.layout import WorldLayout

CATALOG = load_catalog()


def _layout() -> WorldLayout:
    return WorldLayout(
        seed=3,
        world=WorldMap(width=6, height=6, tiles=(TileType.GRASS,) * 36),
        spawn_points=(Position(2, 2), Position(3, 2)),
    )


def _rich_state() -> SessionState:
    wood = CATALOG.item("wood").definition
    berry = CATALOG.item("berry").definition
    hand_item = CATALOG.item("stone_spear")
    body_item = CATALOG.item("fiber_clothes")
    first = Agent(
        AgentId("ag_01"),
        Position(2, 2),
        attributes=AgentAttributes(
            health_centi=9_000,
            hunger_centi=7_000,
            thirst_centi=6_000,
            energy_centi=5_000,
            wetness_centi=100,
            body_temperature_centi=3_700,
            vision=7,
            strength=6,
            dexterity=5,
            endurance=6,
        ),
        inventory=Inventory(
            stacks=(ItemStack(wood, 2), ItemStack(berry, 1)),
            max_slots=12,
            max_weight_grams=24_000,
        ),
        equipment=Equipment(items=((EquipSlot.HAND, hand_item), (EquipSlot.BODY, body_item))),
        status=AgentStatus.ACTIVE,
        memory=Memory(
            tiles=(
                MemoryEntry(
                    Position(1, 1),
                    TileType.GRASS,
                    3,
                    resources=("wood",),
                    structure=StructureKind.FIRE,
                ),
            ),
            agents=(AgentMemory(AgentId("ag_02"), Position(3, 2), 2),),
        ),
        bleeding=True,
    )
    second = Agent(AgentId("ag_02"), Position(3, 2), status=AgentStatus.ABSENT)
    return SessionState(
        seed=7,
        tick=12,
        rng_state=12_345,
        tick_minutes=5,
        world=WorldMap(
            width=4,
            height=3,
            tiles=(
                TileType.GRASS,
                TileType.FIRE,
                TileType.GRASS,
                TileType.GRASS,
                TileType.GRASS,
                TileType.GRASS,
                TileType.GRASS,
                TileType.GRASS,
                TileType.GRASS,
                TileType.GRASS,
                TileType.GRASS,
                TileType.GRASS,
            ),
        ),
        weather=WeatherState(kind=WeatherKind.RAIN, remaining_ticks=4, wind=6),
        agents=(first, second),
        structures=(Structure(StructureKind.FIRE, Position(1, 0), fuel=3, lit=True),),
        ground_items=(GroundItem(Position(1, 2), ItemStack(wood, 3)),),
        resource_nodes=(ResourceNode(Position(2, 1), "wood", 0, 3, 5),),
        corpses=(Corpse.from_agent(second, tick=5, cause="starvation"),),
        alliances=(Alliance.propose(AgentId("ag_01"), AgentId("ag_02"), 0),),
        trades=(
            TradeOffer.propose(
                AgentId("ag_01"),
                AgentId("ag_02"),
                1,
                ((ItemId("wood"), 1),),
                ((ItemId("berry"), 1),),
            ),
        ),
    )


class StateSerializationTests(unittest.TestCase):
    def test_a_rich_state_round_trips_to_the_same_hash(self) -> None:
        state = _rich_state()

        restored = state_from_payload(state_to_payload(state), CATALOG)

        self.assertEqual(canonical_state_hash(state), canonical_state_hash(restored))
        self.assertEqual(restored.tick, state.tick)
        self.assertEqual(restored.rng_state, state.rng_state)

    def test_snapshot_file_round_trips_to_the_same_hash(self) -> None:
        state = _rich_state()
        with tempfile.TemporaryDirectory() as directory:
            path = write_snapshot(Path(directory), state)

            restored = read_snapshot(path, CATALOG)

            self.assertEqual(path.name, "tick_000012.json")
            self.assertEqual(canonical_state_hash(state), canonical_state_hash(restored))
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["schema_version"], "1.0")
            self.assertEqual(data["tick"], 12)


class SnapshotVersionTests(unittest.TestCase):
    def _snapshot_file(self, directory: Path) -> Path:
        path = write_snapshot(directory, _rich_state())
        return path

    def test_an_incompatible_version_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._snapshot_file(Path(directory))
            data = json.loads(path.read_text(encoding="utf-8"))
            data["schema_version"] = "9.9"
            path.write_text(json.dumps(data), encoding="utf-8")

            with self.assertRaises(SnapshotError) as raised:
                read_snapshot(path, CATALOG)

            self.assertIn("9.9", str(raised.exception))
            self.assertIn("1.0", str(raised.exception))

    def test_a_missing_state_payload_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.json"
            path.write_text('{"schema_version": "1.0"}', encoding="utf-8")

            with self.assertRaises(SnapshotError):
                read_snapshot(path, CATALOG)

    def test_invalid_json_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "broken.json"
            path.write_text("{not json", encoding="utf-8")

            with self.assertRaises(SnapshotError):
                read_snapshot(path, CATALOG)


class PeriodicSnapshotTests(unittest.TestCase):
    def _session(
        self,
        directory: Path,
        *,
        every: int = 2,
    ) -> tuple[GameSession, str, str]:
        session = GameSession(
            3,
            layout=_layout(),
            log_dir=directory,
            snapshot_every_ticks=every,
        )
        return (
            session,
            session.join("Nia", session.tokens[0])["agent_id"],
            session.join("Kai", session.tokens[1])["agent_id"],
        )

    def test_snapshots_follow_the_configured_interval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            session, first, second = self._session(path)
            hashes: dict[int, str] = {}

            for tick in range(4):
                session.wait(first, tick)
                session.wait(second, tick)
                hashes[tick + 1] = session.state_hash

            snapshots = sorted((path / "snapshots").glob("*.json"))
            self.assertEqual(
                [snapshot.name for snapshot in snapshots],
                ["tick_000002.json", "tick_000004.json"],
            )
            for snapshot in snapshots:
                restored = read_snapshot(snapshot, load_catalog())
                with self.subTest(snapshot=snapshot.name):
                    self.assertEqual(
                        canonical_state_hash(restored),
                        hashes[restored.tick],
                    )

    def test_snapshots_are_disabled_without_a_log_directory(self) -> None:
        session = GameSession(3, layout=_layout(), snapshot_every_ticks=1)
        first = session.join("Nia", session.tokens[0])["agent_id"]
        second = session.join("Kai", session.tokens[1])["agent_id"]

        session.wait(first, 0)
        session.wait(second, 0)

        self.assertEqual(session.state.tick, 1)

    def test_no_snapshot_is_written_before_the_interval(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            session, first, second = self._session(path, every=10)

            session.wait(first, 0)
            session.wait(second, 0)

            snapshots_dir = path / "snapshots"
            self.assertFalse(snapshots_dir.exists() and any(snapshots_dir.glob("*.json")))

    def test_identical_sessions_write_identical_snapshots(self) -> None:
        with (
            tempfile.TemporaryDirectory() as first_directory,
            tempfile.TemporaryDirectory() as second_directory,
        ):
            first_path = Path(first_directory)
            second_path = Path(second_directory)
            first_session, first, second = self._session(first_path, every=1)
            other_session, other_first, other_second = self._session(
                second_path,
                every=1,
            )

            for session, actor, partner in (
                (first_session, first, second),
                (other_session, other_first, other_second),
            ):
                session.wait(actor, 0)
                session.wait(partner, 0)

            self.assertEqual(
                (first_path / "snapshots" / "tick_000001.json").read_text(encoding="utf-8"),
                (second_path / "snapshots" / "tick_000001.json").read_text(encoding="utf-8"),
            )

    def test_a_failed_replace_leaves_no_partial_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)

            with (
                patch(
                    "iasim.persistence.state.Path.replace",
                    side_effect=OSError("disk full"),
                ),
                self.assertRaises(SnapshotError),
            ):
                write_snapshot(path, _rich_state())

            self.assertFalse((path / "tick_000012.json").exists())
            self.assertEqual(list(path.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
