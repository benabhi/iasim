"""Canonical gatherable resource nodes and their regeneration schedule."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from iasim.domain.geometry import Position
from iasim.domain.tiles import TileType, WorldMap

if TYPE_CHECKING:
    from iasim.crafting.catalog import Catalog

RESOURCE_REGENERATION_TICKS = 288


@dataclass(frozen=True, slots=True)
class ResourceNode:
    """One gatherable node at a world position and catalog resource id."""

    position: Position
    resource_id: str
    remaining: int
    capacity: int
    regrow_at_tick: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.position, Position):
            raise ValueError(f"position must be a Position, got {self.position!r}")
        if not self.resource_id or not self.resource_id.strip():
            raise ValueError("resource_id must not be empty")
        if type(self.capacity) is not int or self.capacity < 1:
            raise ValueError(f"capacity must be a positive integer, got {self.capacity!r}")
        if type(self.remaining) is not int or not 0 <= self.remaining <= self.capacity:
            raise ValueError(
                f"remaining must be within [0, {self.capacity}], got {self.remaining!r}"
            )
        if self.regrow_at_tick is not None:
            if type(self.regrow_at_tick) is not int or self.regrow_at_tick < 0:
                raise ValueError(
                    f"regrow_at_tick must be a non-negative integer or None, "
                    f"got {self.regrow_at_tick!r}"
                )
            if self.remaining != 0:
                raise ValueError("regrow_at_tick is only valid for depleted nodes")

    @property
    def depleted(self) -> bool:
        """Return whether the node has no harvest remaining."""
        return self.remaining == 0


def initial_resource_nodes(world: WorldMap, catalog: Catalog) -> tuple[ResourceNode, ...]:
    """Create one full node per catalog resource attached to a world tile."""
    nodes: list[ResourceNode] = []
    for y in range(world.height):
        for x in range(world.width):
            position = Position(x, y)
            for resource in catalog.resources_for_tile(world.tile_at(position)):
                nodes.append(
                    ResourceNode(
                        position=position,
                        resource_id=resource.resource_id,
                        remaining=resource.quantity,
                        capacity=resource.quantity,
                    )
                )
    return tuple(nodes)


def node_for(
    nodes: tuple[ResourceNode, ...],
    position: Position,
    resource_id: str,
) -> ResourceNode | None:
    """Return the node matching ``position`` and ``resource_id``, if present."""
    return next(
        (node for node in nodes if node.position == position and node.resource_id == resource_id),
        None,
    )


def available_resource_ids(
    nodes: tuple[ResourceNode, ...],
    position: Position,
    tile: TileType,
    catalog: Catalog,
) -> tuple[str, ...]:
    """Return the catalog resources still harvestable at ``position``."""
    node_ids = {
        node.resource_id for node in nodes if node.position == position and not node.depleted
    }
    return tuple(
        resource.resource_id
        for resource in catalog.resources_for_tile(tile)
        if resource.resource_id in node_ids
    )


def advance_resource_nodes(
    nodes: tuple[ResourceNode, ...],
    *,
    tick: int,
) -> tuple[ResourceNode, ...]:
    """Replenish nodes whose deterministic regrowth tick has arrived."""
    if tick < 0:
        raise ValueError(f"tick must be non-negative, got {tick}")
    changed = False
    advanced: list[ResourceNode] = []
    for node in nodes:
        if node.depleted and node.regrow_at_tick is not None and node.regrow_at_tick <= tick:
            advanced.append(replace(node, remaining=node.capacity, regrow_at_tick=None))
            changed = True
        else:
            advanced.append(node)
    return tuple(advanced) if changed else nodes


def deplete_node(
    node: ResourceNode,
    *,
    tick: int,
    regenerates: bool,
) -> ResourceNode:
    """Remove all remaining harvest from a node and schedule regrowth if allowed."""
    if not regenerates:
        return replace(node, remaining=0, regrow_at_tick=None)
    return replace(
        node,
        remaining=0,
        regrow_at_tick=tick + RESOURCE_REGENERATION_TICKS,
    )
