"""Run the deterministic reference agent against a local IASim MCP server."""

from __future__ import annotations

import argparse
import asyncio

from iasim.reference_agent.reference import run_reference_agent
from iasim.reference_agent.smoke import run_smoke_agent


def main() -> None:
    """Parse CLI arguments and run the reference or smoke loop."""
    parser = argparse.ArgumentParser(description="IASim reference MCP agent")
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8765/mcp",
        help="streamable HTTP MCP endpoint",
    )
    parser.add_argument("--token", required=True, help="per-agent bearer token")
    parser.add_argument("--name", default="Reference", help="agent display name")
    parser.add_argument(
        "--mode",
        choices=("reference", "smoke"),
        default="reference",
        help="reference agent (survive, gather, report) or F0 smoke walker",
    )
    parser.add_argument(
        "--ticks",
        type=int,
        default=500,
        help="resolved ticks (reference) or successful moves (smoke)",
    )
    args = parser.parse_args()

    if args.mode == "smoke":
        positions = asyncio.run(
            run_smoke_agent(
                args.url,
                args.token,
                name=args.name,
                ticks=args.ticks,
            )
        )
        final = positions[-1]
        print(f"smoke agent made {len(positions) - 1} moves; final position ({final.x}, {final.y})")
        return

    report = asyncio.run(
        run_reference_agent(
            args.url,
            args.token,
            name=args.name,
            ticks=args.ticks,
        )
    )
    print(
        f"reference agent ran {report.ticks_run} ticks with "
        f"{report.actions} actions and {report.minds_reported} mind reports; "
        f"alive={report.alive}; final position "
        f"({report.final_position.x}, {report.final_position.y})"
    )
    if report.errors:
        print(f"errors: {report.errors}")


if __name__ == "__main__":
    main()
