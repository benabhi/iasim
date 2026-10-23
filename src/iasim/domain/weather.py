"""Deterministic weather transitions, wind, temperature, and wetness."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from iasim.domain.agents import Agent
from iasim.domain.rng import DeterministicRng
from iasim.domain.tiles import TileType

if TYPE_CHECKING:
    from iasim.domain.session import SessionState

DEFAULT_WEATHER_MIN_TICKS: Final = 12
DEFAULT_WEATHER_MAX_TICKS: Final = 72
BASE_TEMPERATURE_CENTI: Final = 22 * 100
WATER_WETNESS_CENTI: Final = 2 * 100
MAX_WETNESS_CENTI: Final = 100 * 100


class WeatherKind(StrEnum):
    """MVP weather states from SRS section 3.4.1."""

    CLEAR = "clear"
    CLOUDY = "cloudy"
    RAIN = "rain"
    STORM = "storm"
    FOG = "fog"


@dataclass(frozen=True, slots=True)
class WeatherProfile:
    """Deterministic environmental properties of one weather state."""

    temperature_offset_centi: int
    visibility_factor: float
    wetness_delta_centi: int
    wind_min: int
    wind_max: int

    def __post_init__(self) -> None:
        if not 0.0 <= self.visibility_factor <= 1.0:
            raise ValueError("visibility_factor must be within [0.0, 1.0]")
        if not 0 <= self.wind_min <= self.wind_max <= 10:
            raise ValueError("wind range must be within [0, 10]")


_WEATHER_PROFILES: Final[dict[WeatherKind, WeatherProfile]] = {
    WeatherKind.CLEAR: WeatherProfile(
        temperature_offset_centi=0,
        visibility_factor=1.0,
        wetness_delta_centi=-100,
        wind_min=0,
        wind_max=3,
    ),
    WeatherKind.CLOUDY: WeatherProfile(
        temperature_offset_centi=-100,
        visibility_factor=0.95,
        wetness_delta_centi=-50,
        wind_min=0,
        wind_max=4,
    ),
    WeatherKind.RAIN: WeatherProfile(
        temperature_offset_centi=-300,
        visibility_factor=0.80,
        wetness_delta_centi=150,
        wind_min=2,
        wind_max=6,
    ),
    WeatherKind.STORM: WeatherProfile(
        temperature_offset_centi=-500,
        visibility_factor=0.60,
        wetness_delta_centi=250,
        wind_min=8,
        wind_max=10,
    ),
    WeatherKind.FOG: WeatherProfile(
        temperature_offset_centi=-200,
        visibility_factor=0.40,
        wetness_delta_centi=50,
        wind_min=0,
        wind_max=2,
    ),
}

# Weighted transitions keep the MVP weather sequence varied without introducing
# a second source of randomness. Snow and seasonal transitions are F2 work.
_TRANSITIONS: Final[dict[WeatherKind, tuple[tuple[WeatherKind, int], ...]]] = {
    WeatherKind.CLEAR: (
        (WeatherKind.CLOUDY, 5),
        (WeatherKind.RAIN, 2),
        (WeatherKind.FOG, 1),
    ),
    WeatherKind.CLOUDY: (
        (WeatherKind.CLEAR, 4),
        (WeatherKind.RAIN, 3),
        (WeatherKind.FOG, 1),
    ),
    WeatherKind.RAIN: (
        (WeatherKind.CLOUDY, 4),
        (WeatherKind.STORM, 2),
        (WeatherKind.CLEAR, 2),
    ),
    WeatherKind.STORM: (
        (WeatherKind.RAIN, 4),
        (WeatherKind.CLOUDY, 3),
    ),
    WeatherKind.FOG: (
        (WeatherKind.CLEAR, 4),
        (WeatherKind.CLOUDY, 3),
    ),
}


@dataclass(frozen=True, slots=True)
class WeatherState:
    """Current weather and its deterministic environmental values."""

    kind: WeatherKind = WeatherKind.CLEAR
    remaining_ticks: int = DEFAULT_WEATHER_MIN_TICKS
    wind: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.kind, WeatherKind):
            raise ValueError(f"kind must be a WeatherKind, got {self.kind!r}")
        if type(self.remaining_ticks) is not int or self.remaining_ticks < 1:
            raise ValueError(f"remaining_ticks must be positive, got {self.remaining_ticks!r}")
        if type(self.wind) is not int or not 0 <= self.wind <= 10:
            raise ValueError(f"wind must be within [0, 10], got {self.wind!r}")

    @classmethod
    def initial(cls, min_ticks: int = DEFAULT_WEATHER_MIN_TICKS) -> WeatherState:
        """Return a deterministic clear-weather starting state."""
        return cls(remaining_ticks=min_ticks)

    @property
    def profile(self) -> WeatherProfile:
        """Return the static profile for this weather kind."""
        return _WEATHER_PROFILES[self.kind]

    @property
    def ambient_temperature_centi(self) -> int:
        """Return ambient temperature in hundredths of a degree Celsius."""
        return BASE_TEMPERATURE_CENTI + self.profile.temperature_offset_centi

    @property
    def temperature_c(self) -> float:
        """Return ambient temperature in degrees Celsius."""
        return self.ambient_temperature_centi / 100.0

    @property
    def visibility_factor(self) -> float:
        """Return the weather visibility multiplier."""
        return self.profile.visibility_factor

    @property
    def wetness_delta_centi(self) -> int:
        """Return the per-tick agent wetness change before terrain effects."""
        return self.profile.wetness_delta_centi


def advance_weather(
    weather: WeatherState,
    rng_state: int,
    *,
    min_ticks: int = DEFAULT_WEATHER_MIN_TICKS,
    max_ticks: int = DEFAULT_WEATHER_MAX_TICKS,
) -> tuple[WeatherState, int]:
    """Advance weather one tick and return the new weather and RNG state.

    A transition consumes the deterministic stream only when the current
    weather ends; durations stay within the inclusive configured bounds.
    """
    _validate_duration_bounds(min_ticks, max_ticks)
    rng = DeterministicRng.from_state(rng_state)
    if weather.remaining_ticks > 1:
        return replace(weather, remaining_ticks=weather.remaining_ticks - 1), rng.state

    kind = _choose_next(weather.kind, rng)
    profile = _WEATHER_PROFILES[kind]
    wind = rng.randint(profile.wind_min, profile.wind_max)
    remaining = rng.randint(min_ticks, max_ticks)
    return (
        WeatherState(kind=kind, remaining_ticks=remaining, wind=wind),
        rng.state,
    )


def apply_weather_wetness(state: SessionState) -> SessionState:
    """Apply one tick of weather and water wetness to living agents."""
    delta = state.weather.wetness_delta_centi
    agents: list[Agent] = []
    for agent in state.agents:
        if not agent.is_alive:
            agents.append(agent)
            continue
        water_bonus = (
            WATER_WETNESS_CENTI
            if state.world.tile_at(agent.position) in {TileType.SHALLOW_WATER, TileType.FRESH_WATER}
            else 0
        )
        wetness = max(
            0,
            min(MAX_WETNESS_CENTI, agent.attributes.wetness_centi + delta + water_bonus),
        )
        agents.append(
            replace(
                agent,
                attributes=replace(agent.attributes, wetness_centi=wetness),
            )
        )
    return replace(state, agents=tuple(agents))


def _choose_next(current: WeatherKind, rng: DeterministicRng) -> WeatherKind:
    transitions = _TRANSITIONS[current]
    roll = rng.randint(1, sum(weight for _, weight in transitions))
    for kind, weight in transitions:
        if roll <= weight:
            return kind
        roll -= weight
    raise AssertionError("weighted weather transition did not select a kind")


def _validate_duration_bounds(min_ticks: int, max_ticks: int) -> None:
    if type(min_ticks) is not int or type(max_ticks) is not int:
        raise ValueError("weather duration bounds must be integers")
    if min_ticks < 1:
        raise ValueError(f"min_ticks must be positive, got {min_ticks}")
    if max_ticks < min_ticks:
        raise ValueError(f"max_ticks must be >= min_ticks, got {max_ticks} and {min_ticks}")
