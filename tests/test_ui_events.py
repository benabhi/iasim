"""Tests for the F4 event log: filtering, pagination, rendering and controls."""

from __future__ import annotations

import unittest

from iasim.domain.identifiers import AgentId
from iasim.ui.controls import KEY_GUIDE, UiState, UiView, handle_key
from iasim.ui.events import (
    CATEGORY_ACTIONS,
    CATEGORY_COMBAT,
    CATEGORY_LABELS,
    CATEGORY_MCP,
    CATEGORY_ORDER,
    PAGE_SIZE,
    EventRow,
    filter_events,
    next_category,
    page_count,
    page_rows,
)
from iasim.ui.layout import render_events_screen

AGENTS = (AgentId("ag_01"), AgentId("ag_02"))


def _rows(count: int = 8) -> tuple[EventRow, ...]:
    categories = (
        CATEGORY_ACTIONS,
        CATEGORY_COMBAT,
        "social",
        "necesidades",
        "clima",
        CATEGORY_MCP,
    )
    rows = [
        EventRow(
            tick=index,
            category=categories[index % len(categories)],
            agents=f"ag_0{(index % 2) + 1}",
            message=f"evento {index}",
            result="ok",
        )
        for index in range(count)
    ]
    rows.extend(
        (
            EventRow(
                tick=count,
                category=CATEGORY_MCP,
                agents="ag_01",
                message="join",
                result="conectado",
            ),
            EventRow(
                tick=count + 1,
                category=CATEGORY_MCP,
                agents="ag_02",
                message="disconnect",
                result="transport_closed",
            ),
            EventRow(
                tick=count + 2,
                category=CATEGORY_COMBAT,
                agents="ag_01 → ag_02",
                message="ataque",
                result="killed",
            ),
        )
    )
    return tuple(rows)


class EventFilterTests(unittest.TestCase):
    def test_categories_cover_the_srs_filters(self) -> None:
        self.assertEqual(
            set(CATEGORY_ORDER),
            {
                "acciones",
                "combate",
                "social",
                "necesidades",
                "clima",
                "mcp",
            },
        )
        self.assertEqual(set(CATEGORY_LABELS), set(CATEGORY_ORDER))

    def test_rows_validate_their_category_and_tick(self) -> None:
        with self.assertRaises(ValueError):
            EventRow(tick=0, category="unknown", agents="", message="")
        with self.assertRaises(ValueError):
            EventRow(tick=-1, category=CATEGORY_ACTIONS, agents="", message="")

    def test_query_matches_message_agents_and_result_case_insensitively(self) -> None:
        rows = _rows()

        joined = filter_events(rows, query="JOIN")
        disconnected = filter_events(rows, query="transport_closed")
        by_agent = filter_events(rows, query="ag_02")

        self.assertEqual(len(joined), 1)
        self.assertEqual(joined[0].message, "join")
        self.assertEqual(len(disconnected), 1)
        self.assertEqual(disconnected[0].message, "disconnect")
        self.assertTrue(all("ag_02" in row.agents for row in by_agent))

    def test_category_and_agent_filters_combine(self) -> None:
        rows = _rows(6)

        combat = filter_events(rows, category=CATEGORY_COMBAT, agent_id="ag_01")
        actions = filter_events(rows, category=CATEGORY_ACTIONS)

        self.assertTrue(all(row.category == CATEGORY_COMBAT for row in combat))
        self.assertTrue(all("ag_01" in row.agents for row in combat))
        self.assertTrue(all(row.category == CATEGORY_ACTIONS for row in actions))

    def test_category_cycle_wraps_through_all_and_the_six_filters(self) -> None:
        seen = []
        category = None
        for _ in range(7):
            category = next_category(category)
            seen.append(category)

        self.assertEqual(seen[-1], None)
        self.assertEqual(
            set(seen[:-1]),
            set(CATEGORY_ORDER),
        )

    def test_pages_cover_every_row_without_truncation(self) -> None:
        rows = _rows(45)

        self.assertEqual(page_count(len(rows)), 3)
        first = page_rows(rows, 0)
        second = page_rows(rows, 1)
        third = page_rows(rows, 2)
        self.assertEqual(len(first), PAGE_SIZE)
        self.assertEqual(len(second), PAGE_SIZE)
        self.assertEqual(len(third), len(rows) - 2 * PAGE_SIZE)
        self.assertEqual(len({*first, *second, *third}), len(rows))


class EventScreenTests(unittest.TestCase):
    def _panel_text(self, screen) -> str:
        return "\n".join(screen.row_text(y) for y in range(45))

    def test_the_log_shows_columns_categories_and_lifecycle_rows(self) -> None:
        screen = render_events_screen(_rows())
        text = self._panel_text(screen)

        self.assertEqual((screen.width, screen.height), (160, 45))
        self.assertTrue(all(len(screen.row_text(y)) == 160 for y in range(45)))
        for expected in (
            "F4 · EVENTOS",
            "Búsqueda: —",
            "Filtro: TODOS",
            "Agente: TODOS",
            "TICK",
            "HORA",
            "TIPO",
            "AGENTES",
            "MENSAJE",
            "RESULTADO",
            "join",
            "disconnect",
            "ataque",
            "ACCIONES",
            "COMBATE",
            "MCP/ERRORES",
            "[PgUp/PgDn] Página",
            "[/] Buscar",
        ):
            self.assertIn(expected, text)

    def test_type_colors_are_distinct_and_paired_with_labels(self) -> None:
        screen = render_events_screen(
            (
                EventRow(0, CATEGORY_ACTIONS, "ag_01", "camina", "moved"),
                EventRow(0, CATEGORY_COMBAT, "ag_01", "ataca", "hit"),
            )
        )

        colors = {screen.cell_at(2, y).fg for y in (3, 4)}
        self.assertEqual(len(colors), 2)
        self.assertIn("ACCIONES", screen.to_text())
        self.assertIn("COMBATE", screen.to_text())

    def test_search_and_filters_reduce_the_visible_rows(self) -> None:
        rows = _rows()

        searched = render_events_screen(rows, query="disconnect")
        combat = render_events_screen(rows, category=CATEGORY_COMBAT)
        agent = render_events_screen(rows, agent_id="ag_01")

        self.assertIn("Búsqueda: disconnect", searched.to_text())
        self.assertIn("1/", searched.to_text())
        self.assertNotIn("evento 0", searched.to_text())
        self.assertIn("Filtro: COMBATE", combat.to_text())
        self.assertIn("Agente: ag_01", agent.to_text())
        self.assertIn(
            "— sin eventos para este filtro —",
            render_events_screen(
                rows,
                query="no-existe",
            ).to_text(),
        )

    def test_later_pages_show_the_remaining_rows(self) -> None:
        rows = _rows(45)

        first = render_events_screen(rows, page=0).to_text()
        third = render_events_screen(rows, page=2).to_text()

        self.assertIn("Página 1/3", first)
        self.assertIn("Página 3/3", third)
        self.assertIn("evento 0", first)
        self.assertNotIn("evento 44", first)
        self.assertIn("evento 44", third)

    def test_long_content_is_clipped_within_the_screen(self) -> None:
        rows = (
            EventRow(
                tick=1,
                category=CATEGORY_ACTIONS,
                agents="A" * 200,
                message="M" * 400,
                result="R" * 200,
            ),
        )

        screen = render_events_screen(rows)

        self.assertTrue(all(len(screen.row_text(y)) == 160 for y in range(45)))
        self.assertIn("…", screen.to_text())


class EventControlTests(unittest.TestCase):
    def test_f4_toggles_the_log_view(self) -> None:
        state = handle_key(UiState(), "f4", AGENTS)

        self.assertEqual(state.view, UiView.EVENT_LOG)
        self.assertEqual(handle_key(state, "f4", AGENTS).view, UiView.NONE)

    def test_slash_search_accepts_text_and_backspace(self) -> None:
        state = handle_key(UiState(), "f4", AGENTS)
        state = handle_key(state, "/", AGENTS)
        self.assertTrue(state.event_search_open)
        for char in "join":
            state = handle_key(state, char, AGENTS)
        self.assertEqual(state.event_query, "join")
        self.assertEqual(handle_key(state, "backspace", AGENTS).event_query, "joi")
        state = handle_key(state, "enter", AGENTS)
        self.assertFalse(state.event_search_open)
        self.assertEqual(state.event_query, "join")

    def test_type_and_agent_filters_cycle(self) -> None:
        state = handle_key(UiState(), "f4", AGENTS)
        state = handle_key(state, "t", AGENTS)
        self.assertEqual(state.event_category, CATEGORY_ORDER[0])
        state = handle_key(state, "t", AGENTS)
        self.assertEqual(state.event_category, CATEGORY_ORDER[1])
        state = handle_key(state, "a", AGENTS)
        self.assertTrue(state.event_agent_only)
        self.assertEqual(handle_key(state, "a", AGENTS).event_agent_only, False)

    def test_paging_and_escape(self) -> None:
        state = handle_key(UiState(), "f4", AGENTS)
        state = handle_key(state, "pagedown", AGENTS)
        self.assertEqual(state.event_page, 1)
        state = handle_key(state, "pagedown", AGENTS)
        state = handle_key(state, "pageup", AGENTS)
        self.assertEqual(state.event_page, 1)
        state = handle_key(state, "up", AGENTS)
        state = handle_key(state, "up", AGENTS)
        self.assertEqual(state.event_page, 0)
        self.assertEqual(handle_key(state, "esc", AGENTS).view, UiView.NONE)

    def test_key_guide_mentions_the_event_log(self) -> None:
        keys = {key for key, _ in KEY_GUIDE}
        self.assertTrue({"F4", "/", "T / A"} <= keys)


if __name__ == "__main__":
    unittest.main()
