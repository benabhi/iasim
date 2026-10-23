"""Permanent death records and lootable corpses."""

from __future__ import annotations

from dataclasses import dataclass

from iasim.domain.agents import Agent
from iasim.domain.geometry import Position
from iasim.domain.identifiers import AgentId
from iasim.domain.items import Equipment, Inventory


@dataclass(frozen=True, slots=True)
class Corpse:
    """The inventory, equipment, and death record left by one agent."""

    corpse_id: str
    agent_id: AgentId
    position: Position
    inventory: Inventory
    equipment: Equipment
    death_tick: int
    cause: str
    killer_id: AgentId | None = None

    def __post_init__(self) -> None:
        if not self.corpse_id or not self.corpse_id.strip():
            raise ValueError("corpse_id must not be empty")
        if self.death_tick < 0:
            raise ValueError("death_tick must be non-negative")
        if not self.cause or not self.cause.strip():
            raise ValueError("death cause must not be empty")

    @classmethod
    def from_agent(
        cls,
        agent: Agent,
        *,
        tick: int,
        cause: str,
        killer_id: AgentId | None = None,
    ) -> Corpse:
        """Build a corpse from an agent, preserving inventory and equipment."""
        return cls(
            corpse_id=f"corpse_{agent.agent_id}",
            agent_id=agent.agent_id,
            position=agent.position,
            inventory=agent.inventory,
            equipment=agent.equipment,
            death_tick=tick,
            cause=cause,
            killer_id=killer_id,
        )

    @property
    def has_items(self) -> bool:
        """Return whether the corpse still has lootable inventory or equipment."""
        return bool(self.inventory.stacks or self.equipment.items)

    def as_observation(self) -> dict[str, object]:
        """Return a perception-safe corpse entity payload."""
        return {
            "type": "corpse",
            "corpse_id": self.corpse_id,
            "agent_id": self.agent_id,
            "death_tick": self.death_tick,
            "cause": self.cause,
            "killer_id": self.killer_id,
            "lootable": self.has_items,
        }
