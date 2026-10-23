"""Command-line entry point for IASim."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from iasim import MCP_PROTOCOL_VERSION, __version__


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level IASim argument parser."""
    parser = argparse.ArgumentParser(
        prog="iasim",
        description="Deterministic multi-agent survival simulation sandbox.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"IASim {__version__} (MCP protocol {MCP_PROTOCOL_VERSION})",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Parse command-line arguments and return the process exit code."""
    parser = build_parser()
    parser.parse_args(argv)
    print("IASim scaffold ready; simulation not implemented yet.")
    return 0
