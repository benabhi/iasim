"""Stable identifiers and validation helpers for domain entities."""

from __future__ import annotations

import re
from typing import NewType

AgentId = NewType("AgentId", str)
ItemId = NewType("ItemId", str)

_AGENT_ID_PATTERN = re.compile(r"^ag_[0-9]{2}$")
_ITEM_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


def validate_agent_id(value: str) -> str:
    """Return ``value`` when it matches the ``ag_NN`` agent id format."""
    if _AGENT_ID_PATTERN.fullmatch(value) is None:
        raise ValueError(f"invalid agent id: {value!r}; expected 'ag_NN'")
    return value


def validate_item_id(value: str) -> str:
    """Return ``value`` when it is a lowercase snake_case item id."""
    if _ITEM_ID_PATTERN.fullmatch(value) is None:
        raise ValueError(f"invalid item id: {value!r}; expected lowercase snake_case")
    return value
