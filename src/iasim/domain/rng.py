"""Deterministic pseudo-random primitives for the simulation.

All simulation randomness must flow through this module. It never touches the
global ``random`` module or operating-system entropy, so a seed and call order
fully determine the sequence on every platform.
"""

from __future__ import annotations

from hashlib import blake2b

_MASK64 = (1 << 64) - 1
_GOLDEN_GAMMA = 0x9E3779B97F4A7C15
_MIX_A = 0xBF58476D1CE4E5B9
_MIX_B = 0x94D049BB133111EB


def _mix64(value: int) -> int:
    """Return the SplitMix64 finalizer applied to a 64-bit integer."""
    value &= _MASK64
    value = ((value ^ (value >> 30)) * _MIX_A) & _MASK64
    value = ((value ^ (value >> 27)) * _MIX_B) & _MASK64
    return value ^ (value >> 31)


def _agent_key(agent: str | int) -> int:
    """Map an agent identifier to a stable 64-bit integer."""
    if isinstance(agent, int):
        return agent & _MASK64
    return int.from_bytes(blake2b(agent.encode("utf-8"), digest_size=8).digest(), "big")


class DeterministicRng:
    """Seeded SplitMix64 stream with platform-independent output."""

    def __init__(self, seed: int) -> None:
        self._state = seed & _MASK64

    @property
    def state(self) -> int:
        """Return the current 64-bit state for persistence."""
        return self._state

    @classmethod
    def from_state(cls, state: int) -> DeterministicRng:
        """Restore a stream from a previously saved state."""
        return cls(state)

    def next_u64(self) -> int:
        """Advance the stream and return the next unsigned 64-bit value."""
        self._state = (self._state + _GOLDEN_GAMMA) & _MASK64
        return _mix64(self._state)

    def randint(self, low: int, high: int) -> int:
        """Return a value in the inclusive range ``[low, high]``."""
        if low > high:
            raise ValueError(f"low must be <= high, got {low} and {high}")
        span = high - low + 1
        if span > 1 << 64:
            raise ValueError("range must not exceed 2**64 values")
        limit = (1 << 64) - ((1 << 64) % span)
        while True:
            value = self.next_u64()
            if value < limit:
                return low + value % span

    def d6(self) -> int:
        """Return a six-sided die roll in ``[1, 6]``."""
        return self.randint(1, 6)

    def chance(self, probability: float) -> bool:
        """Return ``True`` with the given probability in ``[0.0, 1.0]``."""
        if not 0.0 <= probability <= 1.0:
            raise ValueError("probability must be within [0.0, 1.0]")
        return (self.next_u64() >> 11) / float(1 << 53) < probability


def roll_d6(seed: int, tick: int, agent: str | int) -> int:
    """Return a stateless d6 derived from seed, tick, and agent identity.

    Unlike :meth:`DeterministicRng.d6`, this roll does not depend on call
    order. It implements the SRS initiative roll ``1d6(seed, tick, agente)``.
    """
    if tick < 0:
        raise ValueError("tick must be non-negative")
    value = _mix64(seed)
    value = _mix64(value ^ tick)
    value = _mix64(value ^ _agent_key(agent))
    return 1 + value % 6
