"""Tests for fire, workbench, and shelter construction."""

from __future__ import annotations

import unittest

from iasim.crafting import load_catalog
from iasim.domain.actions import Action, ActionKind
from iasim.domain.agents import Agent
from iasim.domain.construction import (
    ConstructionOutcome,
    advance_fires,
    construction_resolvers,
)
from iasim.domain.geometry import Position
from iasim.domain.hashing import canonical_state_hash
from iasim.domain.identifiers import AgentId
from iasim.domain.items import GroundItem, Inventory, ItemStack
from iasim.domain.session import SessionState
from iasim.domain.tiles import TileType, WorldMap
from iasim.domain.turns import TurnEngine
from iasim.domain.weather import WeatherKind, WeatherState
from iasim.domain.world import Structure, StructureKind


def _world(
    *,
    target: TileType = TileType.GRASS,
    fire: Position | None = None,
    shelter: Position | None = None,
) -> WorldMap:
    tiles = [TileType.GRASS] * 49
    if target is not TileType.GRASS:
        tiles[2 * 7 + 3] = target
    if fire is not None:
        tiles[fire.y * 7 + fire.x] = TileType.FIRE
    if shelter is not None:
        tiles[shelter.y * 7 + shelter.x] = TileType.SHELTER
    return WorldMap(width=7, height=7, tiles=tuple(tiles))


def _agent(*kit_ids: str) -> Agent:
    catalog = load_catalog()
    inventory = Inventory.for_strength(5)
    for kit_id in kit_ids:
        inventory = inventory.add(ItemStack(catalog.item(kit_id).definition, 1))
    return Agent(AgentId("ag_01"), Position(2, 2), inventory=inventory)


def _state(
    agent: Agent,
    *,
    world: WorldMap | None = None,
    structures: tuple[Structure, ...] = (),
    ground_items: tuple[GroundItem, ...] = (),
    weather: WeatherState | None = None,
) -> SessionState:
    return SessionState(
        seed=42,
        tick=0,
        rng_state=42,
        world=_world() if world is None else world,
        agents=(agent,),
        structures=structures,
        ground_items=ground_items,
        weather=weather or WeatherState(),
    )


def _resolve(
    state: SessionState,
    *,
    structure_id: object = "fire",
    x: int = 3,
    y: int = 2,
) -> tuple[SessionState, str]:
    engine = TurnEngine(
        state,
        resolvers=construction_resolvers(load_catalog()),
    )
    engine.submit(
        Action(
            AgentId("ag_01"),
            0,
            ActionKind.BUILD,
            (("structure_id", structure_id), ("x", x), ("y", y)),
        )
    )
    result = engine.resolve()
    return engine.state, result.events[0].outcome


class ConstructionTests(unittest.TestCase):
    def test_build_fire_consumes_kit_and_replaces_the_tile(self) -> None:
        state, outcome = _resolve(_state(_agent("camp_kit")))

        self.assertEqual(outcome, ConstructionOutcome.BUILT.value)
        self.assertIsNone(state.agents[0].inventory.stack_for("camp_kit"))
        self.assertEqual(state.world.tile_at(Position(3, 2)), TileType.FIRE)
        self.assertEqual(state.structures[0].kind, StructureKind.FIRE)
        self.assertEqual(state.structures[0].fuel, 100)
        self.assertTrue(state.structures[0].lit)

    def test_build_workbench_and_shelter(self) -> None:
        workbench, workbench_outcome = _resolve(
            _state(_agent("workbench_kit")),
            structure_id="workbench",
        )
        shelter, shelter_outcome = _resolve(
            _state(_agent("shelter_kit")),
            structure_id="shelter",
        )

        self.assertEqual(workbench_outcome, ConstructionOutcome.BUILT.value)
        self.assertEqual(workbench.world.tile_at(Position(3, 2)), TileType.WORKBENCH)
        self.assertEqual(workbench.structures[0].kind, StructureKind.WORKBENCH)
        self.assertFalse(workbench.structures[0].lit)
        self.assertEqual(shelter_outcome, ConstructionOutcome.BUILT.value)
        self.assertEqual(shelter.world.tile_at(Position(3, 2)), TileType.SHELTER)
        self.assertEqual(shelter.structures[0].kind, StructureKind.SHELTER)

    def test_build_without_kit_is_atomic(self) -> None:
        state, outcome = _resolve(_state(_agent()))

        self.assertEqual(outcome, ConstructionOutcome.MISSING_KIT.value)
        self.assertEqual(state.world.tile_at(Position(3, 2)), TileType.GRASS)
        self.assertEqual(state.structures, ())

    def test_build_rejects_non_adjacent_targets(self) -> None:
        state, outcome = _resolve(_state(_agent("camp_kit")), x=4, y=2)

        self.assertEqual(outcome, ConstructionOutcome.NOT_IN_RANGE.value)
        self.assertEqual(state.world.tile_at(Position(4, 2)), TileType.GRASS)
        self.assertEqual(state.structures, ())

    def test_build_rejects_occupied_targets(self) -> None:
        catalog = load_catalog()
        ground = GroundItem(Position(3, 2), ItemStack(catalog.item("berry").definition, 1))
        state, outcome = _resolve(
            _state(_agent("camp_kit"), ground_items=(ground,)),
        )

        self.assertEqual(outcome, ConstructionOutcome.OCCUPIED.value)
        self.assertEqual(state.ground_items, (ground,))
        self.assertEqual(state.structures, ())

    def test_build_rejects_impassable_terrain(self) -> None:
        state, outcome = _resolve(
            _state(_agent("camp_kit"), world=_world(target=TileType.ROCK)),
        )

        self.assertEqual(outcome, ConstructionOutcome.INVALID_TERRAIN.value)
        self.assertEqual(state.structures, ())

    def test_build_rejects_unknown_structure(self) -> None:
        state, outcome = _resolve(
            _state(_agent("camp_kit")),
            structure_id="tower",
        )

        self.assertEqual(outcome, ConstructionOutcome.UNKNOWN_STRUCTURE.value)
        self.assertEqual(state.structures, ())


class FireTickTests(unittest.TestCase):
    def _state_with_fire(
        self,
        *,
        fuel: int,
        lit: bool,
        weather: WeatherState,
        sheltered: bool = False,
    ) -> SessionState:
        fire_position = Position(2, 1)
        shelter_position = Position(3, 2)
        structures = [Structure(StructureKind.FIRE, fire_position, fuel=fuel, lit=lit)]
        if sheltered:
            structures.append(Structure(StructureKind.SHELTER, shelter_position))
        world = _world(
            fire=fire_position,
            shelter=shelter_position if sheltered else None,
        )
        return _state(
            _agent(),
            world=world,
            structures=tuple(structures),
            weather=weather,
        )

    def test_clear_weather_consumes_one_fuel_per_tick(self) -> None:
        state = self._state_with_fire(
            fuel=2,
            lit=True,
            weather=WeatherState(kind=WeatherKind.CLEAR),
        )

        once = advance_fires(state)
        twice = advance_fires(once)

        self.assertEqual(once.structures[0].fuel, 1)
        self.assertTrue(once.structures[0].lit)
        self.assertEqual(twice.structures[0].fuel, 0)
        self.assertFalse(twice.structures[0].lit)

    def test_rain_extinguishes_an_exposed_fire(self) -> None:
        state = self._state_with_fire(
            fuel=50,
            lit=True,
            weather=WeatherState(kind=WeatherKind.RAIN),
        )

        advanced = advance_fires(state)

        self.assertFalse(advanced.structures[0].lit)
        self.assertEqual(advanced.structures[0].fuel, 50)

    def test_adjacent_shelter_keeps_fire_lit_in_rain(self) -> None:
        state = self._state_with_fire(
            fuel=50,
            lit=True,
            weather=WeatherState(kind=WeatherKind.RAIN),
            sheltered=True,
        )

        advanced = advance_fires(state)

        self.assertTrue(advanced.structures[0].lit)
        self.assertEqual(advanced.structures[0].fuel, 49)

    def test_shelter_blocks_the_storm_wind_fuel_penalty(self) -> None:
        state = self._state_with_fire(
            fuel=50,
            lit=True,
            weather=WeatherState(kind=WeatherKind.STORM, wind=10),
            sheltered=True,
        )

        advanced = advance_fires(state)

        self.assertEqual(advanced.structures[0].fuel, 49)

    def test_fire_fuel_is_part_of_the_canonical_hash(self) -> None:
        state = self._state_with_fire(
            fuel=50,
            lit=True,
            weather=WeatherState(kind=WeatherKind.CLEAR),
        )
        advanced = advance_fires(state)

        self.assertNotEqual(
            canonical_state_hash(state),
            canonical_state_hash(advanced),
        )


if __name__ == "__main__":
    unittest.main()
