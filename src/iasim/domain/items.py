"""Item definitions, stacks, inventories, and items on the ground."""

from __future__ import annotations

from dataclasses import dataclass

from iasim.domain.geometry import Position
from iasim.domain.identifiers import ItemId, validate_item_id

BASE_SLOTS = 10
BASE_CAPACITY_GRAMS = 10_000
CAPACITY_GRAMS_PER_STRENGTH = 2_000


@dataclass(frozen=True, slots=True)
class ItemDefinition:
    """Static properties of an item type from the catalog."""

    item_id: ItemId
    unit_weight_grams: int
    stackable: bool
    max_stack: int = 1

    def __post_init__(self) -> None:
        validate_item_id(self.item_id)
        if self.unit_weight_grams < 0:
            raise ValueError(
                f"unit_weight_grams must be non-negative, got {self.unit_weight_grams}"
            )
        if self.max_stack < 1:
            raise ValueError(f"max_stack must be at least 1, got {self.max_stack}")
        if not self.stackable and self.max_stack != 1:
            raise ValueError("non-stackable items must have max_stack=1")


@dataclass(frozen=True, slots=True)
class ItemStack:
    """A quantity of one item type."""

    definition: ItemDefinition
    quantity: int

    def __post_init__(self) -> None:
        if self.quantity < 1:
            raise ValueError(f"quantity must be at least 1, got {self.quantity}")
        if not self.definition.stackable and self.quantity != 1:
            raise ValueError("non-stackable items cannot have quantity greater than 1")
        if self.quantity > self.definition.max_stack:
            raise ValueError(
                f"quantity {self.quantity} exceeds max_stack {self.definition.max_stack}"
            )

    @property
    def total_weight_grams(self) -> int:
        """Return the stack weight in grams."""
        return self.definition.unit_weight_grams * self.quantity


@dataclass(frozen=True, slots=True)
class Inventory:
    """Immutable inventory with slot and weight capacity."""

    stacks: tuple[ItemStack, ...] = ()
    max_slots: int = BASE_SLOTS
    max_weight_grams: int = BASE_CAPACITY_GRAMS + CAPACITY_GRAMS_PER_STRENGTH * 5

    def __post_init__(self) -> None:
        if self.max_slots < 1:
            raise ValueError(f"max_slots must be at least 1, got {self.max_slots}")
        if self.max_weight_grams < 0:
            raise ValueError(f"max_weight_grams must be non-negative, got {self.max_weight_grams}")
        if len(self.stacks) > self.max_slots:
            raise ValueError(
                f"inventory uses {len(self.stacks)} slots, maximum is {self.max_slots}"
            )
        item_ids = [stack.definition.item_id for stack in self.stacks]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("inventory must not contain duplicate item ids")
        if self.total_weight_grams > self.max_weight_grams:
            raise ValueError(
                f"inventory weighs {self.total_weight_grams} g, "
                f"maximum is {self.max_weight_grams} g"
            )

    @property
    def total_weight_grams(self) -> int:
        """Return the combined weight of all stacks in grams."""
        return sum(stack.total_weight_grams for stack in self.stacks)

    @property
    def is_empty(self) -> bool:
        """Return whether the inventory has no stacks."""
        return not self.stacks

    @staticmethod
    def base_capacity_grams(strength: int) -> int:
        """Return the SRS base carrying capacity for a strength value."""
        if not 1 <= strength <= 10:
            raise ValueError(f"strength must be within [1, 10], got {strength}")
        return BASE_CAPACITY_GRAMS + CAPACITY_GRAMS_PER_STRENGTH * strength

    @classmethod
    def for_strength(
        cls,
        strength: int,
        *,
        bonus_slots: int = 0,
        bonus_weight_grams: int = 0,
    ) -> Inventory:
        """Create an empty inventory with the SRS capacity for ``strength``."""
        if bonus_slots < 0:
            raise ValueError(f"bonus_slots must be non-negative, got {bonus_slots}")
        if bonus_weight_grams < 0:
            raise ValueError(f"bonus_weight_grams must be non-negative, got {bonus_weight_grams}")
        return cls(
            max_slots=BASE_SLOTS + bonus_slots,
            max_weight_grams=cls.base_capacity_grams(strength) + bonus_weight_grams,
        )


@dataclass(frozen=True, slots=True)
class GroundItem:
    """An item stack lying on the world map."""

    position: Position
    stack: ItemStack
