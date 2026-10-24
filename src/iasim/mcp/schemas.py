"""Strict wire schemas for MCP tool arguments.

The MCP server derives each tool's JSON schema from these annotations, so an
invalid argument is rejected at the protocol boundary before it reaches the
session. Domain rules still validate the semantics of a well-formed request.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

Tick = Annotated[int, Field(ge=0, description="Tick the request belongs to.")]
PositiveQuantity = Annotated[int, Field(ge=1, description="Units of the item; at least one.")]
TimeoutMillis = Annotated[
    int,
    Field(ge=0, le=60_000, description="Maximum wait in milliseconds."),
]


class TradeItem(BaseModel):
    """One item line of a trade lot."""

    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(min_length=1, max_length=64, description="Catalog item id.")
    qty: int = Field(ge=1, description="Units traded; at least one.")
