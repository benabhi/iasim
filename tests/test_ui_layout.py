"""Tests for the deterministic 160x45 base layout."""

from __future__ import annotations

import hashlib
import unittest

from iasim.crafting import load_catalog
from iasim.domain.agents import Agent, AgentAttributes, AgentStatus
from iasim.domain.alliances import Alliance, AllianceStatus, alliance_id_for
from iasim.domain.corpse import Corpse
from iasim.domain.geometry import Position
from iasim.domain.identifiers import AgentId, ItemId
from iasim.domain.items import Inventory, ItemStack
from iasim.domain.mind import MindReport
from iasim.domain.session import SessionState
from iasim.domain.tiles import TileType, WorldMap
from iasim.domain.trades import TradeOffer
from iasim.domain.usage import AgentUsage, CostSource, UsageEntry
from iasim.ui import theme
from iasim.ui.layout import render_base_screen, render_help_screen
from iasim.ui.panel import PanelState, RightPanelTab
from iasim.world.generation import generate_layout

CATALOG = load_catalog()
LAYOUT = generate_layout(42, agent_count=3)
NAMES = {
    AgentId("ag_01"): "Nia",
    AgentId("ag_02"): "Kai",
    AgentId("ag_03"): "Luma",
}
GOLDEN_HASH = "5b0ab8cf5b6c0bc0f086c2064056665bc5e38192eabda7d7bcaedaa68456d3e5"


def _state() -> SessionState:
    agents = tuple(
        Agent(AgentId(f"ag_{index + 1:02d}"), spawn)
        for index, spawn in enumerate(LAYOUT.spawn_points[:3])
    )
    return SessionState(
        seed=42,
        tick=0,
        rng_state=42,
        world=LAYOUT.world,
        agents=agents,
    )


def _screen():
    return render_base_screen(
        _state(),
        NAMES,
        selected_agent_id=AgentId("ag_01"),
    )


def _hash(screen) -> str:
    payload = "".join(f"{cell.char}{cell.fg}{cell.bg}{cell.bold}" for cell in screen.cells).encode(
        "utf-8"
    )
    return hashlib.sha256(payload).hexdigest()


class BaseLayoutTests(unittest.TestCase):
    def test_screen_is_exactly_160x45(self) -> None:
        screen = _screen()
        lines = screen.to_text().splitlines()

        self.assertEqual(screen.width, 160)
        self.assertEqual(screen.height, 45)
        self.assertEqual(len(lines), 45)
        self.assertEqual({len(line) for line in lines}, {160})

    def test_map_panel_and_bottom_bar_do_not_overlap(self) -> None:
        screen = _screen()

        self.assertIn(screen.cell_at(0, 0).char, theme.TILE_GLYPHS.values())
        self.assertIn(screen.cell_at(79, 39).char, theme.TILE_GLYPHS.values())
        self.assertEqual(screen.cell_at(80, 0).char, "│")
        self.assertEqual(screen.cell_at(80, 43).char, "│")
        self.assertEqual(screen.cell_at(81, 0).char, " ")

        bottom = screen.row_text(44)
        self.assertTrue(bottom.startswith("[ESPACIO] Pausa"))
        self.assertIn("[F1] Ayuda", bottom)
        self.assertIn("[Q] Salir", bottom)
        self.assertEqual(len(bottom), 160)

    def test_agents_appear_on_map_and_panel(self) -> None:
        screen = _screen()
        state = _state()

        for agent in state.agents:
            self.assertEqual(
                screen.cell_at(agent.position.x, agent.position.y).char,
                "@",
            )

        panel_text = "\n".join(screen.row_text(y)[80:] for y in range(45))
        for name in ("Nia", "Kai", "Luma"):
            self.assertIn(name, panel_text)
        self.assertIn("AGENTE SELECCIONADO", panel_text)

    def test_panel_shows_world_state(self) -> None:
        screen = _screen()
        panel_text = "\n".join(screen.row_text(y)[80:] for y in range(45))

        self.assertIn("DÍA 1", panel_text)
        self.assertIn("AMANECER", panel_text)
        self.assertIn("EN CURSO", panel_text)
        self.assertIn("AGENTES 3/8", panel_text)
        self.assertIn("ENTORNO", panel_text)
        self.assertIn("INVENTARIO", panel_text)

    def test_panel_shows_reported_ai_usage(self) -> None:
        usage = {
            AgentId("ag_01"): AgentUsage(
                entries=(
                    UsageEntry(
                        model="gpt-5",
                        reasoning_effort="high",
                        input_tokens=120,
                        output_tokens=30,
                        cost_usd=0.01,
                        cost_source=CostSource.REPORTED,
                    ),
                )
            )
        }
        screen = render_base_screen(
            _state(),
            NAMES,
            selected_agent_id=AgentId("ag_01"),
            usage=usage,
        )
        panel_text = "\n".join(screen.row_text(y)[80:] for y in range(45))

        self.assertIn("USO IA (REPORTADO)", panel_text)
        self.assertIn("gpt-5 / high: 120 in / 30 out", panel_text)
        self.assertIn("TOTAL 150 tokens - USD 0.0100 (reportado)", panel_text)

    def test_snapshot_is_deterministic(self) -> None:
        first = _screen()
        second = _screen()

        self.assertEqual(first.to_text(), second.to_text())
        self.assertEqual(_hash(first), GOLDEN_HASH)
        self.assertEqual(_hash(second), GOLDEN_HASH)

    def test_focus_mode_hides_tiles_and_agents_behind_a_blocker(self) -> None:
        tiles = [TileType.GRASS] * 100
        tiles[5 * 10 + 5] = TileType.TREE
        state = SessionState(
            seed=42,
            tick=0,
            rng_state=42,
            world=WorldMap(width=10, height=10, tiles=tuple(tiles)),
            agents=(
                Agent(AgentId("ag_01"), Position(4, 5)),
                Agent(AgentId("ag_02"), Position(6, 5)),
            ),
        )
        screen = render_base_screen(
            state,
            NAMES,
            selected_agent_id=AgentId("ag_01"),
            focus_mode=True,
        )

        self.assertEqual(screen.cell_at(4, 5).char, "@")
        self.assertEqual(
            screen.cell_at(5, 5).char,
            theme.tile_glyph(TileType.TREE),
        )
        self.assertEqual(screen.cell_at(6, 5).char, " ")

    def test_theme_covers_every_tile_type(self) -> None:
        self.assertEqual(set(theme.TILE_GLYPHS), set(TileType))
        self.assertEqual(set(theme.TILE_COLORS), set(TileType))
        self.assertEqual(set(theme.TILE_BACKGROUNDS), set(TileType))
        self.assertEqual(set(theme.ASCII_TILE_GLYPHS), set(TileType))
        self.assertEqual(set(theme.TILE_LABELS), set(TileType))

    def test_help_screen_lists_controls_glyphs_and_statuses(self) -> None:
        screen = render_help_screen()
        text = screen.to_text()

        self.assertEqual(screen.width, 160)
        self.assertEqual(screen.height, 45)
        for expected in (
            "AYUDA Y LEYENDA",
            "ESPACIO",
            "TAB",
            "F1",
            "Q",
            "R",
            "GLIFOS",
            "ESTADOS",
            "BARRAS",
        ):
            self.assertIn(expected, text)
        self.assertIn("mesa de trabajo", text)
        self.assertIn("HAMBRE", text)

    def test_ascii_help_uses_ascii_legend_glyphs(self) -> None:
        text = render_help_screen(ascii_mode=True).to_text()

        self.assertIn("# lleno", text)
        self.assertIn("T árbol", text)
        self.assertNotIn("♣", text)

    def test_ascii_fallback_changes_map_and_bar_glyphs(self) -> None:
        state = _state()
        screen = render_base_screen(
            state,
            NAMES,
            selected_agent_id=AgentId("ag_01"),
            ascii_mode=True,
        )
        map_chars = {
            screen.cell_at(x, y).char
            for y in range(40)
            for x in range(80)
            if state.world.tile_at(Position(x, y)) not in (TileType.DEEP_WATER,)
        }
        panel_text = "\n".join(screen.row_text(y)[80:] for y in range(45))
        bottom = screen.row_text(44)

        self.assertTrue(map_chars <= set(theme.ASCII_TILE_GLYPHS.values()) | {"@"})
        self.assertIn("|", bottom)
        self.assertNotIn("│", bottom)
        self.assertIn("#", panel_text)
        self.assertNotIn("█", panel_text)
        self.assertNotIn("░", panel_text)

    def test_html_preview_contains_screen_and_legend(self) -> None:
        preview = _screen().to_html("IASim test")

        self.assertIn("<html", preview)
        self.assertIn("IASim test", preview)
        self.assertIn("agua profunda", preview)
        self.assertIn("<span", preview)
        self.assertIn("</html>", preview)


class TabbedPanelTests(unittest.TestCase):
    def _panel_text(self, screen) -> str:
        return "\n".join(screen.row_text(y)[80:] for y in range(44))

    def _eight_agent_state(self) -> SessionState:
        layout = generate_layout(7, agent_count=8)
        agents = tuple(
            Agent(AgentId(f"ag_{index + 1:02d}"), layout.spawn_points[index]) for index in range(8)
        )
        return SessionState(
            seed=7,
            tick=0,
            rng_state=7,
            world=layout.world,
            agents=agents,
        )

    def test_summary_tab_is_default_and_shows_counters(self) -> None:
        screen = render_base_screen(
            _state(),
            NAMES,
            selected_agent_id=AgentId("ag_01"),
            events=[f"evento {index}" for index in range(20)],
        )

        panel = self._panel_text(screen)

        self.assertIn("◆ RESUMEN", panel)
        self.assertIn("EVENTOS 20", panel)
        self.assertIn("VÍNCULOS", panel)
        self.assertIn("AGENTES", panel)
        self.assertIn("AGENTE SELECCIONADO", panel)
        self.assertIn("MENTE (REPORTADO)", panel)
        self.assertIn("ENTORNO", panel)
        self.assertIn("RELACIONES", panel)
        self.assertIn("EVENTOS", panel)
        self.assertIn("DÍA 1", panel)
        self.assertIn("AMANECER", panel)
        self.assertIn("EN CURSO", panel)
        self.assertIn("AGENTES 3/8", panel)

    def test_each_tab_marks_itself_and_keeps_the_agent_strip(self) -> None:
        for tab in (
            RightPanelTab.EVENTS,
            RightPanelTab.MIND,
            RightPanelTab.LINKS,
        ):
            with self.subTest(tab=tab.value):
                screen = render_base_screen(
                    _state(),
                    NAMES,
                    selected_agent_id=AgentId("ag_01"),
                    events=["evento"],
                    panel=PanelState(tab=tab),
                )
                panel = self._panel_text(screen)
                self.assertIn("◆", panel)
                self.assertIn("1@Nia", panel)
                self.assertIn("3@Luma", panel)

    def test_mind_tab_wraps_long_thoughts(self) -> None:
        thought = " ".join(["Necesito comida y agua"] * 6)
        reports = {
            AgentId("ag_01"): MindReport(
                agent_id=AgentId("ag_01"),
                tick=0,
                intent="Sobrevivir",
                thought=thought,
                plan="Buscar el río",
            )
        }
        screen = render_base_screen(
            _state(),
            NAMES,
            selected_agent_id=AgentId("ag_01"),
            mind_reports=reports,
            panel=PanelState(tab=RightPanelTab.MIND),
        )
        panel = self._panel_text(screen)
        lines = panel.splitlines()

        self.assertIn("◆ MENTE", panel)
        self.assertIn("Intención: Sobrevivir", panel)
        self.assertIn("Pensamiento:", panel)
        self.assertIn("Plan: Buscar el río", panel)
        self.assertGreater(
            sum(1 for line in lines if "Necesito comida" in line),
            1,
        )
        self.assertTrue(all(len(line) == 80 for line in lines))

    def test_events_tab_scrolls_with_an_indicator(self) -> None:
        events = [f"evento {index}" for index in range(60)]
        screen = render_base_screen(
            _state(),
            NAMES,
            selected_agent_id=AgentId("ag_01"),
            events=events,
            panel=PanelState(tab=RightPanelTab.EVENTS, scroll=10),
        )
        panel = self._panel_text(screen)

        self.assertIn("evento 10", panel)
        self.assertNotIn("evento 0 ", panel)
        self.assertIn("11-", panel)
        self.assertIn("de 60", panel)

    def test_links_tab_shows_inventory_equipment_and_relationships(self) -> None:
        catalog = load_catalog()
        inventory = Inventory.for_strength(5).add(ItemStack(catalog.item("wood").definition, 2))
        agents = (
            Agent(AgentId("ag_01"), Position(2, 2), inventory=inventory),
            Agent(AgentId("ag_02"), Position(3, 2)),
        )
        alliance = Alliance(
            alliance_id=alliance_id_for(AgentId("ag_01"), AgentId("ag_02")),
            members=(AgentId("ag_01"), AgentId("ag_02")),
            status=AllianceStatus.ACTIVE,
            proposed_by=AgentId("ag_01"),
            offered_tick=0,
            accepted_tick=1,
        )
        trade = TradeOffer.propose(
            AgentId("ag_01"),
            AgentId("ag_02"),
            2,
            ((ItemId("wood"), 1),),
            ((ItemId("berry"), 1),),
        )
        state = SessionState(
            seed=1,
            tick=3,
            rng_state=1,
            world=WorldMap(width=6, height=6, tiles=(TileType.GRASS,) * 36),
            agents=agents,
            alliances=(alliance,),
            trades=(trade,),
        )
        screen = render_base_screen(
            state,
            {AgentId("ag_01"): "Nia", AgentId("ag_02"): "Kai"},
            selected_agent_id=AgentId("ag_01"),
            messages=["hola"],
            betrayals=["Nia atacó a Kai"],
            panel=PanelState(tab=RightPanelTab.LINKS),
        )
        panel = self._panel_text(screen)

        for expected in (
            "◆ VÍNCULOS",
            "INVENTARIO",
            "wood x2",
            "EQUIPO",
            "ALIANZAS",
            "Nia-Kai",
            "TRUEQUES",
            "1 pendientes",
            "MENSAJES",
            "hola",
            "TRAICIONES",
            "Nia atacó a Kai",
        ):
            self.assertIn(expected, panel)

    def test_dead_agents_keep_all_sections(self) -> None:
        dead = Agent(
            AgentId("ag_02"),
            Position(3, 2),
            attributes=AgentAttributes(health_centi=0),
            status=AgentStatus.DEAD,
        )
        state = SessionState(
            seed=1,
            tick=3,
            rng_state=1,
            world=WorldMap(width=6, height=6, tiles=(TileType.GRASS,) * 36),
            agents=(Agent(AgentId("ag_01"), Position(2, 2)), dead),
            corpses=(Corpse.from_agent(dead, tick=2, cause="starvation"),),
        )
        screen = render_base_screen(
            state,
            {AgentId("ag_01"): "Nia", AgentId("ag_02"): "Kai"},
            selected_agent_id=AgentId("ag_02"),
        )
        panel = self._panel_text(screen)

        self.assertIn("AGENTES", panel)
        self.assertIn("AGENTE SELECCIONADO", panel)
        self.assertIn("Estado: MUERTO", panel)
        self.assertIn("starvation", panel)
        self.assertIn("MENTE (REPORTADO)", panel)
        self.assertIn("ENTORNO", panel)
        self.assertIn("RELACIONES", panel)
        self.assertIn("EVENTOS", panel)
        self.assertNotIn("Salud", panel)

    def test_long_content_truncates_safely(self) -> None:
        long_name = "N" * 120
        screen = render_base_screen(
            _state(),
            {agent: long_name for agent in NAMES},
            selected_agent_id=AgentId("ag_01"),
            events=["E" * 200],
        )
        panel_lines = [screen.row_text(y)[80:] for y in range(44)]

        self.assertTrue(all(len(line) == 80 for line in panel_lines))
        self.assertTrue(any("…" in line for line in panel_lines))
        self.assertTrue(all(len(screen.row_text(y)) == 160 for y in range(45)))

    def test_eight_agents_keep_every_summary_section(self) -> None:
        state = self._eight_agent_state()
        names = {agent.agent_id: f"Agente {index + 1}" for index, agent in enumerate(state.agents)}
        screen = render_base_screen(
            state,
            names,
            selected_agent_id=AgentId("ag_01"),
            events=["evento"],
        )
        panel = self._panel_text(screen)

        for expected in (
            "AGENTES",
            "AGENTE SELECCIONADO",
            "MENTE (REPORTADO)",
            "ENTORNO",
            "RELACIONES",
            "EVENTOS",
        ):
            self.assertIn(expected, panel)
        self.assertIn("8/8", panel)

    def test_ascii_tabs_use_ascii_markers(self) -> None:
        screen = render_base_screen(
            _state(),
            NAMES,
            selected_agent_id=AgentId("ag_01"),
            events=["evento"],
            ascii_mode=True,
            panel=PanelState(tab=RightPanelTab.EVENTS),
        )
        panel = self._panel_text(screen)

        self.assertIn("> EVENTOS", panel)
        self.assertNotIn("◆", panel)


if __name__ == "__main__":
    unittest.main()
