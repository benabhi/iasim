"""Tests for presentation-only operator controls."""

from __future__ import annotations

import unittest

from iasim.domain.identifiers import AgentId
from iasim.ui.controls import KEY_GUIDE, SPEEDS, UiCommand, UiState, handle_key

AGENTS = (AgentId("ag_01"), AgentId("ag_02"), AgentId("ag_03"))


class UiControlTests(unittest.TestCase):
    def test_space_toggles_pause(self) -> None:
        state = handle_key(UiState(), " ", AGENTS)
        self.assertTrue(state.paused)

        state = handle_key(state, "space", AGENTS)
        self.assertFalse(state.paused)

    def test_digits_and_tab_select_agents(self) -> None:
        state = handle_key(UiState(), "2", AGENTS)
        self.assertEqual(state.selected_agent_id, AgentId("ag_02"))

        state = handle_key(state, "tab", AGENTS)
        self.assertEqual(state.selected_agent_id, AgentId("ag_03"))

        state = handle_key(state, "tab", AGENTS)
        self.assertEqual(state.selected_agent_id, AgentId("ag_01"))

    def test_selection_ignores_missing_or_out_of_range_agents(self) -> None:
        self.assertEqual(handle_key(UiState(), "9", AGENTS), UiState())
        self.assertEqual(
            handle_key(UiState(), "2", ()),
            UiState(),
        )

    def test_speed_is_bounded_to_supported_values(self) -> None:
        state = UiState()
        for expected in SPEEDS[1:]:
            state = handle_key(state, "+", AGENTS)
            self.assertEqual(state.speed, expected)

        state = handle_key(state, "+", AGENTS)
        self.assertEqual(state.speed, SPEEDS[-1])

        for expected in reversed(SPEEDS[:-1]):
            state = handle_key(state, "-", AGENTS)
            self.assertEqual(state.speed, expected)

        state = handle_key(state, "-", AGENTS)
        self.assertEqual(state.speed, SPEEDS[0])

    def test_f1_opens_help_and_escape_closes_it(self) -> None:
        state = handle_key(UiState(), "f1", AGENTS)
        self.assertTrue(state.help_open)

        state = handle_key(state, "esc", AGENTS)
        self.assertFalse(state.help_open)

    def test_a_toggles_ascii_mode(self) -> None:
        state = handle_key(UiState(), "a", AGENTS)
        self.assertTrue(state.ascii_mode)
        state = handle_key(state, "a", AGENTS)
        self.assertFalse(state.ascii_mode)

    def test_v_toggles_focus_mode(self) -> None:
        state = handle_key(UiState(), "v", AGENTS)
        self.assertTrue(state.focus_mode)
        state = handle_key(state, "v", AGENTS)
        self.assertFalse(state.focus_mode)

    def test_quit_and_restart_require_confirmation(self) -> None:
        quit_pending = handle_key(UiState(), "q", AGENTS)
        self.assertEqual(quit_pending.pending_confirmation, UiCommand.QUIT)
        self.assertFalse(quit_pending.quit_requested)

        quit_confirmed = handle_key(quit_pending, "q", AGENTS)
        self.assertTrue(quit_confirmed.quit_requested)
        self.assertIsNone(quit_confirmed.pending_confirmation)

        restart_pending = handle_key(UiState(), "r", AGENTS)
        self.assertEqual(restart_pending.pending_confirmation, UiCommand.RESTART)
        self.assertFalse(restart_pending.restart_requested)

        restart_confirmed = handle_key(restart_pending, "r", AGENTS)
        self.assertTrue(restart_confirmed.restart_requested)

    def test_escape_cancels_confirmation(self) -> None:
        pending = handle_key(UiState(), "q", AGENTS)
        cancelled = handle_key(pending, "esc", AGENTS)

        self.assertIsNone(cancelled.pending_confirmation)
        self.assertFalse(cancelled.quit_requested)

    def test_key_guide_covers_critical_controls(self) -> None:
        keys = {key for key, _ in KEY_GUIDE}

        self.assertTrue({"ESPACIO", "1-8", "TAB", "+ / -", "F1", "A", "Q", "R", "ESC"} <= keys)


if __name__ == "__main__":
    unittest.main()
