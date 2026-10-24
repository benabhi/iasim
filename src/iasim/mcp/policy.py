"""Security policy for the MCP agent surface.

The agent-facing tool catalog is a fixed allowlist. Adding a tool requires
updating this list, which keeps the security review explicit: no
administration, debug, teleport, map-editing, full-map, RNG, or operator tool
may ever be exposed (AGENTS.md section 7, SRS RF-505 and RF-1012).
"""

from __future__ import annotations

from collections.abc import Iterable

ALLOWED_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "iasim_join",
        "iasim_leave",
        "iasim_observe",
        "iasim_wait_for_tick",
        "iasim_get_session_info",
        "iasim_get_recipes",
        "iasim_get_inventory",
        "iasim_inspect",
        "iasim_move",
        "iasim_move_to",
        "iasim_wait",
        "iasim_rest",
        "iasim_sleep",
        "iasim_gather",
        "iasim_pickup",
        "iasim_drop",
        "iasim_eat",
        "iasim_drink",
        "iasim_fill",
        "iasim_use",
        "iasim_equip",
        "iasim_unequip",
        "iasim_craft",
        "iasim_build",
        "iasim_attack",
        "iasim_throw",
        "iasim_flee",
        "iasim_loot",
        "iasim_offer_alliance",
        "iasim_accept_alliance",
        "iasim_break_alliance",
        "iasim_offer_trade",
        "iasim_accept_trade",
        "iasim_decline_trade",
        "iasim_say",
        "iasim_report_mind",
        "iasim_report_usage",
    }
)

# Argument names that would let an agent address another agent, read the RNG,
# or ask for the map; no tool may declare any of them.
FORBIDDEN_ARGUMENT_NAMES: frozenset[str] = frozenset(
    {
        "admin",
        "agent",
        "agent_id",
        "debug",
        "map",
        "operator",
        "rng",
        "rng_state",
        "seed",
        "tiles",
        "token",
        "world",
    }
)

FORBIDDEN_TOOL_TOKENS: tuple[str, ...] = (
    "admin",
    "debug",
    "kill",
    "map",
    "operator",
    "rng",
    "seed",
    "spawn",
    "teleport",
    "token",
)


def enforce_tool_policy(registered: Iterable[str]) -> None:
    """Raise when the registered tool names differ from the allowlist."""
    names = set(registered)
    unexpected = sorted(names - ALLOWED_TOOL_NAMES)
    missing = sorted(ALLOWED_TOOL_NAMES - names)
    if not unexpected and not missing:
        return
    details: list[str] = []
    if unexpected:
        details.append(f"unexpected={unexpected}")
    if missing:
        details.append(f"missing={missing}")
    raise RuntimeError("MCP tool catalog violates the allowlist: " + ", ".join(details))
