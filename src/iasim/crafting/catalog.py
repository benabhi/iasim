"""Validated MVP item, resource, and recipe catalog."""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

from iasim.domain.identifiers import ItemId, validate_item_id
from iasim.domain.items import EquipSlot, ItemDefinition, ItemKind, ItemSpec
from iasim.domain.tiles import TileType
from iasim.domain.world import StructureKind

DEFAULT_CATALOG_PATH = Path(__file__).with_name("data") / "catalog.toml"
_CATALOG_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class CatalogError(ValueError):
    """The catalog data is missing, malformed, or internally inconsistent."""


@dataclass(frozen=True, slots=True)
class ResourceSpec:
    """A gatherable resource node attached to one map tile type."""

    resource_id: str
    tile: TileType
    item_id: ItemId
    quantity: int
    required_tool: ItemId | None = None
    regenerates: bool = False

    def __post_init__(self) -> None:
        _validate_catalog_id(self.resource_id, "resource id")
        if not isinstance(self.tile, TileType):
            raise ValueError(f"tile must be a TileType, got {self.tile!r}")
        if not isinstance(self.item_id, str):
            raise ValueError(f"item_id must be a string, got {self.item_id!r}")
        if self.quantity < 1:
            raise ValueError(f"quantity must be positive, got {self.quantity}")
        if self.required_tool is not None and not isinstance(self.required_tool, str):
            raise ValueError(f"required_tool must be a string, got {self.required_tool!r}")


@dataclass(frozen=True, slots=True)
class RecipeSpec:
    """One deterministic crafting recipe."""

    recipe_id: str
    level: int
    station: StructureKind | None
    ingredients: tuple[tuple[ItemId, int], ...]
    output: ItemId
    output_quantity: int = 1

    def __post_init__(self) -> None:
        _validate_catalog_id(self.recipe_id, "recipe id")
        if self.level not in (1, 2):
            raise ValueError(f"level must be 1 or 2, got {self.level}")
        if self.level == 1 and self.station is not None:
            raise ValueError("level-1 recipes must not require a station")
        if self.level == 2 and self.station is not StructureKind.WORKBENCH:
            raise ValueError("level-2 recipes require a workbench")
        if not self.ingredients:
            raise ValueError("ingredients must not be empty")
        ingredient_ids = [item_id for item_id, _ in self.ingredients]
        if len(ingredient_ids) != len(set(ingredient_ids)):
            raise ValueError("ingredients must not contain duplicate item ids")
        for item_id, quantity in self.ingredients:
            if not isinstance(item_id, str) or not item_id:
                raise ValueError(f"ingredient id must be a non-empty string, got {item_id!r}")
            if quantity < 1:
                raise ValueError(f"ingredient quantity must be positive, got {quantity}")
        if not isinstance(self.output, str) or not self.output:
            raise ValueError(f"output must be a non-empty string, got {self.output!r}")
        if self.output_quantity < 1:
            raise ValueError(f"output_quantity must be positive, got {self.output_quantity}")


@dataclass(frozen=True, slots=True)
class Catalog:
    """Immutable catalog loaded from one validated TOML source."""

    items: Mapping[str, ItemSpec]
    resources: Mapping[str, ResourceSpec]
    recipes: Mapping[str, RecipeSpec]
    source: Path

    def item(self, item_id: str) -> ItemSpec:
        """Return the item spec for ``item_id``."""
        try:
            return self.items[item_id]
        except KeyError:
            raise CatalogError(f"unknown item id {item_id!r}") from None

    def resource(self, resource_id: str) -> ResourceSpec:
        """Return the resource spec for ``resource_id``."""
        try:
            return self.resources[resource_id]
        except KeyError:
            raise CatalogError(f"unknown resource id {resource_id!r}") from None

    def recipe(self, recipe_id: str) -> RecipeSpec:
        """Return the recipe spec for ``recipe_id``."""
        try:
            return self.recipes[recipe_id]
        except KeyError:
            raise CatalogError(f"unknown recipe id {recipe_id!r}") from None

    def resources_for_tile(self, tile: TileType) -> tuple[ResourceSpec, ...]:
        """Return all resource nodes attached to ``tile`` in catalog order."""
        return tuple(resource for resource in self.resources.values() if resource.tile is tile)


def load_catalog(path: str | Path | None = None) -> Catalog:
    """Load and validate a catalog, defaulting to the packaged MVP data."""
    source = Path(path) if path is not None else DEFAULT_CATALOG_PATH
    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise CatalogError(f"cannot read catalog {source}: {exc}") from exc
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise CatalogError(f"{source}: invalid TOML: {exc}") from exc

    items = _load_items(data.get("items"), source)
    resources = _load_resources(data.get("resources"), source)
    recipes = _load_recipes(data.get("recipes"), source)

    for resource in resources.values():
        if resource.item_id not in items:
            raise CatalogError(
                f"{source}: resource {resource.resource_id!r} references unknown item "
                f"{resource.item_id!r}"
            )
        if resource.required_tool is not None:
            tool = items.get(resource.required_tool)
            if tool is None:
                raise CatalogError(
                    f"{source}: resource {resource.resource_id!r} requires unknown tool "
                    f"{resource.required_tool!r}"
                )
            if not tool.tool_tags:
                raise CatalogError(
                    f"{source}: resource {resource.resource_id!r} requires "
                    f"{resource.required_tool!r}, which is not a tool"
                )

    for recipe in recipes.values():
        for item_id, _ in recipe.ingredients:
            if item_id not in items:
                raise CatalogError(
                    f"{source}: recipe {recipe.recipe_id!r} references unknown ingredient "
                    f"{item_id!r}"
                )
        if recipe.output not in items:
            raise CatalogError(
                f"{source}: recipe {recipe.recipe_id!r} references unknown output {recipe.output!r}"
            )

    return Catalog(
        items=MappingProxyType(dict(items)),
        resources=MappingProxyType(dict(resources)),
        recipes=MappingProxyType(dict(recipes)),
        source=source,
    )


def _load_items(raw: Any, source: Path) -> dict[str, ItemSpec]:
    entries = _require_entries(raw, "items", source)
    items: dict[str, ItemSpec] = {}
    for index, entry in enumerate(entries):
        item = _parse_item(entry, source, index)
        if item.item_id in items:
            raise CatalogError(f"{source}: duplicate item id {item.item_id!r}")
        items[str(item.item_id)] = item
    if not items:
        raise CatalogError(f"{source}: catalog must contain at least one item")
    return items


def _parse_item(entry: Any, source: Path, index: int) -> ItemSpec:
    context = f"items[{index}]"
    data = _require_mapping(entry, source, context)
    item_id = _require_str(data, "id", source, context)
    _validate_item_id(item_id, source, context)
    name = _require_str(data, "name", source, context)
    weight = _require_int(data, "weight_g", source, context)
    stackable = _require_bool(data, "stackable", source, context)
    max_stack = _optional_int(data, "max_stack", 1, source, context)
    try:
        definition = ItemDefinition(ItemId(item_id), weight, stackable, max_stack)
    except ValueError as exc:
        raise CatalogError(f"{source}: {context}: {exc}") from exc

    kind_text = _require_str(data, "kind", source, context)
    try:
        kind = ItemKind(kind_text)
    except ValueError as exc:
        raise CatalogError(f"{source}: {context}: unknown item kind {kind_text!r}") from exc
    equip_text = _optional_str(data, "equip_slot", source, context)
    try:
        equip_slot = EquipSlot(equip_text) if equip_text is not None else None
    except ValueError as exc:
        raise CatalogError(f"{source}: {context}: unknown equipment slot {equip_text!r}") from exc
    structure_text = _optional_str(data, "structure", source, context)
    try:
        structure = StructureKind(structure_text) if structure_text is not None else None
    except ValueError as exc:
        raise CatalogError(f"{source}: {context}: unknown structure {structure_text!r}") from exc

    try:
        return ItemSpec(
            definition=definition,
            name=name,
            kind=kind,
            equip_slot=equip_slot,
            weapon_damage=_optional_int(data, "weapon_damage", 0, source, context),
            tool_tags=_optional_str_tuple(data, "tool_tags", source, context),
            hunger_restore=_optional_int(data, "hunger_restore", 0, source, context),
            thirst_restore=_optional_int(data, "thirst_restore", 0, source, context),
            water_charges=_optional_int(data, "water_charges", 0, source, context),
            bonus_slots=_optional_int(data, "bonus_slots", 0, source, context),
            bonus_weight_grams=_optional_int(data, "bonus_weight_g", 0, source, context),
            light_radius=_optional_int(data, "light_radius", 0, source, context),
            duration_ticks=_optional_int(data, "duration_ticks", 0, source, context),
            stops_bleeding=_optional_bool(data, "stops_bleeding", False, source, context),
            thermal_insulation=_optional_int(data, "thermal_insulation", 0, source, context),
            structure=structure,
        )
    except ValueError as exc:
        raise CatalogError(f"{source}: {context}: {exc}") from exc


def _load_resources(raw: Any, source: Path) -> dict[str, ResourceSpec]:
    entries = _require_entries(raw, "resources", source)
    resources: dict[str, ResourceSpec] = {}
    for index, entry in enumerate(entries):
        data = _require_mapping(entry, source, f"resources[{index}]")
        context = f"resources[{index}]"
        resource_id = _require_str(data, "id", source, context)
        tile_text = _require_str(data, "tile", source, context)
        try:
            tile = TileType(tile_text)
        except ValueError as exc:
            raise CatalogError(f"{source}: {context}: unknown tile {tile_text!r}") from exc
        item_text = _require_str(data, "item", source, context)
        _validate_item_id(item_text, source, context)
        required_tool_text = _optional_str(data, "required_tool", source, context)
        if required_tool_text is not None:
            _validate_item_id(required_tool_text, source, context)
        try:
            resource = ResourceSpec(
                resource_id=resource_id,
                tile=tile,
                item_id=ItemId(item_text),
                quantity=_require_int(data, "quantity", source, context),
                required_tool=(
                    ItemId(required_tool_text) if required_tool_text is not None else None
                ),
                regenerates=_optional_bool(data, "regenerates", False, source, context),
            )
        except ValueError as exc:
            raise CatalogError(f"{source}: {context}: {exc}") from exc
        if resource.resource_id in resources:
            raise CatalogError(f"{source}: duplicate resource id {resource.resource_id!r}")
        resources[resource.resource_id] = resource
    if not resources:
        raise CatalogError(f"{source}: catalog must contain at least one resource")
    return resources


def _load_recipes(raw: Any, source: Path) -> dict[str, RecipeSpec]:
    entries = _require_entries(raw, "recipes", source)
    recipes: dict[str, RecipeSpec] = {}
    for index, entry in enumerate(entries):
        data = _require_mapping(entry, source, f"recipes[{index}]")
        context = f"recipes[{index}]"
        recipe_id = _require_str(data, "id", source, context)
        station_text = _optional_str(data, "station", source, context)
        try:
            station = StructureKind(station_text) if station_text is not None else None
        except ValueError as exc:
            raise CatalogError(f"{source}: {context}: unknown station {station_text!r}") from exc
        ingredients = _parse_ingredients(data.get("ingredients"), source, context)
        output = _require_str(data, "output", source, context)
        _validate_item_id(output, source, context)
        try:
            recipe = RecipeSpec(
                recipe_id=recipe_id,
                level=_require_int(data, "level", source, context),
                station=station,
                ingredients=ingredients,
                output=ItemId(output),
                output_quantity=_optional_int(data, "output_quantity", 1, source, context),
            )
        except ValueError as exc:
            raise CatalogError(f"{source}: {context}: {exc}") from exc
        if recipe.recipe_id in recipes:
            raise CatalogError(f"{source}: duplicate recipe id {recipe.recipe_id!r}")
        recipes[recipe.recipe_id] = recipe
    if not recipes:
        raise CatalogError(f"{source}: catalog must contain at least one recipe")
    return recipes


def _parse_ingredients(raw: Any, source: Path, context: str) -> tuple[tuple[ItemId, int], ...]:
    data = _require_mapping(raw, source, f"{context}.ingredients")
    parsed: list[tuple[ItemId, int]] = []
    for item_id, quantity in data.items():
        if not isinstance(item_id, str):
            raise CatalogError(f"{source}: {context}: ingredient id must be a string")
        _validate_item_id(item_id, source, context)
        if type(quantity) is not int or quantity < 1:
            raise CatalogError(
                f"{source}: {context}: ingredient {item_id!r} must have a positive integer quantity"
            )
        parsed.append((ItemId(item_id), quantity))
    if not parsed:
        raise CatalogError(f"{source}: {context}: ingredients must not be empty")
    return tuple(sorted(parsed, key=lambda ingredient: str(ingredient[0])))


def _require_entries(raw: Any, section: str, source: Path) -> list[Any]:
    if not isinstance(raw, list):
        raise CatalogError(f"{source}: {section} must be an array of tables")
    return raw


def _require_mapping(raw: Any, source: Path, context: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise CatalogError(f"{source}: {context} must be a table")
    return raw


def _require_str(data: dict[str, Any], key: str, source: Path, context: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise CatalogError(f"{source}: {context}.{key} must be a non-empty string")
    return value


def _optional_str(data: dict[str, Any], key: str, source: Path, context: str) -> str | None:
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise CatalogError(f"{source}: {context}.{key} must be a non-empty string")
    return value


def _require_int(data: dict[str, Any], key: str, source: Path, context: str) -> int:
    value = data.get(key)
    if type(value) is not int:
        raise CatalogError(f"{source}: {context}.{key} must be an integer")
    return value


def _optional_int(data: dict[str, Any], key: str, default: int, source: Path, context: str) -> int:
    if key not in data:
        return default
    return _require_int(data, key, source, context)


def _require_bool(data: dict[str, Any], key: str, source: Path, context: str) -> bool:
    value = data.get(key)
    if not isinstance(value, bool):
        raise CatalogError(f"{source}: {context}.{key} must be a boolean")
    return value


def _optional_bool(
    data: dict[str, Any], key: str, default: bool, source: Path, context: str
) -> bool:
    if key not in data:
        return default
    return _require_bool(data, key, source, context)


def _optional_str_tuple(
    data: dict[str, Any], key: str, source: Path, context: str
) -> tuple[str, ...]:
    value = data.get(key, [])
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise CatalogError(f"{source}: {context}.{key} must be an array of strings")
    return tuple(value)


def _validate_item_id(item_id: str, source: Path, context: str) -> None:
    try:
        validate_item_id(item_id)
    except ValueError as exc:
        raise CatalogError(f"{source}: {context}: {exc}") from exc


def _validate_catalog_id(value: str, label: str) -> None:
    if _CATALOG_ID_PATTERN.fullmatch(value) is None:
        raise ValueError(f"invalid {label}: {value!r}; expected lowercase snake_case")
