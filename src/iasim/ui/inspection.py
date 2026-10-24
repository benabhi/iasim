"""Read-only inspection details for tiles, structures, corpses and agents.

The operator cursor never mutates the simulation: this module only formats the
current state into short lines for the inspection panel.
"""

from __future__ import annotations

from collections.abc import Mapping

from iasim.domain.agents import Agent, AgentStatus
from iasim.domain.alliances import is_allied
from iasim.domain.geometry import Position
from iasim.domain.identifiers import AgentId
from iasim.domain.session import SessionState
from iasim.ui import theme

MAX_INSPECTION_LINES = 4


def describe_position(
    state: SessionState,
    names: Mapping[AgentId, str],
    position: Position,
    *,
    selected_agent_id: AgentId | None = None,
) -> tuple[str, ...]:
    """Return the read-only details for one map cell."""
    if not state.world.contains(position):
        return ("Fuera del mapa",)
    lines: list[str] = []
    tile = state.world.tile_at(position)
    resources = sorted(
        node.resource_id
        for node in state.resource_nodes
        if node.position == position and not node.depleted
    )
    resource_text = f" · recursos: {', '.join(resources)}" if resources else ""
    lines.append(f"Celda ({position.x},{position.y}) · {theme.TILE_LABELS[tile]}{resource_text}")
    for structure in state.structures:
        if structure.position != position:
            continue
        label = theme.TILE_LABELS[structure.kind.tile]
        fire = " · encendido" if structure.lit else ""
        lines.append(f"Estructura: {label}{fire}")
    for corpse in state.corpses:
        if corpse.position != position:
            continue
        loot = ", ".join(
            f"{stack.definition.item_id} x{stack.quantity}" for stack in corpse.inventory.stacks
        )
        killer = (
            f" · autor {names.get(corpse.killer_id, str(corpse.killer_id))}"
            if corpse.killer_id is not None
            else ""
        )
        owner = names.get(corpse.agent_id, str(corpse.agent_id))
        lines.append(f"Cadáver de {owner} · {corpse.cause}{killer} · botín: {loot or '—'}")
    items = [item for item in state.ground_items if item.position == position]
    if items:
        lines.append(
            "Objetos: "
            + ", ".join(f"{item.stack.definition.item_id} x{item.stack.quantity}" for item in items)
        )
    for agent in state.agents:
        if agent.position != position:
            continue
        lines.append(_agent_line(state, names, agent, selected_agent_id=selected_agent_id))
    return tuple(lines[:MAX_INSPECTION_LINES])


def _agent_line(
    state: SessionState,
    names: Mapping[AgentId, str],
    agent: Agent,
    *,
    selected_agent_id: AgentId | None,
) -> str:
    name = names.get(agent.agent_id, str(agent.agent_id))
    relation = _relation(state, agent, selected_agent_id)
    if not agent.is_alive:
        return f"Agente {name} · MUERTO · {relation}"
    equipment = ", ".join(spec.item_id for _, spec in agent.equipment.items) or "—"
    if agent.status is AgentStatus.ABSENT:
        state_label = "ausente"
    elif agent.status is AgentStatus.SLEEPING:
        state_label = "durmiendo"
    else:
        state_label = "activo"
    return (
        f"Agente {name} · {state_label} · salud {_health_band(agent)} · "
        f"equipo {equipment} · relación {relation}"
    )


def _health_band(agent: Agent) -> str:
    health = agent.attributes.health
    if health >= 70:
        return "sana"
    if health >= 35:
        return "herida"
    return "crítica"


def _relation(
    state: SessionState,
    agent: Agent,
    selected_agent_id: AgentId | None,
) -> str:
    if selected_agent_id is None:
        return "neutral"
    if agent.agent_id == selected_agent_id:
        return "seleccionado"
    if is_allied(state.alliances, selected_agent_id, agent.agent_id):
        return "aliada"
    return "neutral"
