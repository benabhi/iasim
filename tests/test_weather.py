"""Tests for deterministic weather, wetness, and observation fields."""

from __future__ import annotations

import unittest

from iasim.app.session import GameSession
from iasim.domain.agents import Agent, AgentAttributes
from iasim.domain.geometry import Position
from iasim.domain.hashing import canonical_state_hash
from iasim.domain.identifiers import AgentId
from iasim.domain.session import SessionState
from iasim.domain.tiles import TileType, WorldMap
from iasim.domain.weather import (
    BASE_TEMPERATURE_CENTI,
    WeatherKind,
    WeatherState,
    advance_weather,
    apply_weather_wetness,
)
from iasim.world.layout import WorldLayout


def _world(tile: TileType = TileType.GRASS) -> WorldMap:
    return WorldMap(width=5, height=5, tiles=(tile,) * 25)


def _state(
    *,
    weather: WeatherState | None = None,
    position: Position | None = None,
    wetness_centi: int = 0,
    world: WorldMap | None = None,
) -> SessionState:
    agent = Agent(
        AgentId("ag_01"),
        Position(2, 2) if position is None else position,
        attributes=AgentAttributes(wetness_centi=wetness_centi),
    )
    return SessionState(
        seed=42,
        tick=0,
        rng_state=42,
        world=_world() if world is None else world,
        agents=(agent,),
        weather=weather or WeatherState(),
    )


class WeatherStateTests(unittest.TestCase):
    def test_weather_state_validates_bounds(self) -> None:
        with self.assertRaises(ValueError):
            WeatherState(remaining_ticks=0)
        with self.assertRaises(ValueError):
            WeatherState(wind=-1)
        with self.assertRaises(ValueError):
            WeatherState(wind=11)
        with self.assertRaises(ValueError):
            WeatherState(kind="rain")  # type: ignore[arg-type]

    def test_weather_profiles_match_visibility_and_temperature_offsets(self) -> None:
        self.assertEqual(WeatherState(kind=WeatherKind.CLEAR).temperature_c, 22.0)
        self.assertEqual(WeatherState(kind=WeatherKind.CLOUDY).temperature_c, 21.0)
        self.assertEqual(WeatherState(kind=WeatherKind.RAIN).temperature_c, 19.0)
        self.assertEqual(WeatherState(kind=WeatherKind.STORM).temperature_c, 17.0)
        self.assertEqual(WeatherState(kind=WeatherKind.FOG).temperature_c, 20.0)
        self.assertEqual(WeatherState(kind=WeatherKind.RAIN).visibility_factor, 0.8)
        self.assertEqual(WeatherState(kind=WeatherKind.STORM).visibility_factor, 0.6)
        self.assertEqual(WeatherState(kind=WeatherKind.FOG).visibility_factor, 0.4)


class WeatherTransitionTests(unittest.TestCase):
    def test_advance_decrements_without_consuming_rng(self) -> None:
        weather = WeatherState(remaining_ticks=3)
        advanced, rng_state = advance_weather(weather, 42, min_ticks=3, max_ticks=3)

        self.assertEqual(advanced.kind, WeatherKind.CLEAR)
        self.assertEqual(advanced.remaining_ticks, 2)
        self.assertEqual(rng_state, 42)

    def test_advance_transitions_within_configured_duration_bounds(self) -> None:
        weather = WeatherState(remaining_ticks=1)
        first, first_rng = advance_weather(weather, 42, min_ticks=5, max_ticks=9)
        second, second_rng = advance_weather(weather, 42, min_ticks=5, max_ticks=9)

        self.assertEqual(first, second)
        self.assertEqual(first_rng, second_rng)
        self.assertIn(first.kind, set(WeatherKind))
        self.assertGreaterEqual(first.remaining_ticks, 5)
        self.assertLessEqual(first.remaining_ticks, 9)
        self.assertGreaterEqual(first.wind, 0)
        self.assertLessEqual(first.wind, 10)
        self.assertEqual(
            first.ambient_temperature_centi, 2200 + first.profile.temperature_offset_centi
        )

    def test_transition_bounds_are_validated(self) -> None:
        with self.assertRaises(ValueError):
            advance_weather(WeatherState(), 42, min_ticks=0, max_ticks=5)
        with self.assertRaises(ValueError):
            advance_weather(WeatherState(), 42, min_ticks=5, max_ticks=4)


class WetnessTests(unittest.TestCase):
    def test_rain_increases_wetness_and_clear_dries_the_agent(self) -> None:
        rainy, _ = advance_weather(
            WeatherState(kind=WeatherKind.RAIN, remaining_ticks=2),
            42,
            min_ticks=1,
            max_ticks=1,
        )
        state = apply_weather_wetness(_state(weather=rainy))
        self.assertEqual(state.agents[0].attributes.wetness_centi, 150)

        clear = WeatherState(kind=WeatherKind.CLEAR, remaining_ticks=2)
        state = apply_weather_wetness(_state(weather=clear, wetness_centi=300))
        self.assertEqual(state.agents[0].attributes.wetness_centi, 200)

    def test_water_tile_adds_wetness_and_values_are_capped(self) -> None:
        storm = WeatherState(kind=WeatherKind.STORM, remaining_ticks=2)
        state = apply_weather_wetness(
            _state(
                weather=storm,
                wetness_centi=9_900,
                world=_world(TileType.FRESH_WATER),
            )
        )

        self.assertEqual(state.agents[0].attributes.wetness_centi, 10_000)


class WeatherSessionTests(unittest.TestCase):
    def _layout(self) -> WorldLayout:
        return WorldLayout(
            seed=42,
            world=_world(),
            spawn_points=(Position(2, 2),),
        )

    def test_initial_observation_exposes_weather_and_time_fields(self) -> None:
        session = GameSession(42, layout=self._layout())
        agent_id = session.join("Nia", session.tokens[0])["agent_id"]
        observation = session.observe(agent_id)

        self.assertEqual(observation["environment"]["weather"], "clear")
        self.assertEqual(observation["environment"]["temperature_c"], 22.0)
        self.assertEqual(observation["environment"]["wind"], 0)
        self.assertEqual(observation["environment"]["visibility_factor"], 1.0)
        self.assertEqual(observation["time"]["phase"], "dawn")

    def test_weather_transitions_are_reproducible_across_sessions(self) -> None:
        def run() -> dict[str, object]:
            session = GameSession(
                42,
                layout=self._layout(),
                weather_min_ticks=1,
                weather_max_ticks=1,
            )
            agent_id = session.join("Nia", session.tokens[0])["agent_id"]
            session.wait(agent_id, 0)
            observation = session.observe(agent_id)
            return {
                "environment": observation["environment"],
                "wetness": observation["agent"]["wetness"],
                "tick": observation["tick"],
            }

        first = run()
        second = run()

        self.assertEqual(first, second)
        self.assertEqual(first["tick"], 1)
        self.assertIn(
            first["environment"]["weather"],
            {kind.value for kind in WeatherKind},
        )

    def test_weather_changes_state_hash_and_wetness(self) -> None:
        base = _state(weather=WeatherState(kind=WeatherKind.CLEAR))
        rainy = apply_weather_wetness(_state(weather=WeatherState(kind=WeatherKind.RAIN)))

        self.assertNotEqual(canonical_state_hash(base), canonical_state_hash(rainy))
        self.assertEqual(rainy.agents[0].attributes.wetness_centi, 150)
        self.assertEqual(base.weather.ambient_temperature_centi, BASE_TEMPERATURE_CENTI)


if __name__ == "__main__":
    unittest.main()
