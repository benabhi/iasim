"""Tests for eight-direction movement and wait."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from iasim.domain.actions import Action, ActionKind
from iasim.domain.agents import Agent, AgentAttributes, AgentStatus
from iasim.domain.geometry import Position
from iasim.domain.identifiers import AgentId, ItemId
from iasim.domain.items import GroundItem, ItemDefinition, ItemStack
from iasim.domain.movement import (
    MovementOutcome,
    movement_resolvers,
    resolve_move,
)
from iasim.domain.session import SessionState
from iasim.domain.tiles import TileType, WorldMap
from iasim.domain.turns import TurnEngine, TurnResult
from iasim.domain.world import Structure, StructureKind

DIRECTIONS = (
    (-1, -1),
    (-1, 0),
    (-1, 1),
    (0, -1),
    (0, 1),
    (1, -1),
    (1, 0),
    (1, 1),
)
BERRY = ItemDefinition(ItemId("berry"), 50, True, 99)


def _world(
    overrides: dict[Position, TileType] | None = None,
    *,
    width: int = 5,
    height: int = 5,
) -> WorldMap:
    tiles = [TileType.GRASS] * (width * height)
    if overrides is not None:
        for position, tile in overrides.items():
            tiles[position.y * width + position.x] = tile
    return WorldMap(width=width, height=height, tiles=tuple(tiles))


def _agent(
    agent_id: str,
    x: int,
    y: int,
    *,
    status: AgentStatus = AgentStatus.ACTIVE,
    health_centi: int = 10_000,
) -> Agent:
    return Agent(
        AgentId(agent_id),
        Position(x, y),
        attributes=AgentAttributes(health_centi=health_centi),
        status=status,
    )


def _state(
    agents: tuple[Agent, ...],
    *,
    world: WorldMap | None = None,
    structures: tuple[Structure, ...] = (),
    ground_items: tuple[GroundItem, ...] = (),
) -> SessionState:
    return SessionState(
        seed=42,
        tick=0,
        rng_state=42,
        world=world if world is not None else _world(),
        agents=agents,
        structures=structures,
        ground_items=ground_items,
    )


def _move_action(
    agent_id: str,
    dx: object,
    dy: object,
    *,
    tick: int = 0,
) -> Action:
    return Action(
        AgentId(agent_id),
        tick,
        ActionKind.MOVE,
        (("dx", dx), ("dy", dy)),
    )


class MovementTests(unittest.TestCase):
    def test_all_eight_directions_move(self) -> None:
        for dx, dy in DIRECTIONS:
            with self.subTest(dx=dx, dy=dy):
                agent = _agent("ag_01", 2, 2)
                engine = TurnEngine(
                    _state((agent,)),
                    resolvers=movement_resolvers(),
                )
                engine.submit(_move_action("ag_01", dx, dy))

                result = engine.resolve()

                self.assertEqual(
                    engine.state.agents[0].position,
                    Position(2 + dx, 2 + dy),
                )
                self.assertEqual(result.events[0].outcome, MovementOutcome.MOVED.value)

    def test_wait_keeps_position(self) -> None:
        engine = TurnEngine(
            _state((_agent("ag_01", 2, 2),)),
            resolvers=movement_resolvers(),
        )
        engine.submit(Action(AgentId("ag_01"), 0, ActionKind.WAIT))

        result = engine.resolve()

        self.assertEqual(engine.state.agents[0].position, Position(2, 2))
        self.assertEqual(result.events[0].outcome, MovementOutcome.WAITED.value)

    def test_out_of_bounds_is_rejected(self) -> None:
        for dx, dy in ((-1, 0), (0, -1), (-1, -1)):
            with self.subTest(dx=dx, dy=dy):
                engine = TurnEngine(
                    _state((_agent("ag_01", 0, 0),)),
                    resolvers=movement_resolvers(),
                )
                engine.submit(_move_action("ag_01", dx, dy))

                result = engine.resolve()

                self.assertEqual(engine.state.agents[0].position, Position(0, 0))
                self.assertEqual(
                    result.events[0].outcome,
                    MovementOutcome.OUT_OF_BOUNDS.value,
                )

    def test_impassable_terrain_is_rejected(self) -> None:
        for tile in (
            TileType.DEEP_WATER,
            TileType.TREE,
            TileType.ROCK,
            TileType.FIRE,
        ):
            with self.subTest(tile=tile):
                world = _world({Position(3, 2): tile})
                agent = _agent("ag_01", 2, 2)
                engine = TurnEngine(
                    _state((agent,), world=world),
                    resolvers=movement_resolvers(),
                )
                engine.submit(_move_action("ag_01", 1, 0))

                result = engine.resolve()

                self.assertEqual(engine.state.agents[0].position, Position(2, 2))
                self.assertEqual(
                    result.events[0].outcome,
                    MovementOutcome.IMPASSABLE.value,
                )

    def test_structures_block_except_shelters(self) -> None:
        for kind, tile, outcome in (
            (StructureKind.WORKBENCH, TileType.WORKBENCH, MovementOutcome.STRUCTURE),
            (StructureKind.FIRE, TileType.FIRE, MovementOutcome.STRUCTURE),
            (StructureKind.SHELTER, TileType.SHELTER, MovementOutcome.MOVED),
        ):
            with self.subTest(kind=kind):
                world = _world({Position(3, 2): tile})
                agent = _agent("ag_01", 2, 2)
                structure = Structure(kind, Position(3, 2))
                engine = TurnEngine(
                    _state((agent,), world=world, structures=(structure,)),
                    resolvers=movement_resolvers(),
                )
                engine.submit(_move_action("ag_01", 1, 0))

                result = engine.resolve()

                self.assertEqual(result.events[0].outcome, outcome.value)
                expected = Position(3, 2) if outcome is MovementOutcome.MOVED else Position(2, 2)
                self.assertEqual(engine.state.agents[0].position, expected)

    def test_living_agents_block_but_dead_agents_do_not(self) -> None:
        living = _agent("ag_02", 3, 2)
        engine = TurnEngine(
            _state((_agent("ag_01", 2, 2), living)),
            resolvers=movement_resolvers(),
        )
        engine.submit(_move_action("ag_01", 1, 0))

        result = engine.resolve()

        self.assertEqual(engine.state.agents[0].position, Position(2, 2))
        self.assertEqual(result.events[0].outcome, MovementOutcome.OCCUPIED.value)

        dead = _agent("ag_02", 3, 2, status=AgentStatus.DEAD, health_centi=0)
        engine = TurnEngine(
            _state((_agent("ag_01", 2, 2), dead)),
            resolvers=movement_resolvers(),
        )
        engine.submit(_move_action("ag_01", 1, 0))

        result = engine.resolve()

        self.assertEqual(engine.state.agents[0].position, Position(3, 2))
        self.assertEqual(result.events[0].outcome, MovementOutcome.MOVED.value)

    def test_ground_items_do_not_block(self) -> None:
        ground_item = GroundItem(Position(3, 2), ItemStack(BERRY, 1))
        engine = TurnEngine(
            _state((_agent("ag_01", 2, 2),), ground_items=(ground_item,)),
            resolvers=movement_resolvers(),
        )
        engine.submit(_move_action("ag_01", 1, 0))

        result = engine.resolve()

        self.assertEqual(engine.state.agents[0].position, Position(3, 2))
        self.assertEqual(result.events[0].outcome, MovementOutcome.MOVED.value)

    def test_water_is_walkable(self) -> None:
        world = _world({Position(3, 2): TileType.FRESH_WATER})
        engine = TurnEngine(
            _state((_agent("ag_01", 2, 2),), world=world),
            resolvers=movement_resolvers(),
        )
        engine.submit(_move_action("ag_01", 1, 0))

        result = engine.resolve()

        self.assertEqual(engine.state.agents[0].position, Position(3, 2))
        self.assertEqual(result.events[0].outcome, MovementOutcome.MOVED.value)

    def test_simultaneous_moves_resolve_by_initiative(self) -> None:
        agents = (_agent("ag_01", 2, 2), _agent("ag_02", 4, 2))
        actions = (
            _move_action("ag_01", 1, 0),
            _move_action("ag_02", -1, 0),
        )

        def run(
            first_initiative: int,
            second_initiative: int,
        ) -> tuple[TurnEngine, TurnResult]:
            engine = TurnEngine(_state(agents), resolvers=movement_resolvers())
            for action in actions:
                engine.submit(action)

            def fake_initiative(
                agent: Agent,
                seed: int,
                tick: int,
                weapon_speed: int = 0,
            ) -> int:
                return first_initiative if agent.agent_id == "ag_01" else second_initiative

            with patch("iasim.domain.turns.initiative", side_effect=fake_initiative):
                result = engine.resolve()
            return engine, result

        first_engine, first_result = run(20, 10)
        self.assertEqual(first_engine.state.agents[0].position, Position(3, 2))
        self.assertEqual(first_engine.state.agents[1].position, Position(4, 2))
        self.assertEqual(first_result.events[0].outcome, MovementOutcome.MOVED.value)
        self.assertEqual(first_result.events[1].outcome, MovementOutcome.OCCUPIED.value)

        second_engine, second_result = run(10, 20)
        self.assertEqual(second_engine.state.agents[0].position, Position(2, 2))
        self.assertEqual(second_engine.state.agents[1].position, Position(3, 2))
        self.assertEqual(second_result.events[0].outcome, MovementOutcome.MOVED.value)
        self.assertEqual(second_result.events[1].outcome, MovementOutcome.OCCUPIED.value)

    def test_invalid_directions_are_rejected(self) -> None:
        cases = (
            (),
            (("dx", 0), ("dy", 0)),
            (("dx", 2), ("dy", 0)),
            (("dx", "1"), ("dy", 0)),
            (("dx", True), ("dy", 0)),
            (("dx", 1),),
        )
        for payload in cases:
            with self.subTest(payload=payload):
                agent = _agent("ag_01", 2, 2)
                action = Action(AgentId("ag_01"), 0, ActionKind.MOVE, payload)
                state = _state((agent,))

                new_state, events = resolve_move(state, action)

                self.assertEqual(new_state, state)
                self.assertEqual(events[0].outcome, MovementOutcome.INVALID_DIRECTION.value)

    def test_unknown_agent_is_reported(self) -> None:
        state = _state((_agent("ag_01", 2, 2),))
        action = _move_action("ag_99", 1, 0)

        new_state, events = resolve_move(state, action)

        self.assertEqual(new_state, state)
        self.assertEqual(events[0].outcome, MovementOutcome.UNKNOWN_AGENT.value)

    def test_move_event_carries_kind_and_tick(self) -> None:
        engine = TurnEngine(
            _state((_agent("ag_01", 2, 2),)),
            resolvers=movement_resolvers(),
        )
        engine.submit(_move_action("ag_01", 1, 0))

        result = engine.resolve()

        event = result.events[0]
        self.assertEqual(event.agent_id, "ag_01")
        self.assertEqual(event.kind, ActionKind.MOVE)
        self.assertEqual(event.tick, 0)


if __name__ == "__main__":
    unittest.main()
