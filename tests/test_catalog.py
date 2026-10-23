"""Tests for the validated MVP item, resource, and recipe catalog."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from iasim.crafting import CatalogError, load_catalog
from iasim.domain.tiles import TileType
from iasim.domain.world import StructureKind

VALID_CATALOG = """
[[items]]
id = "wood"
name = "Madera"
weight_g = 1000
stackable = true
max_stack = 99
kind = "resource"

[[resources]]
id = "tree_branches"
tile = "tree"
item = "wood"
quantity = 1

[[recipes]]
id = "wood_kit"
level = 1
ingredients = { wood = 1 }
output = "wood"
"""


class CatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = load_catalog()

    def test_default_catalog_contains_mvp_content(self) -> None:
        self.assertEqual(len(self.catalog.items), 19)
        self.assertEqual(len(self.catalog.resources), 11)
        self.assertEqual(len(self.catalog.recipes), 12)
        self.assertEqual(self.catalog.item("berry").hunger_restore, 15)
        self.assertEqual(self.catalog.item("stone_axe").tool_tags, ("axe",))
        self.assertEqual(self.catalog.item("backpack").bonus_slots, 6)
        self.assertEqual(self.catalog.item("backpack").bonus_weight_grams, 10_000)
        self.assertIs(self.catalog.item("camp_kit").structure, StructureKind.FIRE)

    def test_every_recipe_has_valid_station_ingredients_and_output(self) -> None:
        for recipe in self.catalog.recipes.values():
            with self.subTest(recipe=recipe.recipe_id):
                if recipe.level == 1:
                    self.assertIsNone(recipe.station)
                else:
                    self.assertIs(recipe.station, StructureKind.WORKBENCH)
                self.assertTrue(recipe.ingredients)
                self.assertEqual(len(recipe.ingredients), len(set(recipe.ingredients)))
                for item_id, quantity in recipe.ingredients:
                    self.assertIn(item_id, self.catalog.items)
                    self.assertGreater(quantity, 0)
                self.assertIn(recipe.output, self.catalog.items)
                self.assertGreater(recipe.output_quantity, 0)

    def test_tool_gates_and_manual_resources(self) -> None:
        self.assertEqual(
            self.catalog.resource("tree_logs").required_tool,
            "stone_axe",
        )
        self.assertEqual(
            self.catalog.resource("rock_face_stone").required_tool,
            "stone_pick",
        )
        for resource_id in ("tree_branches", "rocky_ground_stone", "palm_coconut"):
            with self.subTest(resource=resource_id):
                self.assertIsNone(self.catalog.resource(resource_id).required_tool)

        for resource in self.catalog.resources.values():
            if resource.required_tool is not None:
                self.assertTrue(self.catalog.item(resource.required_tool).tool_tags)

    def test_resources_for_tile_is_stable(self) -> None:
        resources = self.catalog.resources_for_tile(TileType.TALL_GRASS)

        self.assertEqual(
            [resource.resource_id for resource in resources],
            ["tall_grass_fiber", "tall_grass_reed"],
        )

    def test_unknown_lookup_is_clear(self) -> None:
        with self.assertRaises(CatalogError):
            self.catalog.item("missing")
        with self.assertRaises(CatalogError):
            self.catalog.resource("missing")
        with self.assertRaises(CatalogError):
            self.catalog.recipe("missing")

    def test_duplicate_item_ids_are_rejected(self) -> None:
        text = (
            VALID_CATALOG
            + """
[[items]]
id = "wood"
name = "Otra madera"
weight_g = 1000
stackable = true
max_stack = 99
kind = "resource"
"""
        )
        with self.assertRaises(CatalogError) as raised:
            self._load(text)
        self.assertIn("duplicate item id", str(raised.exception))

    def test_duplicate_resource_and_recipe_ids_are_rejected(self) -> None:
        duplicate_resource = (
            VALID_CATALOG
            + """
[[resources]]
id = "tree_branches"
tile = "tree"
item = "wood"
quantity = 1
"""
        )
        duplicate_recipe = (
            VALID_CATALOG
            + """
[[recipes]]
id = "wood_kit"
level = 1
ingredients = { wood = 1 }
output = "wood"
"""
        )
        for text, expected in (
            (duplicate_resource, "duplicate resource id"),
            (duplicate_recipe, "duplicate recipe id"),
        ):
            with self.subTest(expected=expected):
                with self.assertRaises(CatalogError) as raised:
                    self._load(text)
                self.assertIn(expected, str(raised.exception))

    def test_unknown_references_are_rejected(self) -> None:
        cases = (
            (
                VALID_CATALOG.replace('item = "wood"', 'item = "missing"'),
                "unknown item",
            ),
            (
                VALID_CATALOG
                + """
[[resources]]
id = "bad_tool"
tile = "tree"
item = "wood"
quantity = 1
required_tool = "missing_tool"
""",
                "unknown tool",
            ),
            (
                VALID_CATALOG.replace("wood = 1", "missing = 1"),
                "unknown ingredient",
            ),
            (
                VALID_CATALOG.replace('output = "wood"', 'output = "missing"'),
                "unknown output",
            ),
        )
        for text, expected in cases:
            with self.subTest(expected=expected):
                with self.assertRaises(CatalogError) as raised:
                    self._load(text)
                self.assertIn(expected, str(raised.exception))

    def test_a_non_tool_cannot_satisfy_a_tool_gate(self) -> None:
        text = VALID_CATALOG.replace(
            "quantity = 1",
            'quantity = 1\nrequired_tool = "wood"',
        )
        with self.assertRaises(CatalogError) as raised:
            self._load(text)
        self.assertIn("not a tool", str(raised.exception))

    def test_recipe_station_level_is_validated(self) -> None:
        missing_station = VALID_CATALOG.replace("level = 1", "level = 2")
        station_on_level_one = VALID_CATALOG.replace(
            "level = 1",
            'level = 1\nstation = "workbench"',
        )
        for text in (missing_station, station_on_level_one):
            with self.subTest(text=text), self.assertRaises(CatalogError):
                self._load(text)

    def test_invalid_item_definition_is_rejected(self) -> None:
        negative_weight = VALID_CATALOG.replace("weight_g = 1000", "weight_g = -1")
        invalid_stack = VALID_CATALOG.replace("max_stack = 99", "max_stack = 0")
        for text in (negative_weight, invalid_stack):
            with self.subTest(text=text), self.assertRaises(CatalogError):
                self._load(text)

    def test_unknown_tile_and_missing_sections_are_rejected(self) -> None:
        unknown_tile = VALID_CATALOG.replace('tile = "tree"', 'tile = "moon"')
        with self.assertRaises(CatalogError) as raised:
            self._load(unknown_tile)
        self.assertIn("unknown tile", str(raised.exception))

        with self.assertRaises(CatalogError):
            self._load("[[items]]\n")
        with self.assertRaises(CatalogError):
            self._load("[[resources]]\n")

    def _load(self, text: str):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.toml"
            path.write_text(text, encoding="utf-8")
            return load_catalog(path)


if __name__ == "__main__":
    unittest.main()
