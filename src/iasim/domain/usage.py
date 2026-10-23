"""Reported LLM usage accounting for operator observability.

Usage is deliberately not part of :class:`iasim.domain.session.SessionState`:
it comes from an external agent, does not change simulation rules, and must not
affect the canonical state hash.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

TOKENS_PER_MILLION = 1_000_000.0


class CostSource(StrEnum):
    """How the reported cost was obtained."""

    REPORTED = "reported"
    ESTIMATED = "estimated"
    MIXED = "mixed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ModelPricing:
    """Optional per-model prices in USD per million tokens."""

    input_per_million_usd: float
    output_per_million_usd: float

    def __post_init__(self) -> None:
        for label, value in (
            ("input_per_million_usd", self.input_per_million_usd),
            ("output_per_million_usd", self.output_per_million_usd),
        ):
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{label} must be finite and non-negative, got {value!r}")

    def estimate(self, input_tokens: int, output_tokens: int) -> float:
        """Return the approximate cost for a report at these token counts."""
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("token counts must be non-negative")
        return (
            input_tokens * self.input_per_million_usd + output_tokens * self.output_per_million_usd
        ) / TOKENS_PER_MILLION


@dataclass(frozen=True, slots=True)
class UsageEntry:
    """One model/effort bucket of accumulated usage."""

    model: str
    input_tokens: int
    output_tokens: int
    reasoning_effort: str | None = None
    cost_usd: float | None = None
    cost_source: CostSource = CostSource.UNKNOWN
    cost_complete: bool = True

    def __post_init__(self) -> None:
        if not self.model or not self.model.strip():
            raise ValueError("model must not be empty")
        if self.input_tokens < 0 or self.output_tokens < 0:
            raise ValueError("token counts must be non-negative")
        if self.cost_usd is not None and (not math.isfinite(self.cost_usd) or self.cost_usd < 0):
            raise ValueError(f"cost_usd must be finite and non-negative, got {self.cost_usd!r}")
        if self.cost_usd is None:
            if self.cost_source is not CostSource.UNKNOWN:
                raise ValueError("unknown cost must use CostSource.UNKNOWN")
            object.__setattr__(self, "cost_complete", False)
        elif self.cost_source is CostSource.UNKNOWN:
            raise ValueError("a known cost must have a known source")

    @property
    def total_tokens(self) -> int:
        """Return input plus output tokens."""
        return self.input_tokens + self.output_tokens

    def merged_with(self, other: UsageEntry) -> UsageEntry:
        """Merge another report from the same model and effort bucket."""
        if (self.model, self.reasoning_effort) != (other.model, other.reasoning_effort):
            raise ValueError("cannot merge different model/effort buckets")
        if self.cost_usd is None and other.cost_usd is None:
            cost = None
            source = CostSource.UNKNOWN
        elif self.cost_usd is None or other.cost_usd is None:
            cost = self.cost_usd if self.cost_usd is not None else other.cost_usd
            source = CostSource.MIXED
        else:
            cost = self.cost_usd + other.cost_usd
            source = self.cost_source if self.cost_source is other.cost_source else CostSource.MIXED
        return replace(
            self,
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cost_usd=cost,
            cost_source=source,
            cost_complete=self.cost_complete and other.cost_complete,
        )

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-ready representation for MCP and operator tooling."""
        return {
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
            "cost_complete": self.cost_complete,
            "cost_source": self.cost_source.value,
        }


@dataclass(frozen=True, slots=True)
class AgentUsage:
    """Accumulated usage for one connected agent."""

    entries: tuple[UsageEntry, ...] = ()

    @property
    def input_tokens(self) -> int:
        """Return total reported input tokens."""
        return sum(entry.input_tokens for entry in self.entries)

    @property
    def output_tokens(self) -> int:
        """Return total reported output tokens."""
        return sum(entry.output_tokens for entry in self.entries)

    @property
    def total_tokens(self) -> int:
        """Return total reported input plus output tokens."""
        return self.input_tokens + self.output_tokens

    @property
    def cost_usd(self) -> float | None:
        """Return the sum of known costs, or None when none is known."""
        known = [entry.cost_usd for entry in self.entries if entry.cost_usd is not None]
        return sum(known) if known else None

    @property
    def cost_complete(self) -> bool:
        """Return whether every bucket has a complete known cost."""
        return bool(self.entries) and all(entry.cost_complete for entry in self.entries)

    @property
    def cost_source(self) -> CostSource:
        """Return the aggregate source label for the known cost."""
        sources = {entry.cost_source for entry in self.entries}
        if not sources or sources == {CostSource.UNKNOWN}:
            return CostSource.UNKNOWN
        if len(sources) == 1:
            return next(iter(sources))
        return CostSource.MIXED

    @property
    def latest(self) -> UsageEntry | None:
        """Return the most recently reported bucket."""
        return self.entries[-1] if self.entries else None

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-ready aggregate for MCP and operator tooling."""
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
            "cost_complete": self.cost_complete,
            "cost_source": self.cost_source.value,
            "latest": self.latest.as_dict() if self.latest is not None else None,
            "entries": [entry.as_dict() for entry in self.entries],
        }
