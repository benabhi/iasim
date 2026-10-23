"""Per-agent tile, resource, structure, and agent memory."""

from __future__ import annotations

from dataclasses import dataclass, replace

from iasim.domain.geometry import Position
from iasim.domain.identifiers import AgentId
from iasim.domain.tiles import TileType
from iasim.domain.world import StructureKind


@dataclass(frozen=True, slots=True)
class MemoryEntry:
    """One previously perceived map cell."""

    position: Position
    tile: TileType
    last_seen_tick: int
    resources: tuple[str, ...] = ()
    structure: StructureKind | None = None
    stale: bool = False

    def __post_init__(self) -> None:
        if self.last_seen_tick < 0:
            raise ValueError("last_seen_tick must be non-negative")
        if not isinstance(self.tile, TileType):
            raise ValueError(f"tile must be a TileType, got {self.tile!r}")
        if self.structure is not None and not isinstance(self.structure, StructureKind):
            raise ValueError(f"structure must be a StructureKind, got {self.structure!r}")


@dataclass(frozen=True, slots=True)
class AgentMemory:
    """The last known position of another agent."""

    agent_id: AgentId
    position: Position
    last_seen_tick: int
    stale: bool = False

    def __post_init__(self) -> None:
        if self.last_seen_tick < 0:
            raise ValueError("last_seen_tick must be non-negative")


@dataclass(frozen=True, slots=True)
class Memory:
    """Immutable per-agent memory ordered by position and agent id."""

    tiles: tuple[MemoryEntry, ...] = ()
    agents: tuple[AgentMemory, ...] = ()

    def __post_init__(self) -> None:
        positions = [entry.position for entry in self.tiles]
        if len(positions) != len(set(positions)):
            raise ValueError("memory must not contain duplicate tile positions")
        agent_ids = [entry.agent_id for entry in self.agents]
        if len(agent_ids) != len(set(agent_ids)):
            raise ValueError("memory must not contain duplicate agent ids")

    def refresh(
        self,
        visible_tiles: tuple[MemoryEntry, ...],
        visible_agents: tuple[AgentMemory, ...],
    ) -> Memory:
        """Merge current perceptions and mark unseen memories stale."""
        visible_by_position = {entry.position: entry for entry in visible_tiles}
        visible_agent_ids = {entry.agent_id for entry in visible_agents}
        merged_tiles: list[MemoryEntry] = []
        for entry in self.tiles:
            if entry.position in visible_by_position:
                merged_tiles.append(visible_by_position[entry.position])
            else:
                merged_tiles.append(replace(entry, stale=True))
        known_positions = {entry.position for entry in self.tiles}
        merged_tiles.extend(
            entry for entry in visible_tiles if entry.position not in known_positions
        )
        merged_agents: list[AgentMemory] = []
        for agent_entry in self.agents:
            if agent_entry.agent_id in visible_agent_ids:
                merged_agents.append(
                    next(
                        current
                        for current in visible_agents
                        if current.agent_id == agent_entry.agent_id
                    )
                )
            else:
                merged_agents.append(replace(agent_entry, stale=True))
        known_agents = {agent_entry.agent_id for agent_entry in self.agents}
        merged_agents.extend(
            agent_entry
            for agent_entry in visible_agents
            if agent_entry.agent_id not in known_agents
        )
        return Memory(
            tiles=tuple(
                sorted(merged_tiles, key=lambda entry: (entry.position.y, entry.position.x))
            ),
            agents=tuple(sorted(merged_agents, key=lambda entry: entry.agent_id)),
        )
