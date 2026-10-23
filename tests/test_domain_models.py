"""Tests for the core domain models."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from iasim.domain.agents import Agent, AgentAttributes, AgentProfile, AgentStatus
from iasim.domain.geometry import Position
from iasim.domain.identifiers import AgentId, ItemId
from iasim.domain.items import (
    BASE_SLOTS,
    GroundItem,
    Inventory,
    ItemDefinition,
    ItemStack,
)
from iasim.domain.rng import U64_MASK
from iasim.domain.session import SessionState
from iasim.domain.tiles import TileType, WorldMap
from iasim.domain.world import Structure, StructureKind

WOOD = ItemDefinition(ItemId("wood"), 1000, True, 99)
BERRY = ItemDefinition(ItemId("berry"), 50, True, 99)
SPEAR = ItemDefinition(ItemId("stone_spear"), 2000, False)


def _world_with_shelter() -> WorldMap:
    return WorldMap(
        width=3,
        height=3,
        tiles=(
            TileType.SHELTER,
            TileType.GRASS,
            TileType.GRASS,
            TileType.GRASS,
            TileType.GRASS,
            TileType.GRASS,
            TileType.GRASS,
            TileType.GRASS,
            TileType.GRASS,
        ),
    )


class PositionTests(unittest.TestCase):
    def test_rejects_negative_coordinates(self) -> None:
        with self.assertRaises(ValueError):
            Position(-1, 0)
        with self.assertRaises(ValueError):
            Position(0, -1)

    def test_is_hashable_and_comparable(self) -> None:
        self.assertEqual(Position(1, 2), Position(1, 2))
        self.assertEqual({Position(1, 2)}, {Position(1, 2)})


class TileTypeTests(unittest.TestCase):
    def test_deep_water_blocks_movement_and_vision(self) -> None:
        tile = TileType.DEEP_WATER

        self.assertFalse(tile.walkable)
        self.assertFalse(tile.transparent)
        self.assertIsNone(tile.movement_cost)
        self.assertFalse(tile.drinkable)

    def test_shallow_water_is_walkable_at_double_cost(self) -> None:
        tile = TileType.SHALLOW_WATER

        self.assertTrue(tile.walkable)
        self.assertTrue(tile.transparent)
        self.assertEqual(tile.movement_cost, 2)
        self.assertFalse(tile.drinkable)

    def test_fresh_water_is_drinkable_at_double_cost(self) -> None:
        tile = TileType.FRESH_WATER

        self.assertEqual(tile.movement_cost, 2)
        self.assertTrue(tile.drinkable)

    def test_land_tiles_have_unit_cost(self) -> None:
        for tile in (
            TileType.SAND,
            TileType.GRASS,
            TileType.TALL_GRASS,
            TileType.BUSH,
            TileType.SHELTER,
        ):
            with self.subTest(tile=tile):
                self.assertTrue(tile.walkable)
                self.assertEqual(tile.movement_cost, 1)

    def test_obstacles_block_movement(self) -> None:
        for tile in (
            TileType.TREE,
            TileType.PALM,
            TileType.ROCK,
            TileType.WORKBENCH,
            TileType.FIRE,
        ):
            with self.subTest(tile=tile):
                self.assertFalse(tile.walkable)
                self.assertIsNone(tile.movement_cost)


class WorldMapTests(unittest.TestCase):
    def test_filled_map_returns_tiles_by_coordinate(self) -> None:
        world = WorldMap.filled(2, 2, TileType.GRASS)

        self.assertTrue(world.contains(Position(1, 1)))
        self.assertFalse(world.contains(Position(2, 0)))
        self.assertEqual(world.tile_at(Position(1, 1)), TileType.GRASS)

    def test_tile_at_rejects_out_of_bounds(self) -> None:
        world = WorldMap.filled(2, 2, TileType.GRASS)

        with self.assertRaises(ValueError):
            world.tile_at(Position(2, 0))
        with self.assertRaises(ValueError):
            world.tile_at(Position(0, 2))

    def test_tile_count_must_match_dimensions(self) -> None:
        with self.assertRaises(ValueError):
            WorldMap(width=2, height=2, tiles=(TileType.GRASS,))

    def test_dimensions_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            WorldMap(width=0, height=1, tiles=())
        with self.assertRaises(ValueError):
            WorldMap(width=1, height=0, tiles=())

    def test_tiles_must_be_tile_types(self) -> None:
        with self.assertRaises(ValueError):
            WorldMap(width=1, height=1, tiles=("grass",))  # type: ignore[arg-type]


class ItemModelTests(unittest.TestCase):
    def test_item_definition_rejects_invalid_fields(self) -> None:
        with self.assertRaises(ValueError):
            ItemDefinition(ItemId("Wood"), 1, True)
        with self.assertRaises(ValueError):
            ItemDefinition(ItemId("wood"), -1, True)
        with self.assertRaises(ValueError):
            ItemDefinition(ItemId("wood"), 1, True, max_stack=0)
        with self.assertRaises(ValueError):
            ItemDefinition(ItemId("wood"), 1, False, max_stack=2)

    def test_stack_enforces_quantity_and_max_stack(self) -> None:
        self.assertEqual(ItemStack(WOOD, 3).total_weight_grams, 3000)

        with self.assertRaises(ValueError):
            ItemStack(WOOD, 0)
        with self.assertRaises(ValueError):
            ItemStack(WOOD, 100)
        with self.assertRaises(ValueError):
            ItemStack(SPEAR, 2)

    def test_inventory_rejects_duplicate_items(self) -> None:
        with self.assertRaises(ValueError):
            Inventory(stacks=(ItemStack(WOOD, 1), ItemStack(WOOD, 2)))

    def test_inventory_enforces_slots_and_weight(self) -> None:
        stacks = tuple(
            ItemStack(ItemDefinition(ItemId(f"item_{index}"), 1, True), 1) for index in range(11)
        )

        with self.assertRaises(ValueError):
            Inventory(stacks=stacks)
        with self.assertRaises(ValueError):
            Inventory(stacks=(ItemStack(WOOD, 21),))

        inventory = Inventory(stacks=(ItemStack(WOOD, 3), ItemStack(BERRY, 2)))
        self.assertEqual(inventory.total_weight_grams, 3100)
        self.assertFalse(inventory.is_empty)
        self.assertTrue(Inventory().is_empty)

    def test_inventory_for_strength_uses_srs_capacity(self) -> None:
        inventory = Inventory.for_strength(5)

        self.assertEqual(inventory.max_slots, BASE_SLOTS)
        self.assertEqual(inventory.max_weight_grams, 20_000)
        self.assertEqual(Inventory.for_strength(10).max_weight_grams, 30_000)

        with self.assertRaises(ValueError):
            Inventory.for_strength(0)
        with self.assertRaises(ValueError):
            Inventory.for_strength(11)
        with self.assertRaises(ValueError):
            Inventory.for_strength(5, bonus_slots=-1)
        with self.assertRaises(ValueError):
            Inventory.for_strength(5, bonus_weight_grams=-1)


class AgentAttributeTests(unittest.TestCase):
    def test_defaults_match_srs(self) -> None:
        attributes = AgentAttributes()

        self.assertEqual(attributes.health_centi, 10_000)
        self.assertEqual(attributes.health, 100.0)
        self.assertEqual(attributes.hunger, 15.0)
        self.assertEqual(attributes.thirst, 15.0)
        self.assertEqual(attributes.energy, 80.0)
        self.assertEqual(attributes.body_temperature_c, 37.0)
        self.assertEqual(attributes.vision, 8)
        self.assertEqual(attributes.strength, 5)

    def test_rejects_out_of_range_values(self) -> None:
        invalid = [
            {"health_centi": 10_001},
            {"hunger_centi": -1},
            {"thirst_centi": 10_001},
            {"energy_centi": -1},
            {"wetness_centi": 10_001},
            {"body_temperature_centi": 3_399},
            {"body_temperature_centi": 4_201},
            {"vision": 2},
            {"vision": 13},
            {"strength": 0},
            {"strength": 11},
            {"dexterity": 0},
            {"endurance": 11},
        ]

        for kwargs in invalid:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                AgentAttributes(**kwargs)


class AgentTests(unittest.TestCase):
    def test_default_agent_is_alive_and_has_base_inventory(self) -> None:
        agent = Agent(AgentId("ag_01"), Position(1, 1))

        self.assertTrue(agent.is_alive)
        self.assertEqual(agent.status, AgentStatus.ACTIVE)
        self.assertEqual(agent.inventory.max_weight_grams, 20_000)

    def test_rejects_invalid_agent_id(self) -> None:
        with self.assertRaises(ValueError):
            Agent(AgentId("agent_1"), Position(0, 0))

    def test_dead_agent_requires_zero_health(self) -> None:
        dead = Agent(
            AgentId("ag_01"),
            Position(1, 1),
            attributes=AgentAttributes(health_centi=0),
            status=AgentStatus.DEAD,
        )

        self.assertFalse(dead.is_alive)
        with self.assertRaises(ValueError):
            Agent(AgentId("ag_01"), Position(1, 1), status=AgentStatus.DEAD)
        with self.assertRaises(ValueError):
            Agent(AgentId("ag_01"), Position(1, 1), attributes=AgentAttributes(health_centi=0))

    def test_inventory_must_cover_strength_and_base_slots(self) -> None:
        with self.assertRaises(ValueError):
            Agent(AgentId("ag_01"), Position(1, 1), attributes=AgentAttributes(strength=10))

        Agent(
            AgentId("ag_01"),
            Position(1, 1),
            attributes=AgentAttributes(strength=10),
            inventory=Inventory.for_strength(10),
        )

        with self.assertRaises(ValueError):
            Agent(
                AgentId("ag_01"),
                Position(1, 1),
                inventory=Inventory(max_slots=9, max_weight_grams=20_000),
            )

    def test_rejects_non_enum_status(self) -> None:
        with self.assertRaises(ValueError):
            Agent(AgentId("ag_01"), Position(1, 1), status="active")  # type: ignore[arg-type]

    def test_profile_builds_inventory_for_custom_strength(self) -> None:
        profile = AgentProfile(attributes=AgentAttributes(strength=10))

        agent = profile.build(AgentId("ag_01"), Position(1, 1))

        self.assertEqual(agent.attributes.strength, 10)
        self.assertEqual(agent.inventory.max_weight_grams, 30_000)


class StructureTests(unittest.TestCase):
    def test_kind_maps_to_tile(self) -> None:
        self.assertEqual(StructureKind.WORKBENCH.tile, TileType.WORKBENCH)
        self.assertEqual(StructureKind.SHELTER.tile, TileType.SHELTER)
        self.assertEqual(StructureKind.FIRE.tile, TileType.FIRE)

    def test_rejects_non_enum_kind(self) -> None:
        with self.assertRaises(ValueError):
            Structure(kind="fire", position=Position(0, 0))  # type: ignore[arg-type]


class SessionStateTests(unittest.TestCase):
    def _valid_state(self) -> SessionState:
        world = _world_with_shelter()
        agent = Agent(AgentId("ag_01"), Position(1, 1))
        shelter = Structure(StructureKind.SHELTER, Position(0, 0))
        ground_item = GroundItem(Position(2, 2), ItemStack(BERRY, 3))
        return SessionState(
            seed=42,
            tick=0,
            rng_state=42,
            world=world,
            agents=(agent,),
            structures=(shelter,),
            ground_items=(ground_item,),
        )

    def test_accepts_a_consistent_state(self) -> None:
        state = self._valid_state()

        self.assertEqual(state.seed, 42)
        self.assertEqual(state.tick, 0)
        self.assertEqual(state.agents[0].agent_id, "ag_01")
        self.assertEqual(state.world.tile_at(Position(0, 0)), TileType.SHELTER)

    def test_accepts_the_maximum_rng_state(self) -> None:
        state = SessionState(
            seed=0,
            tick=0,
            rng_state=U64_MASK,
            world=WorldMap.filled(1, 1, TileType.GRASS),
        )

        self.assertEqual(state.rng_state, U64_MASK)

    def test_rejects_negative_seed_tick_and_bad_rng_state(self) -> None:
        world = WorldMap.filled(1, 1, TileType.GRASS)

        with self.assertRaises(ValueError):
            SessionState(seed=-1, tick=0, rng_state=0, world=world)
        with self.assertRaises(ValueError):
            SessionState(seed=0, tick=-1, rng_state=0, world=world)
        with self.assertRaises(ValueError):
            SessionState(seed=0, tick=0, rng_state=-1, world=world)
        with self.assertRaises(ValueError):
            SessionState(seed=0, tick=0, rng_state=U64_MASK + 1, world=world)
        with self.assertRaises(ValueError):
            SessionState(seed=0, tick=0, rng_state=0, world=world, tick_minutes=0)

    def test_rejects_duplicate_agent_ids(self) -> None:
        world = WorldMap.filled(3, 3, TileType.GRASS)
        first = Agent(AgentId("ag_01"), Position(0, 0))
        second = Agent(AgentId("ag_01"), Position(1, 1))

        with self.assertRaises(ValueError):
            SessionState(seed=0, tick=0, rng_state=0, world=world, agents=(first, second))

    def test_rejects_agent_outside_or_on_impassable_tile(self) -> None:
        world = WorldMap.filled(2, 2, TileType.GRASS)

        with self.assertRaises(ValueError):
            SessionState(
                seed=0,
                tick=0,
                rng_state=0,
                world=world,
                agents=(Agent(AgentId("ag_01"), Position(2, 0)),),
            )

        water = WorldMap.filled(1, 1, TileType.DEEP_WATER)
        with self.assertRaises(ValueError):
            SessionState(
                seed=0,
                tick=0,
                rng_state=0,
                world=water,
                agents=(Agent(AgentId("ag_01"), Position(0, 0)),),
            )

    def test_rejects_structure_mismatch_duplicates_and_bounds(self) -> None:
        world = _world_with_shelter()

        with self.assertRaises(ValueError):
            SessionState(
                seed=0,
                tick=0,
                rng_state=0,
                world=world,
                structures=(Structure(StructureKind.SHELTER, Position(1, 1)),),
            )
        with self.assertRaises(ValueError):
            SessionState(
                seed=0,
                tick=0,
                rng_state=0,
                world=world,
                structures=(
                    Structure(StructureKind.SHELTER, Position(0, 0)),
                    Structure(StructureKind.SHELTER, Position(0, 0)),
                ),
            )
        with self.assertRaises(ValueError):
            SessionState(
                seed=0,
                tick=0,
                rng_state=0,
                world=world,
                structures=(Structure(StructureKind.SHELTER, Position(3, 0)),),
            )

    def test_rejects_ground_item_outside_the_world(self) -> None:
        world = WorldMap.filled(1, 1, TileType.GRASS)

        with self.assertRaises(ValueError):
            SessionState(
                seed=0,
                tick=0,
                rng_state=0,
                world=world,
                ground_items=(GroundItem(Position(1, 0), ItemStack(BERRY, 1)),),
            )


class DomainBoundaryTests(unittest.TestCase):
    def test_domain_has_no_forbidden_imports(self) -> None:
        domain_dir = Path(__file__).resolve().parents[1] / "src" / "iasim" / "domain"
        forbidden = ("iasim.ui", "iasim.mcp", "iasim.persistence", "random")

        for path in sorted(domain_dir.glob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module is not None:
                    modules = [node.module]
                else:
                    continue
                for module in modules:
                    self.assertFalse(
                        any(
                            module == prefix or module.startswith(prefix + ".")
                            for prefix in forbidden
                        ),
                        f"{path.name} imports forbidden module {module}",
                    )


if __name__ == "__main__":
    unittest.main()
