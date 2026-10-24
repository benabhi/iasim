"""Canonical immutable session state."""

from __future__ import annotations

from dataclasses import dataclass, field

from iasim.domain.agents import Agent
from iasim.domain.alliances import Alliance
from iasim.domain.corpse import Corpse
from iasim.domain.items import GroundItem
from iasim.domain.resources import ResourceNode
from iasim.domain.rng import U64_MASK
from iasim.domain.tiles import WorldMap
from iasim.domain.trades import TradeOffer
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
    resource_nodes: tuple[ResourceNode, ...] = ()
    corpses: tuple[Corpse, ...] = ()
    alliances: tuple[Alliance, ...] = ()
    trades: tuple[TradeOffer, ...] = ()

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

        resource_keys = [(node.position, node.resource_id) for node in self.resource_nodes]
        if len(resource_keys) != len(set(resource_keys)):
            raise ValueError("session must not contain duplicate resource nodes")
        for node in self.resource_nodes:
            if not self.world.contains(node.position):
                raise ValueError(f"resource node {node.resource_id!r} is outside the world")

        corpse_ids = [corpse.corpse_id for corpse in self.corpses]
        if len(corpse_ids) != len(set(corpse_ids)):
            raise ValueError("session must not contain duplicate corpse ids")
        for corpse in self.corpses:
            if not self.world.contains(corpse.position):
                raise ValueError(f"corpse {corpse.corpse_id!r} is outside the world")

        alliance_ids = [alliance.alliance_id for alliance in self.alliances]
        if len(alliance_ids) != len(set(alliance_ids)):
            raise ValueError("session must not contain duplicate alliance ids")
        if alliance_ids != sorted(alliance_ids):
            raise ValueError("session alliances must be sorted by alliance id")

        trade_ids = [trade.trade_id for trade in self.trades]
        if len(trade_ids) != len(set(trade_ids)):
            raise ValueError("session must not contain duplicate trade ids")
        if trade_ids != sorted(trade_ids):
            raise ValueError("session trades must be sorted by trade id")
