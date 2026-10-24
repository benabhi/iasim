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
from iasim.domain.items import GroundItem, Inventory, ItemStack
from iasim.domain.memory import AgentMemory, Memory, MemoryEntry
from iasim.domain.mind import MindReport
from iasim.domain.session import SessionState
from iasim.domain.tiles import TileType, WorldMap
from iasim.domain.trades import TradeOffer
from iasim.domain.usage import AgentUsage, CostSource, UsageEntry
from iasim.domain.weather import WeatherKind, WeatherState
from iasim.domain.world import Structure, StructureKind
from iasim.ui import theme
from iasim.ui.layout import (
    render_agent_screen,
    render_base_screen,
    render_help_screen,
    render_map_screen,
    render_replay_screen,
    render_world_screen,
)
from iasim.ui.panel import PanelState, RightPanelTab
from iasim.world.generation import generate_layout

CATALOG = load_catalog()
LAYOUT = generate_layout(42, agent_count=3)
NAMES = {
    AgentId("ag_01"): "Nia",
    AgentId("ag_02"): "Kai",
    AgentId("ag_03"): "Luma",
}
GOLDEN_HASH = "5bc8272d96d037ffc93203980a3408722718d6df5e91a3d30972d8f4f5aa7491"


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


class MapLayerTests(unittest.TestCase):
    def _grassy_state(self, *, weather: WeatherState | None = None) -> SessionState:
        return SessionState(
            seed=9,
            tick=5,
            rng_state=9,
            world=WorldMap(width=8, height=8, tiles=(TileType.GRASS,) * 64),
            weather=weather or WeatherState(),
            agents=(Agent(AgentId("ag_01"), Position(2, 2)),),
        )

    def _state_with_entities(self) -> SessionState:
        catalog = load_catalog()
        tiles = [TileType.GRASS] * 64
        tiles[1 * 8 + 1] = TileType.FIRE
        return SessionState(
            seed=9,
            tick=5,
            rng_state=9,
            world=WorldMap(width=8, height=8, tiles=tuple(tiles)),
            weather=WeatherState(kind=WeatherKind.RAIN, remaining_ticks=5, wind=3),
            agents=(Agent(AgentId("ag_01"), Position(4, 1)),),
            structures=(Structure(StructureKind.FIRE, Position(1, 1), lit=True),),
            ground_items=(
                GroundItem(
                    Position(3, 1),
                    ItemStack(catalog.item("wood").definition, 1),
                ),
            ),
            corpses=(
                Corpse.from_agent(
                    Agent(AgentId("ag_02"), Position(2, 1)),
                    tick=4,
                    cause="starvation",
                ),
            ),
        )

    def test_the_operator_sees_the_complete_map(self) -> None:
        state = self._grassy_state()

        screen = render_base_screen(state, {AgentId("ag_01"): "Nia"})

        for y in range(8):
            for x in range(8):
                if (x, y) == (2, 2):
                    self.assertEqual(screen.cell_at(x, y).char, "@")
                    continue
                self.assertEqual(
                    screen.cell_at(x, y).char,
                    theme.tile_glyph(TileType.GRASS),
                )

    def test_entities_render_with_distinct_glyphs_and_colors(self) -> None:
        state = self._state_with_entities()

        screen = render_base_screen(state, {}, weather_overlay=True)

        fire = screen.cell_at(1, 1)
        corpse = screen.cell_at(2, 1)
        item = screen.cell_at(3, 1)
        agent = screen.cell_at(4, 1)
        self.assertEqual(fire.char, theme.STRUCTURE_GLYPHS[StructureKind.FIRE])
        self.assertEqual(fire.fg, theme.STRUCTURE_COLORS[StructureKind.FIRE])
        self.assertEqual(corpse.char, theme.CORPSE_GLYPH)
        self.assertEqual(corpse.fg, theme.CORPSE_COLOR)
        self.assertEqual(item.char, theme.GROUND_ITEM_GLYPH)
        self.assertEqual(item.fg, theme.GROUND_ITEM_COLOR)
        self.assertEqual(agent.char, "@")
        self.assertEqual(agent.fg, theme.AGENT_COLOR)
        self.assertEqual(len({fire.fg, corpse.fg, item.fg, agent.fg}), 4)

    def test_weather_overlays_are_deterministic_and_do_not_hide_entities(self) -> None:
        state = self._state_with_entities()

        first = render_base_screen(state, {}, weather_overlay=True)
        second = render_base_screen(state, {}, weather_overlay=True)
        without = render_base_screen(state, {}, weather_overlay=False)

        self.assertEqual(first.to_text(), second.to_text())
        self.assertNotEqual(first.to_text(), without.to_text())
        weather_glyphs = {
            theme.WEATHER_RAIN_GLYPH,
            theme.WEATHER_WIND_GLYPH,
            theme.WEATHER_FOG_GLYPH,
        }
        map_glyphs = {first.cell_at(x, y).char for y in range(40) for x in range(80)}
        self.assertTrue(map_glyphs & weather_glyphs)
        self.assertFalse(
            {without.cell_at(x, y).char for y in range(40) for x in range(80)} & weather_glyphs
        )
        self.assertEqual(
            first.cell_at(1, 1).char,
            theme.STRUCTURE_GLYPHS[StructureKind.FIRE],
        )

    def test_weather_is_visible_in_the_environment_section(self) -> None:
        state = self._state_with_entities()

        screen = render_base_screen(state, {}, selected_agent_id=AgentId("ag_01"))

        panel = "\n".join(screen.row_text(y)[80:] for y in range(44))
        self.assertIn("LLUVIA", panel)

    def test_focus_mode_uses_memory_and_hides_unseen_cells(self) -> None:
        memory = Memory(
            tiles=(
                MemoryEntry(Position(30, 30), TileType.SAND, 3),
                MemoryEntry(Position(31, 30), TileType.TREE, 2, stale=True),
                MemoryEntry(
                    Position(30, 31),
                    TileType.GRASS,
                    2,
                    structure=StructureKind.FIRE,
                ),
            ),
            agents=(AgentMemory(AgentId("ag_02"), Position(29, 29), 3),),
        )
        state = SessionState(
            seed=9,
            tick=5,
            rng_state=9,
            world=WorldMap(width=40, height=40, tiles=(TileType.GRASS,) * 1600),
            agents=(
                Agent(AgentId("ag_01"), Position(1, 1), memory=memory),
                Agent(AgentId("ag_02"), Position(20, 20)),
            ),
            ground_items=(
                GroundItem(
                    Position(35, 20),
                    ItemStack(CATALOG.item("wood").definition, 1),
                ),
            ),
        )

        screen = render_base_screen(
            state,
            {AgentId("ag_01"): "Nia", AgentId("ag_02"): "Kai"},
            selected_agent_id=AgentId("ag_01"),
            focus_mode=True,
            weather_overlay=False,
        )

        remembered = screen.cell_at(30, 30)
        stale = screen.cell_at(31, 30)
        familiar = screen.cell_at(30, 31)
        unseen = screen.cell_at(35, 35)
        self.assertEqual(remembered.char, theme.tile_glyph(TileType.SAND))
        self.assertEqual(remembered.fg, theme.MEMORY_COLOR)
        self.assertEqual(stale.char, theme.tile_glyph(TileType.TREE))
        self.assertEqual(stale.fg, theme.STALE_MEMORY_COLOR)
        self.assertEqual(
            familiar.char,
            theme.STRUCTURE_GLYPHS[StructureKind.FIRE],
        )
        self.assertEqual(unseen.char, " ")
        self.assertEqual(unseen.bg, theme.BLACK)
        self.assertEqual(screen.cell_at(29, 29).char, "…")
        hidden_item = screen.cell_at(35, 20)
        self.assertNotEqual(hidden_item.char, theme.GROUND_ITEM_GLYPH)

    def test_focus_keeps_visible_entities_normal(self) -> None:
        state = self._state_with_entities()

        screen = render_base_screen(
            state,
            {},
            selected_agent_id=AgentId("ag_01"),
            focus_mode=True,
        )

        self.assertEqual(screen.cell_at(4, 1).char, "@")
        self.assertEqual(
            screen.cell_at(1, 1).char,
            theme.STRUCTURE_GLYPHS[StructureKind.FIRE],
        )


class AgentSheetTests(unittest.TestCase):
    def _state(self) -> SessionState:
        catalog = load_catalog()
        agents = tuple(
            Agent(
                AgentId(f"ag_{index + 1:02d}"),
                LAYOUT.spawn_points[index],
                inventory=Inventory.for_strength(5).add(
                    ItemStack(catalog.item("wood").definition, index + 1)
                ),
            )
            for index in range(3)
        )
        return SessionState(
            seed=42,
            tick=0,
            rng_state=42,
            world=LAYOUT.world,
            agents=agents,
        )

    def test_the_agent_sheet_is_three_columns_of_content(self) -> None:
        screen = render_agent_screen(
            self._state(),
            NAMES,
            selected_agent_id=AgentId("ag_01"),
        )
        text = screen.to_text()

        self.assertEqual((screen.width, screen.height), (160, 45))
        self.assertTrue(all(len(screen.row_text(y)) == 160 for y in range(45)))
        for expected in (
            "F2 · FICHA DEL AGENTE · Nia",
            "IDENTIDAD",
            "SALUD Y NECESIDADES",
            "HABILIDADES",
            "EQUIPO",
            "MENTE (REPORTADO POR EL AGENTE)",
            "TIMELINE",
            "INVENTARIO",
            "RELACIONES",
            "MENSAJES",
            "[TAB] Siguiente agente",
        ):
            self.assertIn(expected, text)

    def test_the_sheet_follows_the_selected_agent(self) -> None:
        screen = render_agent_screen(
            self._state(),
            NAMES,
            selected_agent_id=AgentId("ag_02"),
        )

        self.assertIn("FICHA DEL AGENTE · Kai", screen.to_text())

    def test_the_sheet_shows_mind_usage_and_timeline(self) -> None:
        reports = {
            AgentId("ag_01"): MindReport(
                agent_id=AgentId("ag_01"),
                tick=3,
                intent="Buscar agua",
                thought="Tengo sed y el río está cerca.",
                plan="Ir al río",
                confidence=80,
            )
        }
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
        timeline = [f"t{index} · acción {index}" for index in range(25)]

        screen = render_agent_screen(
            self._state(),
            NAMES,
            selected_agent_id=AgentId("ag_01"),
            mind_reports=reports,
            usage=usage,
            timeline=timeline,
        )
        text = screen.to_text()

        self.assertIn("Intención: Buscar agua", text)
        self.assertIn("Plan: Ir al río", text)
        self.assertIn("gpt-5 / high: 120 in / 30 out", text)
        self.assertIn("+5 anteriores", text)
        self.assertIn("t24 · acción 24", text)
        self.assertNotIn("t0 · acción 0", text)

    def test_dead_agents_show_cause_killer_and_loot(self) -> None:
        catalog = load_catalog()
        dead = Agent(
            AgentId("ag_02"),
            LAYOUT.spawn_points[1],
            attributes=AgentAttributes(health_centi=0),
            status=AgentStatus.DEAD,
            inventory=Inventory.for_strength(5).add(ItemStack(catalog.item("berry").definition, 3)),
        )
        corpse = Corpse.from_agent(
            dead,
            tick=7,
            cause="attack",
            killer_id=AgentId("ag_01"),
        )
        state = SessionState(
            seed=42,
            tick=10,
            rng_state=42,
            world=LAYOUT.world,
            agents=(Agent(AgentId("ag_01"), LAYOUT.spawn_points[0]), dead),
            corpses=(corpse,),
        )

        screen = render_agent_screen(
            state,
            NAMES,
            selected_agent_id=AgentId("ag_02"),
        )
        text = screen.to_text()

        self.assertIn("Estado: MUERTO", text)
        self.assertIn("muerto por attack", text)
        self.assertIn("CADÁVER", text)
        self.assertIn("Botín:", text)
        self.assertIn("berry x3", text)

    def test_a_long_thought_wraps_within_the_column(self) -> None:
        reports = {
            AgentId("ag_01"): MindReport(
                agent_id=AgentId("ag_01"),
                tick=1,
                intent="Sobrevivir",
                thought=" ".join(["Necesito comida y agua potable"] * 5),
            )
        }

        screen = render_agent_screen(
            self._state(),
            NAMES,
            selected_agent_id=AgentId("ag_01"),
            mind_reports=reports,
        )
        column = "\n".join(screen.row_text(y)[53:103] for y in range(3, 43))
        matches = [line for line in column.splitlines() if "Necesito comida" in line]

        self.assertGreater(len(matches), 1)
        self.assertTrue(all(len(screen.row_text(y)) == 160 for y in range(45)))

    def test_the_sheet_handles_a_missing_agent(self) -> None:
        empty = SessionState(
            seed=1,
            tick=0,
            rng_state=1,
            world=WorldMap(width=4, height=4, tiles=(TileType.GRASS,) * 16),
        )

        screen = render_agent_screen(empty, {})

        self.assertIn("sin agente seleccionado", screen.to_text())


class WorldSummaryTests(unittest.TestCase):
    def _state(self) -> SessionState:
        tiles = [TileType.GRASS] * 64
        tiles[1 * 8 + 1] = TileType.FIRE
        tiles[1 * 8 + 2] = TileType.SHELTER
        tiles[3 * 8 + 3] = TileType.TREE
        tiles[4 * 8 + 4] = TileType.BUSH
        dead = Agent(
            AgentId("ag_03"),
            Position(7, 7),
            attributes=AgentAttributes(health_centi=0),
            status=AgentStatus.DEAD,
        )
        return SessionState(
            seed=2,
            tick=0,
            rng_state=2,
            world=WorldMap(width=8, height=8, tiles=tuple(tiles)),
            weather=WeatherState(kind=WeatherKind.RAIN, remaining_ticks=5, wind=4),
            agents=(
                Agent(AgentId("ag_01"), Position(0, 0)),
                Agent(AgentId("ag_02"), Position(5, 5)),
                dead,
            ),
            structures=(
                Structure(StructureKind.FIRE, Position(1, 1)),
                Structure(StructureKind.SHELTER, Position(2, 1)),
            ),
            trades=(
                TradeOffer.propose(
                    AgentId("ag_01"),
                    AgentId("ag_02"),
                    0,
                    ((ItemId("wood"), 1),),
                    ((ItemId("berry"), 1),),
                ),
            ),
        )

    def test_the_world_screen_shows_climate_agents_and_summary(self) -> None:
        reports = {
            AgentId("ag_01"): MindReport(
                agent_id=AgentId("ag_01"),
                tick=0,
                intent="Buscar agua",
                thought="Sed",
            )
        }
        results = {
            AgentId("ag_01"): {"action": "move", "outcome": "moved"},
        }
        screen = render_world_screen(
            self._state(),
            NAMES,
            selected_agent_id=AgentId("ag_01"),
            events=["evento uno", "evento dos"],
            mind_reports=reports,
            last_results=results,
            paused=True,
        )
        text = screen.to_text()

        self.assertEqual((screen.width, screen.height), (160, 45))
        self.assertTrue(all(len(screen.row_text(y)) == 160 for y in range(45)))
        for expected in (
            "F3 · MUNDO",
            "DÍA 1",
            "LLUVIA",
            "VIENTO 4",
            "VIS",
            "PAUSA",
            "AGENTES 3/8",
            "AGENTE",
            "POS",
            "SAL",
            "HAM",
            "SED",
            "ENE",
            "TEMP",
            "ESTADO",
            "INTENCIÓN",
            "ÚLTIMA ACCIÓN",
            "Nia",
            "Kai",
            "Luma",
            "MUERTO",
            "Buscar agua",
            "move/moved",
            "MUNDO",
            "Fuegos: 1",
            "Refugios: 1",
            "Cadáveres: 1",
            "Árboles: 1",
            "Arbustos: 1",
            "Ofertas activas: 1",
            "EVENTOS RECIENTES",
            "evento dos",
            "[Enter] Ver ficha F2",
        ):
            self.assertIn(expected, text)

    def test_the_table_marks_the_selected_agent(self) -> None:
        screen = render_world_screen(
            self._state(),
            NAMES,
            selected_agent_id=AgentId("ag_02"),
        )

        selected_row = next(
            row for row in screen.to_text().splitlines() if "Kai" in row and "ag_02" not in row
        )
        self.assertIn("▶", selected_row)

    def test_the_world_screen_handles_an_empty_world(self) -> None:
        empty = SessionState(
            seed=1,
            tick=0,
            rng_state=1,
            world=WorldMap(width=4, height=4, tiles=(TileType.GRASS,) * 16),
        )

        screen = render_world_screen(empty, {})

        self.assertIn("sin agentes", screen.to_text())


class MapScreenTests(unittest.TestCase):
    def _state(self, *, weather: WeatherState | None = None) -> SessionState:
        tiles = [TileType.GRASS] * 64
        tiles[3 * 8 + 3] = TileType.TREE
        agents = (
            Agent(AgentId("ag_01"), Position(1, 1)),
            Agent(AgentId("ag_02"), Position(2, 2)),
        )
        return SessionState(
            seed=3,
            tick=2,
            rng_state=3,
            world=WorldMap(width=8, height=8, tiles=tuple(tiles)),
            weather=weather or WeatherState(),
            agents=agents,
            ground_items=(
                GroundItem(
                    Position(6, 6),
                    ItemStack(CATALOG.item("wood").definition, 1),
                ),
            ),
            corpses=(
                Corpse.from_agent(
                    Agent(AgentId("ag_03"), Position(5, 5)),
                    tick=1,
                    cause="starvation",
                ),
            ),
        )

    def test_the_enlarged_map_is_centered_and_complete(self) -> None:
        screen = render_map_screen(
            self._state(),
            {AgentId("ag_01"): "Nia", AgentId("ag_02"): "Kai"},
            selected_agent_id=AgentId("ag_01"),
        )

        self.assertEqual((screen.width, screen.height), (160, 45))
        self.assertTrue(all(len(screen.row_text(y)) == 160 for y in range(45)))
        self.assertEqual(
            screen.cell_at(40, 0).char,
            theme.tile_glyph(TileType.GRASS),
        )
        self.assertEqual(screen.cell_at(43, 3).char, theme.tile_glyph(TileType.TREE))
        self.assertEqual(screen.cell_at(41, 1).char, "@")
        self.assertEqual(screen.cell_at(45, 5).char, theme.CORPSE_GLYPH)
        self.assertEqual(screen.cell_at(46, 6).char, theme.GROUND_ITEM_GLYPH)
        self.assertEqual(screen.cell_at(0, 0).char, " ")

    def test_header_legend_and_layer_help_are_readable(self) -> None:
        screen = render_map_screen(
            self._state(),
            {AgentId("ag_01"): "Nia", AgentId("ag_02"): "Kai"},
            selected_agent_id=AgentId("ag_01"),
        )
        text = "\n".join(screen.row_text(y) for y in range(40, 45))

        for expected in (
            "F6 · MAPA",
            "MAPA COMPLETO DEL OPERADOR",
            "LEYENDA",
            "árbol",
            "fuego",
            "refugio",
            "cadáver",
            "objeto",
            "agente",
            "memoria",
            "clima",
            "Agente: Nia",
            "Capas: V FOV",
            "[V] FOV",
            "[W] Clima",
            "[X] Inspección",
            "[ESC] Volver",
            "[F6] Cerrar mapa",
        ):
            self.assertIn(expected, text)

    def test_focus_mode_uses_the_selected_agent_fov(self) -> None:
        screen = render_map_screen(
            self._state(),
            {AgentId("ag_01"): "Nia"},
            selected_agent_id=AgentId("ag_01"),
            focus_mode=True,
            weather_overlay=False,
        )
        text = screen.to_text()

        self.assertIn("FOV DEL AGENTE", text)
        self.assertEqual(screen.cell_at(47, 7).char, " ")

    def test_the_weather_layer_can_be_toggled(self) -> None:
        state = self._state(weather=WeatherState(kind=WeatherKind.RAIN, remaining_ticks=5, wind=4))

        with_overlay = render_map_screen(state, {}, weather_overlay=True)
        without_overlay = render_map_screen(state, {}, weather_overlay=False)

        self.assertIn("LLUVIA", with_overlay.to_text())
        self.assertNotEqual(with_overlay.to_text(), without_overlay.to_text())
        self.assertIn("Clima: OFF", without_overlay.to_text())

    def test_the_selected_agent_line_follows_the_selection(self) -> None:
        screen = render_map_screen(
            self._state(),
            {AgentId("ag_01"): "Nia", AgentId("ag_02"): "Kai"},
            selected_agent_id=AgentId("ag_02"),
        )

        self.assertIn("Agente: Kai (2, 2)", screen.to_text())


class ConnectionLifecycleTests(unittest.TestCase):
    def _state(self) -> SessionState:
        catalog = load_catalog()
        absent = Agent(
            AgentId("ag_02"),
            Position(3, 2),
            status=AgentStatus.ABSENT,
        )
        dead = Agent(
            AgentId("ag_03"),
            Position(2, 3),
            attributes=AgentAttributes(health_centi=0),
            status=AgentStatus.DEAD,
            inventory=Inventory.for_strength(5).add(ItemStack(catalog.item("wood").definition, 2)),
        )
        return SessionState(
            seed=1,
            tick=4,
            rng_state=1,
            world=WorldMap(width=6, height=6, tiles=(TileType.GRASS,) * 36),
            agents=(
                Agent(AgentId("ag_01"), Position(2, 2)),
                absent,
                dead,
            ),
            corpses=(Corpse.from_agent(dead, tick=2, cause="attack"),),
        )

    def _panel_text(self, screen) -> str:
        return "\n".join(screen.row_text(y)[80:] for y in range(44))

    def test_connection_states_and_free_slots_are_distinguishable(self) -> None:
        screen = render_base_screen(
            self._state(),
            {
                AgentId("ag_01"): "Nia",
                AgentId("ag_02"): "Kai",
                AgentId("ag_03"): "Luma",
            },
            selected_agent_id=AgentId("ag_01"),
            capacity=5,
        )
        panel = self._panel_text(screen)

        self.assertIn("1 con", panel)
        self.assertIn("1 aus", panel)
        self.assertIn("1 mue", panel)
        self.assertIn("2 lib", panel)
        self.assertIn("LIBRES: ag_04, ag_05", panel)
        self.assertIn("ausente", panel)
        self.assertIn("muerto por attack", panel)
        self.assertNotIn("ag_06", panel)

    def test_waiting_reasons_are_labelled(self) -> None:
        labels = {
            "no_agents": "SIN AGENTES",
            "last_death": "ÚLTIMA MUERTE",
            "no_active_agents": "SIN AGENTES ACTIVOS",
        }
        for reason, label in labels.items():
            with self.subTest(reason=reason):
                screen = render_base_screen(
                    self._state(),
                    {},
                    selected_agent_id=AgentId("ag_01"),
                    waiting_reason=reason,
                )
                panel = self._panel_text(screen)
                self.assertIn("ESPERANDO AGENTES", panel)
                self.assertIn(label, panel)

    def test_disconnected_agents_leave_no_ghost_row(self) -> None:
        state = self._state()
        names = {
            AgentId("ag_01"): "Nia",
            AgentId("ag_02"): "Kai",
            AgentId("ag_09"): "Fantasma",
        }

        screen = render_base_screen(
            state,
            names,
            selected_agent_id=AgentId("ag_01"),
            capacity=5,
        )

        self.assertNotIn("Fantasma", self._panel_text(screen))

    def test_the_compact_strip_marks_absent_agents_and_free_slots(self) -> None:
        screen = render_base_screen(
            self._state(),
            {AgentId("ag_01"): "Nia", AgentId("ag_02"): "Kai"},
            selected_agent_id=AgentId("ag_01"),
            capacity=5,
            panel=PanelState(tab=RightPanelTab.EVENTS),
            events=["evento"],
        )
        panel = self._panel_text(screen)

        self.assertIn("…", panel)
        self.assertIn("+2 libres", panel)

    def test_corpse_loot_is_visible_for_the_dead_selection(self) -> None:
        screen = render_base_screen(
            self._state(),
            {
                AgentId("ag_01"): "Nia",
                AgentId("ag_02"): "Kai",
                AgentId("ag_03"): "Luma",
            },
            selected_agent_id=AgentId("ag_03"),
            capacity=5,
        )
        panel = self._panel_text(screen)

        self.assertIn("CADÁVER", panel)
        self.assertIn("Botín: wood x2", panel)

    def test_the_links_tab_shows_corpse_details(self) -> None:
        screen = render_base_screen(
            self._state(),
            {AgentId("ag_01"): "Nia", AgentId("ag_03"): "Luma"},
            selected_agent_id=AgentId("ag_03"),
            capacity=5,
            panel=PanelState(tab=RightPanelTab.LINKS),
        )
        panel = self._panel_text(screen)

        self.assertIn("CADÁVER", panel)
        self.assertIn("Botín: wood x2", panel)


class ReplayScreenTests(unittest.TestCase):
    def test_the_replay_screen_reuses_the_base_layout_with_a_banner(self) -> None:
        state = _state()
        screen = render_replay_screen(
            state,
            NAMES,
            tick=2,
            total_ticks=5,
            paused=True,
            selected_agent_id=AgentId("ag_01"),
        )
        text = screen.to_text()

        self.assertEqual((screen.width, screen.height), (160, 45))
        self.assertTrue(all(len(screen.row_text(y)) == 160 for y in range(45)))
        for expected in (
            "REPLAY · TICK 2/5 · PAUSA",
            "AGENTES",
            "AGENTE SELECCIONADO",
            "MENTE (REPORTADO)",
            "ENTORNO",
            "RELACIONES",
            "EVENTOS",
            "[←/→] Tick",
            "[F5] Salir del replay",
        ):
            self.assertIn(expected, text)
        agent = state.agents[0]
        self.assertEqual(screen.cell_at(agent.position.x, agent.position.y).char, "@")

    def test_the_replay_banner_reflects_playback_state(self) -> None:
        screen = render_replay_screen(
            _state(),
            NAMES,
            tick=0,
            total_ticks=3,
            paused=False,
        )

        self.assertIn("REPLAY · TICK 0/3 · EN CURSO", screen.to_text())


if __name__ == "__main__":
    unittest.main()
