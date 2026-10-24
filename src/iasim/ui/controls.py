"""Keyboard-driven operator UI state and bindings.

The UI loop owns presentation state only. These helpers never submit game
actions or mutate the simulation; the operator can select and observe agents,
pause presentation, change speed, open help, and request a session-level quit
or restart.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum

from iasim.domain.geometry import Position
from iasim.domain.identifiers import AgentId
from iasim.ui.events import next_category
from iasim.ui.panel import PANEL_PAGE, PANEL_STEP, PanelState, RightPanelTab

SPEEDS: tuple[int, ...] = (1, 2, 4, 8)

KEY_GUIDE: tuple[tuple[str, str], ...] = (
    ("ESPACIO", "Pausa / reanudar"),
    ("1-8", "Seleccionar agente"),
    ("TAB", "Siguiente agente"),
    ("+ / -", "Cambiar velocidad"),
    ("[ / ]", "Cambiar pestaña del panel"),
    ("↑ / ↓", "Desplazar la pestaña activa"),
    ("PgUp/PgDn", "Desplazar una página"),
    ("F1", "Abrir / cerrar ayuda"),
    ("F2", "Abrir / cerrar ficha completa del agente"),
    ("F3", "Abrir / cerrar resumen del mundo"),
    ("F4", "Abrir / cerrar registro de eventos"),
    ("F6", "Abrir / cerrar mapa ampliado"),
    ("/", "Buscar en el registro de eventos"),
    ("T / A", "Filtrar eventos por tipo o agente"),
    ("PgUp/PgDn", "Paginar el registro de eventos"),
    ("A", "Alternar ASCII"),
    ("V", "Alternar foco FOV / mapa completo"),
    ("W", "Alternar capa de clima"),
    ("X", "Activar / desactivar cursor de inspección"),
    ("Enter", "Fijar / liberar la inspección"),
    ("Q", "Salir (confirmar)"),
    ("R", "Reiniciar (confirmar)"),
    ("ESC", "Cancelar / cerrar ayuda o volver a RESUMEN"),
)

STATUS_GUIDE: tuple[tuple[str, str], ...] = (
    ("HAMBRE", "hambre alta"),
    ("SED", "sed alta"),
    ("AGOTADO", "energía baja"),
    ("MOJADO", "mojadura alta"),
    ("SANGRANDO", "herida que causa daño por tick"),
    ("FRÍO", "temperatura corporal baja"),
    ("CALOR", "temperatura corporal alta"),
    ("MUERTO", "agente sin vida"),
)


class UiCommand(StrEnum):
    """Destructive commands that require a second key press."""

    QUIT = "quit"
    RESTART = "restart"


class UiView(StrEnum):
    """Full-screen operator views opened from the base layout."""

    NONE = "none"
    AGENT_SHEET = "agent_sheet"
    WORLD_SUMMARY = "world_summary"
    EVENT_LOG = "event_log"
    MAP_VIEW = "map_view"


@dataclass(frozen=True, slots=True)
class UiState:
    """Presentation-only state controlled by the operator."""

    selected_agent_id: AgentId | None = None
    paused: bool = False
    speed: int = 1
    help_open: bool = False
    ascii_mode: bool = False
    focus_mode: bool = False
    weather_overlay: bool = True
    pending_confirmation: UiCommand | None = None
    quit_requested: bool = False
    restart_requested: bool = False
    panel: PanelState = field(default_factory=PanelState)
    view: UiView = UiView.NONE
    event_query: str = ""
    event_category: str | None = None
    event_agent_only: bool = False
    event_page: int = 0
    event_search_open: bool = False
    cursor: Position | None = None
    inspection_pinned: bool = False


def handle_key(
    state: UiState,
    key: str,
    agent_ids: Sequence[AgentId],
    *,
    world_size: tuple[int, int] | None = None,
) -> UiState:
    """Apply one keyboard event and return the next presentation state."""
    normalized = _normalize_key(key)

    if state.pending_confirmation is not None:
        if normalized == "esc":
            return replace(state, pending_confirmation=None)
        if state.pending_confirmation is UiCommand.QUIT and normalized == "q":
            return replace(state, pending_confirmation=None, quit_requested=True)
        if state.pending_confirmation is UiCommand.RESTART and normalized == "r":
            return replace(state, pending_confirmation=None, restart_requested=True)
        return replace(state, pending_confirmation=None)

    if state.help_open:
        if normalized in {"f1", "esc"}:
            return replace(state, help_open=False)
        return state

    if state.event_search_open:
        if normalized in {"esc", "enter"}:
            return replace(state, event_search_open=False)
        if normalized in {"backspace", "bksp"}:
            return replace(
                state,
                event_query=state.event_query[:-1],
                event_page=0,
            )
        if len(normalized) == 1:
            return replace(
                state,
                event_query=(state.event_query + normalized)[:40],
                event_page=0,
            )
        return state

    if normalized == "esc":
        if state.cursor is not None:
            return replace(state, cursor=None, inspection_pinned=False)
        if state.view is not UiView.NONE:
            return replace(state, view=UiView.NONE)
        if state.panel.tab is not RightPanelTab.SUMMARY:
            return replace(state, panel=state.panel.with_tab(RightPanelTab.SUMMARY))
        return state

    if normalized == "x":
        if state.cursor is None:
            return replace(state, cursor=Position(0, 0))
        return replace(state, cursor=None, inspection_pinned=False)

    if normalized == "enter" and state.cursor is not None:
        return replace(state, inspection_pinned=not state.inspection_pinned)

    if normalized == "f2":
        view = UiView.NONE if state.view is UiView.AGENT_SHEET else UiView.AGENT_SHEET
        return replace(state, view=view)

    if normalized == "f3":
        view = UiView.NONE if state.view is UiView.WORLD_SUMMARY else UiView.WORLD_SUMMARY
        return replace(state, view=view)

    if normalized == "f4":
        view = UiView.NONE if state.view is UiView.EVENT_LOG else UiView.EVENT_LOG
        return replace(state, view=view, event_search_open=False)

    if normalized == "f6":
        view = UiView.NONE if state.view is UiView.MAP_VIEW else UiView.MAP_VIEW
        return replace(state, view=view)

    if normalized == "enter" and state.view is UiView.WORLD_SUMMARY:
        return replace(state, view=UiView.AGENT_SHEET)

    if state.view is UiView.EVENT_LOG and normalized == "/":
        return replace(state, event_search_open=True)

    if state.view is UiView.EVENT_LOG and normalized == "t":
        return replace(
            state,
            event_category=next_category(state.event_category),
            event_page=0,
        )

    if state.view is UiView.EVENT_LOG and normalized == "a":
        return replace(
            state,
            event_agent_only=not state.event_agent_only,
            event_page=0,
        )

    if normalized in {"[", "leftbracket", "lbrace"}:
        return replace(state, panel=state.panel.cycle(-1))

    if normalized in {"]", "rightbracket", "rbrace"}:
        return replace(state, panel=state.panel.cycle(1))

    if state.cursor is not None and normalized in {"up", "down", "left", "right"}:
        dx = {"left": -1, "right": 1}.get(normalized, 0)
        dy = {"up": -1, "down": 1}.get(normalized, 0)
        return replace(
            state,
            cursor=_move_cursor(state.cursor, dx, dy, world_size),
        )

    if normalized in {"up", "down"}:
        if state.view is UiView.EVENT_LOG:
            return replace(
                state,
                event_page=_move_page(state.event_page, -1 if normalized == "up" else 1),
            )
        delta = -PANEL_STEP if normalized == "up" else PANEL_STEP
        return replace(state, panel=state.panel.scrolled(delta))

    if normalized in {"pageup", "pgup", "prior"}:
        if state.view is UiView.EVENT_LOG:
            return replace(state, event_page=_move_page(state.event_page, -1))
        return replace(state, panel=state.panel.scrolled(-PANEL_PAGE))

    if normalized in {"pagedown", "pgdn", "next"}:
        if state.view is UiView.EVENT_LOG:
            return replace(state, event_page=_move_page(state.event_page, 1))
        return replace(state, panel=state.panel.scrolled(PANEL_PAGE))

    if normalized == "home":
        return replace(state, panel=replace(state.panel, scroll=0))

    if normalized == "end":
        return replace(state, panel=state.panel.scrolled(10_000))

    if normalized == "space":
        return replace(state, paused=not state.paused)

    if len(normalized) == 1 and normalized.isdigit():
        index = int(normalized) - 1
        if 0 <= index < len(agent_ids):
            return replace(state, selected_agent_id=agent_ids[index])
        return state

    if normalized == "tab":
        return _cycle_agent(state, agent_ids)

    if normalized in {"+", "="}:
        return replace(state, speed=_next_speed(state.speed, 1))

    if normalized == "-":
        return replace(state, speed=_next_speed(state.speed, -1))

    if normalized == "f1":
        return replace(state, help_open=True)

    if normalized == "a":
        return replace(state, ascii_mode=not state.ascii_mode)

    if normalized == "v":
        return replace(state, focus_mode=not state.focus_mode)

    if normalized == "w":
        return replace(state, weather_overlay=not state.weather_overlay)

    if normalized == "q":
        return replace(state, pending_confirmation=UiCommand.QUIT)

    if normalized == "r":
        return replace(state, pending_confirmation=UiCommand.RESTART)

    return state


def _move_page(page: int, delta: int) -> int:
    return max(0, page + delta)


def _move_cursor(
    cursor: Position,
    dx: int,
    dy: int,
    world_size: tuple[int, int] | None,
) -> Position:
    width, height = world_size or (80, 40)
    return Position(
        min(max(cursor.x + dx, 0), max(0, width - 1)),
        min(max(cursor.y + dy, 0), max(0, height - 1)),
    )


def _normalize_key(key: str) -> str:
    normalized = key.strip().lower()
    if normalized in {"", "space", "spacebar"}:
        return "space"
    return normalized


def _cycle_agent(state: UiState, agent_ids: Sequence[AgentId]) -> UiState:
    if not agent_ids:
        return state
    if state.selected_agent_id not in agent_ids:
        return replace(state, selected_agent_id=agent_ids[0])
    index = agent_ids.index(state.selected_agent_id)
    return replace(state, selected_agent_id=agent_ids[(index + 1) % len(agent_ids)])


def _next_speed(speed: int, direction: int) -> int:
    if speed not in SPEEDS:
        speed = SPEEDS[0]
    index = SPEEDS.index(speed) + direction
    index = max(0, min(len(SPEEDS) - 1, index))
    return SPEEDS[index]
