"""Tests for tcod-backed move_to pathfinding."""

from __future__ import annotations

import unittest

from iasim.domain.actions import Action, ActionKind
from iasim.domain.agents import Agent
from iasim.domain.geometry import Position
from iasim.domain.identifiers import AgentId
from iasim.domain.session import SessionState
from iasim.domain.tiles import TileType, WorldMap
from iasim.domain.turns import TurnEngine
from iasim.world.pathfinding_actions import MoveToOutcome, move_to_resolvers
from iasim.world.tcod_pathfinding import find_path


def _world(*wall_positions: Position) -> WorldMap:
    tiles = [TileType.GRASS] * 25
    for position in wall_positions:
        tiles[position.y * 5 + position.x] = TileType.ROCK
    return WorldMap(width=5, height=5, tiles=tuple(tiles))


def _agent(position: Position | None = None) -> Agent:
    return Agent(AgentId("ag_01"), Position(1, 1) if position is None else position)


def _state(world: WorldMap, agents: tuple[Agent, ...] | None = None) -> SessionState:
    return SessionState(
        seed=42,
        tick=0,
        rng_state=42,
        world=world,
        agents=agents or (_agent(),),
    )


def _resolve(
    state: SessionState,
    target: Position,
) -> tuple[SessionState, str]:
    engine = TurnEngine(state, resolvers=move_to_resolvers())
    engine.submit(
        Action(
            AgentId("ag_01"),
            0,
            ActionKind.MOVE_TO,
            (("x", target.x), ("y", target.y)),
        )
    )
    result = engine.resolve()
    return engine.state, result.events[0].outcome


class TcodPathfindingTests(unittest.TestCase):
    def test_open_path_is_deterministic_and_excludes_start(self) -> None:
        world = _world()
        first = find_path(world, Position(1, 1), Position(3, 1))
        second = find_path(world, Position(1, 1), Position(3, 1))

        self.assertEqual(first, second)
        self.assertEqual(first[-1], Position(3, 1))
        self.assertNotIn(Position(1, 1), first)

    def test_obstacles_are_routed_around(self) -> None:
        world = _world(Position(2, 1))

        path = find_path(world, Position(1, 1), Position(3, 1))

        self.assertTrue(path)
        self.assertNotIn(Position(2, 1), path)
        self.assertEqual(path[-1], Position(3, 1))

    def test_unreachable_goal_returns_empty_path(self) -> None:
        world = _world(
            Position(2, 0),
            Position(2, 1),
            Position(2, 2),
            Position(2, 3),
            Position(2, 4),
        )

        self.assertEqual(
            find_path(world, Position(1, 2), Position(3, 2)),
            (),
        )


class MoveToActionTests(unittest.TestCase):
    def test_move_to_advances_exactly_one_step(self) -> None:
        state, outcome = _resolve(_state(_world()), Position(4, 2))

        self.assertEqual(outcome, MoveToOutcome.MOVED.value)
        self.assertNotEqual(state.agents[0].position, Position(1, 1))
        self.assertLessEqual(
            max(
                abs(state.agents[0].position.x - 1),
                abs(state.agents[0].position.y - 1),
            ),
            1,
        )

    def test_occupied_goal_has_no_path(self) -> None:
        state, outcome = _resolve(
            _state(
                _world(),
                agents=(_agent(), Agent(AgentId("ag_02"), Position(3, 2))),
            ),
            Position(3, 2),
        )

        self.assertEqual(outcome, MoveToOutcome.NO_PATH.value)
        self.assertEqual(state.agents[0].position, Position(1, 1))

    def test_out_of_bounds_target_is_rejected(self) -> None:
        state, outcome = _resolve(_state(_world()), Position(5, 1))

        self.assertEqual(outcome, MoveToOutcome.OUT_OF_BOUNDS.value)
        self.assertEqual(state.agents[0].position, Position(1, 1))


if __name__ == "__main__":
    unittest.main()
