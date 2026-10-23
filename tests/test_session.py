"""Tests for the application-level game session."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from iasim.app.session import GameSession, SessionPhase
from iasim.crafting import load_catalog
from iasim.domain.agents import AgentAttributes, AgentProfile
from iasim.domain.geometry import Position
from iasim.domain.identifiers import ItemId
from iasim.domain.items import Inventory, ItemDefinition, ItemStack
from iasim.domain.tiles import TileType, WorldMap
from iasim.world.layout import WorldLayout


def _layout(
    spawns: tuple[Position, ...] = (Position(2, 2),),
    *,
    blocked: Position | None = None,
) -> WorldLayout:
    tiles = [TileType.GRASS] * 25
    if blocked is not None:
        tiles[blocked.y * 5 + blocked.x] = TileType.DEEP_WATER
    return WorldLayout(
        seed=42,
        world=WorldMap(width=5, height=5, tiles=tuple(tiles)),
        spawn_points=spawns,
    )


def _session(layout: WorldLayout | None = None, **kwargs: object) -> GameSession:
    return GameSession(42, layout=layout if layout is not None else _layout(), **kwargs)


def _join(session: GameSession, name: str, slot: int = 0) -> dict[str, object]:
    return session.join(name, session.tokens[slot])


class GameSessionTests(unittest.TestCase):
    def test_open_session_waits_without_agents_and_runs_after_join(self) -> None:
        session = _session()

        self.assertEqual(session.phase, SessionPhase.WAITING)
        self.assertEqual(session.joined_agents, 0)
        self.assertEqual(session.alive_agents, 0)
        self.assertEqual(session.max_agents, 1)

        joined = _join(session, "Nia")

        self.assertTrue(joined["ok"])
        self.assertEqual(joined["phase"], "running")
        self.assertEqual(joined["session"]["joined_agents"], 1)
        self.assertEqual(joined["session"]["max_agents"], 1)
        self.assertEqual(session.phase, SessionPhase.RUNNING)
        self.assertEqual(session.health()["phase"], "running")

    def test_join_and_observation_do_not_expose_the_map(self) -> None:
        session = _session()

        joined = _join(session, "Nia")
        observation = session.observe(joined["agent_id"])

        self.assertTrue(joined["ok"])
        self.assertEqual(joined["agent_id"], "ag_01")
        self.assertEqual(joined["spawn"], [2, 2])
        self.assertEqual(joined["tick"], 0)
        self.assertEqual(observation["tick"], 0)
        self.assertEqual(observation["session"]["phase"], "running")
        self.assertEqual(observation["session"]["joined_agents"], 1)
        self.assertEqual(observation["agent"]["name"], "Nia")
        self.assertEqual(observation["agent"]["pos"], [2, 2])
        self.assertEqual(observation["time"]["day"], 1)
        self.assertEqual(observation["time"]["hour"], 6)
        self.assertEqual(observation["time"]["phase"], "dawn")
        self.assertNotIn("world", observation)
        self.assertNotIn("seed", observation)
        self.assertNotIn("rng_state", observation)
        self.assertNotIn("tiles", observation)
        self.assertLessEqual(len(observation["perception"]["visible"]), 49)
        self.assertEqual(
            {action["action"] for action in observation["available_actions"]},
            {
                "move",
                "move_to",
                "wait",
                "gather",
                "pickup",
                "drop",
                "eat",
                "drink",
                "fill",
                "craft",
                "build",
                "rest",
                "sleep",
            },
        )

    def test_move_advances_tick_and_updates_position(self) -> None:
        session = _session()
        agent_id = _join(session, "Nia")["agent_id"]

        result = session.move(agent_id, 0, 1, 0)
        observation = session.observe(agent_id)

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "queued")
        self.assertEqual(observation["tick"], 1)
        self.assertEqual(observation["agent"]["pos"], [3, 2])
        self.assertEqual(observation["last_action_result"]["status"], "success")
        self.assertEqual(observation["last_action_result"]["action"], "move")
        self.assertEqual(observation["last_action_result"]["outcome"], "moved")
        self.assertAlmostEqual(observation["agent"]["hunger"], 15.35, places=2)
        self.assertAlmostEqual(observation["agent"]["thirst"], 15.66, places=2)
        self.assertAlmostEqual(observation["agent"]["energy"], 79.75, places=2)

    def test_wait_advances_tick_without_moving(self) -> None:
        session = _session()
        agent_id = _join(session, "Nia")["agent_id"]
        session.move(agent_id, 0, 1, 0)

        result = session.wait(agent_id, 1)
        observation = session.observe(agent_id)

        self.assertTrue(result["ok"])
        self.assertEqual(observation["tick"], 2)
        self.assertEqual(observation["agent"]["pos"], [3, 2])
        self.assertEqual(observation["last_action_result"]["action"], "wait")
        self.assertEqual(observation["last_action_result"]["outcome"], "waited")

    def test_gather_updates_inventory_and_reports_the_action(self) -> None:
        tiles = [TileType.GRASS] * 25
        tiles[2 * 5 + 3] = TileType.BUSH
        layout = WorldLayout(
            seed=42,
            world=WorldMap(width=5, height=5, tiles=tuple(tiles)),
            spawn_points=(Position(2, 2),),
        )
        session = _session(layout)
        agent_id = _join(session, "Nia")["agent_id"]

        result = session.gather(agent_id, 0, 3, 2)
        observation = session.observe(agent_id)

        self.assertTrue(result["ok"])
        self.assertEqual(observation["tick"], 1)
        self.assertEqual(observation["last_action_result"]["action"], "gather")
        self.assertEqual(observation["last_action_result"]["outcome"], "gathered")
        self.assertEqual(
            observation["inventory"]["items"][0]["item_id"],
            "berry",
        )
        self.assertEqual(observation["inventory"]["items"][0]["qty"], 2)

    def test_eat_updates_needs_and_inventory_in_the_session(self) -> None:
        catalog = load_catalog()
        inventory = Inventory.for_strength(5).add(ItemStack(catalog.item("berry").definition, 1))
        session = _session(profiles=(AgentProfile(inventory=inventory),))
        agent_id = _join(session, "Nia")["agent_id"]

        result = session.eat(agent_id, 0, "berry")
        observation = session.observe(agent_id)

        self.assertTrue(result["ok"])
        self.assertEqual(observation["last_action_result"]["action"], "eat")
        self.assertEqual(observation["last_action_result"]["status"], "success")
        self.assertEqual(observation["inventory"]["items"], [])
        self.assertLess(observation["agent"]["hunger"], 1.0)

    def test_craft_updates_inventory_and_reports_the_action(self) -> None:
        catalog = load_catalog()
        inventory = Inventory.for_strength(5).add_quantity(
            catalog.item("stone").definition,
            2,
        )
        session = _session(profiles=(AgentProfile(inventory=inventory),))
        agent_id = _join(session, "Nia")["agent_id"]

        result = session.craft(agent_id, 0, "sharp_stone")
        observation = session.observe(agent_id)

        self.assertTrue(result["ok"])
        self.assertEqual(observation["last_action_result"]["action"], "craft")
        self.assertEqual(observation["last_action_result"]["status"], "success")
        self.assertIsNone(
            next(
                (item for item in observation["inventory"]["items"] if item["item_id"] == "stone"),
                None,
            )
        )
        self.assertEqual(
            next(
                item
                for item in observation["inventory"]["items"]
                if item["item_id"] == "sharp_stone"
            )["qty"],
            1,
        )

    def test_build_places_a_structure_and_reports_the_action(self) -> None:
        catalog = load_catalog()
        inventory = Inventory.for_strength(5).add(ItemStack(catalog.item("camp_kit").definition, 1))
        session = _session(profiles=(AgentProfile(inventory=inventory),))
        agent_id = _join(session, "Nia")["agent_id"]

        result = session.build(agent_id, 0, "fire", 3, 2)
        observation = session.observe(agent_id)

        self.assertTrue(result["ok"])
        self.assertEqual(observation["last_action_result"]["action"], "build")
        self.assertEqual(observation["last_action_result"]["status"], "success")
        self.assertEqual(session.state.structures[0].kind.value, "fire")
        self.assertEqual(session.state.structures[0].fuel, 99)

    def test_move_to_advances_one_step_per_tick(self) -> None:
        session = _session()
        agent_id = _join(session, "Nia")["agent_id"]

        first = session.move_to(agent_id, 0, 4, 2)
        first_observation = session.observe(agent_id)
        second = session.move_to(agent_id, 1, 4, 2)
        second_observation = session.observe(agent_id)

        self.assertTrue(first["ok"])
        self.assertEqual(first_observation["last_action_result"]["action"], "move_to")
        self.assertNotEqual(first_observation["agent"]["pos"], [2, 2])
        self.assertTrue(second["ok"])
        self.assertEqual(second_observation["agent"]["pos"], [4, 2])

    def test_blocked_move_is_reported_in_the_next_observation(self) -> None:
        session = _session(_layout(blocked=Position(3, 2)))
        agent_id = _join(session, "Nia")["agent_id"]

        result = session.move(agent_id, 0, 1, 0)
        observation = session.observe(agent_id)

        self.assertTrue(result["ok"])
        self.assertEqual(observation["tick"], 1)
        self.assertEqual(observation["agent"]["pos"], [2, 2])
        self.assertEqual(observation["last_action_result"]["status"], "rejected")
        self.assertEqual(observation["last_action_result"]["outcome"], "impassable")

    def test_duplicate_actions_are_rejected_until_all_agents_act(self) -> None:
        layout = _layout(spawns=(Position(1, 1), Position(3, 3)))
        session = _session(layout)
        first = _join(session, "Nia", 0)["agent_id"]
        second = _join(session, "Kai", 1)["agent_id"]

        first_move = session.move(first, 0, 1, 0)
        duplicate = session.move(first, 0, 0, 1)
        second_wait = session.wait(second, 0)

        self.assertTrue(first_move["ok"])
        self.assertFalse(duplicate["ok"])
        self.assertEqual(duplicate["error"]["code"], "ALREADY_ACTED")
        self.assertTrue(second_wait["ok"])
        self.assertEqual(session.observe(first)["tick"], 1)

    def test_stale_and_invalid_actions_are_rejected(self) -> None:
        session = _session()
        agent_id = _join(session, "Nia")["agent_id"]

        future = session.move(agent_id, 1, 1, 0)
        unknown = session.move("ag_99", 0, 1, 0)
        invalid = session.move("bad", 0, 1, 0)
        negative = session.move(agent_id, -1, 1, 0)
        session.move(agent_id, 0, 1, 0)
        stale = session.move(agent_id, 0, 0, 1)

        self.assertEqual(future["error"]["code"], "INVALID_TICK")
        self.assertEqual(unknown["error"]["code"], "NOT_YOUR_TURN")
        self.assertEqual(invalid["error"]["code"], "NOT_YOUR_TURN")
        self.assertEqual(negative["error"]["code"], "INVALID_TICK")
        self.assertEqual(stale["error"]["code"], "STALE_TICK")

    def test_wait_for_tick_returns_new_tick_and_times_out(self) -> None:
        session = _session()
        agent_id = _join(session, "Nia")["agent_id"]
        session.move(agent_id, 0, 1, 0)

        fresh = session.wait_for_tick(agent_id, 0, 100)
        timed_out = session.wait_for_tick(agent_id, 1, 10)
        future = session.wait_for_tick(agent_id, 2, 10)

        self.assertEqual(fresh["tick"], 1)
        self.assertFalse(timed_out["ok"])
        self.assertEqual(timed_out["error"]["code"], "NO_NEW_TICK")
        self.assertFalse(future["ok"])
        self.assertEqual(future["error"]["code"], "INVALID_TICK")

    def test_join_rejects_invalid_names_and_reused_tokens(self) -> None:
        session = _session()
        token = session.tokens[0]

        empty = session.join("  ", token)
        control = session.join("bad\nname", token)
        long_name = session.join("x" * 41, token)
        joined = session.join("Nia", token)
        reused = session.join("Kai", token)

        self.assertEqual(empty["error"]["code"], "INVALID_NAME")
        self.assertEqual(control["error"]["code"], "INVALID_NAME")
        self.assertEqual(long_name["error"]["code"], "INVALID_NAME")
        self.assertTrue(joined["ok"])
        self.assertEqual(reused["error"]["code"], "ALREADY_JOINED")

    def test_joins_are_accepted_between_ticks_and_blocked_mid_tick(self) -> None:
        layout = _layout(
            spawns=(Position(1, 1), Position(3, 3), Position(1, 3)),
        )
        session = _session(layout)
        first = _join(session, "Nia", 0)["agent_id"]
        second = _join(session, "Kai", 1)["agent_id"]
        session.move(first, 0, 1, 0)

        mid_tick = session.join("Mira", session.tokens[2])
        self.assertEqual(mid_tick["error"]["code"], "TICK_IN_PROGRESS")

        session.wait(second, 0)
        joined = session.join("Mira", session.tokens[2])

        self.assertTrue(joined["ok"])
        self.assertEqual(joined["tick"], 1)
        self.assertEqual(joined["phase"], "running")
        self.assertEqual(session.joined_agents, 3)

    def test_profiles_configure_agent_slots(self) -> None:
        layout = _layout(spawns=(Position(1, 1), Position(3, 3)))
        profiles = (
            AgentProfile(attributes=AgentAttributes(strength=10)),
            AgentProfile(attributes=AgentAttributes(dexterity=8)),
        )
        session = GameSession(42, layout=layout, profiles=profiles)

        first = _join(session, "Strong", 0)
        second = _join(session, "Quick", 1)
        first_observation = session.observe(first["agent_id"])
        second_observation = session.observe(second["agent_id"])

        self.assertEqual(len(session.tokens), 2)
        self.assertEqual(first_observation["agent"]["strength"], 10)
        self.assertEqual(first_observation["agent"]["carry_capacity_kg"], 30.0)
        self.assertEqual(second_observation["agent"]["dexterity"], 8)

    def test_default_profiles_support_one_to_eight_agents(self) -> None:
        session = GameSession(42)
        agent_ids: list[str] = []

        self.assertEqual(len(session.tokens), 8)
        for slot in range(8):
            joined = _join(session, f"Agent{slot + 1}", slot)
            self.assertTrue(joined["ok"])
            agent_ids.append(str(joined["agent_id"]))

        self.assertEqual(session.health()["agents"], 8)
        self.assertEqual(session.phase, SessionPhase.RUNNING)
        for agent_id in agent_ids:
            self.assertTrue(session.wait(agent_id, 0)["ok"])
        self.assertEqual(session.tick, 1)

    def test_leave_removes_agent_drops_inventory_and_frees_slot(self) -> None:
        wood = ItemDefinition(ItemId("wood"), 1_000, True, 99)
        inventory = Inventory(
            stacks=(ItemStack(wood, 2),),
            max_slots=10,
            max_weight_grams=20_000,
        )
        profile = AgentProfile(inventory=inventory)
        session = GameSession(
            42,
            max_agents=1,
            layout=_layout(),
            profiles=(profile,),
        )
        joined = _join(session, "Nia")
        token = session.tokens[0]

        left = session.leave(joined["agent_id"])

        self.assertTrue(left["ok"])
        self.assertEqual(left["phase"], "waiting")
        self.assertEqual(session.state.agents, ())
        self.assertEqual(session.phase, SessionPhase.WAITING)
        self.assertEqual(session.joined_agents, 0)
        self.assertEqual(session.alive_agents, 0)
        self.assertEqual(len(session.state.ground_items), 1)
        dropped = session.state.ground_items[0]
        self.assertEqual(dropped.position, Position(2, 2))
        self.assertEqual(dropped.stack.definition.item_id, "wood")
        self.assertEqual(dropped.stack.quantity, 2)

        rejoined = session.join("Nia", token)

        self.assertTrue(rejoined["ok"])
        self.assertEqual(rejoined["phase"], "running")
        self.assertEqual(session.joined_agents, 1)

    def test_leave_cancels_only_the_leaving_agents_pending_action(self) -> None:
        layout = _layout(spawns=(Position(1, 1), Position(3, 3)))
        session = _session(layout)
        first = _join(session, "Nia", 0)["agent_id"]
        second = _join(session, "Kai", 1)["agent_id"]
        session.move(first, 0, 1, 0)

        left = session.leave(second)

        self.assertTrue(left["ok"])
        self.assertEqual(left["tick"], 1)
        self.assertEqual(session.observe(first)["tick"], 1)
        self.assertEqual(session.state.agents[0].agent_id, first)

    def test_finish_and_restart_create_clean_waiting_state(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            token_path = Path(directory) / "agents.json"
            session = _session(token_path=token_path)
            old_token = session.tokens[0]
            _join(session, "Nia")
            session.move("ag_01", 0, 1, 0)

            summary = session.finish()
            restarted = session.restart(seed=43)

            self.assertEqual(summary["phase"], "finished")
            self.assertEqual(summary["end_reason"], "operator")
            self.assertEqual(summary["state_hash"], session.final_state_hash)
            self.assertEqual(
                session.move("ag_01", 1, 1, 0)["error"]["code"],
                "SESSION_FINISHED",
            )
            self.assertEqual(restarted.phase, SessionPhase.WAITING)
            self.assertEqual(restarted.tick, 0)
            self.assertEqual(restarted.state.agents, ())
            self.assertEqual(restarted.state.seed, 43)
            self.assertEqual(restarted.joined_agents, 0)
            self.assertNotEqual(restarted.tokens, (old_token,))
            self.assertEqual(
                json.loads(token_path.read_text(encoding="utf-8"))["seed"],
                43,
            )
            self.assertEqual(
                restarted.join("Nia", old_token)["error"]["code"],
                "UNAUTHORIZED",
            )

        with self.assertRaises(RuntimeError):
            _session().restart()

    def test_max_agents_is_bounded_to_one_to_eight(self) -> None:
        self.assertEqual(GameSession(42, max_agents=1).max_agents, 1)
        self.assertEqual(len(GameSession(42, max_agents=1).tokens), 1)
        self.assertEqual(GameSession(42).max_agents, 8)
        with self.assertRaises(ValueError):
            GameSession(42, max_agents=0)
        with self.assertRaises(ValueError):
            GameSession(42, max_agents=9)

    def test_profiles_must_fit_available_spawns(self) -> None:
        with self.assertRaises(ValueError):
            GameSession(42, layout=_layout(), profiles=())
        with self.assertRaises(ValueError):
            GameSession(
                42,
                layout=_layout(),
                profiles=(AgentProfile(), AgentProfile()),
            )

    def test_health_has_no_session_secrets(self) -> None:
        session = _session()
        _join(session, "Nia")

        health = session.health()

        self.assertEqual(health["status"], "ok")
        self.assertEqual(health["agents"], 1)
        self.assertNotIn("world", health)
        self.assertNotIn("seed", health)
        self.assertNotIn("rng_state", health)

    def test_observing_unknown_agent_is_rejected(self) -> None:
        session = _session()

        observation = session.observe("ag_99")

        self.assertFalse(observation["ok"])
        self.assertEqual(observation["error"]["code"], "NOT_YOUR_TURN")


if __name__ == "__main__":
    unittest.main()
