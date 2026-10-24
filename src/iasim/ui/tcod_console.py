"""libtcod console and keyboard adapters for the operator UI."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import tcod
import tcod.event

from iasim.domain.identifiers import AgentId
from iasim.ui.controls import UiState, handle_key
from iasim.ui.layout import BaseScreen

_KEY_BY_NAME: dict[str, str] = {
    "SPACE": "space",
    "ESCAPE": "esc",
    "TAB": "tab",
    "RETURN": "enter",
    "BACKSPACE": "backspace",
    "PLUS": "+",
    "MINUS": "-",
    "SLASH": "/",
    "F1": "f1",
    "F2": "f2",
    "F3": "f3",
    "F4": "f4",
    "F5": "f5",
    "F6": "f6",
    "F7": "f7",
    "F8": "f8",
    "F9": "f9",
    "F10": "f10",
    "F11": "f11",
    "F12": "f12",
    "UP": "up",
    "DOWN": "down",
    "LEFT": "left",
    "RIGHT": "right",
    "PAGEUP": "pageup",
    "PAGEDOWN": "pagedown",
    "HOME": "home",
    "END": "end",
    "LEFTBRACKET": "[",
    "RIGHTBRACKET": "]",
    "LBRACKET": "[",
    "RBRACKET": "]",
}


def screen_to_console(screen: BaseScreen) -> tcod.console.Console:
    """Convert an immutable BaseScreen into a libtcod console."""
    console = tcod.console.Console(screen.width, screen.height)
    chars = np.asarray(
        [
            [
                ord(cell.char[0]) if cell.char else 32
                for cell in screen.cells[row * screen.width : (row + 1) * screen.width]
            ]
            for row in range(screen.height)
        ],
        dtype=np.int32,
    )
    foreground = np.asarray(
        [
            [cell.fg for cell in screen.cells[row * screen.width : (row + 1) * screen.width]]
            for row in range(screen.height)
        ],
        dtype=np.uint8,
    )
    background = np.asarray(
        [
            [cell.bg for cell in screen.cells[row * screen.width : (row + 1) * screen.width]]
            for row in range(screen.height)
        ],
        dtype=np.uint8,
    )
    console.ch[:] = chars
    console.fg[:] = foreground
    console.bg[:] = background
    return console


def key_from_event(event: tcod.event.KeyDown) -> str | None:
    """Map a libtcod key event to the existing UI key vocabulary."""
    name = event.sym.name
    if name in _KEY_BY_NAME:
        return _KEY_BY_NAME[name]
    if name.startswith("N") and name[1:].isdigit():
        return name[1:]
    if len(name) == 1 and name.isalpha():
        return name.lower()
    return None


def request_fullscreen(enabled: bool) -> None:
    """Ask the terminal backend to switch fullscreen (window-level, F11)."""
    setter = getattr(tcod, "sys_set_fullscreen", None)
    if callable(setter):
        setter(enabled)


def handle_tcod_event(
    state: UiState,
    event: tcod.event.KeyDown,
    agent_ids: Sequence[AgentId],
) -> UiState:
    """Apply a libtcod key event through the presentation-only controller."""
    key = key_from_event(event)
    return state if key is None else handle_key(state, key, agent_ids)
