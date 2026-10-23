"""Item definitions, stacks, inventories, and items on the ground."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from iasim.domain.geometry import Position
from iasim.domain.identifiers import ItemId, validate_item_id
from iasim.domain.world import StructureKind

BASE_SLOTS = 10
BASE_CAPACITY_GRAMS = 10_000
CAPACITY_GRAMS_PER_STRENGTH = 2_000


class InventoryError(ValueError):
    """An inventory or equipment mutation would violate capacity or ownership."""


class ItemKind(StrEnum):
    """Functional categories used by the MVP catalog."""

    RESOURCE = "resource"
    FOOD = "food"
    COMPONENT = "component"
    WEAPON = "weapon"
    TOOL = "tool"
    LIGHT = "light"
    CONSUMABLE = "consumable"
    CONTAINER = "container"
    EQUIPMENT = "equipment"
    KIT = "kit"


class EquipSlot(StrEnum):
    """Equipment slots from the SRS inventory contract."""

    HAND = "hand"
    BODY = "body"
    BACK = "back"
    LIGHT = "light"


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
    charges: int = 0

    def __post_init__(self) -> None:
        if self.quantity < 1:
            raise ValueError(f"quantity must be at least 1, got {self.quantity}")
        if not self.definition.stackable and self.quantity != 1:
            raise ValueError("non-stackable items cannot have quantity greater than 1")
        if self.quantity > self.definition.max_stack:
            raise ValueError(
                f"quantity {self.quantity} exceeds max_stack {self.definition.max_stack}"
            )
        if type(self.charges) is not int:
            raise ValueError(f"charges must be an integer, got {self.charges!r}")
        if self.charges < 0:
            raise ValueError(f"charges must be non-negative, got {self.charges}")
        if self.definition.stackable and self.charges:
            raise ValueError("stackable items cannot carry per-instance charges")

    @property
    def total_weight_grams(self) -> int:
        """Return the stack weight in grams."""
        return self.definition.unit_weight_grams * self.quantity

    def with_charges(self, charges: int) -> ItemStack:
        """Return this stack with a new per-instance charge count."""
        return replace(self, charges=charges)


@dataclass(frozen=True, slots=True)
class ItemSpec:
    """Catalog metadata layered over the immutable item definition."""

    definition: ItemDefinition
    name: str
    kind: ItemKind
    equip_slot: EquipSlot | None = None
    weapon_damage: int = 0
    tool_tags: tuple[str, ...] = ()
    hunger_restore: int = 0
    thirst_restore: int = 0
    water_charges: int = 0
    bonus_slots: int = 0
    bonus_weight_grams: int = 0
    light_radius: int = 0
    duration_ticks: int = 0
    stops_bleeding: bool = False
    thermal_insulation: int = 0
    structure: StructureKind | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.definition, ItemDefinition):
            raise ValueError("definition must be an ItemDefinition")
        if not self.name.strip():
            raise ValueError("name must not be empty")
        if not isinstance(self.kind, ItemKind):
            raise ValueError(f"kind must be an ItemKind, got {self.kind!r}")
        if self.equip_slot is not None and not isinstance(self.equip_slot, EquipSlot):
            raise ValueError(f"equip_slot must be an EquipSlot, got {self.equip_slot!r}")
        for field_name, value in (
            ("weapon_damage", self.weapon_damage),
            ("hunger_restore", self.hunger_restore),
            ("thirst_restore", self.thirst_restore),
            ("water_charges", self.water_charges),
            ("bonus_slots", self.bonus_slots),
            ("bonus_weight_grams", self.bonus_weight_grams),
            ("light_radius", self.light_radius),
            ("duration_ticks", self.duration_ticks),
            ("thermal_insulation", self.thermal_insulation),
        ):
            if value < 0:
                raise ValueError(f"{field_name} must be non-negative, got {value}")
        if self.tool_tags != tuple(dict.fromkeys(self.tool_tags)):
            raise ValueError("tool_tags must not contain duplicates")
        if any(not tag for tag in self.tool_tags):
            raise ValueError("tool_tags must not contain empty values")
        if self.kind is ItemKind.KIT and self.structure is None:
            raise ValueError("kit items must declare a structure")
        if self.structure is not None and not isinstance(self.structure, StructureKind):
            raise ValueError(f"structure must be a StructureKind, got {self.structure!r}")

    @property
    def item_id(self) -> ItemId:
        """Return the stable item id."""
        return self.definition.item_id


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

    def stack_for(self, item_id: str) -> ItemStack | None:
        """Return the stack for ``item_id``, if present."""
        return next(
            (stack for stack in self.stacks if stack.definition.item_id == item_id),
            None,
        )

    def with_capacity(
        self,
        *,
        max_slots: int | None = None,
        max_weight_grams: int | None = None,
    ) -> Inventory:
        """Return this inventory with adjusted slot and/or weight limits."""
        try:
            return replace(
                self,
                max_slots=self.max_slots if max_slots is None else max_slots,
                max_weight_grams=(
                    self.max_weight_grams if max_weight_grams is None else max_weight_grams
                ),
            )
        except ValueError as exc:
            raise InventoryError(str(exc)) from exc

    def add(self, stack: ItemStack) -> Inventory:
        """Add one stack, merging into an existing stack when possible."""
        existing = self.stack_for(stack.definition.item_id)
        if existing is not None:
            if existing.definition != stack.definition:
                raise InventoryError(
                    f"item {stack.definition.item_id!r} already has a different definition"
                )
            if existing.charges != stack.charges:
                raise InventoryError(
                    f"cannot merge {stack.definition.item_id!r} stacks with different charges"
                )
            quantity = existing.quantity + stack.quantity
            if quantity > existing.definition.max_stack:
                raise InventoryError(
                    f"stack for {stack.definition.item_id!r} would exceed "
                    f"max_stack {existing.definition.max_stack}"
                )
            merged = ItemStack(existing.definition, quantity, charges=existing.charges)
            new_stacks = tuple(
                merged if current is existing else current for current in self.stacks
            )
        else:
            if len(self.stacks) >= self.max_slots:
                raise InventoryError(
                    f"inventory is full: {len(self.stacks)}/{self.max_slots} slots"
                )
            new_stacks = (*self.stacks, stack)
        try:
            return replace(self, stacks=new_stacks)
        except ValueError as exc:
            raise InventoryError(str(exc)) from exc

    def add_quantity(self, definition: ItemDefinition, quantity: int) -> Inventory:
        """Create one stack and add it to the inventory."""
        try:
            stack = ItemStack(definition, quantity)
        except ValueError as exc:
            raise InventoryError(str(exc)) from exc
        return self.add(stack)

    def remove(self, item_id: str, quantity: int) -> Inventory:
        """Remove ``quantity`` units of ``item_id`` from the inventory."""
        if quantity < 1:
            raise InventoryError(f"quantity must be positive, got {quantity}")
        existing = self.stack_for(item_id)
        if existing is None:
            raise InventoryError(f"item {item_id!r} is not in the inventory")
        if quantity > existing.quantity:
            raise InventoryError(
                f"cannot remove {quantity} of {item_id!r}; only {existing.quantity} available"
            )
        if quantity == existing.quantity:
            new_stacks = tuple(stack for stack in self.stacks if stack is not existing)
        else:
            replacement = ItemStack(
                existing.definition,
                existing.quantity - quantity,
                charges=existing.charges,
            )
            new_stacks = tuple(replacement if stack is existing else stack for stack in self.stacks)
        return replace(self, stacks=new_stacks)

    def remove_stack(self, item_id: str) -> tuple[Inventory, ItemStack]:
        """Remove and return the full stack for ``item_id``."""
        existing = self.stack_for(item_id)
        if existing is None:
            raise InventoryError(f"item {item_id!r} is not in the inventory")
        return self.remove(item_id, existing.quantity), existing

    def transfer_to(
        self,
        target: Inventory,
        item_id: str,
        quantity: int,
    ) -> tuple[Inventory, Inventory]:
        """Atomically move items to ``target``; neither side changes on failure."""
        existing = self.stack_for(item_id)
        if existing is None:
            raise InventoryError(f"item {item_id!r} is not in the inventory")
        if quantity < 1 or quantity > existing.quantity:
            raise InventoryError(
                f"cannot transfer {quantity} of {item_id!r}; only {existing.quantity} available"
            )
        source = self.remove(item_id, quantity)
        destination = target.add(ItemStack(existing.definition, quantity, charges=existing.charges))
        return source, destination

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
class Equipment:
    """Immutable equipped item slots with derived stat accessors."""

    items: tuple[tuple[EquipSlot, ItemSpec], ...] = ()

    def __post_init__(self) -> None:
        slots = [slot for slot, _ in self.items]
        if len(slots) != len(set(slots)):
            raise ValueError("equipment must not contain duplicate slots")
        for slot, spec in self.items:
            if not isinstance(slot, EquipSlot):
                raise ValueError(f"slot must be an EquipSlot, got {slot!r}")
            if not isinstance(spec, ItemSpec):
                raise ValueError(f"equipment item must be an ItemSpec, got {spec!r}")
            if spec.equip_slot is not slot:
                raise ValueError(
                    f"item {spec.item_id!r} belongs in {spec.equip_slot!r}, not {slot!r}"
                )

    def item(self, slot: EquipSlot) -> ItemSpec | None:
        """Return the item equipped in ``slot``, if any."""
        return next((spec for current, spec in self.items if current is slot), None)

    def equip(self, spec: ItemSpec) -> Equipment:
        """Return equipment with ``spec`` in its declared slot."""
        if spec.equip_slot is None:
            raise InventoryError(f"item {spec.item_id!r} is not equipable")
        if self.item(spec.equip_slot) is not None:
            raise InventoryError(f"equipment slot {spec.equip_slot.value!r} is occupied")
        return replace(self, items=(*self.items, (spec.equip_slot, spec)))

    def unequip(self, slot: EquipSlot) -> Equipment:
        """Return equipment without the item in ``slot``."""
        if self.item(slot) is None:
            raise InventoryError(f"equipment slot {slot.value!r} is empty")
        return replace(
            self,
            items=tuple((current, spec) for current, spec in self.items if current is not slot),
        )

    @property
    def bonus_slots(self) -> int:
        """Return the total inventory slot bonus from equipped items."""
        return sum(spec.bonus_slots for _, spec in self.items)

    @property
    def bonus_weight_grams(self) -> int:
        """Return the total carrying capacity bonus from equipped items."""
        return sum(spec.bonus_weight_grams for _, spec in self.items)

    @property
    def weapon_damage(self) -> int:
        """Return the damage of the equipped hand weapon."""
        hand = self.item(EquipSlot.HAND)
        return hand.weapon_damage if hand is not None else 0

    @property
    def light_radius(self) -> int:
        """Return the light radius of the equipped light source."""
        light = self.item(EquipSlot.LIGHT)
        return light.light_radius if light is not None else 0

    @property
    def thermal_insulation(self) -> int:
        """Return the thermal insulation of equipped body clothing."""
        body = self.item(EquipSlot.BODY)
        return body.thermal_insulation if body is not None else 0

    @property
    def water_charges(self) -> int:
        """Return the total water charges of equipped containers."""
        return sum(spec.water_charges for _, spec in self.items)


@dataclass(frozen=True, slots=True)
class GroundItem:
    """An item stack lying on the world map."""

    position: Position
    stack: ItemStack
