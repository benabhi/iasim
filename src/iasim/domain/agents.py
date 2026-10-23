"""Agent attributes, status, and immutable agent state."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum

from iasim.domain.geometry import Position
from iasim.domain.identifiers import AgentId, validate_agent_id
from iasim.domain.items import (
    BASE_SLOTS,
    Equipment,
    EquipSlot,
    Inventory,
    InventoryError,
    ItemSpec,
    ItemStack,
)

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
    equipment: Equipment = field(default_factory=Equipment)
    status: AgentStatus = AgentStatus.ACTIVE

    def __post_init__(self) -> None:
        validate_agent_id(self.agent_id)
        if not isinstance(self.status, AgentStatus):
            raise ValueError(f"status must be an AgentStatus, got {self.status!r}")
        if not isinstance(self.equipment, Equipment):
            raise ValueError(f"equipment must be an Equipment, got {self.equipment!r}")
        required_slots = BASE_SLOTS + self.equipment.bonus_slots
        if self.inventory.max_slots < required_slots:
            raise ValueError(
                f"inventory has {self.inventory.max_slots} slots, required minimum is "
                f"{required_slots}"
            )
        required_capacity = (
            Inventory.base_capacity_grams(self.attributes.strength)
            + self.equipment.bonus_weight_grams
        )
        if self.inventory.max_weight_grams < required_capacity:
            raise ValueError(f"inventory capacity is below the required {required_capacity} g")
        has_zero_health = self.attributes.health_centi == 0
        if self.status is AgentStatus.DEAD and not has_zero_health:
            raise ValueError("dead agents must have zero health")
        if self.status is not AgentStatus.DEAD and has_zero_health:
            raise ValueError("agents with zero health must have the dead status")

    @property
    def is_alive(self) -> bool:
        """Return whether the agent is not dead."""
        return self.status is not AgentStatus.DEAD

    @property
    def max_slots(self) -> int:
        """Return effective inventory slots including equipment bonuses."""
        return BASE_SLOTS + self.equipment.bonus_slots

    @property
    def carry_capacity_grams(self) -> int:
        """Return effective carrying capacity including equipment bonuses."""
        return (
            Inventory.base_capacity_grams(self.attributes.strength)
            + self.equipment.bonus_weight_grams
        )

    @property
    def weapon_damage(self) -> int:
        """Return the damage of the equipped hand weapon."""
        return self.equipment.weapon_damage

    @property
    def light_radius(self) -> int:
        """Return the light radius of the equipped light source."""
        return self.equipment.light_radius

    @property
    def effective_vision(self) -> int:
        """Return base vision plus equipped light radius."""
        return self.attributes.vision + self.equipment.light_radius

    @property
    def thermal_insulation(self) -> int:
        """Return the insulation from equipped body clothing."""
        return self.equipment.thermal_insulation

    def equip(self, spec: ItemSpec) -> Agent:
        """Equip one unit of ``spec`` from the inventory."""
        if spec.equip_slot is None:
            raise InventoryError(f"item {spec.item_id!r} is not equipable")
        if self.equipment.item(spec.equip_slot) is not None:
            raise InventoryError(f"equipment slot {spec.equip_slot.value!r} is occupied")
        stack = self.inventory.stack_for(spec.item_id)
        if stack is None:
            raise InventoryError(f"item {spec.item_id!r} is not in the inventory")
        if stack.definition != spec.definition:
            raise InventoryError(f"item {spec.item_id!r} does not match the catalog definition")
        new_inventory = self.inventory.remove(spec.item_id, 1)
        new_equipment = self.equipment.equip(spec)
        new_inventory = new_inventory.with_capacity(
            max_slots=BASE_SLOTS + new_equipment.bonus_slots,
            max_weight_grams=(
                Inventory.base_capacity_grams(self.attributes.strength)
                + new_equipment.bonus_weight_grams
            ),
        )
        return replace(self, inventory=new_inventory, equipment=new_equipment)

    def unequip(self, slot: EquipSlot) -> Agent:
        """Move the item in ``slot`` back into the inventory."""
        spec = self.equipment.item(slot)
        if spec is None:
            raise InventoryError(f"equipment slot {slot.value!r} is empty")
        new_equipment = self.equipment.unequip(slot)
        base_inventory = self.inventory.with_capacity(
            max_slots=BASE_SLOTS + new_equipment.bonus_slots,
            max_weight_grams=(
                Inventory.base_capacity_grams(self.attributes.strength)
                + new_equipment.bonus_weight_grams
            ),
        )
        new_inventory = base_inventory.add(ItemStack(spec.definition, 1))
        return replace(self, inventory=new_inventory, equipment=new_equipment)


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
