"""Canonical immutable session state."""

from __future__ import annotations

from dataclasses import dataclass, field

from iasim.domain.agents import Agent
from iasim.domain.items import GroundItem
from iasim.domain.rng import U64_MASK
from iasim.domain.tiles import WorldMap
from iasim.domain.weather import WeatherState
from iasim.domain.world import Structure


@dataclass(frozen=True, slots=True)
class SessionState:
    """Immutable canonical state of one simulation session."""

    seed: int
    tick: int
    rng_state: int
    world: WorldMap
    tick_minutes: int = 5
    agents: tuple[Agent, ...] = ()
    structures: tuple[Structure, ...] = ()
    ground_items: tuple[GroundItem, ...] = ()
    weather: WeatherState = field(default_factory=WeatherState)

    def __post_init__(self) -> None:
        if self.seed < 0:
            raise ValueError(f"seed must be non-negative, got {self.seed}")
        if self.tick < 0:
            raise ValueError(f"tick must be non-negative, got {self.tick}")
        if not 0 <= self.rng_state <= U64_MASK:
            raise ValueError(f"rng_state must be a 64-bit unsigned value, got {self.rng_state}")
        if self.tick_minutes < 1:
            raise ValueError(f"tick_minutes must be at least 1, got {self.tick_minutes}")

        agent_ids = [agent.agent_id for agent in self.agents]
        if len(agent_ids) != len(set(agent_ids)):
            raise ValueError("session must not contain duplicate agent ids")
        for agent in self.agents:
            if not self.world.contains(agent.position):
                raise ValueError(f"agent {agent.agent_id!r} is outside the world")
            if not self.world.tile_at(agent.position).walkable:
                raise ValueError(f"agent {agent.agent_id!r} is on an impassable tile")

        structure_positions = [structure.position for structure in self.structures]
        if len(structure_positions) != len(set(structure_positions)):
            raise ValueError("session must not contain two structures on one tile")
        for structure in self.structures:
            if not self.world.contains(structure.position):
                raise ValueError(f"structure {structure.kind!r} is outside the world")
            if self.world.tile_at(structure.position) is not structure.kind.tile:
                raise ValueError(
                    f"structure {structure.kind!r} does not match the tile at {structure.position}"
                )

        for ground_item in self.ground_items:
            if not self.world.contains(ground_item.position):
                raise ValueError("ground item is outside the world")
