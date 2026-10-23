"""Tests for light/weather vision, body temperature, and climate mitigation."""

from __future__ import annotations

import unittest

from iasim.app.session import GameSession
from iasim.crafting import load_catalog
from iasim.domain.agents import Agent, AgentAttributes
from iasim.domain.climate import (
    BODY_MAX_CENTI,
    BODY_MIN_CENTI,
    apply_climate_tick,
    effective_vision,
)
from iasim.domain.clock import SimulationClock
from iasim.domain.geometry import Position
from iasim.domain.identifiers import AgentId
from iasim.domain.items import Inventory, ItemStack
from iasim.domain.session import SessionState
from iasim.domain.tiles import TileType, WorldMap
from iasim.domain.weather import WeatherKind, WeatherState
from iasim.domain.world import Structure, StructureKind
from iasim.world.layout import WorldLayout


def _world(*, shelter: Position | None = None, fire: Position | None = None) -> WorldMap:
    tiles = [TileType.GRASS] * 49
    if shelter is not None:
        tiles[shelter.y * 7 + shelter.x] = TileType.SHELTER
    if fire is not None:
        tiles[fire.y * 7 + fire.x] = TileType.FIRE
    return WorldMap(width=7, height=7, tiles=tuple(tiles))


def _agent(
    *,
    body_temp_centi: int = 3_700,
    wetness_centi: int = 0,
    clothes: bool = False,
    torch: bool = False,
) -> Agent:
    catalog = load_catalog()
    inventory = Inventory.for_strength(5)
    if clothes:
        inventory = inventory.add(ItemStack(catalog.item("fiber_clothes").definition, 1))
    if torch:
        inventory = inventory.add(ItemStack(catalog.item("torch").definition, 1))
    agent = Agent(
        AgentId("ag_01"),
        Position(2, 2),
        attributes=AgentAttributes(
            body_temperature_centi=body_temp_centi,
            wetness_centi=wetness_centi,
        ),
        inventory=inventory,
    )
    if clothes:
        agent = agent.equip(catalog.item("fiber_clothes"))
    if torch:
        agent = agent.equip(catalog.item("torch"))
    return agent


def _state(
    agent: Agent,
    *,
    weather: WeatherState,
    structures: tuple[Structure, ...] = (),
    world: WorldMap | None = None,
) -> SessionState:
    return SessionState(
        seed=42,
        tick=0,
        rng_state=42,
        world=_world() if world is None else world,
        agents=(agent,),
        structures=structures,
        weather=weather,
    )


class VisionTests(unittest.TestCase):
    def test_light_and_weather_modify_vision(self) -> None:
        agent = _agent()
        clear = WeatherState(kind=WeatherKind.CLEAR)
        rain = WeatherState(kind=WeatherKind.RAIN)
        day = SimulationClock()
        day.advance(24)
        night = SimulationClock()
        night.advance(168)

        self.assertEqual(effective_vision(agent, day, clear, ()), 8)
        self.assertEqual(effective_vision(agent, night, clear, ()), 2)
        self.assertEqual(effective_vision(agent, day, rain, ()), 6)
        self.assertEqual(
            effective_vision(
                agent,
                day,
                WeatherState(kind=WeatherKind.STORM),
                (),
            ),
            5,
        )
        self.assertEqual(
            effective_vision(
                agent,
                day,
                WeatherState(kind=WeatherKind.CLEAR, wind=6),
                (),
            ),
            7,
        )

    def test_torch_and_fire_add_light(self) -> None:
        clear = WeatherState(kind=WeatherKind.CLEAR)
        day = SimulationClock()
        day.advance(24)
        night = SimulationClock()
        night.advance(168)
        torch_agent = _agent(torch=True)
        fire = Structure(StructureKind.FIRE, Position(3, 2), fuel=10, lit=True)

        self.assertEqual(effective_vision(torch_agent, night, clear, ()), 5)
        self.assertEqual(effective_vision(_agent(), day, clear, (fire,)), 13)

    def test_unlit_fire_does_not_add_light(self) -> None:
        clear = WeatherState(kind=WeatherKind.CLEAR)
        day = SimulationClock()
        day.advance(24)
        fire = Structure(StructureKind.FIRE, Position(3, 2), fuel=10, lit=False)

        self.assertEqual(effective_vision(_agent(), day, clear, (fire,)), 8)


class ClimateTickTests(unittest.TestCase):
    def test_rain_lowers_body_temperature_toward_its_target(self) -> None:
        state = _state(_agent(), weather=WeatherState(kind=WeatherKind.RAIN))

        advanced = apply_climate_tick(state, SimulationClock())

        self.assertLess(advanced.agents[0].attributes.body_temperature_centi, 3_700)
        self.assertGreaterEqual(
            advanced.agents[0].attributes.body_temperature_centi, BODY_MIN_CENTI
        )

    def test_fire_and_clothing_mitigate_cooling(self) -> None:
        fire = Structure(StructureKind.FIRE, Position(3, 2), fuel=10, lit=True)
        fire_state = _state(
            _agent(body_temp_centi=3_500),
            weather=WeatherState(kind=WeatherKind.RAIN),
            structures=(fire,),
            world=_world(fire=Position(3, 2)),
        )
        warm_state = _state(
            _agent(body_temp_centi=3_500, clothes=True),
            weather=WeatherState(kind=WeatherKind.RAIN),
        )
        naked_state = _state(
            _agent(body_temp_centi=3_500),
            weather=WeatherState(kind=WeatherKind.RAIN),
        )

        fire_result = apply_climate_tick(fire_state, SimulationClock())
        warm_result = apply_climate_tick(warm_state, SimulationClock())
        naked_result = apply_climate_tick(naked_state, SimulationClock())

        self.assertGreater(
            fire_result.agents[0].attributes.body_temperature_centi,
            naked_result.agents[0].attributes.body_temperature_centi,
        )
        self.assertGreater(
            warm_result.agents[0].attributes.body_temperature_centi,
            naked_result.agents[0].attributes.body_temperature_centi,
        )

    def test_wind_cools_unless_the_agent_is_sheltered(self) -> None:
        exposed = _state(
            _agent(body_temp_centi=3_700),
            weather=WeatherState(kind=WeatherKind.CLEAR, wind=10),
        )
        shelter_position = Position(2, 2)
        sheltered = _state(
            _agent(body_temp_centi=3_700),
            weather=WeatherState(kind=WeatherKind.CLEAR, wind=10),
            structures=(Structure(StructureKind.SHELTER, shelter_position),),
            world=_world(shelter=shelter_position),
        )

        exposed_result = apply_climate_tick(exposed, SimulationClock())
        sheltered_result = apply_climate_tick(sheltered, SimulationClock())

        self.assertLess(
            exposed_result.agents[0].attributes.body_temperature_centi,
            3_700,
        )
        self.assertGreater(
            sheltered_result.agents[0].attributes.body_temperature_centi,
            exposed_result.agents[0].attributes.body_temperature_centi,
        )

    def test_shelter_dries_agent_and_keeps_temperature_bounded(self) -> None:
        shelter_position = Position(2, 2)
        shelter = Structure(StructureKind.SHELTER, shelter_position)
        state = _state(
            _agent(body_temp_centi=3_500, wetness_centi=1_000),
            weather=WeatherState(kind=WeatherKind.RAIN),
            structures=(shelter,),
            world=_world(shelter=shelter_position),
        )

        advanced = apply_climate_tick(state, SimulationClock())

        self.assertEqual(advanced.agents[0].attributes.wetness_centi, 800)
        self.assertLessEqual(
            advanced.agents[0].attributes.body_temperature_centi,
            BODY_MAX_CENTI,
        )


class ClimateSessionTests(unittest.TestCase):
    def test_observation_uses_environment_adjusted_vision(self) -> None:
        layout = WorldLayout(
            seed=42,
            world=WorldMap(width=5, height=5, tiles=(TileType.GRASS,) * 25),
            spawn_points=(Position(2, 2),),
        )
        session = GameSession(42, layout=layout)
        agent_id = session.join("Nia", session.tokens[0])["agent_id"]

        observation = session.observe(agent_id)

        self.assertEqual(observation["agent"]["effective_vision"], 5)
        self.assertEqual(observation["time"]["phase"], "dawn")


if __name__ == "__main__":
    unittest.main()
