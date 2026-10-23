"""Deterministic simulation clock driven only by tick arithmetic."""

from __future__ import annotations

from enum import StrEnum

MINUTES_PER_DAY = 24 * 60
DEFAULT_TICK_MINUTES = 5
START_DAY = 1
START_MINUTE_OF_DAY = 6 * 60

_DAWN_START = 5 * 60
_DAY_START = 7 * 60
_DUSK_START = 18 * 60
_NIGHT_START = 20 * 60


class DayPhase(StrEnum):
    """Light phases defined by SRS section 3.4."""

    DAWN = "dawn"
    DAY = "day"
    DUSK = "dusk"
    NIGHT = "night"


_LIGHT_FACTORS: dict[DayPhase, float] = {
    DayPhase.DAWN: 0.65,
    DayPhase.DAY: 1.0,
    DayPhase.DUSK: 0.65,
    DayPhase.NIGHT: 0.25,
}


class SimulationClock:
    """Map an integer tick to day, time, phase, and light factor.

    Tick 0 is Day 1 at 06:00 and the clock never reads the system time.
    """

    def __init__(self, tick_minutes: int = DEFAULT_TICK_MINUTES) -> None:
        if tick_minutes < 1:
            raise ValueError("tick_minutes must be at least 1")
        self._tick_minutes = tick_minutes
        self._tick = 0

    @property
    def tick(self) -> int:
        """Return the current tick."""
        return self._tick

    @property
    def tick_minutes(self) -> int:
        """Return how many game minutes each tick represents."""
        return self._tick_minutes

    @property
    def total_game_minutes(self) -> int:
        """Return game minutes elapsed since tick 0."""
        return self._tick * self._tick_minutes

    @property
    def day(self) -> int:
        """Return the current in-game day number, starting at 1."""
        total = START_MINUTE_OF_DAY + self.total_game_minutes
        return START_DAY + total // MINUTES_PER_DAY

    @property
    def minute_of_day(self) -> int:
        """Return the current minute within the day, from 0 to 1439."""
        return (START_MINUTE_OF_DAY + self.total_game_minutes) % MINUTES_PER_DAY

    @property
    def hour(self) -> int:
        """Return the current in-game hour."""
        return self.minute_of_day // 60

    @property
    def minute(self) -> int:
        """Return the current in-game minute."""
        return self.minute_of_day % 60

    @property
    def phase(self) -> DayPhase:
        """Return the current light phase."""
        minute = self.minute_of_day
        if _DAWN_START <= minute < _DAY_START:
            return DayPhase.DAWN
        if _DAY_START <= minute < _DUSK_START:
            return DayPhase.DAY
        if _DUSK_START <= minute < _NIGHT_START:
            return DayPhase.DUSK
        return DayPhase.NIGHT

    @property
    def light_factor(self) -> float:
        """Return the SRS light multiplier for the current phase."""
        return _LIGHT_FACTORS[self.phase]

    def advance(self, ticks: int = 1) -> int:
        """Advance by ``ticks`` and return the new tick."""
        if ticks < 0:
            raise ValueError("ticks must be non-negative")
        self._tick += ticks
        return self._tick
