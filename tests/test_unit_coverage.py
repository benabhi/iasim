"""Focused unit coverage for the MVP domains named by RF-1304.

Coverage matrix (existing suites + the gaps closed here):

- world: tests/test_world_generation.py, test_world_validation.py,
  test_domain_models.py, test_resources.py. Gap closed here: WorldMap rejects
  invalid dimensions/tile counts and out-of-bounds indexing through both
  ``contains`` and ``tile_at``.
- needs: tests/test_needs.py. Gaps closed here: ambient cold does not reduce
  thirst below the 20 C baseline, and health does not recover outside the
  36-38 C safe range even when hunger/thirst/energy are stable.
- FOV: tests/test_tcod_fov.py, test_climate.py, test_observation.py. Gaps
  closed here: corner maps stay bounded at radius one and an opaque origin
  still sees its own tile.
- crafting: tests/test_crafting_actions.py, test_construction.py,
  test_catalog.py. Gaps closed here: a non-adjacent workbench does not satisfy
  the station and a diagonally adjacent workbench does (Chebyshev adjacency).
- combat: tests/test_combat.py, test_throwing.py, test_flee.py,
  test_bleeding.py, test_status.py. Gap closed here: attacking an already dead
  target is rejected without consuming RNG.
- persistence: tests/test_save_load.py, test_snapshots.py, test_replay.py,
  test_export.py, test_golden_seed.py. Gap closed here: a payload missing a
  required section raises SnapshotError instead of a bare KeyError.

Known gaps outside this task: the 8-agent 1000-tick performance budget
(iasim-qul.5), real multi-machine LAN validation (iasim-qul.6), and the
three-day scenario (iasim-qul.7).
"""

from __future__ import annotations

import unittest

from iasim.crafting import load_catalog
from iasim.domain.actions import Action, ActionKind
from iasim.domain.agents import Agent, AgentAttributes, AgentStatus
from iasim.domain.combat import CombatOutcome, combat_resolvers
from iasim.domain.crafting_actions import CraftingOutcome, crafting_resolvers
from iasim.domain.geometry import Position
from iasim.domain.identifiers import AgentId
from iasim.domain.items import Inventory
from iasim.domain.needs import apply_needs_tick
from iasim.domain.session import SessionState
from iasim.domain.tiles import TileType, WorldMap
from iasim.domain.turns import ResolvedAction, TurnEngine
from iasim.domain.world import Structure, StructureKind
from iasim.persistence.state import (
    SnapshotError,
    state_from_payload,
    state_to_payload,
)
from iasim.world.tcod_fov import compute_fov


def _world(width: int = 7, height: int = 7) -> WorldMap:
    return WorldMap(
        width=width,
        height=height,
        tiles=(TileType.GRASS,) * (width * height),
    )


class WorldEdgeTests(unittest.TestCase):
    def test_invalid_dimensions_and_tile_counts_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            WorldMap(width=0, height=1, tiles=())
        with self.assertRaises(ValueError):
            WorldMap(width=2, height=2, tiles=(TileType.GRASS,))
        with self.assertRaises(ValueError):
            WorldMap(width=2, height=2, tiles=("grass",) * 4)  # type: ignore[arg-type]

    def test_out_of_bounds_access_is_rejected(self) -> None:
        world = _world(3, 3)

        self.assertFalse(world.contains(Position(3, 0)))
        self.assertFalse(world.contains(Position(0, 3)))
        with self.assertRaises(ValueError):
            world.tile_at(Position(3, 0))
        with self.assertRaises(ValueError):
            world.tile_at(Position(0, 3))


class NeedsEdgeTests(unittest.TestCase):
    def _attributes(self, *, ambient: int, **overrides: int) -> AgentAttributes:
        defaults = {
            "health_centi": 10_000,
            "hunger_centi": 1_500,
            "thirst_centi": 1_500,
            "energy_centi": 8_000,
            "body_temperature_centi": 3_700,
        }
        defaults.update(overrides)
        agent = Agent(
            AgentId("ag_01"),
            Position(2, 2),
            attributes=AgentAttributes(**defaults),
        )
        state = SessionState(
            seed=1,
            tick=0,
            rng_state=1,
            world=_world(5, 5),
            agents=(agent,),
        )
        resolved = (ResolvedAction(AgentId("ag_01"), ActionKind.WAIT, 10),)
        return (
            apply_needs_tick(
                state,
                resolved,
                ambient_temperature_centi=ambient,
            )
            .agents[0]
            .attributes
        )

    def test_cold_ambient_does_not_reduce_thirst_below_the_baseline(self) -> None:
        cold = self._attributes(ambient=500)
        temperate = self._attributes(ambient=2_000)

        self.assertEqual(cold.thirst_centi, temperate.thirst_centi)
        self.assertEqual(cold.hunger_centi, temperate.hunger_centi)

    def test_health_does_not_recover_outside_the_safe_temperature_range(
        self,
    ) -> None:
        cold = self._attributes(ambient=2_000, health_centi=9_999, body_temperature_centi=3_500)
        hot = self._attributes(ambient=2_000, health_centi=9_999, body_temperature_centi=3_900)

        self.assertEqual(cold.health_centi, 9_999)
        self.assertEqual(hot.health_centi, 9_999)


class FovEdgeTests(unittest.TestCase):
    def test_corner_origin_stays_in_bounds_at_radius_one(self) -> None:
        visible = compute_fov(_world(), Position(0, 0), 1)

        self.assertEqual(visible, compute_fov(_world(), Position(0, 0), 1))
        self.assertIn(Position(0, 0), visible)
        self.assertTrue(all(0 <= position.x < 7 and 0 <= position.y < 7 for position in visible))

    def test_an_opaque_origin_still_sees_its_own_tile(self) -> None:
        tiles = [TileType.GRASS] * 49
        tiles[0] = TileType.TREE
        world = WorldMap(width=7, height=7, tiles=tuple(tiles))

        visible = compute_fov(world, Position(0, 0), 3)

        self.assertIn(Position(0, 0), visible)


class CraftingStationEdgeTests(unittest.TestCase):
    def _craft(
        self,
        *,
        workbench: Position,
    ) -> str:
        catalog = load_catalog()
        inventory = Inventory.for_strength(5)
        for item_id, quantity in (
            ("wood", 1),
            ("stone", 2),
            ("sharp_stone", 1),
            ("fiber", 1),
        ):
            inventory = inventory.add_quantity(
                catalog.item(item_id).definition,
                quantity,
            )
        agent = Agent(AgentId("ag_01"), Position(2, 2), inventory=inventory)
        tiles = [TileType.GRASS] * 49
        tiles[workbench.y * 7 + workbench.x] = TileType.WORKBENCH
        state = SessionState(
            seed=42,
            tick=0,
            rng_state=42,
            world=WorldMap(width=7, height=7, tiles=tuple(tiles)),
            agents=(agent,),
            structures=(Structure(StructureKind.WORKBENCH, workbench),),
        )
        engine = TurnEngine(state, resolvers=crafting_resolvers(catalog))
        engine.submit(
            Action(
                AgentId("ag_01"),
                0,
                ActionKind.CRAFT,
                (("recipe_id", "stone_axe"),),
            )
        )
        return engine.resolve().events[0].outcome

    def test_a_distant_workbench_does_not_satisfy_the_station(self) -> None:
        self.assertEqual(
            self._craft(workbench=Position(4, 2)),
            CraftingOutcome.STATION_REQUIRED.value,
        )

    def test_a_diagonally_adjacent_workbench_satisfies_the_station(self) -> None:
        self.assertEqual(
            self._craft(workbench=Position(3, 3)),
            CraftingOutcome.CRAFTED.value,
        )


class CombatEdgeTests(unittest.TestCase):
    def test_attacking_a_dead_target_is_rejected_without_consuming_rng(
        self,
    ) -> None:
        attacker = Agent(AgentId("ag_01"), Position(2, 2))
        dead = Agent(
            AgentId("ag_02"),
            Position(3, 2),
            attributes=AgentAttributes(health_centi=0),
            status=AgentStatus.DEAD,
        )
        state = SessionState(
            seed=1,
            tick=0,
            rng_state=1,
            world=_world(6, 6),
            agents=(attacker, dead),
        )
        engine = TurnEngine(state, resolvers=combat_resolvers())
        engine.submit(
            Action(
                AgentId("ag_01"),
                0,
                ActionKind.ATTACK,
                (("target_id", "ag_02"),),
            )
        )

        result = engine.resolve()

        self.assertEqual(result.events[0].outcome, CombatOutcome.INVALID_TARGET.value)
        self.assertEqual(engine.state.rng_state, state.rng_state)
        self.assertEqual(engine.state.agents[1].attributes.health_centi, 0)


class PersistenceEdgeTests(unittest.TestCase):
    def test_a_payload_missing_a_required_section_raises_snapshot_error(
        self,
    ) -> None:
        catalog = load_catalog()
        agent = Agent(AgentId("ag_01"), Position(2, 2))
        state = SessionState(
            seed=1,
            tick=0,
            rng_state=1,
            world=_world(),
            agents=(agent,),
        )
        payload = state_to_payload(state)
        del payload["agents"]

        with self.assertRaises(SnapshotError):
            state_from_payload(payload, catalog)


if __name__ == "__main__":
    unittest.main()
