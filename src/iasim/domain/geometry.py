"""Grid geometry value objects."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Position:
    """An immutable grid coordinate with non-negative components."""

    x: int
    y: int

    def __post_init__(self) -> None:
        if self.x < 0:
            raise ValueError(f"x must be non-negative, got {self.x}")
        if self.y < 0:
            raise ValueError(f"y must be non-negative, got {self.y}")
