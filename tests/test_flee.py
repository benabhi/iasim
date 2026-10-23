"""Tests for deterministic flee movement."""

from __future__ import annotations

import unittest

from iasim.domain.actions import Action, ActionKind
from iasim.domain.agents import Agent
from iasim.domain.flee import FleeOutcome, flee_resolvers
from iasim.domain.geometry import Position
from iasim.domain.identifiers import AgentId
from iasim.domain.session import SessionState
from iasim.domain.tiles import TileType, WorldMap
from iasim.domain.turns import TurnEngine


def _world(width: int = 6) -> WorldMap:
    return WorldMap(width=width, height=6, tiles=(TileType.GRASS,) * (width * 6))


def _state(
    *,
    agent_position: Position | None = None,
    target_position: Position | None = None,
    width: int = 6,
) -> SessionState:
    return SessionState(
        seed=42,
        tick=0,
        rng_state=42,
        world=_world(width),
        agents=(
            Agent(AgentId("ag_01"), agent_position or Position(2, 2)),
            Agent(AgentId("ag_02"), target_position or Position(3, 2)),
        ),
    )


def _flee(state: SessionState) -> tuple[SessionState, str]:
    engine = TurnEngine(state, resolvers=flee_resolvers())
    engine.submit(
        Action(
            AgentId("ag_01"),
            0,
            ActionKind.FLEE,
            (("target_id", "ag_02"),),
        )
    )
    result = engine.resolve()
    return engine.state, result.events[0].outcome


class FleeTests(unittest.TestCase):
    def test_flee_moves_two_cells_away_and_spends_energy(self) -> None:
        state, outcome = _flee(_state())

        self.assertEqual(outcome, FleeOutcome.FLED.value)
        self.assertEqual(state.agents[0].position, Position(0, 0))
        self.assertEqual(state.agents[0].attributes.energy_centi, 80 * 100 - 100)

    def test_flee_stops_after_one_cell_at_boundary(self) -> None:
        state, outcome = _flee(
            _state(
                agent_position=Position(1, 2),
                target_position=Position(2, 2),
                width=3,
            )
        )

        self.assertEqual(outcome, FleeOutcome.FLED.value)
        self.assertEqual(state.agents[0].position, Position(0, 1))

    def test_flee_rejects_unknown_and_self_targets(self) -> None:
        _, outcome = _flee(_state())
        self.assertEqual(outcome, FleeOutcome.FLED.value)

        engine = TurnEngine(_state(), resolvers=flee_resolvers())
        engine.submit(
            Action(
                AgentId("ag_01"),
                0,
                ActionKind.FLEE,
                (("target_id", "ag_01"),),
            )
        )
        result = engine.resolve()
        self.assertEqual(result.events[0].outcome, FleeOutcome.INVALID_TARGET.value)

    def test_flee_is_blocked_without_a_valid_away_cell(self) -> None:
        state = _state(agent_position=Position(1, 1), target_position=Position(0, 0))
        state = state.__class__(
            seed=state.seed,
            tick=state.tick,
            rng_state=state.rng_state,
            world=WorldMap(
                width=3,
                height=3,
                tiles=(
                    TileType.GRASS,
                    TileType.TREE,
                    TileType.TREE,
                    TileType.TREE,
                    TileType.GRASS,
                    TileType.TREE,
                    TileType.TREE,
                    TileType.TREE,
                    TileType.TREE,
                ),
            ),
            agents=(
                Agent(AgentId("ag_01"), Position(1, 1)),
                Agent(AgentId("ag_02"), Position(0, 0)),
            ),
        )

        reached, outcome = _flee(state)

        self.assertEqual(outcome, FleeOutcome.BLOCKED.value)
        self.assertEqual(reached.agents[0].position, Position(1, 1))


if __name__ == "__main__":
    unittest.main()
