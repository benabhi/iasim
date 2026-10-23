"""Climate effects on vision, body temperature, and wetness."""

from __future__ import annotations

from dataclasses import replace

from iasim.domain.agents import Agent
from iasim.domain.clock import SimulationClock
from iasim.domain.geometry import Position
from iasim.domain.session import SessionState
from iasim.domain.tiles import TileType
from iasim.domain.weather import BASE_TEMPERATURE_CENTI, WeatherState
from iasim.domain.world import Structure, StructureKind

BODY_COMFORT_CENTI = 37 * 100
BODY_MIN_CENTI = 34 * 100
BODY_MAX_CENTI = 42 * 100
BODY_STEP_CENTI = 20
WET_THRESHOLD_CENTI = 60 * 100
WET_COOLING_PER_100_CENTI = 1
SHELTER_WARMTH_CENTI = 150
FIRE_WARMTH_CENTI = 250
SHELTER_DRY_CENTI = 200
FIRE_DRY_CENTI = 200
WIND_COOLING_CENTI_PER_POINT = 15
WIND_VISION_THRESHOLD = 6
WIND_VISION_FACTOR = 0.9
FIRE_LIGHT_RADIUS = 5
FIRE_HEAT_RADIUS = 2


def effective_vision(
    agent: Agent,
    clock: SimulationClock,
    weather: WeatherState,
    structures: tuple[Structure, ...],
) -> int:
    """Return light- and weather-modified vision for an agent.

    This is the numeric vision budget; shadowcasting and occlusion belong to
    the FOV task.
    """
    wind_factor = WIND_VISION_FACTOR if weather.wind >= WIND_VISION_THRESHOLD else 1.0
    base = agent.attributes.vision * clock.light_factor * weather.visibility_factor * wind_factor
    bonus = agent.equipment.light_radius
    if _near_lit_fire(structures, agent.position, FIRE_LIGHT_RADIUS):
        bonus = max(bonus, FIRE_LIGHT_RADIUS)
    return max(0, int(base + bonus + 0.5))


def apply_climate_tick(
    state: SessionState,
    clock: SimulationClock,
) -> SessionState:
    """Dry sheltered/warm agents and move body temperature toward its target."""
    agents: list[Agent] = []
    for agent in state.agents:
        if not agent.is_alive:
            agents.append(agent)
            continue
        wetness = _mitigated_wetness(state, agent)
        target = _body_temperature_target(state, agent, wetness)
        current = agent.attributes.body_temperature_centi
        if current < target:
            current = min(target, current + BODY_STEP_CENTI)
        elif current > target:
            current = max(target, current - BODY_STEP_CENTI)
        attributes = replace(
            agent.attributes,
            wetness_centi=wetness,
            body_temperature_centi=current,
        )
        agents.append(replace(agent, attributes=attributes))
    return replace(state, agents=tuple(agents))


def _body_temperature_target(
    state: SessionState,
    agent: Agent,
    wetness_centi: int,
) -> int:
    ambient_offset = state.weather.ambient_temperature_centi - BASE_TEMPERATURE_CENTI
    wet_cooling = max(0, wetness_centi - WET_THRESHOLD_CENTI) // 100 * WET_COOLING_PER_100_CENTI
    sheltered = _on_shelter(state, agent.position)
    wind_cooling = 0 if sheltered else state.weather.wind * WIND_COOLING_CENTI_PER_POINT
    shelter = SHELTER_WARMTH_CENTI if sheltered else 0
    fire = (
        FIRE_WARMTH_CENTI
        if _near_lit_fire(
            state.structures,
            agent.position,
            FIRE_HEAT_RADIUS,
        )
        else 0
    )
    target = (
        BODY_COMFORT_CENTI
        + ambient_offset
        - wet_cooling
        - wind_cooling
        + agent.thermal_insulation * 100
        + shelter
        + fire
    )
    return max(BODY_MIN_CENTI, min(BODY_MAX_CENTI, target))


def _mitigated_wetness(state: SessionState, agent: Agent) -> int:
    dry = 0
    if _on_shelter(state, agent.position):
        dry += SHELTER_DRY_CENTI
    if _near_lit_fire(state.structures, agent.position, FIRE_HEAT_RADIUS):
        dry += FIRE_DRY_CENTI
    return max(0, agent.attributes.wetness_centi - dry)


def _on_shelter(state: SessionState, position: Position) -> bool:
    return state.world.tile_at(position) is TileType.SHELTER


def _near_lit_fire(
    structures: tuple[Structure, ...],
    position: Position,
    radius: int,
) -> bool:
    return any(
        structure.kind is StructureKind.FIRE
        and structure.lit
        and max(
            abs(structure.position.x - position.x),
            abs(structure.position.y - position.y),
        )
        <= radius
        for structure in structures
    )
