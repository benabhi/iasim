"""Tests for inventory capacity, stacks, transfers, and equipment."""

from __future__ import annotations

import unittest

from iasim.crafting import load_catalog
from iasim.domain.agents import Agent
from iasim.domain.geometry import Position
from iasim.domain.identifiers import AgentId
from iasim.domain.items import (
    BASE_SLOTS,
    EquipSlot,
    Inventory,
    InventoryError,
    ItemStack,
)


class InventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_catalog()

    def _item(self, item_id: str):
        return self.catalog.item(item_id).definition

    def test_add_merges_stacks_and_remove_updates_quantity(self) -> None:
        wood = self._item("wood")
        inventory = Inventory.for_strength(5)

        inventory = inventory.add_quantity(wood, 3).add_quantity(wood, 2)

        self.assertEqual(inventory.stack_for("wood").quantity, 5)
        self.assertEqual(inventory.total_weight_grams, 5_000)

        inventory = inventory.remove("wood", 2)
        self.assertEqual(inventory.stack_for("wood").quantity, 3)

        inventory, stack = inventory.remove_stack("wood")
        self.assertTrue(inventory.is_empty)
        self.assertEqual(stack.quantity, 3)

    def test_slots_and_weight_are_enforced_without_mutating_the_original(self) -> None:
        inventory = Inventory.for_strength(5)
        original = inventory
        for item_id in list(self.catalog.items)[:BASE_SLOTS]:
            inventory = inventory.add(ItemStack(self._item(item_id), 1))

        self.assertEqual(len(inventory.stacks), BASE_SLOTS)
        with self.assertRaises(InventoryError):
            inventory.add(ItemStack(self._item("backpack"), 1))

        with self.assertRaises(InventoryError):
            original.add_quantity(self._item("wood"), 21)
        self.assertTrue(original.is_empty)

    def test_remove_and_transfer_validate_quantities(self) -> None:
        berry = self._item("berry")
        source = Inventory.for_strength(5).add_quantity(berry, 3)
        target = Inventory.for_strength(5)

        with self.assertRaises(InventoryError):
            source.remove("berry", 4)
        with self.assertRaises(InventoryError):
            source.remove("wood", 1)

        new_source, new_target = source.transfer_to(target, "berry", 2)

        self.assertEqual(new_source.stack_for("berry").quantity, 1)
        self.assertEqual(new_target.stack_for("berry").quantity, 2)
        self.assertEqual(source.stack_for("berry").quantity, 3)

    def test_waterskin_charges_survive_transfers_and_stack_removal(self) -> None:
        waterskin = ItemStack(self._item("waterskin"), 1, charges=2)
        source = Inventory.for_strength(5).add(waterskin)
        target = Inventory.for_strength(5)

        new_source, new_target = source.transfer_to(target, "waterskin", 1)

        self.assertTrue(new_source.is_empty)
        self.assertEqual(new_target.stack_for("waterskin").charges, 2)
        _, removed = new_target.remove_stack("waterskin")
        self.assertEqual(removed.charges, 2)

    def test_waterskin_charges_are_capped_by_the_catalog_capacity(self) -> None:
        definition = self._item("waterskin")
        self.assertEqual(definition.water_capacity, 3)

        full = ItemStack(definition, 1, charges=3)
        self.assertEqual(full.charges, 3)
        with self.assertRaises(ValueError):
            ItemStack(definition, 1, charges=4)

    def test_stackable_items_cannot_carry_charges(self) -> None:
        with self.assertRaises(ValueError):
            ItemStack(self._item("berry"), 1, charges=1)

    def test_failed_transfer_leaves_both_sides_unchanged(self) -> None:
        wood = self._item("wood")
        source = Inventory.for_strength(5).add_quantity(wood, 2)
        full_target = Inventory.for_strength(5)
        for item_id in (
            "fiber",
            "stone",
            "berry",
            "coconut",
            "reed",
            "clay",
            "sharp_stone",
            "stone_spear",
            "torch",
            "bandage",
        ):
            full_target = full_target.add(ItemStack(self._item(item_id), 1))

        with self.assertRaises(InventoryError):
            source.transfer_to(full_target, "wood", 1)

        self.assertEqual(source.stack_for("wood").quantity, 2)
        self.assertEqual(len(full_target.stacks), BASE_SLOTS)

    def test_capacity_can_be_resized_but_cannot_drop_current_weight(self) -> None:
        inventory = Inventory.for_strength(5).add_quantity(self._item("wood"), 15)

        with self.assertRaises(InventoryError):
            inventory.with_capacity(max_weight_grams=10_000)

        resized = inventory.with_capacity(max_slots=12, max_weight_grams=25_000)
        self.assertEqual(resized.max_slots, 12)
        self.assertEqual(resized.max_weight_grams, 25_000)
        self.assertEqual(resized.stack_for("wood").quantity, 15)


class EquipmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_catalog()

    def _agent(self, *item_ids: str) -> Agent:
        inventory = Inventory.for_strength(5)
        for item_id in item_ids:
            inventory = inventory.add(ItemStack(self.catalog.item(item_id).definition, 1))
        return Agent(AgentId("ag_01"), Position(1, 1), inventory=inventory)

    def test_weapon_equipment_updates_damage_and_returns_to_inventory(self) -> None:
        agent = self._agent("stone_spear")

        equipped = agent.equip(self.catalog.item("stone_spear"))

        self.assertEqual(equipped.weapon_damage, 7)
        self.assertEqual(equipped.equipment.item(EquipSlot.HAND).item_id, "stone_spear")
        self.assertIsNone(equipped.inventory.stack_for("stone_spear"))
        self.assertEqual(agent.weapon_damage, 0)

        unequipped = equipped.unequip(EquipSlot.HAND)

        self.assertEqual(unequipped.weapon_damage, 0)
        self.assertEqual(unequipped.inventory.stack_for("stone_spear").quantity, 1)
        self.assertIsNone(unequipped.equipment.item(EquipSlot.HAND))

    def test_backpack_updates_capacity_and_unequip_restores_it(self) -> None:
        agent = self._agent("backpack")

        equipped = agent.equip(self.catalog.item("backpack"))

        self.assertEqual(equipped.max_slots, BASE_SLOTS + 6)
        self.assertEqual(equipped.carry_capacity_grams, 30_000)
        self.assertEqual(equipped.inventory.max_slots, BASE_SLOTS + 6)
        self.assertEqual(equipped.inventory.max_weight_grams, 30_000)

        unequipped = equipped.unequip(EquipSlot.BACK)

        self.assertEqual(unequipped.max_slots, BASE_SLOTS)
        self.assertEqual(unequipped.carry_capacity_grams, 20_000)
        self.assertEqual(unequipped.inventory.max_weight_grams, 20_000)
        self.assertEqual(unequipped.inventory.stack_for("backpack").quantity, 1)

    def test_light_and_clothing_update_derived_stats(self) -> None:
        agent = self._agent("torch", "fiber_clothes")

        with_torch = agent.equip(self.catalog.item("torch"))
        with_clothes = with_torch.equip(self.catalog.item("fiber_clothes"))

        self.assertEqual(with_torch.light_radius, 3)
        self.assertEqual(with_torch.effective_vision, 11)
        self.assertEqual(with_clothes.thermal_insulation, 1)
        self.assertEqual(with_clothes.equipment.item(EquipSlot.LIGHT).item_id, "torch")
        self.assertEqual(with_clothes.equipment.item(EquipSlot.BODY).item_id, "fiber_clothes")

    def test_equip_rejects_missing_non_equipable_and_occupied_slots(self) -> None:
        agent = self._agent("stone_spear", "stone_axe", "berry")

        with self.assertRaises(InventoryError):
            self._agent().equip(self.catalog.item("backpack"))
        with self.assertRaises(InventoryError):
            agent.equip(self.catalog.item("berry"))

        armed = agent.equip(self.catalog.item("stone_spear"))
        with self.assertRaises(InventoryError):
            armed.equip(self.catalog.item("stone_axe"))

    def test_unequip_backpack_fails_if_inventory_would_exceed_base_capacity(self) -> None:
        agent = self._agent("backpack")
        equipped = agent.equip(self.catalog.item("backpack"))
        loaded = equipped.inventory.add_quantity(self.catalog.item("wood").definition, 25)
        loaded_agent = Agent(
            equipped.agent_id,
            equipped.position,
            attributes=equipped.attributes,
            inventory=loaded,
            equipment=equipped.equipment,
        )

        with self.assertRaises(InventoryError):
            loaded_agent.unequip(EquipSlot.BACK)

        self.assertIsNotNone(loaded_agent.equipment.item(EquipSlot.BACK))
        self.assertEqual(loaded_agent.inventory.stack_for("wood").quantity, 25)


if __name__ == "__main__":
    unittest.main()
