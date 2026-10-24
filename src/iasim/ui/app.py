"""Integrated operator application: shared state for the GUI and MCP server.

The application is presentation-only. It renders the full 160x45 operator view
from live session snapshots, routes keyboard input through the existing
controls, and never mutates simulation state directly.
"""

from __future__ import annotations

import contextlib
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from iasim.app.session import GameSession
from iasim.domain.identifiers import AgentId
from iasim.errors import PersistenceError
from iasim.ui.controls import UiState, UiView, handle_key
from iasim.ui.events import (
    CATEGORY_ACTIONS,
    CATEGORY_COMBAT,
    CATEGORY_MCP,
    CATEGORY_NEEDS,
    CATEGORY_SOCIAL,
    CATEGORY_WEATHER,
    EventRow,
)
from iasim.ui.layout import (
    BaseScreen,
    render_agent_screen,
    render_base_screen,
    render_events_screen,
    render_help_screen,
    render_map_screen,
    render_metrics_screen,
    render_replay_notice_screen,
    render_settings_screen,
    render_world_screen,
)
from iasim.ui.tcod_console import key_from_event, request_fullscreen, screen_to_console

_EVENT_LABELS: dict[str, str] = {
    "join": "SE UNIÓ",
    "disconnect": "DESCONECTADO",
    "death": "MURIÓ",
    "message": "MENSAJE",
    "waiting": "ESPERANDO",
    "running": "EN CURSO",
    "timeout": "TIEMPO AGOTADO",
    "absent": "AUSENTE",
    "session_end": "SESIÓN TERMINADA",
    "session_saved": "SESIÓN GUARDADA",
    "session_loaded": "SESIÓN CARGADA",
}
_EVENT_FIELDS = ("reason", "cause", "path", "name", "consecutive")
_COMBAT_KINDS = frozenset({"attack", "throw", "flee", "loot", "death"})
_NEEDS_KINDS = frozenset({"eat", "drink", "rest", "sleep", "fill", "use"})
_SOCIAL_KINDS = frozenset(
    {
        "say",
        "message",
        "offer_alliance",
        "accept_alliance",
        "break_alliance",
        "offer_trade",
        "accept_trade",
        "decline_trade",
    }
)
_MCP_KINDS = frozenset(
    {
        "join",
        "disconnect",
        "timeout",
        "absent",
        "waiting",
        "running",
        "session_end",
        "session_saved",
        "session_loaded",
    }
)
_WEATHER_KINDS = frozenset({"weather", "rain", "storm", "fog", "wind", "snow"})


def _event_category(kind: str) -> str:
    if kind in _COMBAT_KINDS:
        return CATEGORY_COMBAT
    if kind in _NEEDS_KINDS:
        return CATEGORY_NEEDS
    if kind in _SOCIAL_KINDS:
        return CATEGORY_SOCIAL
    if kind in _MCP_KINDS:
        return CATEGORY_MCP
    if kind in _WEATHER_KINDS:
        return CATEGORY_WEATHER
    return CATEGORY_ACTIONS


def format_event(
    event: Mapping[str, Any],
    names: Mapping[AgentId, str],
) -> str:
    """Format one recent session event for the operator ticker."""
    kind = str(event.get("kind", "evento"))
    label = _EVENT_LABELS.get(kind, kind.upper())
    agent_id = event.get("agent_id")
    who = ""
    if isinstance(agent_id, str):
        who = names.get(AgentId(agent_id), agent_id)
    tick = event.get("tick", 0)
    details = ", ".join(
        f"{field_name}={event[field_name]}"
        for field_name in _EVENT_FIELDS
        if field_name in event and event[field_name] is not None
    )
    text = f"[{tick}] {label}"
    if who:
        text += f" · {who}"
    if details:
        text += f" · {details}"
    return text


@dataclass(slots=True)
class OperatorApp:
    """Presentation state and rendering for the integrated command."""

    session: GameSession
    capacity: int = 8
    events_limit: int = 50
    ui: UiState = field(default_factory=UiState)

    def _names(self) -> Mapping[AgentId, str]:
        return self.session.names_snapshot()

    def _selected_agent_id(self) -> AgentId | None:
        state = self.session.state
        selected = self.ui.selected_agent_id
        if selected is None and state.agents:
            selected = state.agents[0].agent_id
        return selected

    def _event_rows(self, names: Mapping[AgentId, str]) -> tuple[EventRow, ...]:
        rows: list[EventRow] = []
        for event in self.session.recent_events(self.events_limit):
            kind = str(event.get("kind", "event"))
            tick = event.get("tick", 0)
            if not isinstance(tick, int):
                tick = 0
            agent_id = event.get("agent_id")
            agents = ""
            if isinstance(agent_id, str):
                agents = names.get(AgentId(agent_id), agent_id)
            label = _EVENT_LABELS.get(kind, kind.upper())
            details = ", ".join(
                f"{field_name}={event[field_name]}"
                for field_name in _EVENT_FIELDS
                if field_name in event and event[field_name] is not None
            )
            message = label + (f" · {details}" if details else "")
            result = str(event.get("outcome") or event.get("status") or event.get("error") or "")
            rows.append(
                EventRow(
                    tick=max(0, tick),
                    category=_event_category(kind),
                    agents=agents,
                    message=message,
                    result=result,
                )
            )
        return tuple(rows)

    def render(self) -> BaseScreen:
        """Render the active 160x45 operator view from live session state."""
        state = self.session.state
        names = self._names()
        selected = self._selected_agent_id()
        events = tuple(
            format_event(event, names) for event in self.session.recent_events(self.events_limit)
        )
        ascii_mode = self.ui.ascii_mode

        if self.ui.help_open:
            return render_help_screen(ascii_mode=ascii_mode)
        if self.ui.view is UiView.AGENT_SHEET:
            return render_agent_screen(
                state,
                names,
                selected_agent_id=selected,
                usage=self.session.usage_snapshot(),
                mind_reports=self.session.mind_reports_snapshot(),
                ascii_mode=ascii_mode,
            )
        if self.ui.view is UiView.WORLD_SUMMARY:
            return render_world_screen(
                state,
                names,
                selected_agent_id=selected,
                events=events,
                paused=self.ui.paused,
                capacity=self.capacity,
                mind_reports=self.session.mind_reports_snapshot(),
                ascii_mode=ascii_mode,
            )
        if self.ui.view is UiView.EVENT_LOG:
            rows = self._event_rows(names)
            agent_id = str(selected) if self.ui.event_agent_only and selected is not None else None
            return render_events_screen(
                rows,
                query=self.ui.event_query,
                category=self.ui.event_category,
                agent_id=agent_id,
                page=self.ui.event_page,
                tick_minutes=state.tick_minutes,
                ascii_mode=ascii_mode,
            )
        if self.ui.view is UiView.REPLAY:
            return render_replay_notice_screen(state.tick, ascii_mode=ascii_mode)
        if self.ui.view is UiView.MAP_VIEW:
            return render_map_screen(
                state,
                names,
                selected_agent_id=selected,
                focus_mode=self.ui.focus_mode,
                weather_overlay=self.ui.weather_overlay,
                ascii_mode=ascii_mode,
                cursor=self.ui.cursor,
                inspection_pinned=self.ui.inspection_pinned,
            )
        if self.ui.view is UiView.METRICS:
            return render_metrics_screen(
                self.session.metrics_snapshot(),
                final=self.session.is_finished,
                ascii_mode=ascii_mode,
            )
        if self.ui.view is UiView.SETTINGS:
            return render_settings_screen(self.ui.display, ascii_mode=ascii_mode)

        return render_base_screen(
            state,
            names,
            selected_agent_id=selected,
            events=events,
            paused=self.ui.paused,
            speed=self.ui.speed,
            capacity=self.capacity,
            ascii_mode=ascii_mode,
            focus_mode=self.ui.focus_mode,
            usage=self.session.usage_snapshot(),
            mind_reports=self.session.mind_reports_snapshot(),
            panel=self.ui.panel,
            weather_overlay=self.ui.weather_overlay,
            display=self.ui.display,
        )

    def press(self, key: str) -> str | None:
        """Route one keyboard event through the presentation controls."""
        if key == "f9":
            with contextlib.suppress(PersistenceError):
                self.session.save()
            return None
        state = self.session.state
        agent_ids = tuple(agent.agent_id for agent in state.agents)
        before_fullscreen = self.ui.display.fullscreen
        self.ui = handle_key(
            self.ui,
            key,
            agent_ids,
            world_size=(80, 40),
        )
        if self.ui.display.fullscreen != before_fullscreen:
            request_fullscreen(self.ui.display.fullscreen)
        if self.ui.quit_requested:
            return "quit"
        if self.ui.restart_requested:
            return "restart"
        return None


def run_gui(
    session: GameSession,
    *,
    capacity: int = 8,
    stop_event: threading.Event | None = None,
) -> None:
    """Open the full 160x45 operator GUI until the operator quits."""
    import tcod

    app = OperatorApp(session, capacity=capacity)
    with tcod.context.new(columns=160, rows=45, title="IASim") as context:
        console = screen_to_console(app.render())
        while not (stop_event is not None and stop_event.is_set()):
            context.present(console)
            for event in tcod.event.get():
                if isinstance(event, tcod.event.Quit):
                    return
                if isinstance(event, tcod.event.KeyDown):
                    key = key_from_event(event)
                    if key is None:
                        continue
                    action = app.press(key)
                    if action in {"quit", "restart"}:
                        return
            console = screen_to_console(app.render())
            time.sleep(0.02)


def wait_for_shutdown() -> None:
    """Block the headless process until Ctrl+C, then return cleanly."""
    try:
        while True:
            time.sleep(0.2)
    except KeyboardInterrupt:
        return
