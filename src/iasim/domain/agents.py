"""Agent attributes, status, and immutable agent state."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from iasim.domain.geometry import Position
from iasim.domain.identifiers import AgentId, validate_agent_id
from iasim.domain.items import BASE_SLOTS, Inventory

_CENTI = 100


def _require_range(name: str, value: int, minimum: int, maximum: int) -> None:
    """Reject a value outside the inclusive integer range."""
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be within [{minimum}, {maximum}], got {value}")


@dataclass(frozen=True, slots=True)
class AgentAttributes:
    """Agent attributes stored in deterministic integer units.

    Continuous values use hundredths as described in SRS section 3.5.2.
    """

    health_centi: int = 100 * _CENTI
    hunger_centi: int = 15 * _CENTI
    thirst_centi: int = 15 * _CENTI
    energy_centi: int = 80 * _CENTI
    wetness_centi: int = 0
    body_temperature_centi: int = 37 * _CENTI
    vision: int = 8
    strength: int = 5
    dexterity: int = 5
    endurance: int = 5

    def __post_init__(self) -> None:
        _require_range("health_centi", self.health_centi, 0, 100 * _CENTI)
        _require_range("hunger_centi", self.hunger_centi, 0, 100 * _CENTI)
        _require_range("thirst_centi", self.thirst_centi, 0, 100 * _CENTI)
        _require_range("energy_centi", self.energy_centi, 0, 100 * _CENTI)
        _require_range("wetness_centi", self.wetness_centi, 0, 100 * _CENTI)
        _require_range(
            "body_temperature_centi", self.body_temperature_centi, 34 * _CENTI, 42 * _CENTI
        )
        _require_range("vision", self.vision, 3, 12)
        _require_range("strength", self.strength, 1, 10)
        _require_range("dexterity", self.dexterity, 1, 10)
        _require_range("endurance", self.endurance, 1, 10)

    @property
    def health(self) -> float:
        """Return health in whole units."""
        return self.health_centi / _CENTI

    @property
    def hunger(self) -> float:
        """Return hunger in whole units."""
        return self.hunger_centi / _CENTI

    @property
    def thirst(self) -> float:
        """Return thirst in whole units."""
        return self.thirst_centi / _CENTI

    @property
    def energy(self) -> float:
        """Return energy in whole units."""
        return self.energy_centi / _CENTI

    @property
    def wetness(self) -> float:
        """Return wetness in whole units."""
        return self.wetness_centi / _CENTI

    @property
    def body_temperature_c(self) -> float:
        """Return body temperature in degrees Celsius."""
        return self.body_temperature_centi / _CENTI


class AgentStatus(StrEnum):
    """Lifecycle states from the SRS turn and timeout rules."""

    ACTIVE = "active"
    ABSENT = "absent"
    SLEEPING = "sleeping"
    DEAD = "dead"


def _default_inventory() -> Inventory:
    """Return the default inventory for the default strength of five."""
    return Inventory.for_strength(5)


@dataclass(frozen=True, slots=True)
class Agent:
    """Immutable agent state at a point in time."""

    agent_id: AgentId
    position: Position
    attributes: AgentAttributes = field(default_factory=AgentAttributes)
    inventory: Inventory = field(default_factory=_default_inventory)
    status: AgentStatus = AgentStatus.ACTIVE

    def __post_init__(self) -> None:
        validate_agent_id(self.agent_id)
        if not isinstance(self.status, AgentStatus):
            raise ValueError(f"status must be an AgentStatus, got {self.status!r}")
        if self.inventory.max_slots < BASE_SLOTS:
            raise ValueError(
                f"inventory has {self.inventory.max_slots} slots, base minimum is {BASE_SLOTS}"
            )
        required_capacity = Inventory.base_capacity_grams(self.attributes.strength)
        if self.inventory.max_weight_grams < required_capacity:
            raise ValueError(
                f"inventory capacity is below the strength-based minimum of {required_capacity} g"
            )
        has_zero_health = self.attributes.health_centi == 0
        if self.status is AgentStatus.DEAD and not has_zero_health:
            raise ValueError("dead agents must have zero health")
        if self.status is not AgentStatus.DEAD and has_zero_health:
            raise ValueError("agents with zero health must have the dead status")

    @property
    def is_alive(self) -> bool:
        """Return whether the agent is not dead."""
        return self.status is not AgentStatus.DEAD


@dataclass(frozen=True, slots=True)
class AgentProfile:
    """Starting attributes and inventory for one agent slot."""

    attributes: AgentAttributes = field(default_factory=AgentAttributes)
    inventory: Inventory | None = None

    def build(
        self,
        agent_id: AgentId,
        position: Position,
        status: AgentStatus = AgentStatus.ACTIVE,
    ) -> Agent:
        """Build an agent from this profile."""
        inventory = (
            self.inventory
            if self.inventory is not None
            else Inventory.for_strength(self.attributes.strength)
        )
        return Agent(
            agent_id,
            position,
            attributes=self.attributes,
            inventory=inventory,
            status=status,
        )
