"""Deterministic 160x45 base layout for the operator UI."""

from __future__ import annotations

import html
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from iasim.domain.agents import Agent, AgentStatus
from iasim.domain.clock import DayPhase, SimulationClock
from iasim.domain.geometry import Position
from iasim.domain.identifiers import AgentId
from iasim.domain.session import SessionState
from iasim.domain.tiles import TileType
from iasim.domain.world import StructureKind
from iasim.ui import theme
from iasim.ui.controls import KEY_GUIDE, STATUS_GUIDE

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
    "[ESPACIO] Pausa │ [1-8/TAB] Agente │ [+/-] Vel │ [F1] Ayuda │ [F2] Agente │ "
    "[F3] Mundo │ [F4] Log │ [F5] Replay │ [F6] Mapa │ [F9] Guardar │ [Q] Salir"
)

HELP_FOOTER = "ESC volver │ F1 cerrar ayuda │ A ASCII │ Q/R requieren confirmación"

_PHASE_LABELS: dict[DayPhase, str] = {
    DayPhase.DAWN: "AMANECER",
    DayPhase.DAY: "DÍA",
    DayPhase.DUSK: "ATARDECER",
    DayPhase.NIGHT: "NOCHE",
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
) -> BaseScreen:
    """Render the deterministic base screen without mutating the session."""
    canvas = _Canvas()
    canvas.fill(0, 0, SCREEN_WIDTH, SCREEN_HEIGHT, fg=theme.WHITE, bg=theme.BLACK)
    _render_map(canvas, state, selected_agent_id, ascii_mode)
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
    )
    _render_bottom_bar(canvas, ascii_mode)
    return canvas.to_screen()


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
) -> None:
    for y in range(MAP_HEIGHT):
        for x in range(MAP_WIDTH):
            if x >= state.world.width or y >= state.world.height:
                continue
            tile = state.world.tile_at(Position(x, y))
            canvas.put(
                x,
                y,
                theme.tile_glyph(tile, ascii_mode=ascii_mode),
                fg=theme.TILE_COLORS[tile],
                bg=theme.TILE_BACKGROUNDS[tile],
            )

    for agent in state.agents:
        if not (0 <= agent.position.x < MAP_WIDTH and 0 <= agent.position.y < MAP_HEIGHT):
            continue
        selected = agent.agent_id == selected_agent_id
        tile = state.world.tile_at(agent.position)
        canvas.put(
            agent.position.x,
            agent.position.y,
            _agent_glyph(agent, ascii_mode),
            fg=theme.AGENT_COLOR,
            bg=theme.SELECTED_BG if selected else theme.TILE_BACKGROUNDS[tile],
            bold=selected,
        )


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
) -> None:
    canvas.fill(
        PANEL_X,
        0,
        PANEL_WIDTH,
        BOTTOM_BAR_Y,
        fg=theme.WHITE,
        bg=theme.PANEL_BG,
    )
    vertical = theme.ASCII_VERTICAL if ascii_mode else "│"
    separator = (theme.ASCII_HORIZONTAL if ascii_mode else "─") * PANEL_CONTENT_WIDTH
    for y in range(BOTTOM_BAR_Y):
        canvas.put(PANEL_X, y, vertical, fg=theme.DIM, bg=theme.PANEL_BG)

    clock = SimulationClock(state.tick_minutes)
    clock.advance(state.tick)
    phase = _PHASE_LABELS[clock.phase]
    _panel(
        canvas,
        0,
        f"DÍA {clock.day} · {clock.hour:02d}:{clock.minute:02d} · {phase} · "
        "DESPEJADO · 22 °C · VIENTO 0",
        fg=theme.WHITE,
        bold=True,
    )
    _panel(
        canvas,
        1,
        f"{'PAUSA' if paused else 'EN CURSO'} · VEL {speed}x · "
        f"AGENTES {len(state.agents)}/{capacity}",
        fg=theme.CYAN,
    )
    _panel(canvas, 2, separator, fg=theme.DIM)
    _panel(canvas, 3, "AGENTES", fg=theme.CYAN, bold=True)

    agents = list(state.agents)[:capacity]
    selected = _resolve_selected(state, selected_agent_id)
    y = 4
    for index, agent in enumerate(agents, start=1):
        name = names.get(agent.agent_id, str(agent.agent_id))
        is_selected = selected is not None and agent.agent_id == selected.agent_id
        _panel(
            canvas,
            y,
            _agent_line(index, agent, name, ascii_mode),
            fg=theme.WHITE,
            bg=theme.SELECTED_BG if is_selected else theme.PANEL_BG,
            bold=is_selected,
        )
        y += 1
    if not agents:
        _panel(canvas, y, "— sin agentes —", fg=theme.DIM)
        y += 1

    y += 1
    _panel(canvas, y, separator, fg=theme.DIM)
    y += 1
    if selected is None:
        _panel(canvas, y, "— sin agente seleccionado —", fg=theme.DIM)
        return

    selected_name = names.get(selected.agent_id, str(selected.agent_id))
    _panel(
        canvas,
        y,
        f"AGENTE SELECCIONADO · {selected_name} · {_agent_glyph(selected, ascii_mode)} · "
        f"({selected.position.x}, {selected.position.y})",
        fg=theme.CYAN,
        bold=True,
    )
    y += 1
    attributes = selected.attributes
    inventory = selected.inventory
    _panel(
        canvas,
        y,
        f"Salud   {_bar(attributes.health, 100, ascii_mode)} {attributes.health:>3.0f}",
    )
    y += 1
    _panel(
        canvas,
        y,
        f"Hambre  {_bar(attributes.hunger, 100, ascii_mode)} {attributes.hunger:>3.0f}",
    )
    y += 1
    _panel(
        canvas,
        y,
        f"Sed     {_bar(attributes.thirst, 100, ascii_mode)} {attributes.thirst:>3.0f}",
    )
    y += 1
    _panel(
        canvas,
        y,
        f"Energía {_bar(attributes.energy, 100, ascii_mode)} {attributes.energy:>3.0f}",
    )
    y += 1
    temperature = attributes.body_temperature_c
    _panel(
        canvas,
        y,
        f"Temp    {_bar((temperature - 34.0) / 8.0 * 100, 100, ascii_mode)} {temperature:>4.1f} °C",
    )
    y += 1
    _panel(
        canvas,
        y,
        f"Mojado  {_bar(attributes.wetness, 100, ascii_mode)} {attributes.wetness:>3.0f}",
    )
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
    _panel(
        canvas,
        y,
        f"CARGA {inventory.total_weight_grams / 1000.0:.1f}/"
        f"{inventory.max_weight_grams / 1000.0:.1f} kg · EQUIPO: —",
    )
    y += 1

    y += 1
    _panel(canvas, y, separator, fg=theme.DIM)
    y += 1
    _panel(canvas, y, "MENTE (REPORTADO)", fg=theme.CYAN, bold=True)
    y += 1
    _panel(canvas, y, "— sin reporte —", fg=theme.DIM)
    y += 2

    _panel(canvas, y, separator, fg=theme.DIM)
    y += 1
    _panel(canvas, y, "ENTORNO", fg=theme.CYAN, bold=True)
    y += 1
    _panel(canvas, y, "Clima: DESPEJADO · Temp: 22 °C · Viento: 0 · Visibilidad: 1.00")
    y += 1
    fires = sum(1 for structure in state.structures if structure.kind is StructureKind.FIRE)
    shelters = sum(1 for structure in state.structures if structure.kind is StructureKind.SHELTER)
    corpses = sum(1 for agent in state.agents if agent.status is AgentStatus.DEAD)
    _panel(canvas, y, f"Fuegos: {fires} · Refugios: {shelters} · Cadáveres: {corpses}")
    y += 2

    _panel(canvas, y, separator, fg=theme.DIM)
    y += 1
    _panel(canvas, y, "EVENTOS", fg=theme.CYAN, bold=True)
    y += 1
    event_lines = list(events)[-2:] if events else ["— sin eventos —"]
    for line in event_lines:
        _panel(canvas, y, line, fg=theme.DIM)
        y += 1
    y += 1

    _panel(canvas, y, separator, fg=theme.DIM)
    y += 1
    _panel(canvas, y, "INVENTARIO", fg=theme.CYAN, bold=True)
    y += 1
    items = [f"{stack.definition.item_id} x{stack.quantity}" for stack in inventory.stacks[:2]]
    for line in items or ["— vacío —"]:
        _panel(canvas, y, line, fg=theme.DIM)
        y += 1


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
        text[:PANEL_CONTENT_WIDTH],
        fg=fg,
        bg=bg,
        bold=bold,
    )


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


def _agent_line(index: int, agent: Agent, name: str, ascii_mode: bool = False) -> str:
    if agent.status is AgentStatus.DEAD:
        return f"{index:>1} {_agent_glyph(agent, ascii_mode)} {name:<8} — muerta"
    attributes = agent.attributes
    health_symbol = "H" if ascii_mode else "♥"
    return (
        f"{index:>1} {_agent_glyph(agent, ascii_mode)} {name:<8} "
        f"{health_symbol}{attributes.health:>3.0f} H{attributes.hunger:>3.0f} "
        f"S{attributes.thirst:>3.0f} E{attributes.energy:>3.0f}"
    )


def _status_tags(agent: Agent) -> list[str]:
    tags: list[str] = []
    attributes = agent.attributes
    if agent.status is AgentStatus.DEAD:
        tags.append("MUERTO")
    if attributes.hunger > 70:
        tags.append("HAMBRE")
    if attributes.thirst > 70:
        tags.append("SED")
    if attributes.energy < 20:
        tags.append("AGOTADO")
    if attributes.wetness > 60:
        tags.append("MOJADO")
    if attributes.body_temperature_centi < 3500:
        tags.append("FRÍO")
    if attributes.body_temperature_centi > 4000:
        tags.append("CALOR")
    return tags


def _bar(value: float, maximum: float, ascii_mode: bool = False) -> str:
    ratio = 0.0 if maximum <= 0 else value / maximum
    filled = max(0, min(10, round(ratio * 10)))
    fill_char = theme.ASCII_BAR_FILLED if ascii_mode else "█"
    empty_char = theme.ASCII_BAR_EMPTY if ascii_mode else "░"
    return fill_char * filled + empty_char * (10 - filled)


def _hex(color: theme.RGB) -> str:
    red, green, blue = color
    return f"#{red:02x}{green:02x}{blue:02x}"
