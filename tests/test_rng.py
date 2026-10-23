"""Tests for the deterministic RNG primitives."""

from __future__ import annotations

import unittest

from iasim.domain.rng import DeterministicRng, roll_d6


class DeterministicRngTests(unittest.TestCase):
    def test_splitmix64_seed_zero_matches_reference_vectors(self) -> None:
        rng = DeterministicRng(0)
        expected = [
            0xE220A8397B1DCDAF,
            0x6E789E6AA1B965F4,
            0x06C45D188009454F,
            0xF88BB8A8724C81EC,
            0x1B39896A51A8749B,
        ]

        self.assertEqual([rng.next_u64() for _ in expected], expected)

    def test_same_seed_repeats_the_same_sequence(self) -> None:
        first = DeterministicRng(42)
        second = DeterministicRng(42)

        self.assertEqual(
            [first.next_u64() for _ in range(16)],
            [second.next_u64() for _ in range(16)],
        )
        self.assertNotEqual(DeterministicRng(42).next_u64(), DeterministicRng(43).next_u64())

    def test_randint_stays_in_the_inclusive_range(self) -> None:
        rng = DeterministicRng(7)

        values = {rng.randint(1, 6) for _ in range(200)}

        self.assertTrue(values)
        self.assertLessEqual(values, {1, 2, 3, 4, 5, 6})
        self.assertGreater(len(values), 1)
        self.assertEqual(rng.randint(5, 5), 5)
        with self.assertRaises(ValueError):
            rng.randint(6, 5)

    def test_randint_rejects_ranges_wider_than_64_bits(self) -> None:
        with self.assertRaises(ValueError):
            DeterministicRng(1).randint(0, 1 << 65)

    def test_d6_returns_only_valid_faces(self) -> None:
        rng = DeterministicRng(11)

        rolls = {rng.d6() for _ in range(100)}

        self.assertTrue(rolls)
        self.assertLessEqual(rolls, {1, 2, 3, 4, 5, 6})

    def test_chance_honours_the_probability_bounds(self) -> None:
        rng = DeterministicRng(3)

        self.assertFalse(rng.chance(0.0))
        self.assertTrue(rng.chance(1.0))
        with self.assertRaises(ValueError):
            rng.chance(-0.1)
        with self.assertRaises(ValueError):
            rng.chance(1.1)

    def test_state_round_trip_resumes_the_same_sequence(self) -> None:
        rng = DeterministicRng(99)
        for _ in range(5):
            rng.next_u64()
        saved_state = rng.state
        expected = [rng.next_u64() for _ in range(5)]

        restored = DeterministicRng.from_state(saved_state)

        self.assertEqual(restored.state, saved_state)
        self.assertEqual([restored.next_u64() for _ in range(5)], expected)


class DerivedRollTests(unittest.TestCase):
    def test_roll_d6_matches_a_golden_value(self) -> None:
        self.assertEqual(roll_d6(42, 7, "ag_02"), 3)

    def test_roll_d6_is_order_independent(self) -> None:
        expected = roll_d6(42, 7, "ag_02")

        for _ in range(3):
            roll_d6(1, 2, "ag_01")

        self.assertEqual(roll_d6(42, 7, "ag_02"), expected)
        self.assertEqual(roll_d6(42, 7, 2), roll_d6(42, 7, 2))

    def test_roll_d6_varies_with_seed_and_tick(self) -> None:
        values = {roll_d6(42, tick, "ag_02") for tick in range(64)}

        self.assertTrue(values)
        self.assertLessEqual(values, {1, 2, 3, 4, 5, 6})
        self.assertGreater(len(values), 1)
        self.assertNotEqual(
            [roll_d6(42, tick, "ag_02") for tick in range(32)],
            [roll_d6(43, tick, "ag_02") for tick in range(32)],
        )

    def test_roll_d6_rejects_negative_ticks(self) -> None:
        with self.assertRaises(ValueError):
            roll_d6(42, -1, "ag_02")
