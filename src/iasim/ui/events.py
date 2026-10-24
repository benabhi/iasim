"""Event-log rows, category filters, search, and pagination helpers.

The F4 view is a pure projection over recorded events: categories label every
row so the operator never depends on color alone, and filtering never mutates
or trims the log.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from iasim.ui import theme

CATEGORY_ACTIONS = "acciones"
CATEGORY_COMBAT = "combate"
CATEGORY_SOCIAL = "social"
CATEGORY_NEEDS = "necesidades"
CATEGORY_WEATHER = "clima"
CATEGORY_MCP = "mcp"

CATEGORY_ORDER: tuple[str, ...] = (
    CATEGORY_ACTIONS,
    CATEGORY_COMBAT,
    CATEGORY_SOCIAL,
    CATEGORY_NEEDS,
    CATEGORY_WEATHER,
    CATEGORY_MCP,
)

CATEGORY_LABELS: dict[str, str] = {
    CATEGORY_ACTIONS: "ACCIONES",
    CATEGORY_COMBAT: "COMBATE",
    CATEGORY_SOCIAL: "SOCIAL",
    CATEGORY_NEEDS: "NECESIDADES",
    CATEGORY_WEATHER: "CLIMA",
    CATEGORY_MCP: "MCP/ERRORES",
}

EVENT_COLORS: dict[str, theme.RGB] = {
    CATEGORY_ACTIONS: theme.WHITE,
    CATEGORY_COMBAT: theme.RED,
    CATEGORY_SOCIAL: theme.CYAN,
    CATEGORY_NEEDS: theme.YELLOW,
    CATEGORY_WEATHER: (140, 190, 220),
    CATEGORY_MCP: theme.GREEN,
}

PAGE_SIZE = 20


@dataclass(frozen=True, slots=True)
class EventRow:
    """One recorded event ready for the F4 table."""

    tick: int
    category: str
    agents: str
    message: str
    result: str = ""

    def __post_init__(self) -> None:
        if self.tick < 0:
            raise ValueError(f"tick must be non-negative, got {self.tick}")
        if self.category not in CATEGORY_LABELS:
            raise ValueError(f"unknown event category {self.category!r}")


def filter_events(
    rows: Sequence[EventRow],
    *,
    query: str = "",
    category: str | None = None,
    agent_id: str | None = None,
) -> tuple[EventRow, ...]:
    """Return the matching events in their original order."""
    text = query.strip().lower()
    filtered: list[EventRow] = []
    for row in rows:
        if category is not None and row.category != category:
            continue
        if agent_id is not None and agent_id not in row.agents:
            continue
        if text:
            haystack = " ".join((row.agents, row.message, row.result, row.category)).lower()
            if text not in haystack:
                continue
        filtered.append(row)
    return tuple(filtered)


def page_count(total: int, page_size: int = PAGE_SIZE) -> int:
    """Return the number of pages needed for ``total`` events."""
    if total <= 0:
        return 1
    return (total + page_size - 1) // page_size


def page_rows(
    rows: Sequence[EventRow],
    page: int,
    page_size: int = PAGE_SIZE,
) -> tuple[EventRow, ...]:
    """Return the rows of one clamped page."""
    pages = page_count(len(rows), page_size)
    current = max(0, min(page, pages - 1))
    start = current * page_size
    return tuple(rows[start : start + page_size])


def next_category(category: str | None, direction: int = 1) -> str | None:
    """Cycle through ``None`` (all) and the category filters."""
    options: tuple[str | None, ...] = (None, *CATEGORY_ORDER)
    index = options.index(category)
    return options[(index + direction) % len(options)]
