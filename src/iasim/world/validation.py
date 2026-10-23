"""Validation of generated world layouts against the SRS."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterator

from iasim.domain.geometry import Position
from iasim.domain.tiles import TileType, WorldMap
from iasim.errors import WorldValidationError
from iasim.world.layout import WorldLayout
from iasim.world.rules import (
    FOOD_SOURCES,
    FRESH_WATER_SOURCES,
    MAX_FRESH_WATER_DISTANCE,
    MAX_RESOURCE_DISTANCE,
    MIN_SPAWN_DISTANCE,
    ROCK_SOURCES,
    SPAWN_ALLOWED_TILES,
    WATER_TILES,
    WOOD_SOURCES,
)


def validate_layout(layout: WorldLayout) -> None:
    """Raise :class:`WorldValidationError` when a layout breaks SRS rules."""
    issues: list[str] = []
    world = layout.world
    spawns = layout.spawn_points

    if layout.seed < 0:
        issues.append("seed must be non-negative")
    if not spawns:
        issues.append("no spawn points")

    valid_spawns: list[tuple[int, Position]] = []
    for spawn_index, position in enumerate(spawns):
        if not world.contains(position):
            issues.append(f"spawn {spawn_index} is outside the world")
            continue
        tile = world.tile_at(position)
        if tile not in SPAWN_ALLOWED_TILES:
            issues.append(f"spawn {spawn_index} is on {tile.value}")
            continue
        valid_spawns.append((spawn_index, position))

    if len(set(spawns)) != len(spawns):
        issues.append("spawn points must be distinct")

    for offset, (first_index, first) in enumerate(valid_spawns):
        for second_index, second in valid_spawns[offset + 1 :]:
            distance = manhattan(first, second)
            if distance < MIN_SPAWN_DISTANCE:
                issues.append(
                    f"spawns {first_index} and {second_index} are {distance} cells apart; "
                    f"minimum is {MIN_SPAWN_DISTANCE}"
                )

    if not land_is_connected(world):
        issues.append("land is not fully connected")

    world_tiles = set(world.tiles)
    resource_checks = (
        ("fresh water", FRESH_WATER_SOURCES, MAX_FRESH_WATER_DISTANCE),
        ("food", FOOD_SOURCES, MAX_RESOURCE_DISTANCE),
        ("wood", WOOD_SOURCES, MAX_RESOURCE_DISTANCE),
        ("rock", ROCK_SOURCES, MAX_RESOURCE_DISTANCE),
    )
    for resource_name, sources, limit in resource_checks:
        if not world_tiles.intersection(sources):
            issues.append(f"missing {resource_name} source")
            continue
        distances = resource_distances(world, sources)
        for spawn_index, position in valid_spawns:
            distance = distances[position.y * world.width + position.x]
            if distance <= limit:
                continue
            if distance > len(world.tiles):
                issues.append(f"spawn {spawn_index} cannot reach {resource_name}")
            else:
                issues.append(
                    f"spawn {spawn_index} is {distance} cells from {resource_name}; "
                    f"maximum is {limit}"
                )

    component = largest_walkable_component(world)
    for spawn_index, position in valid_spawns:
        if not component[position.y * world.width + position.x]:
            issues.append(f"spawn {spawn_index} is not connected to the largest walkable component")

    if issues:
        raise WorldValidationError("; ".join(issues))


def manhattan(first: Position, second: Position) -> int:
    """Return the Manhattan distance between two positions."""
    return abs(first.x - second.x) + abs(first.y - second.y)


def largest_walkable_component(world: WorldMap) -> list[bool]:
    """Return a mask of the largest 4-connected walkable component."""
    visited = [False] * len(world.tiles)
    best: list[int] = []
    for start, tile in enumerate(world.tiles):
        if visited[start] or not tile.walkable:
            continue
        component: list[int] = []
        queue = deque([start])
        visited[start] = True
        while queue:
            current = queue.popleft()
            component.append(current)
            y, x = divmod(current, world.width)
            for nx, ny in _neighbours(x, y, world.width, world.height):
                neighbour = ny * world.width + nx
                if not visited[neighbour] and world.tiles[neighbour].walkable:
                    visited[neighbour] = True
                    queue.append(neighbour)
        if len(component) > len(best):
            best = component

    result = [False] * len(world.tiles)
    for index in best:
        result[index] = True
    return result


def land_is_connected(world: WorldMap) -> bool:
    """Return whether every non-water tile belongs to one land component."""
    land = [tile not in WATER_TILES for tile in world.tiles]
    total = sum(land)
    if total == 0:
        return False

    start = next(index for index, is_land in enumerate(land) if is_land)
    visited = [False] * len(world.tiles)
    visited[start] = True
    queue = deque([start])
    reached = 0
    while queue:
        current = queue.popleft()
        reached += 1
        y, x = divmod(current, world.width)
        for nx, ny in _neighbours(x, y, world.width, world.height):
            neighbour = ny * world.width + nx
            if land[neighbour] and not visited[neighbour]:
                visited[neighbour] = True
                queue.append(neighbour)
    return reached == total


def resource_distances(world: WorldMap, sources: frozenset[TileType]) -> list[int]:
    """Return the walkable path distance from every cell to the nearest source."""
    size = len(world.tiles)
    infinity = size + 1
    distances = [infinity] * size
    queue: deque[int] = deque()
    for index, tile in enumerate(world.tiles):
        if tile in sources:
            distances[index] = 0
            queue.append(index)

    while queue:
        current = queue.popleft()
        y, x = divmod(current, world.width)
        for nx, ny in _neighbours(x, y, world.width, world.height):
            neighbour = ny * world.width + nx
            tile = world.tiles[neighbour]
            if distances[neighbour] == infinity and (tile.walkable or tile in sources):
                distances[neighbour] = distances[current] + 1
                queue.append(neighbour)
    return distances


def _neighbours(x: int, y: int, width: int, height: int) -> Iterator[tuple[int, int]]:
    """Yield the in-bounds 4-neighbour coordinates in a fixed order."""
    if x > 0:
        yield x - 1, y
    if x + 1 < width:
        yield x + 1, y
    if y > 0:
        yield x, y - 1
    if y + 1 < height:
        yield x, y + 1
