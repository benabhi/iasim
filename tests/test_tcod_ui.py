"""Tests for the libtcod console and keyboard adapters."""

from __future__ import annotations

import unittest

from tcod.event import KeyDown, KeySym, Modifier, Scancode

from iasim.domain.identifiers import AgentId
from iasim.domain.session import SessionState
from iasim.domain.tiles import TileType, WorldMap
from iasim.ui.controls import UiState
from iasim.ui.layout import render_base_screen
from iasim.ui.tcod_console import handle_tcod_event, key_from_event, screen_to_console


def _screen():
    state = SessionState(
        seed=42,
        tick=0,
        rng_state=42,
        world=WorldMap(width=5, height=5, tiles=(TileType.GRASS,) * 25),
    )
    return render_base_screen(state, {})


class TcodUiTests(unittest.TestCase):
    def test_screen_converts_to_a_same_size_console(self) -> None:
        screen = _screen()
        console = screen_to_console(screen)

        self.assertEqual((console.width, console.height), (screen.width, screen.height))
        self.assertEqual(chr(int(console.ch[0, 0])), screen.cell_at(0, 0).char[0])

    def test_key_adapter_uses_the_existing_controller(self) -> None:
        focus_event = KeyDown(
            sym=KeySym.V,
            scancode=Scancode.V,
            mod=Modifier.NONE,
        )
        select_event = KeyDown(
            sym=KeySym.N2,
            scancode=Scancode.N2,
            mod=Modifier.NONE,
        )

        self.assertEqual(key_from_event(focus_event), "v")
        self.assertTrue(handle_tcod_event(UiState(), focus_event, ()).focus_mode)
        self.assertEqual(
            handle_tcod_event(
                UiState(),
                select_event,
                (AgentId("ag_01"), AgentId("ag_02")),
            ).selected_agent_id,
            AgentId("ag_02"),
        )


if __name__ == "__main__":
    unittest.main()
