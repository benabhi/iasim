"""Tests for the deterministic simulation clock."""

from __future__ import annotations

import unittest

from iasim.domain.clock import DayPhase, SimulationClock


class SimulationClockTests(unittest.TestCase):
    def test_tick_zero_is_day_one_at_six(self) -> None:
        clock = SimulationClock()

        self.assertEqual(clock.tick, 0)
        self.assertEqual(clock.day, 1)
        self.assertEqual((clock.hour, clock.minute), (6, 0))
        self.assertEqual(clock.phase, DayPhase.DAWN)
        self.assertEqual(clock.light_factor, 0.65)

    def test_288_ticks_advance_one_full_day(self) -> None:
        clock = SimulationClock()

        self.assertEqual(clock.advance(288), 288)

        self.assertEqual(clock.day, 2)
        self.assertEqual((clock.hour, clock.minute), (6, 0))

    def test_day_rolls_over_at_midnight(self) -> None:
        clock = SimulationClock()
        clock.advance(215)

        self.assertEqual(clock.day, 1)
        self.assertEqual((clock.hour, clock.minute), (23, 55))

        clock.advance()

        self.assertEqual(clock.day, 2)
        self.assertEqual((clock.hour, clock.minute), (0, 0))
        self.assertEqual(clock.phase, DayPhase.NIGHT)

    def test_phase_and_light_boundaries(self) -> None:
        cases = [
            (0, DayPhase.DAWN, 0.65),
            (12, DayPhase.DAY, 1.0),
            (143, DayPhase.DAY, 1.0),
            (144, DayPhase.DUSK, 0.65),
            (167, DayPhase.DUSK, 0.65),
            (168, DayPhase.NIGHT, 0.25),
            (215, DayPhase.NIGHT, 0.25),
            (216, DayPhase.NIGHT, 0.25),
            (275, DayPhase.NIGHT, 0.25),
            (276, DayPhase.DAWN, 0.65),
            (287, DayPhase.DAWN, 0.65),
            (288, DayPhase.DAWN, 0.65),
        ]

        for ticks, expected_phase, expected_light in cases:
            with self.subTest(ticks=ticks):
                clock = SimulationClock()
                clock.advance(ticks)

                self.assertEqual(clock.phase, expected_phase)
                self.assertEqual(clock.light_factor, expected_light)

    def test_tick_minutes_is_configurable(self) -> None:
        clock = SimulationClock(tick_minutes=10)

        self.assertEqual(clock.tick_minutes, 10)
        self.assertEqual(clock.advance(144), 144)
        self.assertEqual(clock.day, 2)
        self.assertEqual((clock.hour, clock.minute), (6, 0))

    def test_multiple_days_are_counted_from_midnight(self) -> None:
        clock = SimulationClock()

        clock.advance(864)

        self.assertEqual(clock.day, 4)
        self.assertEqual((clock.hour, clock.minute), (6, 0))

    def test_advance_zero_does_not_change_the_tick(self) -> None:
        clock = SimulationClock()

        self.assertEqual(clock.advance(0), 0)
        self.assertEqual(clock.tick, 0)

    def test_invalid_tick_minutes_and_negative_advance_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            SimulationClock(tick_minutes=0)

        clock = SimulationClock()
        with self.assertRaises(ValueError):
            clock.advance(-1)

        self.assertEqual(clock.tick, 0)
