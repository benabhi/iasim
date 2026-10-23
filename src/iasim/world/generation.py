"""Deterministic island generation for the 80x40 IASim world."""

from __future__ import annotations

import heapq
from collections import deque
from collections.abc import Iterator

from iasim.domain.geometry import Position
from iasim.domain.rng import U64_MASK, DeterministicRng, roll_d6
from iasim.domain.tiles import TileType, WorldMap
from iasim.errors import WorldGenerationError, WorldValidationError
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
from iasim.world.validation import (
    largest_walkable_component,
    resource_distances,
    validate_layout,
)

WORLD_WIDTH = 80
WORLD_HEIGHT = 40

_LAND_PERCENT = 55
_MIN_LAND_PERCENT = 15
_MAX_ATTEMPTS = 8

_MASK_STAGE = 0x1A2B3C4D5E6F7081
_RELIEF_STAGE = 0x2B3C4D5E6F708192
_MOISTURE_STAGE = 0x3C4D5E6F708192A3
_FEATURES_STAGE = 0x4D5E6F708192A3B4
_BANKS_STAGE = 0x6F708192A3B4C5D6
_RIVER_STAGE = 0x5E6F708192A3B4C5

_REQUIRED_TILES = frozenset(
    {
        TileType.DEEP_WATER,
        TileType.SHALLOW_WATER,
        TileType.FRESH_WATER,
        TileType.SAND,
        TileType.GRASS,
        TileType.TALL_GRASS,
        TileType.TREE,
        TileType.PALM,
        TileType.BUSH,
        TileType.ROCK,
        TileType.ROCKY_GROUND,
        TileType.CLAY,
    }
)


def generate_world(seed: int) -> WorldMap:
    """Generate the validated deterministic 80x40 island for ``seed``."""
    return generate_layout(seed, agent_count=8).world


def generate_layout(seed: int, agent_count: int = 8) -> WorldLayout:
    """Generate a validated layout with ``agent_count`` spawn points."""
    if seed < 0:
        raise ValueError(f"seed must be non-negative, got {seed}")
    if not 1 <= agent_count <= 8:
        raise ValueError(f"agent_count must be within [1, 8], got {agent_count}")

    last_error = "no valid map was produced"
    for attempt in range(_MAX_ATTEMPTS):
        derived_seed = seed if attempt == 0 else (seed + attempt * 0x9E3779B97F4A7C15) & U64_MASK
        tiles = _generate_once(derived_seed)
        if tiles is None:
            last_error = "generation produced no land"
            continue
        if _land_percent(tiles) < _MIN_LAND_PERCENT:
            last_error = "land share is below the minimum"
            continue
        _ensure_required_tiles(tiles)
        if not _REQUIRED_TILES.issubset(tiles):
            last_error = "required tile types are missing"
            continue

        world = WorldMap(width=WORLD_WIDTH, height=WORLD_HEIGHT, tiles=tuple(tiles))
        spawn_points = _select_spawn_points(world, agent_count)
        if len(spawn_points) != agent_count:
            last_error = f"only {len(spawn_points)} spawn points could be placed"
            continue

        layout = WorldLayout(seed=seed, world=world, spawn_points=spawn_points)
        try:
            validate_layout(layout)
        except WorldValidationError as exc:
            last_error = str(exc)
            continue
        return layout

    raise WorldGenerationError(f"could not generate a valid island for seed {seed}: {last_error}")


def _select_spawn_points(world: WorldMap, agent_count: int) -> tuple[Position, ...]:
    """Select separated, connected, resource-reachable spawn points."""
    component = largest_walkable_component(world)
    water_distances = resource_distances(world, FRESH_WATER_SOURCES)
    food_distances = resource_distances(world, FOOD_SOURCES)
    wood_distances = resource_distances(world, WOOD_SOURCES)
    rock_distances = resource_distances(world, ROCK_SOURCES)

    candidates = [
        index
        for index, tile in enumerate(world.tiles)
        if component[index]
        and tile in SPAWN_ALLOWED_TILES
        and water_distances[index] <= MAX_FRESH_WATER_DISTANCE
        and food_distances[index] <= MAX_RESOURCE_DISTANCE
        and wood_distances[index] <= MAX_RESOURCE_DISTANCE
        and rock_distances[index] <= MAX_RESOURCE_DISTANCE
    ]
    if not candidates:
        return ()

    center_x = world.width // 2
    center_y = world.height // 2
    start = min(
        candidates,
        key=lambda index: (
            abs(index % world.width - center_x) + abs(index // world.width - center_y),
            index,
        ),
    )
    selected = [start]
    while len(selected) < agent_count:
        best = -1
        best_distance = -1
        for index in candidates:
            if index in selected:
                continue
            nearest = min(
                abs(index % world.width - other % world.width)
                + abs(index // world.width - other // world.width)
                for other in selected
            )
            if nearest > best_distance or (nearest == best_distance and (best < 0 or index < best)):
                best = index
                best_distance = nearest
        if best < 0 or best_distance < MIN_SPAWN_DISTANCE:
            break
        selected.append(best)

    return tuple(Position(index % world.width, index // world.width) for index in selected)


def _generate_once(seed: int) -> list[TileType] | None:
    """Run all generation stages once with a derived seed."""
    mask_rng = DeterministicRng(seed ^ _MASK_STAGE)
    relief_rng = DeterministicRng(seed ^ _RELIEF_STAGE)
    moisture_rng = DeterministicRng(seed ^ _MOISTURE_STAGE)
    feature_rng = DeterministicRng(seed ^ _FEATURES_STAGE)
    banks_rng = DeterministicRng(seed ^ _BANKS_STAGE)

    noise = _smooth(_random_field(mask_rng), passes=5)
    falloff = _radial_falloff()
    scores = [
        (noise[index] * 3 + falloff[index] * 2) // 5 for index in range(WORLD_WIDTH * WORLD_HEIGHT)
    ]

    mask = _largest_component(_land_mask(scores))
    if not any(mask):
        return None

    tiles = [TileType.GRASS if land else TileType.DEEP_WATER for land in mask]
    _force_border(tiles)
    _add_shallow_water(tiles)
    _add_beaches(tiles)
    _force_border(tiles)

    _carve_river(tiles, scores, seed)
    if not any(tile is TileType.FRESH_WATER for tile in tiles):
        return None
    _add_river_banks(tiles, banks_rng)

    relief = _smooth(_random_field(relief_rng), passes=4)
    _add_relief(tiles, relief)

    moisture = _smooth(_random_field(moisture_rng), passes=5)
    _add_biomes(tiles, moisture, feature_rng)

    _force_border(tiles)
    return tiles


def _random_field(rng: DeterministicRng) -> list[int]:
    """Return one random value in [0, 1000] per map cell."""
    return [rng.randint(0, 1000) for _ in range(WORLD_WIDTH * WORLD_HEIGHT)]


def _smooth(values: list[int], passes: int) -> list[int]:
    """Apply a deterministic 3x3 box blur several times."""
    current = values
    for _ in range(passes):
        next_values = [0] * (WORLD_WIDTH * WORLD_HEIGHT)
        for y in range(WORLD_HEIGHT):
            row = y * WORLD_WIDTH
            for x in range(WORLD_WIDTH):
                total = 0
                count = 0
                for ny in range(max(0, y - 1), min(WORLD_HEIGHT, y + 2)):
                    neighbour_row = ny * WORLD_WIDTH
                    for nx in range(max(0, x - 1), min(WORLD_WIDTH, x + 2)):
                        total += current[neighbour_row + nx]
                        count += 1
                next_values[row + x] = total // count
        current = next_values
    return current


def _radial_falloff() -> list[int]:
    """Return an integer island falloff score from the map centre."""
    center_x2 = WORLD_WIDTH - 1
    center_y2 = WORLD_HEIGHT - 1
    max_dx = WORLD_WIDTH - 1
    max_dy = WORLD_HEIGHT - 1
    falloff = [0] * (WORLD_WIDTH * WORLD_HEIGHT)
    for y in range(WORLD_HEIGHT):
        dy = abs(2 * y - center_y2)
        dy_term = (dy * dy * 1000) // (max_dy * max_dy)
        row = y * WORLD_WIDTH
        for x in range(WORLD_WIDTH):
            dx = abs(2 * x - center_x2)
            dx_term = (dx * dx * 1000) // (max_dx * max_dx)
            falloff[row + x] = max(0, 1000 - dx_term - dy_term)
    return falloff


def _land_mask(scores: list[int]) -> list[bool]:
    """Select the highest-scoring interior cells up to the land target."""
    interior = [
        scores[y * WORLD_WIDTH + x]
        for y in range(1, WORLD_HEIGHT - 1)
        for x in range(1, WORLD_WIDTH - 1)
    ]
    cut = int(len(interior) * (100 - _LAND_PERCENT) / 100)
    threshold = sorted(interior)[cut]
    mask = [False] * (WORLD_WIDTH * WORLD_HEIGHT)
    for y in range(1, WORLD_HEIGHT - 1):
        for x in range(1, WORLD_WIDTH - 1):
            index = y * WORLD_WIDTH + x
            mask[index] = scores[index] >= threshold
    return mask


def _largest_component(mask: list[bool]) -> list[bool]:
    """Return only the largest 4-connected land component."""
    visited = [False] * (WORLD_WIDTH * WORLD_HEIGHT)
    best: list[int] = []
    for y in range(WORLD_HEIGHT):
        for x in range(WORLD_WIDTH):
            start = y * WORLD_WIDTH + x
            if not mask[start] or visited[start]:
                continue
            component: list[int] = []
            queue = deque([start])
            visited[start] = True
            while queue:
                current = queue.popleft()
                component.append(current)
                cy, cx = divmod(current, WORLD_WIDTH)
                for nx, ny in _neighbours(cx, cy):
                    neighbour = ny * WORLD_WIDTH + nx
                    if mask[neighbour] and not visited[neighbour]:
                        visited[neighbour] = True
                        queue.append(neighbour)
            if len(component) > len(best):
                best = component

    result = [False] * (WORLD_WIDTH * WORLD_HEIGHT)
    for index in best:
        result[index] = True
    return result


def _add_shallow_water(tiles: list[TileType]) -> None:
    """Create a one-cell shallow shelf around the land."""
    deep_water = [index for index, tile in enumerate(tiles) if tile is TileType.DEEP_WATER]
    for index in deep_water:
        y, x = divmod(index, WORLD_WIDTH)
        if any(tiles[ny * WORLD_WIDTH + nx] is TileType.GRASS for nx, ny in _neighbours(x, y)):
            tiles[index] = TileType.SHALLOW_WATER


def _add_beaches(tiles: list[TileType]) -> None:
    """Turn the outer land ring into sand."""
    grass = [index for index, tile in enumerate(tiles) if tile is TileType.GRASS]
    for index in grass:
        y, x = divmod(index, WORLD_WIDTH)
        if any(
            tiles[ny * WORLD_WIDTH + nx] in {TileType.DEEP_WATER, TileType.SHALLOW_WATER}
            for nx, ny in _neighbours(x, y)
        ):
            tiles[index] = TileType.SAND


def _carve_river(tiles: list[TileType], scores: list[int], seed: int) -> None:
    """Carve a fresh-water river from an inland high point to the sea."""
    distance = _distance_to_water(tiles)
    candidates = [
        index for index, tile in enumerate(tiles) if tile is TileType.GRASS and distance[index] >= 8
    ]
    if not candidates:
        candidates = [index for index, tile in enumerate(tiles) if tile is TileType.GRASS]
    if not candidates:
        return

    source = min(candidates, key=lambda index: (-scores[index], index))
    size = WORLD_WIDTH * WORLD_HEIGHT
    infinity = 1 << 60
    distances = [infinity] * size
    previous = [-1] * size
    distances[source] = 0
    heap: list[tuple[int, int]] = [(0, source)]
    target = -1

    while heap:
        cost, current = heapq.heappop(heap)
        if cost != distances[current]:
            continue
        if tiles[current] in WATER_TILES:
            target = current
            break
        y, x = divmod(current, WORLD_WIDTH)
        for nx, ny in _neighbours(x, y):
            neighbour = ny * WORLD_WIDTH + nx
            if tiles[neighbour] in WATER_TILES:
                step = 0
            else:
                jitter = roll_d6(seed ^ _RIVER_STAGE, neighbour, 0)
                step = 1 + (1000 - scores[neighbour]) // 150 + jitter
            new_cost = cost + step
            if new_cost < distances[neighbour]:
                distances[neighbour] = new_cost
                previous[neighbour] = current
                heapq.heappush(heap, (new_cost, neighbour))

    if target < 0:
        return

    path: list[int] = []
    current = target
    while current != -1:
        path.append(current)
        if current == source:
            break
        current = previous[current]
    path.reverse()

    for index in path:
        if tiles[index] not in WATER_TILES:
            tiles[index] = TileType.FRESH_WATER


def _add_river_banks(tiles: list[TileType], rng: DeterministicRng) -> None:
    """Add reeds and clay on the grass next to the river."""
    river = [index for index, tile in enumerate(tiles) if tile is TileType.FRESH_WATER]
    for index in river:
        y, x = divmod(index, WORLD_WIDTH)
        for nx, ny in _neighbours(x, y):
            neighbour = ny * WORLD_WIDTH + nx
            if tiles[neighbour] is not TileType.GRASS:
                continue
            if rng.chance(0.20):
                tiles[neighbour] = TileType.CLAY
            elif rng.chance(0.40):
                tiles[neighbour] = TileType.TALL_GRASS


def _add_relief(tiles: list[TileType], relief: list[int]) -> None:
    """Place rocky ground and impassable rock clusters by relief."""
    grass = [index for index, tile in enumerate(tiles) if tile is TileType.GRASS]
    if not grass:
        return
    ranked = sorted(grass, key=lambda index: (relief[index], index))
    rock_count = max(1, len(ranked) * 8 // 100)
    rocky_count = max(1, len(ranked) * 10 // 100)

    for index in ranked[-rock_count:]:
        tiles[index] = TileType.ROCK
    for index in ranked[-(rock_count + rocky_count) : -rock_count]:
        if tiles[index] is TileType.GRASS:
            tiles[index] = TileType.ROCKY_GROUND


def _add_biomes(tiles: list[TileType], moisture: list[int], rng: DeterministicRng) -> None:
    """Place forest, prairie, reeds, bushes and palms."""
    grass = [index for index, tile in enumerate(tiles) if tile is TileType.GRASS]
    if grass:
        forest_threshold = _percentile([moisture[index] for index in grass], 70)
        tall_threshold = _percentile([moisture[index] for index in grass], 80)
        for index in grass:
            if moisture[index] >= forest_threshold and rng.chance(0.55):
                tiles[index] = TileType.TREE
            elif moisture[index] >= tall_threshold:
                tiles[index] = TileType.TALL_GRASS
            elif rng.chance(0.08):
                tiles[index] = TileType.BUSH

    sand = [index for index, tile in enumerate(tiles) if tile is TileType.SAND]
    for index in sand:
        y, x = divmod(index, WORLD_WIDTH)
        if any(
            tiles[ny * WORLD_WIDTH + nx] in {TileType.DEEP_WATER, TileType.SHALLOW_WATER}
            for nx, ny in _neighbours(x, y)
        ) and rng.chance(0.18):
            tiles[index] = TileType.PALM


def _ensure_required_tiles(tiles: list[TileType]) -> None:
    """Guarantee at least one tile of every required natural type."""
    _ensure_tile(tiles, TileType.TREE, _indices_of(tiles, TileType.GRASS))
    _ensure_tile(tiles, TileType.TALL_GRASS, _indices_of(tiles, TileType.GRASS))
    _ensure_tile(tiles, TileType.BUSH, _indices_of(tiles, TileType.GRASS))
    _ensure_tile(tiles, TileType.PALM, _indices_of(tiles, TileType.SAND))
    _ensure_tile(tiles, TileType.ROCK, _indices_of(tiles, TileType.GRASS))
    _ensure_tile(tiles, TileType.ROCKY_GROUND, _indices_of(tiles, TileType.GRASS))
    clay_candidates = [
        index
        for index in _indices_of(tiles, TileType.GRASS)
        if _adjacent_to(tiles, index, TileType.FRESH_WATER)
    ]
    _ensure_tile(tiles, TileType.CLAY, clay_candidates)


def _ensure_tile(tiles: list[TileType], target: TileType, candidates: list[int]) -> None:
    """Replace the first candidate with ``target`` when it is missing."""
    if any(tile is target for tile in tiles):
        return
    for index in candidates:
        if tiles[index] is not target:
            tiles[index] = target
            return


def _indices_of(tiles: list[TileType], tile_type: TileType) -> list[int]:
    """Return the indices currently holding ``tile_type``."""
    return [index for index, tile in enumerate(tiles) if tile is tile_type]


def _adjacent_to(tiles: list[TileType], index: int, target: TileType) -> bool:
    """Return whether a cell touches a cell of ``target`` type."""
    y, x = divmod(index, WORLD_WIDTH)
    return any(tiles[ny * WORLD_WIDTH + nx] is target for nx, ny in _neighbours(x, y))


def _distance_to_water(tiles: list[TileType]) -> list[int]:
    """Return the 4-neighbour distance from every cell to the nearest water."""
    size = WORLD_WIDTH * WORLD_HEIGHT
    distance = [size] * size
    queue: deque[int] = deque()
    for index, tile in enumerate(tiles):
        if tile in WATER_TILES:
            distance[index] = 0
            queue.append(index)
    while queue:
        current = queue.popleft()
        y, x = divmod(current, WORLD_WIDTH)
        for nx, ny in _neighbours(x, y):
            neighbour = ny * WORLD_WIDTH + nx
            if distance[neighbour] > distance[current] + 1:
                distance[neighbour] = distance[current] + 1
                queue.append(neighbour)
    return distance


def _land_percent(tiles: list[TileType]) -> int:
    """Return the percentage of cells that are not water."""
    land = sum(1 for tile in tiles if tile not in WATER_TILES)
    return land * 100 // (WORLD_WIDTH * WORLD_HEIGHT)


def _percentile(values: list[int], percent: int) -> int:
    """Return the value at the given percentile."""
    ordered = sorted(values)
    index = min(len(ordered) - 1, len(ordered) * percent // 100)
    return ordered[index]


def _force_border(tiles: list[TileType]) -> None:
    """Keep the entire outer ring as deep water."""
    for x in range(WORLD_WIDTH):
        tiles[x] = TileType.DEEP_WATER
        tiles[(WORLD_HEIGHT - 1) * WORLD_WIDTH + x] = TileType.DEEP_WATER
    for y in range(WORLD_HEIGHT):
        tiles[y * WORLD_WIDTH] = TileType.DEEP_WATER
        tiles[y * WORLD_WIDTH + WORLD_WIDTH - 1] = TileType.DEEP_WATER


def _neighbours(x: int, y: int) -> Iterator[tuple[int, int]]:
    """Yield the in-bounds 4-neighbour coordinates in a fixed order."""
    if x > 0:
        yield x - 1, y
    if x + 1 < WORLD_WIDTH:
        yield x + 1, y
    if y > 0:
        yield x, y - 1
    if y + 1 < WORLD_HEIGHT:
        yield x, y + 1
