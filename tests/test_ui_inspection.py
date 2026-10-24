"""Tests for the read-only inspection cursor, details, and overlays."""

from __future__ import annotations

import unittest

from iasim.crafting import load_catalog
from iasim.domain.agents import Agent, AgentAttributes, AgentStatus
from iasim.domain.alliances import Alliance, AllianceStatus, alliance_id_for
from iasim.domain.corpse import Corpse
from iasim.domain.geometry import Position
from iasim.domain.hashing import canonical_state_hash
from iasim.domain.identifiers import AgentId
from iasim.domain.items import GroundItem, Inventory, ItemStack
from iasim.domain.resources import ResourceNode
from iasim.domain.session import SessionState
from iasim.domain.tiles import TileType, WorldMap
from iasim.domain.world import Structure, StructureKind
from iasim.ui import theme
from iasim.ui.controls import UiState, UiView, handle_key
from iasim.ui.inspection import describe_position
from iasim.ui.layout import render_base_screen, render_map_screen

CATALOG = load_catalog()
NAMES = {AgentId("ag_01"): "Nia", AgentId("ag_02"): "Kai", AgentId("ag_03"): "Luma"}
AGENTS = (AgentId("ag_01"), AgentId("ag_02"))


def _state() -> SessionState:
    tiles = [TileType.GRASS] * 100
    tiles[2 * 10 + 2] = TileType.TREE
    tiles[3 * 10 + 3] = TileType.FIRE
    inventory = Inventory.for_strength(5).add(ItemStack(CATALOG.item("wood").definition, 2))
    dead = Agent(
        AgentId("ag_03"),
        Position(4, 4),
        attributes=AgentAttributes(health_centi=0),
        status=AgentStatus.DEAD,
        inventory=inventory,
    )
    alliance_id = alliance_id_for(AgentId("ag_01"), AgentId("ag_02"))
    return SessionState(
        seed=5,
        tick=0,
        rng_state=5,
        world=WorldMap(width=10, height=10, tiles=tuple(tiles)),
        agents=(
            Agent(AgentId("ag_01"), Position(6, 6)),
            Agent(AgentId("ag_02"), Position(6, 7)),
            dead,
        ),
        structures=(Structure(StructureKind.FIRE, Position(3, 3), lit=True),),
        resource_nodes=(ResourceNode(Position(2, 2), "tree_logs", 2, 3),),
        ground_items=(
            GroundItem(
                Position(5, 5),
                ItemStack(CATALOG.item("berry").definition, 3),
            ),
        ),
        corpses=(Corpse.from_agent(dead, tick=1, cause="starvation"),),
        alliances=(
            Alliance(
                alliance_id=alliance_id,
                members=(AgentId("ag_01"), AgentId("ag_02")),
                status=AllianceStatus.ACTIVE,
                proposed_by=AgentId("ag_01"),
                offered_tick=0,
                accepted_tick=1,
            ),
        ),
    )


class InspectionDetailTests(unittest.TestCase):
    def test_a_plain_tile_is_described(self) -> None:
        lines = describe_position(_state(), NAMES, Position(0, 0))

        self.assertIn("Celda (0,0)", lines[0])
        self.assertIn("pasto", lines[0])

    def test_a_tree_reports_its_available_resources(self) -> None:
        lines = describe_position(_state(), NAMES, Position(2, 2))

        self.assertIn("árbol", lines[0])
        self.assertIn("tree_logs", lines[0])

    def test_structures_and_corpses_are_described(self) -> None:
        state = _state()

        fire = describe_position(state, NAMES, Position(3, 3))
        corpse = describe_position(state, NAMES, Position(4, 4))

        self.assertIn("Estructura: fuego", fire[1])
        self.assertIn("encendido", fire[1])
        self.assertIn("Cadáver de Luma", corpse[1])
        self.assertIn("starvation", corpse[1])
        self.assertIn("wood x2", corpse[1])

    def test_ground_items_are_described(self) -> None:
        lines = describe_position(_state(), NAMES, Position(5, 5))

        self.assertIn("Objetos:", lines[1])
        self.assertIn("berry x3", lines[1])

    def test_living_agents_report_state_equipment_and_relation(self) -> None:
        lines = describe_position(
            _state(),
            NAMES,
            Position(6, 7),
            selected_agent_id=AgentId("ag_01"),
        )

        self.assertIn("Agente Kai", lines[1])
        self.assertIn("aliada", lines[1])
        self.assertIn("equipo", lines[1])

    def test_dead_agents_report_death(self) -> None:
        lines = describe_position(
            _state(),
            NAMES,
            Position(4, 4),
            selected_agent_id=AgentId("ag_01"),
        )

        self.assertTrue(any("MUERTO" in line for line in lines))

    def test_out_of_world_positions_are_safe(self) -> None:
        lines = describe_position(_state(), NAMES, Position(50, 50))

        self.assertEqual(lines, ("Fuera del mapa",))

    def test_inspection_never_mutates_the_state(self) -> None:
        state = _state()
        before = canonical_state_hash(state)

        describe_position(state, NAMES, Position(4, 4))
        describe_position(state, NAMES, Position(6, 6))

        self.assertEqual(canonical_state_hash(state), before)


class InspectionControlTests(unittest.TestCase):
    def test_x_toggles_the_cursor(self) -> None:
        state = handle_key(UiState(), "x", AGENTS, world_size=(10, 10))

        self.assertEqual(state.cursor, Position(0, 0))
        self.assertIsNone(handle_key(state, "x", AGENTS).cursor)

    def test_arrows_move_and_clamp_the_cursor(self) -> None:
        state = handle_key(UiState(), "x", AGENTS, world_size=(10, 10))
        for _ in range(3):
            state = handle_key(state, "right", AGENTS, world_size=(10, 10))
            state = handle_key(state, "down", AGENTS, world_size=(10, 10))
        self.assertEqual(state.cursor, Position(3, 3))

        for _ in range(20):
            state = handle_key(state, "left", AGENTS, world_size=(10, 10))
            state = handle_key(state, "up", AGENTS, world_size=(10, 10))
        self.assertEqual(state.cursor, Position(0, 0))

        for _ in range(20):
            state = handle_key(state, "right", AGENTS, world_size=(10, 10))
            state = handle_key(state, "down", AGENTS, world_size=(10, 10))
        self.assertEqual(state.cursor, Position(9, 9))

    def test_arrows_do_not_scroll_the_panel_while_the_cursor_is_active(self) -> None:
        state = handle_key(UiState(), "x", AGENTS, world_size=(10, 10))
        state = handle_key(state, "down", AGENTS, world_size=(10, 10))

        self.assertEqual(state.cursor, Position(0, 1))
        self.assertEqual(state.panel.scroll, 0)

        inactive = handle_key(UiState(), "down", AGENTS, world_size=(10, 10))
        self.assertEqual(inactive.panel.scroll, 1)

    def test_enter_pins_and_escape_closes_the_cursor_first(self) -> None:
        state = handle_key(UiState(), "x", AGENTS, world_size=(10, 10))
        state = handle_key(state, "enter", AGENTS, world_size=(10, 10))
        self.assertTrue(state.inspection_pinned)

        state = handle_key(state, "f6", AGENTS, world_size=(10, 10))
        state = handle_key(state, "esc", AGENTS, world_size=(10, 10))
        self.assertIsNone(state.cursor)
        self.assertEqual(state.view, UiView.MAP_VIEW)
        self.assertEqual(
            handle_key(state, "esc", AGENTS, world_size=(10, 10)).view,
            UiView.NONE,
        )


class InspectionRenderTests(unittest.TestCase):
    def test_the_base_screen_highlights_the_cursor_without_hiding_entities(self) -> None:
        screen = render_base_screen(
            _state(),
            NAMES,
            selected_agent_id=AgentId("ag_01"),
            cursor=Position(6, 7),
        )

        cell = screen.cell_at(6, 7)
        self.assertEqual(cell.char, "@")
        self.assertEqual(cell.bg, theme.CURSOR_BG)
        ticker = "\n".join(screen.row_text(y)[:80] for y in range(40, 44))
        self.assertIn("INSPECCIÓN", ticker)
        self.assertIn("Agente Kai", ticker)

    def test_the_cursor_can_highlight_empty_tiles(self) -> None:
        screen = render_base_screen(
            _state(),
            NAMES,
            selected_agent_id=AgentId("ag_01"),
            cursor=Position(0, 0),
        )

        self.assertEqual(screen.cell_at(0, 0).bg, theme.CURSOR_BG)
        self.assertEqual(screen.cell_at(0, 0).char, theme.tile_glyph(TileType.GRASS))
        self.assertIn("INSPECCIÓN", screen.to_text())

    def test_the_f6_map_highlights_the_cursor_and_shows_details(self) -> None:
        screen = render_map_screen(
            _state(),
            NAMES,
            selected_agent_id=AgentId("ag_01"),
            cursor=Position(4, 4),
        )

        self.assertEqual(screen.cell_at(40 + 4, 4).bg, theme.CURSOR_BG)
        self.assertIn("Inspección (4,4)", screen.to_text())
        self.assertIn("Cadáver de Luma", screen.to_text())

    def test_an_out_of_world_cursor_is_ignored(self) -> None:
        screen = render_base_screen(
            _state(),
            NAMES,
            selected_agent_id=AgentId("ag_01"),
            cursor=Position(20, 20),
        )

        self.assertEqual(screen.cell_at(20, 20).bg, theme.BLACK)
        self.assertIn("Fuera del mapa", screen.to_text())


if __name__ == "__main__":
    unittest.main()
