"""Deterministic 160x45 base layout for the operator UI."""

from __future__ import annotations

import html
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from iasim.domain.agents import Agent, AgentStatus
from iasim.domain.alliances import Alliance, AllianceStatus
from iasim.domain.climate import effective_vision
from iasim.domain.clock import DayPhase, SimulationClock
from iasim.domain.geometry import Position
from iasim.domain.identifiers import AgentId
from iasim.domain.memory import AgentMemory, MemoryEntry
from iasim.domain.mind import MindReport
from iasim.domain.session import SessionState
from iasim.domain.status import Condition, status_tags
from iasim.domain.tiles import TileType
from iasim.domain.trades import TradeStatus
from iasim.domain.usage import AgentUsage, CostSource
from iasim.domain.weather import WeatherKind, WeatherState
from iasim.domain.world import StructureKind
from iasim.ui import theme
from iasim.ui.controls import KEY_GUIDE, STATUS_GUIDE
from iasim.ui.panel import PANEL_TABS, TAB_LABELS, PanelState, RightPanelTab
from iasim.world.tcod_fov import compute_fov

SCREEN_WIDTH = 160
SCREEN_HEIGHT = 45
MAP_WIDTH = 80
MAP_HEIGHT = 40
TICKER_Y = 40
PANEL_X = 80
PANEL_WIDTH = 80
PANEL_CONTENT_X = PANEL_X + 2
PANEL_CONTENT_WIDTH = SCREEN_WIDTH - PANEL_CONTENT_X
BOTTOM_BAR_Y = 44

BOTTOM_BAR = (
    "[ESPACIO] Pausa│[1-8/TAB] Agente│[+/-] Vel│[ / ] Pestaña│[F1] Ayuda│"
    "[F2] Agente│[F3] Mundo│[F4] Log│[F5] Replay│[F6] Mapa│[F9] Guardar│[Q] Salir"
)

HELP_FOOTER = "ESC volver │ F1 cerrar ayuda │ A ASCII │ Q/R requieren confirmación"

_SHEET_COLUMN_WIDTH = 50
_SHEET_HEIGHT = 40
_SHEET_CENTER_X = 53
_SHEET_RIGHT_X = 106
_SHEET_TIMELINE_LIMIT = 20

_PHASE_LABELS: dict[DayPhase, str] = {
    DayPhase.DAWN: "AMANECER",
    DayPhase.DAY: "DÍA",
    DayPhase.DUSK: "ATARDECER",
    DayPhase.NIGHT: "NOCHE",
}

_STATUS_LABELS: dict[Condition, str] = {
    Condition.HUNGRY: "HAMBRE",
    Condition.STARVING: "INANICIÓN",
    Condition.THIRSTY: "SED",
    Condition.DEHYDRATED: "DESHIDRATADO",
    Condition.EXHAUSTED: "AGOTADO",
    Condition.HYPOTHERMIA: "HIPOTERMIA",
    Condition.HEAT_STROKE: "GOLPE DE CALOR",
    Condition.WET: "MOJADO",
    Condition.BLEEDING: "SANGRANDO",
    Condition.DEAD: "MUERTO",
}

_COST_SOURCE_LABELS: dict[CostSource, str] = {
    CostSource.REPORTED: "reportado",
    CostSource.ESTIMATED: "estimado",
    CostSource.MIXED: "mixto",
    CostSource.UNKNOWN: "desconocido",
}

_WEATHER_LABELS: dict[WeatherKind, str] = {
    WeatherKind.CLEAR: "DESPEJADO",
    WeatherKind.CLOUDY: "NUBLADO",
    WeatherKind.RAIN: "LLUVIA",
    WeatherKind.STORM: "TORMENTA",
    WeatherKind.FOG: "NIEBLA",
}


@dataclass(frozen=True, slots=True)
class Cell:
    """One terminal cell with foreground, background, and emphasis."""

    char: str = " "
    fg: theme.RGB = theme.WHITE
    bg: theme.RGB = theme.BLACK
    bold: bool = False


@dataclass(frozen=True, slots=True)
class BaseScreen:
    """A frozen terminal screen ready for text, HTML, or libtcod rendering."""

    width: int
    height: int
    cells: tuple[Cell, ...]

    def cell_at(self, x: int, y: int) -> Cell:
        """Return the cell at screen coordinates."""
        if not (0 <= x < self.width and 0 <= y < self.height):
            raise IndexError(f"cell ({x}, {y}) is outside the screen")
        return self.cells[y * self.width + x]

    def row_text(self, y: int) -> str:
        """Return one row as plain text."""
        if not 0 <= y < self.height:
            raise IndexError(f"row {y} is outside the screen")
        start = y * self.width
        return "".join(cell.char for cell in self.cells[start : start + self.width])

    def to_text(self) -> str:
        """Return the whole screen as plain text."""
        return "\n".join(self.row_text(y) for y in range(self.height))

    def to_html(self, title: str = "IASim", *, font_size: int = 12) -> str:
        """Return a self-contained HTML preview with colors and a legend."""
        parts = [
            "<!doctype html><html lang='es'><head><meta charset='utf-8'>",
            f"<title>{html.escape(title)}</title>",
            "<style>",
            "body{margin:0;padding:24px;background:#08090c;color:#e4e7ec;",
            "font-family:ui-monospace,Consolas,'DejaVu Sans Mono',monospace;}",
            "h1{font-size:18px;margin:0 0 16px 0;font-weight:600;}",
            f".screen{{white-space:pre;font-size:{font_size}px;line-height:1.0;",
            "letter-spacing:0;display:inline-block;border:1px solid #2a303a;}",
            ".legend{margin-top:16px;color:#aab2bf;font-size:13px;line-height:1.8;}",
            "</style></head><body>",
            f"<h1>{html.escape(title)}</h1>",
            "<div class='screen'>",
        ]
        for index, cell in enumerate(self.cells):
            char = "&nbsp;" if cell.char == " " else html.escape(cell.char)
            weight = 600 if cell.bold else 400
            parts.append(
                f"<span style='color:{_hex(cell.fg)};background:{_hex(cell.bg)};"
                f"font-weight:{weight}'>{char}</span>"
            )
            if (index + 1) % self.width == 0:
                parts.append("\n")
        parts.append("</div><div class='legend'>")
        parts.append(
            " · ".join(
                f"<span style='color:{_hex(theme.TILE_COLORS[tile])}'>"
                f"{theme.TILE_GLYPHS[tile]}</span> {theme.TILE_LABELS[tile]}"
                for tile in theme.TILE_LABELS
            )
        )
        parts.append(f" · <span style='color:{_hex(theme.AGENT_COLOR)}'>@</span> agente")
        parts.append("</div></body></html>")
        return "".join(parts)


class _Canvas:
    def __init__(self) -> None:
        self._cells = [[Cell() for _ in range(SCREEN_WIDTH)] for _ in range(SCREEN_HEIGHT)]

    def put(
        self,
        x: int,
        y: int,
        text: str,
        *,
        fg: theme.RGB = theme.WHITE,
        bg: theme.RGB = theme.BLACK,
        bold: bool = False,
    ) -> None:
        if not 0 <= y < SCREEN_HEIGHT:
            return
        for offset, char in enumerate(text):
            px = x + offset
            if 0 <= px < SCREEN_WIDTH:
                self._cells[y][px] = Cell(char, fg, bg, bold)

    def fill(
        self,
        x: int,
        y: int,
        width: int,
        height: int,
        *,
        fg: theme.RGB = theme.WHITE,
        bg: theme.RGB = theme.BLACK,
    ) -> None:
        for py in range(max(0, y), min(SCREEN_HEIGHT, y + height)):
            for px in range(max(0, x), min(SCREEN_WIDTH, x + width)):
                self._cells[py][px] = Cell(" ", fg, bg)

    def hline(self, x: int, y: int, width: int, char: str = "─") -> None:
        self.put(x, y, char * width, fg=theme.DIM)

    def to_screen(self) -> BaseScreen:
        return BaseScreen(
            width=SCREEN_WIDTH,
            height=SCREEN_HEIGHT,
            cells=tuple(cell for row in self._cells for cell in row),
        )


def render_base_screen(
    state: SessionState,
    names: Mapping[AgentId, str],
    *,
    selected_agent_id: AgentId | None = None,
    events: Sequence[str] = (),
    paused: bool = False,
    speed: int = 1,
    capacity: int = 8,
    ascii_mode: bool = False,
    focus_mode: bool = False,
    usage: Mapping[AgentId, AgentUsage] | None = None,
    mind_reports: Mapping[AgentId, MindReport] | None = None,
    waiting_reason: str | None = None,
    panel: PanelState | None = None,
    messages: Sequence[str] = (),
    betrayals: Sequence[str] = (),
    weather_overlay: bool = True,
) -> BaseScreen:
    """Render the deterministic base screen without mutating the session."""
    canvas = _Canvas()
    canvas.fill(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT, fg=theme.WHITE, bg=theme.BLACK)
    _render_map(
        canvas,
        state,
        selected_agent_id,
        ascii_mode,
        focus_mode=focus_mode,
        weather_overlay=weather_overlay,
    )
    _render_ticker(canvas, events, ascii_mode)
    _render_panel(
        canvas,
        state,
        names,
        selected_agent_id=selected_agent_id,
        events=events,
        paused=paused,
        speed=speed,
        capacity=capacity,
        ascii_mode=ascii_mode,
        usage=usage,
        mind_reports=mind_reports,
        waiting_reason=waiting_reason,
        panel=panel,
        messages=messages,
        betrayals=betrayals,
    )
    _render_bottom_bar(canvas, ascii_mode)
    return canvas.to_screen()


def render_agent_screen(
    state: SessionState,
    names: Mapping[AgentId, str],
    *,
    selected_agent_id: AgentId | None = None,
    usage: Mapping[AgentId, AgentUsage] | None = None,
    mind_reports: Mapping[AgentId, MindReport] | None = None,
    timeline: Sequence[str] = (),
    messages: Sequence[str] = (),
    betrayals: Sequence[str] = (),
    ascii_mode: bool = False,
) -> BaseScreen:
    """Render the full-screen F2 agent sheet in three columns."""
    canvas = _Canvas()
    canvas.fill(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT, fg=theme.WHITE, bg=theme.BLACK)
    selected = _resolve_selected(state, selected_agent_id)
    divider = theme.ASCII_VERTICAL if ascii_mode else "│"
    for column_x in (_SHEET_CENTER_X - 2, _SHEET_RIGHT_X - 2):
        for row in range(2, BOTTOM_BAR_Y):
            canvas.put(column_x, row, divider, fg=theme.DIM, bg=theme.BLACK)

    if selected is None:
        canvas.put(2, 0, "F2 · FICHA DEL AGENTE", fg=theme.CYAN, bold=True)
        canvas.put(2, 2, "— sin agente seleccionado —", fg=theme.DIM)
        _render_sheet_footer(canvas, ascii_mode)
        return canvas.to_screen()

    name = names.get(selected.agent_id, str(selected.agent_id))
    clock = SimulationClock(state.tick_minutes)
    clock.advance(state.tick)
    canvas.put(
        2,
        0,
        f"F2 · FICHA DEL AGENTE · {name} · {_agent_glyph(selected, ascii_mode)} · "
        f"({selected.position.x}, {selected.position.y}) · "
        f"DÍA {clock.day} · {clock.hour:02d}:{clock.minute:02d}",
        fg=theme.CYAN,
        bold=True,
    )
    canvas.put(
        2,
        1,
        "TAB cicla agentes · 1-8 selecciona · ESC vuelve al panel · F2 abre esta vista",
        fg=theme.DIM,
    )
    left, center, right = _agent_sheet_columns(
        state,
        names,
        selected,
        usage=usage,
        mind_reports=mind_reports,
        timeline=timeline,
        messages=messages,
        betrayals=betrayals,
        ascii_mode=ascii_mode,
    )
    _draw_sheet_column(canvas, 1, 3, _SHEET_COLUMN_WIDTH, left)
    _draw_sheet_column(canvas, _SHEET_CENTER_X, 3, _SHEET_COLUMN_WIDTH, center)
    _draw_sheet_column(canvas, _SHEET_RIGHT_X, 3, _SHEET_COLUMN_WIDTH, right)
    _render_sheet_footer(canvas, ascii_mode)
    return canvas.to_screen()


def _agent_sheet_columns(
    state: SessionState,
    names: Mapping[AgentId, str],
    agent: Agent,
    *,
    usage: Mapping[AgentId, AgentUsage] | None,
    mind_reports: Mapping[AgentId, MindReport] | None,
    timeline: Sequence[str],
    messages: Sequence[str],
    betrayals: Sequence[str],
    ascii_mode: bool,
) -> tuple[list[str], list[str], list[str]]:
    name = names.get(agent.agent_id, str(agent.agent_id))
    attributes = agent.attributes
    inventory = agent.inventory
    left = [
        "IDENTIDAD",
        f"  Nombre: {name}",
        f"  Posición: ({agent.position.x}, {agent.position.y})",
        f"  Estado: {_agent_state_label(agent)}",
    ]
    death = _death_detail(state, agent)
    if death is not None:
        left.append(f"  {death}")
    if agent.is_alive:
        temperature_ratio = (attributes.body_temperature_c - 34.0) / 8.0 * 100
        left.extend(
            [
                "",
                "SALUD Y NECESIDADES",
                f"  Salud   {_bar(attributes.health, 100, ascii_mode)} {attributes.health:>3.0f}",
                f"  Hambre  {_bar(attributes.hunger, 100, ascii_mode)} {attributes.hunger:>3.0f}",
                f"  Sed     {_bar(attributes.thirst, 100, ascii_mode)} {attributes.thirst:>3.0f}",
                f"  Energía {_bar(attributes.energy, 100, ascii_mode)} {attributes.energy:>3.0f}",
                f"  Temp    {_bar(temperature_ratio, 100, ascii_mode)} "
                f"{attributes.body_temperature_c:>4.1f} °C",
                f"  Mojado  {_bar(attributes.wetness, 100, ascii_mode)} {attributes.wetness:>3.0f}",
                "",
                "ESTADOS",
                f"  {' · '.join(_status_tags(agent)) or '—'}",
                "",
                "HABILIDADES",
                f"  FUE {attributes.strength} · DES {attributes.dexterity} · "
                f"RES {attributes.endurance} · VIS {attributes.vision}",
            ]
        )
    equipment = " · ".join(f"{slot.value}:{spec.name}" for slot, spec in agent.equipment.items)
    left.extend(
        [
            "",
            "EQUIPO",
            f"  {equipment or '— sin equipo —'}",
            "CARGA",
            f"  {inventory.total_weight_grams / 1000.0:.1f}/"
            f"{inventory.max_weight_grams / 1000.0:.1f} kg",
        ]
    )
    selected_usage = usage.get(agent.agent_id) if usage is not None else None
    if selected_usage is not None and selected_usage.entries:
        entry = selected_usage.entries[-1]
        left.extend(
            [
                "",
                "USO IA (REPORTADO)",
                f"  {entry.model} / {entry.reasoning_effort or '-'}: "
                f"{entry.input_tokens} in / {entry.output_tokens} out",
                f"  TOTAL {selected_usage.total_tokens} tokens - "
                f"{_usage_cost_text(selected_usage)}",
            ]
        )

    report = None if mind_reports is None else mind_reports.get(agent.agent_id)
    center = ["MENTE (REPORTADO POR EL AGENTE)"]
    if report is None:
        center.append("  — sin reporte —")
    else:
        center.append(f"  Intención: {report.intent}")
        center.extend(f"  {line}" for line in _wrap(report.thought, _SHEET_COLUMN_WIDTH - 2))
        if report.plan is not None:
            center.append(f"  Plan: {report.plan}")
            center.append(f"  Próximo paso reportado: {report.plan}")
        if report.confidence is not None:
            center.append(f"  Confianza: {report.confidence}")
    center.extend(("", "TIMELINE (últimos 20)"))
    history = list(timeline)
    if len(history) > _SHEET_TIMELINE_LIMIT:
        center.append(f"  +{len(history) - _SHEET_TIMELINE_LIMIT} anteriores")
        history = history[-_SHEET_TIMELINE_LIMIT:]
    if history:
        center.extend(f"  {line}" for line in history)
    else:
        center.append("  — sin actividad —")

    right = ["INVENTARIO"]
    if inventory.stacks:
        right.extend(
            f"  {stack.definition.item_id} x{stack.quantity}" for stack in inventory.stacks
        )
    else:
        right.append("  — vacío —")
    right.extend(("", "EQUIPO"))
    if agent.equipment.items:
        right.extend(f"  {slot.value}: {spec.name}" for slot, spec in agent.equipment.items)
    else:
        right.append("  — sin equipo —")
    right.extend(("", "RELACIONES"))
    right.append(f"  Alianzas: {_alliances_line(state, names)}")
    right.append(f"  Trueques: {_trades_line(state, names)}")
    right.append(f"  Traiciones: {_last_betrayal(betrayals)}")
    right.extend(("", "MENSAJES"))
    if messages:
        right.extend(f"  {message}" for message in list(messages)[-8:])
    else:
        right.append("  — sin mensajes —")
    if death is not None:
        corpse = next(
            (candidate for candidate in state.corpses if candidate.agent_id == agent.agent_id),
            None,
        )
        right.extend(("", "CADÁVER"))
        right.append(f"  {death}")
        if corpse is not None:
            loot = [
                f"{stack.definition.item_id} x{stack.quantity}" for stack in corpse.inventory.stacks
            ]
            right.append(f"  Botín: {', '.join(loot) or '— vacío —'}")
    return left, center, right


def _agent_state_label(agent: Agent) -> str:
    if agent.status is AgentStatus.DEAD:
        return "MUERTO"
    if agent.status is AgentStatus.ABSENT:
        return "AUSENTE (timeout)"
    if agent.status is AgentStatus.SLEEPING:
        return "DURMIENDO"
    return "ACTIVO"


def _draw_sheet_column(
    canvas: _Canvas,
    x: int,
    y: int,
    width: int,
    lines: Sequence[str],
) -> None:
    for offset, line in enumerate(lines[:_SHEET_HEIGHT]):
        canvas.put(x, y + offset, _clip(line, width))


def _render_sheet_footer(canvas: _Canvas, ascii_mode: bool) -> None:
    separator = theme.ASCII_VERTICAL if ascii_mode else "│"
    footer = (
        f"[TAB] Siguiente agente {separator} [1-8] Seleccionar {separator} "
        f"[ESC] Volver al panel {separator} [F2] Cerrar ficha"
    )
    text = (footer + " " * SCREEN_WIDTH)[:SCREEN_WIDTH]
    canvas.fill(0, BOTTOM_BAR_Y, SCREEN_WIDTH, 1, fg=theme.BAR_FG, bg=theme.BAR_BG)
    canvas.put(0, BOTTOM_BAR_Y, text, fg=theme.BAR_FG, bg=theme.BAR_BG, bold=True)


def render_world_screen(
    state: SessionState,
    names: Mapping[AgentId, str],
    *,
    selected_agent_id: AgentId | None = None,
    events: Sequence[str] = (),
    paused: bool = False,
    capacity: int = 8,
    mind_reports: Mapping[AgentId, MindReport] | None = None,
    last_results: Mapping[AgentId, Mapping[str, Any]] | None = None,
    ascii_mode: bool = False,
) -> BaseScreen:
    """Render the full-screen F3 world summary with the all-agent table."""
    canvas = _Canvas()
    canvas.fill(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT, fg=theme.WHITE, bg=theme.BLACK)
    clock = SimulationClock(state.tick_minutes)
    clock.advance(state.tick)
    weather = state.weather
    status = "PAUSA" if paused else "EN CURSO"
    canvas.put(
        2,
        0,
        f"F3 · MUNDO · DÍA {clock.day} · {clock.hour:02d}:{clock.minute:02d} · "
        f"{_PHASE_LABELS[clock.phase]} · {_WEATHER_LABELS[weather.kind]} · "
        f"{weather.temperature_c:.0f} °C · VIENTO {weather.wind} · "
        f"VIS {weather.visibility_factor:.2f} · {status}",
        fg=theme.CYAN,
        bold=True,
    )
    alive = sum(1 for agent in state.agents if agent.is_alive)
    free = max(0, capacity - len(state.agents))
    canvas.put(
        2,
        1,
        f"AGENTES {len(state.agents)}/{capacity} · {alive} vivos · {free} libres · "
        "Enter abre F2 · TAB cicla · ESC vuelve al panel",
        fg=theme.DIM,
    )

    selected = _resolve_selected(state, selected_agent_id)
    _draw_world_table(
        canvas,
        state,
        names,
        selected=selected,
        mind_reports=mind_reports,
        last_results=last_results,
        ascii_mode=ascii_mode,
    )
    _draw_world_summary(canvas, state)
    _draw_world_events(canvas, events, ascii_mode)
    _render_world_footer(canvas, ascii_mode)
    return canvas.to_screen()


def _draw_world_table(
    canvas: _Canvas,
    state: SessionState,
    names: Mapping[AgentId, str],
    *,
    selected: Agent | None,
    mind_reports: Mapping[AgentId, MindReport] | None,
    last_results: Mapping[AgentId, Mapping[str, Any]] | None,
    ascii_mode: bool,
) -> None:
    y = 3
    canvas.put(2, y, "AGENTES", fg=theme.CYAN, bold=True)
    y += 1
    canvas.put(2, y, _world_header_row(), fg=theme.DIM, bold=True)
    y += 1
    agents = list(state.agents)[:8]
    if not agents:
        canvas.put(2, y, "— sin agentes —", fg=theme.DIM)
        return
    for index, agent in enumerate(agents, start=1):
        name = names.get(agent.agent_id, str(agent.agent_id))
        report = None if mind_reports is None else mind_reports.get(agent.agent_id)
        intent = "—" if report is None else report.intent
        result = None if last_results is None else last_results.get(agent.agent_id)
        last_action = "—"
        if result is not None:
            action = result.get("action")
            outcome = result.get("outcome")
            last_action = f"{action}/{outcome}" if outcome else str(action)
        is_selected = selected is not None and agent.agent_id == selected.agent_id
        canvas.put(
            2,
            y,
            _world_table_row(
                index,
                agent,
                name,
                intent=intent,
                last_action=last_action,
                selected=is_selected,
                ascii_mode=ascii_mode,
            ),
            fg=theme.WHITE,
            bg=theme.SELECTED_BG if is_selected else theme.BLACK,
            bold=is_selected,
        )
        y += 1


def _world_header_row() -> str:
    return (
        f"{'#':>3} {'AGENTE':<16} {'POS':<9} {'SAL':>6} {'HAM':>7} "
        f"{'SED':>7} {'ENE':>8} {'TEMP':>8} {'ESTADO':<12} "
        f"{'INTENCIÓN':<28} ÚLTIMA ACCIÓN"
    )


def _world_table_row(
    index: int,
    agent: Agent,
    name: str,
    *,
    intent: str,
    last_action: str,
    selected: bool,
    ascii_mode: bool,
) -> str:
    marker = ">" if ascii_mode else "▶"
    prefix = marker if selected else " "
    position = f"({agent.position.x},{agent.position.y})"
    if agent.status is AgentStatus.DEAD:
        state_label = "MUERTO"
        health = hunger = thirst = energy = temperature = "—"
    else:
        attributes = agent.attributes
        state_label = _agent_state_label(agent)
        health = f"{attributes.health:.0f}"
        hunger = f"{attributes.hunger:.0f}"
        thirst = f"{attributes.thirst:.0f}"
        energy = f"{attributes.energy:.0f}"
        temperature = f"{attributes.body_temperature_c:.1f}"
    return (
        f"{prefix}{index:>2} {name:<16.16} {position:<9} "
        f"{health:>6} {hunger:>7} {thirst:>7} {energy:>8} {temperature:>8} "
        f"{state_label:<12} {_clip(intent, 28):<28} {_clip(last_action, 22)}"
    )


def _draw_world_summary(canvas: _Canvas, state: SessionState) -> None:
    y = 5 + len(state.agents[:8])
    fires = sum(1 for structure in state.structures if structure.kind is StructureKind.FIRE)
    shelters = sum(1 for structure in state.structures if structure.kind is StructureKind.SHELTER)
    corpses = sum(1 for agent in state.agents if not agent.is_alive)
    trees = sum(1 for tile in state.world.tiles if tile is TileType.TREE)
    bushes = sum(1 for tile in state.world.tiles if tile is TileType.BUSH)
    offers = sum(1 for trade in state.trades if trade.status is TradeStatus.OPEN)
    canvas.put(2, y + 1, "MUNDO", fg=theme.CYAN, bold=True)
    canvas.put(
        2,
        y + 2,
        f"Fuegos: {fires} · Refugios: {shelters} · Cadáveres: {corpses} · "
        f"Árboles: {trees} · Arbustos: {bushes} · Ofertas activas: {offers}",
        fg=theme.WHITE,
    )


def _draw_world_events(
    canvas: _Canvas,
    events: Sequence[str],
    ascii_mode: bool,
) -> None:
    y = BOTTOM_BAR_Y - 7
    separator = (theme.ASCII_HORIZONTAL if ascii_mode else "─") * (SCREEN_WIDTH - 4)
    canvas.put(2, y, separator, fg=theme.DIM)
    canvas.put(2, y + 1, "EVENTOS RECIENTES", fg=theme.CYAN, bold=True)
    lines = list(events)[-4:] if events else ["— sin eventos —"]
    for offset, line in enumerate(lines, start=2):
        canvas.put(2, y + offset, _clip(line, SCREEN_WIDTH - 6), fg=theme.WHITE)


def _render_world_footer(canvas: _Canvas, ascii_mode: bool) -> None:
    separator = theme.ASCII_VERTICAL if ascii_mode else "│"
    footer = (
        f"[Enter] Ver ficha F2 {separator} [TAB] Siguiente agente {separator} "
        f"[1-8] Seleccionar {separator} [ESC] Volver {separator} [F3] Cerrar mundo"
    )
    text = (footer + " " * SCREEN_WIDTH)[:SCREEN_WIDTH]
    canvas.fill(0, BOTTOM_BAR_Y, SCREEN_WIDTH, 1, fg=theme.BAR_FG, bg=theme.BAR_BG)
    canvas.put(0, BOTTOM_BAR_Y, text, fg=theme.BAR_FG, bg=theme.BAR_BG, bold=True)


def render_help_screen(*, ascii_mode: bool = False) -> BaseScreen:
    """Render the keyboard and glyph/status legend help view."""
    canvas = _Canvas()
    canvas.fill(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT, fg=theme.WHITE, bg=theme.BLACK)
    canvas.put(2, 0, "AYUDA Y LEYENDA", fg=theme.CYAN, bold=True)
    canvas.put(
        2,
        1,
        "IASim · controles del operador · los pensamientos son reportados, no verificados",
        fg=theme.DIM,
    )

    left_x = 2
    right_x = 82
    left_y = 3
    canvas.put(left_x, left_y, "CONTROLES", fg=theme.CYAN, bold=True)
    for offset, (key, description) in enumerate(KEY_GUIDE, start=1):
        canvas.put(
            left_x,
            left_y + offset,
            f"{key:<10} {description}",
            fg=theme.WHITE,
        )
    left_y += len(KEY_GUIDE) + 2

    canvas.put(left_x, left_y, "BARRAS", fg=theme.CYAN, bold=True)
    left_y += 1
    bar_symbols = "█" if not ascii_mode else theme.ASCII_BAR_FILLED
    empty_symbol = "░" if not ascii_mode else theme.ASCII_BAR_EMPTY
    canvas.put(left_x, left_y, f"{bar_symbols} lleno · {empty_symbol} vacío", fg=theme.WHITE)
    left_y += 2

    canvas.put(left_x, left_y, "MENTE", fg=theme.CYAN, bold=True)
    left_y += 1
    canvas.put(
        left_x,
        left_y,
        "El pensamiento y el plan son datos del agente; si no reporta, se muestra sin reporte.",
        fg=theme.WHITE,
    )
    left_y += 2

    canvas.put(left_x, left_y, "CONFIRMACIÓN", fg=theme.CYAN, bold=True)
    left_y += 1
    canvas.put(left_x, left_y, "Q y R piden una segunda pulsación; ESC cancela.", fg=theme.WHITE)
    left_y += 2

    canvas.put(left_x, left_y, "MODO ASCII", fg=theme.CYAN, bold=True)
    left_y += 1
    canvas.put(left_x, left_y, "A alterna glifos y barras ASCII.", fg=theme.WHITE)

    canvas.put(right_x, 3, "GLIFOS", fg=theme.CYAN, bold=True)
    glyph_y = 4
    for tile in TileType:
        glyph = theme.tile_glyph(tile, ascii_mode=ascii_mode)
        label = theme.TILE_LABELS[tile]
        canvas.put(right_x, glyph_y, f"{glyph} {label}", fg=theme.WHITE)
        glyph_y += 1

    glyph_y += 1
    canvas.put(right_x, glyph_y, "ESTADOS", fg=theme.CYAN, bold=True)
    glyph_y += 1
    for tag, description in STATUS_GUIDE:
        canvas.put(right_x, glyph_y, f"{tag:<8} {description}", fg=theme.WHITE)
        glyph_y += 1

    footer = HELP_FOOTER.replace("│", theme.ASCII_VERTICAL if ascii_mode else "│")
    canvas.fill(0, BOTTOM_BAR_Y, SCREEN_WIDTH, 1, fg=theme.BAR_FG, bg=theme.BAR_BG)
    canvas.put(0, BOTTOM_BAR_Y, footer, fg=theme.BAR_FG, bg=theme.BAR_BG, bold=True)
    return canvas.to_screen()


def _render_map(
    canvas: _Canvas,
    state: SessionState,
    selected_agent_id: AgentId | None,
    ascii_mode: bool,
    *,
    focus_mode: bool = False,
    weather_overlay: bool = True,
) -> None:
    selected = _resolve_selected(state, selected_agent_id)
    visible_positions: frozenset[Position] | None = None
    if focus_mode and selected is not None:
        clock = SimulationClock(state.tick_minutes)
        clock.advance(state.tick)
        radius = effective_vision(
            selected,
            clock,
            state.weather,
            state.structures,
        )
        visible_positions = compute_fov(state.world, selected.position, radius)

    structures = {structure.position: structure for structure in state.structures}
    corpses = {corpse.position: corpse for corpse in state.corpses}
    ground_items = {item.position: item for item in state.ground_items}
    depleted = {node.position for node in state.resource_nodes if node.depleted}
    agents_at = {agent.position: agent for agent in state.agents}
    memory_tiles: dict[Position, MemoryEntry] = {}
    memory_agents: tuple[AgentMemory, ...] = ()
    if visible_positions is not None and selected is not None:
        memory_tiles = {entry.position: entry for entry in selected.memory.tiles}
        memory_agents = selected.memory.agents

    for y in range(MAP_HEIGHT):
        for x in range(MAP_WIDTH):
            if x >= state.world.width or y >= state.world.height:
                continue
            position = Position(x, y)
            visible = visible_positions is None or position in visible_positions
            if not visible:
                _render_memory_cell(
                    canvas,
                    position,
                    memory_tiles.get(position),
                    ascii_mode,
                )
                continue
            tile = state.world.tile_at(position)
            background = theme.TILE_BACKGROUNDS[tile]
            color = theme.DIM if position in depleted else theme.TILE_COLORS[tile]
            canvas.put(
                x,
                y,
                theme.tile_glyph(tile, ascii_mode=ascii_mode),
                fg=color,
                bg=background,
            )
            if weather_overlay:
                overlay = _weather_overlay(
                    position,
                    state.weather,
                    state.tick,
                    ascii_mode,
                )
                if overlay is not None:
                    glyph, overlay_color = overlay
                    canvas.put(x, y, glyph, fg=overlay_color, bg=background)
            structure = structures.get(position)
            if structure is not None:
                canvas.put(
                    x,
                    y,
                    theme.structure_glyph(structure.kind, ascii_mode=ascii_mode),
                    fg=theme.STRUCTURE_COLORS[structure.kind],
                    bg=background,
                    bold=structure.lit,
                )
            corpse = corpses.get(position)
            if corpse is not None:
                glyph = theme.ASCII_CORPSE_GLYPH if ascii_mode else theme.CORPSE_GLYPH
                canvas.put(x, y, glyph, fg=theme.CORPSE_COLOR, bg=background)
            item = ground_items.get(position)
            if item is not None:
                glyph = theme.ASCII_GROUND_ITEM_GLYPH if ascii_mode else theme.GROUND_ITEM_GLYPH
                canvas.put(x, y, glyph, fg=theme.GROUND_ITEM_COLOR, bg=background)
            agent = agents_at.get(position)
            if agent is not None:
                is_selected = agent.agent_id == selected_agent_id
                canvas.put(
                    x,
                    y,
                    _agent_glyph(agent, ascii_mode),
                    fg=theme.AGENT_COLOR,
                    bg=theme.SELECTED_BG if is_selected else background,
                    bold=is_selected,
                )

    for remembered in memory_agents:
        position = remembered.position
        if not (0 <= position.x < MAP_WIDTH and 0 <= position.y < MAP_HEIGHT):
            continue
        if visible_positions is not None and position in visible_positions:
            continue
        if position in agents_at:
            continue
        canvas.put(
            position.x,
            position.y,
            "?" if ascii_mode else "…",
            fg=theme.MEMORY_COLOR,
            bg=theme.TILE_BACKGROUNDS[state.world.tile_at(position)],
        )


def _render_memory_cell(
    canvas: _Canvas,
    position: Position,
    entry: MemoryEntry | None,
    ascii_mode: bool,
) -> None:
    """Render one remembered cell outside the current field of view."""
    if entry is None:
        canvas.put(position.x, position.y, " ", fg=theme.BLACK, bg=theme.BLACK)
        return
    color = theme.STALE_MEMORY_COLOR if entry.stale else theme.MEMORY_COLOR
    background = theme.TILE_BACKGROUNDS[entry.tile]
    canvas.put(
        position.x,
        position.y,
        theme.tile_glyph(entry.tile, ascii_mode=ascii_mode),
        fg=color,
        bg=background,
    )
    if entry.structure is not None:
        canvas.put(
            position.x,
            position.y,
            theme.structure_glyph(entry.structure, ascii_mode=ascii_mode),
            fg=color,
            bg=background,
        )


def _weather_overlay(
    position: Position,
    weather: WeatherState,
    tick: int,
    ascii_mode: bool,
) -> tuple[str, theme.RGB] | None:
    """Return a deterministic weather overlay glyph for one visible cell."""
    seed = (
        (position.x * 73_856_093)
        ^ (position.y * 19_349_663)
        ^ (tick * 83_492_791)
        ^ (weather.remaining_ticks * 2_654_435_761)
    )
    if weather.kind in {WeatherKind.RAIN, WeatherKind.STORM} and seed % 9 == 0:
        glyph = theme.ASCII_RAIN_GLYPH if ascii_mode else theme.WEATHER_RAIN_GLYPH
        return glyph, theme.WEATHER_RAIN_COLOR
    if weather.wind > 0 and seed % 23 == 0:
        return theme.WEATHER_WIND_GLYPH, theme.WEATHER_WIND_COLOR
    if weather.kind is WeatherKind.FOG and seed % 5 == 0:
        return theme.WEATHER_FOG_GLYPH, theme.WEATHER_FOG_COLOR
    return None


def _render_ticker(canvas: _Canvas, events: Sequence[str], ascii_mode: bool) -> None:
    canvas.hline(
        0,
        TICKER_Y,
        MAP_WIDTH,
        char=theme.ASCII_HORIZONTAL if ascii_mode else "─",
    )
    canvas.put(1, TICKER_Y + 1, "EVENTOS", fg=theme.CYAN, bg=theme.BLACK, bold=True)
    empty_events = ["- sin eventos -"] if ascii_mode else ["— sin eventos —"]
    lines = list(events)[-2:] if events else empty_events
    for offset, line in enumerate(lines):
        canvas.put(1, TICKER_Y + 2 + offset, line, fg=theme.WHITE, bg=theme.BLACK)


def _render_panel(
    canvas: _Canvas,
    state: SessionState,
    names: Mapping[AgentId, str],
    *,
    selected_agent_id: AgentId | None,
    events: Sequence[str],
    paused: bool,
    speed: int,
    capacity: int,
    ascii_mode: bool,
    usage: Mapping[AgentId, AgentUsage] | None,
    mind_reports: Mapping[AgentId, MindReport] | None,
    waiting_reason: str | None,
    panel: PanelState | None = None,
    messages: Sequence[str] = (),
    betrayals: Sequence[str] = (),
) -> None:
    panel_state = panel if panel is not None else PanelState()
    canvas.fill(
        PANEL_X,
        0,
        PANEL_WIDTH,
        BOTTOM_BAR_Y,
        fg=theme.WHITE,
        bg=theme.PANEL_BG,
    )
    vertical = theme.ASCII_VERTICAL if ascii_mode else "│"
    horizontal = theme.ASCII_HORIZONTAL if ascii_mode else "─"
    separator = horizontal * PANEL_CONTENT_WIDTH
    for row in range(BOTTOM_BAR_Y):
        canvas.put(PANEL_X, row, vertical, fg=theme.DIM, bg=theme.PANEL_BG)

    clock = SimulationClock(state.tick_minutes)
    clock.advance(state.tick)
    weather = state.weather
    _panel(
        canvas,
        0,
        f"DÍA {clock.day} · {clock.hour:02d}:{clock.minute:02d} · "
        f"{_PHASE_LABELS[clock.phase]} · {_WEATHER_LABELS[weather.kind]} · "
        f"{weather.temperature_c:.0f} °C · VIENTO {weather.wind} · "
        f"VIS {weather.visibility_factor:.2f}",
        fg=theme.WHITE,
        bold=True,
    )
    _panel(
        canvas,
        1,
        _status_line(
            state,
            paused=paused,
            speed=speed,
            capacity=capacity,
            waiting_reason=waiting_reason,
        ),
        fg=theme.CYAN,
    )
    selected = _resolve_selected(state, selected_agent_id)
    selected_report = None if selected is None else (mind_reports or {}).get(selected.agent_id)
    _panel(
        canvas,
        2,
        _tab_bar(
            panel_state.tab,
            events=len(events),
            mind_reports=1 if selected_report is not None else 0,
            ascii_mode=ascii_mode,
        ),
        fg=theme.CYAN,
        bold=True,
    )
    _panel(canvas, 3, separator, fg=theme.DIM)

    if panel_state.tab is RightPanelTab.SUMMARY:
        _render_summary(
            canvas,
            state,
            names,
            selected=selected,
            events=events,
            usage=usage,
            mind_reports=mind_reports,
            messages=messages,
            betrayals=betrayals,
            ascii_mode=ascii_mode,
        )
        return

    _render_compact_strip(canvas, 4, state, names, selected, ascii_mode, capacity)
    _panel(canvas, 5, separator, fg=theme.DIM)
    lines = _tab_lines(
        panel_state.tab,
        state,
        names,
        selected=selected,
        report=selected_report,
        events=events,
        messages=messages,
        betrayals=betrayals,
        ascii_mode=ascii_mode,
    )
    _render_scroll_window(canvas, 6, lines, panel_state.scroll, ascii_mode)


def _status_line(
    state: SessionState,
    *,
    paused: bool,
    speed: int,
    capacity: int,
    waiting_reason: str | None,
) -> str:
    status = "PAUSA" if paused else "EN CURSO"
    if waiting_reason is not None:
        status = "ESPERANDO AGENTES"
        if waiting_reason == "last_death":
            status += " · ÚLTIMA MUERTE"
    occupied = len(state.agents)
    alive = sum(1 for agent in state.agents if agent.is_alive)
    free = max(0, capacity - occupied)
    return (
        f"{status} · VEL {speed}x · AGENTES {occupied}/{capacity} · {alive} vivos · {free} libres"
    )


def _tab_bar(
    active: RightPanelTab,
    *,
    events: int,
    mind_reports: int,
    ascii_mode: bool,
) -> str:
    marker = ">" if ascii_mode else "◆"
    parts: list[str] = []
    for tab in PANEL_TABS:
        label = TAB_LABELS[tab]
        if tab is RightPanelTab.EVENTS:
            label = f"{label} {events}"
        elif tab is RightPanelTab.MIND:
            label = f"{label} {mind_reports}"
        prefix = marker if tab is active else " "
        parts.append(f"{prefix} {label}")
    return "   ".join(parts)


def _render_compact_strip(
    canvas: _Canvas,
    y: int,
    state: SessionState,
    names: Mapping[AgentId, str],
    selected: Agent | None,
    ascii_mode: bool,
    capacity: int,
) -> None:
    agents = list(state.agents)[:capacity]
    pieces: list[str] = []
    for index, agent in enumerate(agents, start=1):
        name = names.get(agent.agent_id, str(agent.agent_id))
        mark = "@" if agent.is_alive else ("X" if ascii_mode else "☠")
        selected_mark = ">" if ascii_mode else "▶"
        is_selected = selected is not None and agent.agent_id == selected.agent_id
        prefix = selected_mark if is_selected else " "
        pieces.append(f"{prefix}{index}{mark}{name}")
    text = "  ".join(pieces) if pieces else "— sin agentes —"
    _panel(canvas, y, text, fg=theme.WHITE, bold=True)


def _render_summary(
    canvas: _Canvas,
    state: SessionState,
    names: Mapping[AgentId, str],
    *,
    selected: Agent | None,
    events: Sequence[str],
    usage: Mapping[AgentId, AgentUsage] | None,
    mind_reports: Mapping[AgentId, MindReport] | None,
    messages: Sequence[str],
    betrayals: Sequence[str],
    ascii_mode: bool,
) -> None:
    separator = (theme.ASCII_HORIZONTAL if ascii_mode else "─") * PANEL_CONTENT_WIDTH
    agents = list(state.agents)[:8]
    y = 4
    _panel(canvas, y, "AGENTES", fg=theme.CYAN, bold=True)
    y += 1
    if not agents:
        _panel(canvas, y, "— sin agentes —", fg=theme.DIM)
        y += 1
    for index, agent in enumerate(agents, start=1):
        name = names.get(agent.agent_id, str(agent.agent_id))
        is_selected = selected is not None and agent.agent_id == selected.agent_id
        _panel(
            canvas,
            y,
            _agent_summary_line(
                index,
                agent,
                name,
                ascii_mode=ascii_mode,
                selected=is_selected,
                death=_death_detail(state, agent),
            ),
            bg=theme.SELECTED_BG if is_selected else theme.PANEL_BG,
            bold=is_selected,
        )
        y += 1
    _panel(canvas, y, separator, fg=theme.DIM)
    y += 1
    if selected is None:
        _panel(canvas, y, "— sin agente seleccionado —", fg=theme.DIM)
        return

    y = _render_selected_block(canvas, y, state, selected, names, ascii_mode)

    selected_usage = usage.get(selected.agent_id) if usage is not None else None
    if selected_usage is not None and selected_usage.entries and BOTTOM_BAR_Y - y >= 12:
        y = _render_usage_block(canvas, y, selected_usage)

    available = BOTTOM_BAR_Y - y
    extra = max(0, available - 9)
    mind_extra = min(3, extra)
    extra -= mind_extra
    env_extra = min(2, extra)
    extra -= env_extra
    relations_extra = min(2, extra)
    extra -= relations_extra
    events_extra = min(5, extra)

    y = _render_mind_block(
        canvas,
        y,
        selected,
        None if mind_reports is None else mind_reports.get(selected.agent_id),
        lines=1 + mind_extra,
        separator=separator,
    )
    y = _render_environment_block(
        canvas,
        y,
        state,
        selected,
        messages=messages,
        lines=1 + env_extra,
        separator=separator,
    )
    y = _render_relations_block(
        canvas,
        y,
        state,
        names,
        selected,
        messages=messages,
        betrayals=betrayals,
        lines=1 + relations_extra,
        separator=separator,
    )
    _render_events_block(
        canvas,
        y,
        events,
        lines=2 + events_extra,
        separator=separator,
    )


def _render_selected_block(
    canvas: _Canvas,
    y: int,
    state: SessionState,
    selected: Agent,
    names: Mapping[AgentId, str],
    ascii_mode: bool,
) -> int:
    name = names.get(selected.agent_id, str(selected.agent_id))
    _panel(
        canvas,
        y,
        f"AGENTE SELECCIONADO · {name} · {_agent_glyph(selected, ascii_mode)} · "
        f"({selected.position.x}, {selected.position.y})",
        fg=theme.CYAN,
        bold=True,
    )
    y += 1
    death = _death_detail(state, selected)
    if not selected.is_alive:
        _panel(canvas, y, f"Estado: MUERTO · {death}", fg=theme.RED)
        y += 1
        tags = _status_tags(selected)
        _panel(canvas, y, f"ESTADOS: {' · '.join(tags) if tags else '—'}")
        y += 1
        _panel(canvas, y, "INVENTARIO", fg=theme.CYAN, bold=True)
        y += 1
        _panel(canvas, y, "— saqueado —", fg=theme.DIM)
        return y + 1

    attributes = selected.attributes
    inventory = selected.inventory
    rows = (
        ("Salud   ", attributes.health, f"{attributes.health:>3.0f}"),
        ("Hambre  ", attributes.hunger, f"{attributes.hunger:>3.0f}"),
        ("Sed     ", attributes.thirst, f"{attributes.thirst:>3.0f}"),
        ("Energía ", attributes.energy, f"{attributes.energy:>3.0f}"),
        (
            "Temp    ",
            (attributes.body_temperature_c - 34.0) / 8.0 * 100.0,
            f"{attributes.body_temperature_c:>4.1f}",
        ),
        ("Mojado  ", attributes.wetness, f"{attributes.wetness:>3.0f}"),
    )
    for label, value, shown in rows:
        _panel(canvas, y, f"{label} {_bar(value, 100, ascii_mode)} {shown}")
        y += 1
    _panel(
        canvas,
        y,
        f"FUE {attributes.strength} · DES {attributes.dexterity} · "
        f"RES {attributes.endurance} · VIS {attributes.vision}",
    )
    y += 1
    tags = _status_tags(selected)
    _panel(canvas, y, f"ESTADOS: {' · '.join(tags) if tags else '—'}")
    y += 1
    equipment = " · ".join(
        f"{slot.value}:{spec.item_id}" for slot, spec in selected.equipment.items
    ) or ("-" if ascii_mode else "—")
    _panel(
        canvas,
        y,
        f"CARGA {inventory.total_weight_grams / 1000.0:.1f}/"
        f"{inventory.max_weight_grams / 1000.0:.1f} kg · EQUIPO: {equipment}",
    )
    y += 1
    _panel(canvas, y, "INVENTARIO", fg=theme.CYAN, bold=True)
    y += 1
    items = [f"{stack.definition.item_id} x{stack.quantity}" for stack in inventory.stacks]
    _panel(canvas, y, _clip(", ".join(items) or "— vacío —", PANEL_CONTENT_WIDTH))
    return y + 1


def _render_usage_block(canvas: _Canvas, y: int, usage: AgentUsage) -> int:
    _panel(canvas, y, "USO IA (REPORTADO)", fg=theme.CYAN, bold=True)
    y += 1
    entry = usage.entries[-1]
    effort = entry.reasoning_effort or "-"
    _panel(
        canvas,
        y,
        f"{entry.model} / {effort}: {entry.input_tokens} in / {entry.output_tokens} out",
    )
    y += 1
    _panel(
        canvas,
        y,
        f"TOTAL {usage.total_tokens} tokens - {_usage_cost_text(usage)}",
    )
    return y + 1


def _render_mind_block(
    canvas: _Canvas,
    y: int,
    selected: Agent,
    report: MindReport | None,
    *,
    lines: int,
    separator: str,
) -> int:
    _panel(canvas, y, separator, fg=theme.DIM)
    y += 1
    _panel(canvas, y, "MENTE (REPORTADO)", fg=theme.CYAN, bold=True)
    y += 1
    for line in _mind_lines(report, lines):
        _panel(canvas, y, line)
        y += 1
    return y


def _render_environment_block(
    canvas: _Canvas,
    y: int,
    state: SessionState,
    selected: Agent,
    *,
    messages: Sequence[str],
    lines: int,
    separator: str,
) -> int:
    _panel(canvas, y, separator, fg=theme.DIM)
    y += 1
    _panel(canvas, y, "ENTORNO", fg=theme.CYAN, bold=True)
    y += 1
    weather = state.weather
    content = [
        f"Clima: {_WEATHER_LABELS[weather.kind]} · Temp: "
        f"{weather.temperature_c:.0f} °C · Viento: {weather.wind} · "
        f"Visibilidad: {weather.visibility_factor:.2f}",
        _structures_line(state),
        f"Mensajes: {_last_message(messages, selected)}",
    ]
    for line in content[:lines]:
        _panel(canvas, y, line)
        y += 1
    return y


def _render_relations_block(
    canvas: _Canvas,
    y: int,
    state: SessionState,
    names: Mapping[AgentId, str],
    selected: Agent,
    *,
    messages: Sequence[str],
    betrayals: Sequence[str],
    lines: int,
    separator: str,
) -> int:
    _panel(canvas, y, separator, fg=theme.DIM)
    y += 1
    _panel(canvas, y, "RELACIONES", fg=theme.CYAN, bold=True)
    y += 1
    content = [
        f"Alianzas: {_alliances_line(state, names)}",
        f"Trueques: {_trades_line(state, names)}",
        f"Traiciones: {_last_betrayal(betrayals) if betrayals else '—'}",
    ]
    for line in content[:lines]:
        _panel(canvas, y, line)
        y += 1
    return y


def _render_events_block(
    canvas: _Canvas,
    y: int,
    events: Sequence[str],
    *,
    lines: int,
    separator: str,
) -> None:
    _panel(canvas, y, separator, fg=theme.DIM)
    y += 1
    _panel(canvas, y, "EVENTOS", fg=theme.CYAN, bold=True)
    y += 1
    visible = list(events)[-lines:] if events else ["— sin eventos —"]
    for line in visible:
        _panel(canvas, y, line, fg=theme.DIM)
        y += 1


def _tab_lines(
    tab: RightPanelTab,
    state: SessionState,
    names: Mapping[AgentId, str],
    *,
    selected: Agent | None,
    report: MindReport | None,
    events: Sequence[str],
    messages: Sequence[str],
    betrayals: Sequence[str],
    ascii_mode: bool,
) -> list[str]:
    if tab is RightPanelTab.EVENTS:
        if not events:
            return ["— sin eventos —"]
        return list(events)
    name = "—" if selected is None else names.get(selected.agent_id, str(selected.agent_id))
    if tab is RightPanelTab.MIND:
        if report is None:
            return [f"{name}: — sin reporte —"]
        lines = [f"Intención: {report.intent}"]
        lines.extend(_wrap(f"Pensamiento: {report.thought}", PANEL_CONTENT_WIDTH))
        if report.plan is not None:
            lines.extend(_wrap(f"Plan: {report.plan}", PANEL_CONTENT_WIDTH))
        if report.confidence is not None:
            lines.append(f"Confianza: {report.confidence}")
        return lines
    return _links_lines(state, names, selected, messages, betrayals, ascii_mode)


def _links_lines(
    state: SessionState,
    names: Mapping[AgentId, str],
    selected: Agent | None,
    messages: Sequence[str],
    betrayals: Sequence[str],
    ascii_mode: bool,
) -> list[str]:
    lines: list[str] = ["INVENTARIO"]
    if selected is not None:
        inventory = selected.inventory
        if inventory.stacks:
            lines.extend(
                f"  {stack.definition.item_id} x{stack.quantity}" for stack in inventory.stacks
            )
        else:
            lines.append("  — vacío —")
        lines.append("EQUIPO")
        if selected.equipment.items:
            lines.extend(f"  {slot.value}: {spec.name}" for slot, spec in selected.equipment.items)
        else:
            lines.append("  — sin equipo —")
    else:
        lines.append("  — sin agente seleccionado —")
    lines.extend(("ALIANZAS", f"  {_alliances_line(state, names)}"))
    lines.extend(("TRUEQUES", f"  {_trades_line(state, names)}"))
    lines.append("MENSAJES")
    if messages:
        lines.extend(f"  {message}" for message in list(messages)[-6:])
    else:
        lines.append("  — sin mensajes —")
    lines.append("TRAICIONES")
    if betrayals:
        lines.extend(f"  {betrayal}" for betrayal in list(betrayals)[-6:])
    else:
        lines.append("  — sin traiciones —")
    return lines


def _render_scroll_window(
    canvas: _Canvas,
    y: int,
    lines: Sequence[str],
    scroll: int,
    ascii_mode: bool,
) -> None:
    rows = BOTTOM_BAR_Y - 1 - y
    start = max(0, min(scroll, max(0, len(lines) - rows)))
    for offset, line in enumerate(lines[start : start + rows]):
        _panel(canvas, y + offset, line)
    end = min(len(lines), start + rows)
    if lines:
        indicator = f"{start + 1}-{end} de {len(lines)} · [ ] pestaña · ↑↓ PgUp/PgDn"
    else:
        indicator = "— vacío —"
    _panel(canvas, BOTTOM_BAR_Y - 1, indicator, fg=theme.DIM)


def _render_bottom_bar(canvas: _Canvas, ascii_mode: bool) -> None:
    bar = BOTTOM_BAR.replace("│", theme.ASCII_VERTICAL) if ascii_mode else BOTTOM_BAR
    text = (bar + " " * SCREEN_WIDTH)[:SCREEN_WIDTH]
    canvas.put(0, BOTTOM_BAR_Y, text, fg=theme.BAR_FG, bg=theme.BAR_BG, bold=True)


def _panel(
    canvas: _Canvas,
    y: int,
    text: str,
    *,
    fg: theme.RGB = theme.WHITE,
    bg: theme.RGB = theme.PANEL_BG,
    bold: bool = False,
) -> None:
    if y >= BOTTOM_BAR_Y:
        return
    canvas.put(
        PANEL_CONTENT_X,
        y,
        _clip(text, PANEL_CONTENT_WIDTH),
        fg=fg,
        bg=bg,
        bold=bold,
    )


def _clip(text: str, width: int) -> str:
    """Truncate one panel line by width, marking the cut with an ellipsis."""
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    return text[: width - 1] + "…"


def _wrap(text: str, width: int, *, max_lines: int = 40) -> list[str]:
    """Wrap text to the panel width, marking a truncated tail."""
    if width <= 0:
        return []
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if len(candidate) <= width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
        if len(lines) >= max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if lines and len(lines) == max_lines and " ".join(lines) != text:
        lines[-1] = _clip(lines[-1] + "…", width)
    return lines


def _agent_summary_line(
    index: int,
    agent: Agent,
    name: str,
    *,
    ascii_mode: bool,
    selected: bool,
    death: str | None,
) -> str:
    marker = ">" if ascii_mode else "▶"
    prefix = f"{marker if selected else ' '} {index} {'@' if agent.is_alive else '☠'} {name}"
    if ascii_mode:
        prefix = f"{marker if selected else ' '} {index} {'@' if agent.is_alive else 'X'} {name}"
    if not agent.is_alive:
        return f"{prefix} ☠ {death or 'muerto'}"
    if agent.status is AgentStatus.ABSENT:
        return f"{prefix} … ausente"
    attributes = agent.attributes
    health_symbol = "H" if ascii_mode else "♥"
    tags = _status_tags(agent)
    tag_text = f" [{' · '.join(tags)}]" if tags else ""
    return (
        f"{prefix} {health_symbol}{attributes.health:>3.0f} "
        f"H{attributes.hunger:>3.0f} S{attributes.thirst:>3.0f} "
        f"E{attributes.energy:>3.0f}{tag_text}"
    )


def _death_detail(state: SessionState, agent: Agent) -> str | None:
    for corpse in state.corpses:
        if corpse.agent_id == agent.agent_id:
            killer = f" por {corpse.killer_id}" if corpse.killer_id is not None else ""
            return f"muerto por {corpse.cause}{killer}"
    if agent.status is AgentStatus.DEAD:
        return "muerto"
    return None


def _mind_lines(report: MindReport | None, limit: int) -> list[str]:
    if report is None:
        return ["— sin reporte —"]
    lines = [f"Intención: {report.intent}", f"Pensamiento: {report.thought}"]
    if report.plan is not None:
        lines.append(f"Plan: {report.plan}")
    if report.confidence is not None:
        lines.append(f"Confianza: {report.confidence}")
    return lines[: max(1, limit)]


def _structures_line(state: SessionState) -> str:
    fires = sum(1 for structure in state.structures if structure.kind is StructureKind.FIRE)
    shelters = sum(1 for structure in state.structures if structure.kind is StructureKind.SHELTER)
    corpses = sum(1 for agent in state.agents if not agent.is_alive)
    return f"Fuegos: {fires} · Refugios: {shelters} · Cadáveres: {corpses}"


def _last_message(messages: Sequence[str], selected: Agent) -> str:
    if not messages:
        return "—"
    return messages[-1]


def _alliances_line(
    state: SessionState,
    names: Mapping[AgentId, str],
) -> str:
    active = [alliance for alliance in state.alliances if alliance.status is AllianceStatus.ACTIVE]
    if not active:
        return "—"
    return " · ".join(_alliance_text(alliance, names) for alliance in active[:2])


def _alliance_text(alliance: Alliance, names: Mapping[AgentId, str]) -> str:
    first, second = alliance.members
    return f"{names.get(first, str(first))}-{names.get(second, str(second))}"


def _trades_line(state: SessionState, names: Mapping[AgentId, str]) -> str:
    open_trades = [trade for trade in state.trades if trade.status is TradeStatus.OPEN]
    if not open_trades:
        return "—"
    trade = open_trades[0]
    proposer = names.get(trade.proposer_id, str(trade.proposer_id))
    target = names.get(trade.target_id, str(trade.target_id))
    return f"{len(open_trades)} pendientes · {proposer}→{target}"


def _last_betrayal(betrayals: Sequence[str]) -> str:
    return betrayals[-1] if betrayals else "—"


def _resolve_selected(
    state: SessionState,
    selected_agent_id: AgentId | None,
) -> Agent | None:
    if selected_agent_id is not None:
        for agent in state.agents:
            if agent.agent_id == selected_agent_id:
                return agent
    return state.agents[0] if state.agents else None


def _agent_glyph(agent: Agent, ascii_mode: bool = False) -> str:
    if agent.status is AgentStatus.DEAD:
        return "x" if ascii_mode else "☠"
    if agent.status is AgentStatus.ABSENT:
        return "?" if ascii_mode else "…"
    if agent.status is AgentStatus.SLEEPING:
        return "z"
    return "@"


def _status_tags(agent: Agent) -> list[str]:
    return [_STATUS_LABELS[tag] for tag in status_tags(agent)]


def _usage_cost_text(usage: AgentUsage) -> str:
    if usage.cost_usd is None:
        return "costo desconocido"
    suffix = "" if usage.cost_complete else " + ?"
    source = _COST_SOURCE_LABELS[usage.cost_source]
    return f"USD {usage.cost_usd:.4f}{suffix} ({source})"


def _bar(value: float, maximum: float, ascii_mode: bool = False) -> str:
    ratio = 0.0 if maximum <= 0 else value / maximum
    filled = max(0, min(10, round(ratio * 10)))
    fill_char = theme.ASCII_BAR_FILLED if ascii_mode else "█"
    empty_char = theme.ASCII_BAR_EMPTY if ascii_mode else "░"
    return fill_char * filled + empty_char * (10 - filled)


def _hex(color: theme.RGB) -> str:
    red, green, blue = color
    return f"#{red:02x}{green:02x}{blue:02x}"
