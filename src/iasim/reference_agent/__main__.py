"""Run the F0 smoke agent against a local IASim MCP server."""

from __future__ import annotations

import argparse
import asyncio

from iasim.reference_agent.smoke import run_smoke_agent


def main() -> None:
    """Parse CLI arguments and run the smoke loop."""
    parser = argparse.ArgumentParser(description="IASim F0 smoke agent")
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8765/mcp",
        help="streamable HTTP MCP endpoint",
    )
    parser.add_argument("--name", default="Smoke", help="agent display name")
    parser.add_argument("--ticks", type=int, default=20, help="successful moves to make")
    args = parser.parse_args()

    positions = asyncio.run(run_smoke_agent(args.url, name=args.name, ticks=args.ticks))
    final = positions[-1]
    print(f"smoke agent made {len(positions) - 1} moves; final position ({final.x}, {final.y})")


if __name__ == "__main__":
    main()
