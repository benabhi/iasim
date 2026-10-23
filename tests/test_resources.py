"""Tests for deterministic resource depletion and regeneration."""

from __future__ import annotations

import unittest
from dataclasses import replace

from iasim.app.session import GameSession
from iasim.crafting import load_catalog
from iasim.domain.agents import AgentAttributes, AgentProfile
from iasim.domain.geometry import Position
from iasim.domain.hashing import canonical_state_hash
from iasim.domain.resources import (
    RESOURCE_REGENERATION_TICKS,
    ResourceNode,
    advance_resource_nodes,
    deplete_node,
    initial_resource_nodes,
    node_for,
)
from iasim.domain.tiles import TileType, WorldMap
from iasim.world.layout import WorldLayout


def _layout() -> WorldLayout:
    tiles = [TileType.GRASS] * 25
    tiles[2 * 5 + 3] = TileType.BUSH
    tiles[1 * 5 + 3] = TileType.TREE
    return WorldLayout(
        seed=42,
        world=WorldMap(width=5, height=5, tiles=tuple(tiles)),
        spawn_points=(Position(2, 2),),
    )


class ResourceNodeTests(unittest.TestCase):
    def test_advance_only_replenishes_due_regenerating_nodes(self) -> None:
        depleted = ResourceNode(
            Position(3, 2),
            "bush_berries",
            remaining=0,
            capacity=2,
            regrow_at_tick=RESOURCE_REGENERATION_TICKS,
        )
        finite = ResourceNode(
            Position(3, 1),
            "tree_logs",
            remaining=0,
            capacity=3,
        )

        before = advance_resource_nodes((depleted, finite), tick=RESOURCE_REGENERATION_TICKS - 1)
        after = advance_resource_nodes((depleted, finite), tick=RESOURCE_REGENERATION_TICKS)

        self.assertTrue(before[0].depleted)
        self.assertTrue(before[1].depleted)
        self.assertEqual(after[0].remaining, 2)
        self.assertIsNone(after[0].regrow_at_tick)
        self.assertTrue(after[1].depleted)

    def test_long_run_stays_bounded_and_never_exceeds_capacity(self) -> None:
        node = ResourceNode(
            Position(3, 2),
            "bush_berries",
            remaining=2,
            capacity=2,
        )

        for tick in range(0, RESOURCE_REGENERATION_TICKS * 20):
            if tick % RESOURCE_REGENERATION_TICKS == 0:
                node = deplete_node(node, tick=tick, regenerates=True)
            node = advance_resource_nodes((node,), tick=tick + 1)[0]

        self.assertEqual(node.capacity, 2)
        self.assertLessEqual(node.remaining, node.capacity)
        self.assertGreaterEqual(node.remaining, 0)

    def test_initial_nodes_are_unique_and_full(self) -> None:
        world = _layout().world
        nodes = initial_resource_nodes(world, load_catalog())

        keys = [(node.position, node.resource_id) for node in nodes]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(nodes)
        self.assertTrue(all(node.remaining == node.capacity for node in nodes))


class SessionResourceTests(unittest.TestCase):
    def test_gather_depletes_bush_and_observation_hides_it(self) -> None:
        session = GameSession(42, layout=_layout())
        agent_id = session.join("Nia", session.tokens[0])["agent_id"]
        target = Position(3, 2)

        gathered = session.gather(agent_id, 0, target.x, target.y)
        self.assertTrue(gathered["ok"])
        observation = session.observe(agent_id)
        target_tile = next(
            tile
            for tile in observation["perception"]["visible"]
            if tile["x"] == target.x and tile["y"] == target.y
        )
        target_memory = next(
            entry
            for entry in observation["perception"]["memory_updates"]
            if entry["x"] == target.x and entry["y"] == target.y
        )
        self.assertEqual(target_tile["resources"], [])
        self.assertEqual(target_memory["resources"], [])
        self.assertEqual(observation["last_action_result"]["outcome"], "gathered")
        self.assertEqual(session.state.agents[0].inventory.stack_for("berry").quantity, 2)

        depleted = session.gather(agent_id, 1, target.x, target.y)
        self.assertTrue(depleted["ok"])
        observation = session.observe(agent_id)
        self.assertEqual(observation["last_action_result"]["outcome"], "depleted")

    def test_tick_effects_regenerate_a_depleted_bush_on_schedule(self) -> None:
        profile = AgentProfile(
            attributes=AgentAttributes(
                hunger_centi=0,
                thirst_centi=0,
                energy_centi=100 * 100,
            )
        )
        session = GameSession(42, layout=_layout(), profiles=(profile,))
        agent_id = session.join("Nia", session.tokens[0])["agent_id"]
        target = Position(3, 2)
        self.assertTrue(session.gather(agent_id, 0, target.x, target.y)["ok"])
        depleted = node_for(session.state.resource_nodes, target, "bush_berries")
        assert depleted is not None
        self.assertTrue(depleted.depleted)

        while session.tick < RESOURCE_REGENERATION_TICKS:
            self.assertTrue(session.wait(agent_id, session.tick)["ok"])

        regenerated = node_for(session.state.resource_nodes, target, "bush_berries")
        assert regenerated is not None
        self.assertEqual(regenerated.remaining, 2)
        self.assertIsNone(regenerated.regrow_at_tick)

    def test_persistent_nodes_are_in_the_canonical_hash(self) -> None:
        session = GameSession(42, layout=_layout())
        self.assertTrue(session.state.resource_nodes)
        without_nodes = replace(session.state, resource_nodes=())

        self.assertNotEqual(
            canonical_state_hash(session.state),
            canonical_state_hash(without_nodes),
        )

    def test_node_lookup_uses_position_and_resource_id(self) -> None:
        session = GameSession(42, layout=_layout())
        node = node_for(
            session.state.resource_nodes,
            Position(3, 2),
            "bush_berries",
        )

        assert node is not None
        self.assertEqual(node.remaining, 2)


if __name__ == "__main__":
    unittest.main()
