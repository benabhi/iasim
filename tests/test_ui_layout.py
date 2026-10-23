"""Tests for the deterministic 160x45 base layout."""

from __future__ import annotations

import hashlib
import unittest

from iasim.domain.agents import Agent
from iasim.domain.geometry import Position
from iasim.domain.identifiers import AgentId
from iasim.domain.session import SessionState
from iasim.domain.tiles import TileType, WorldMap
from iasim.ui import theme
from iasim.ui.layout import render_base_screen, render_help_screen
from iasim.world.generation import generate_layout

LAYOUT = generate_layout(42, agent_count=3)
NAMES = {
    AgentId("ag_01"): "Nia",
    AgentId("ag_02"): "Kai",
    AgentId("ag_03"): "Luma",
}
GOLDEN_HASH = "61636864be8bdf086bb5a0f9572d6b28c433172ea48f4c58c6a788ea8e3643cf"


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


if __name__ == "__main__":
    unittest.main()
