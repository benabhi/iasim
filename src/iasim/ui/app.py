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
from iasim.ui.controls import UiState, handle_key
from iasim.ui.layout import BaseScreen, render_base_screen
from iasim.ui.tcod_console import key_from_event, screen_to_console

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

    def render(self) -> BaseScreen:
        """Render the full 160x45 operator view from live session state."""
        state = self.session.state
        names = self.session.names_snapshot()
        selected = self.ui.selected_agent_id
        if selected is None and state.agents:
            selected = state.agents[0].agent_id
        events = tuple(
            format_event(event, names) for event in self.session.recent_events(self.events_limit)
        )
        return render_base_screen(
            state,
            names,
            selected_agent_id=selected,
            events=events,
            paused=self.ui.paused,
            speed=self.ui.speed,
            capacity=self.capacity,
            ascii_mode=self.ui.ascii_mode,
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
        self.ui = handle_key(
            self.ui,
            key,
            agent_ids,
            world_size=(80, 40),
        )
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
