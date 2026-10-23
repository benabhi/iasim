"""Sanitization for untrusted agent-provided text."""

from __future__ import annotations

import re

_ANSI_PATTERN = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))")


def sanitize_text(value: str) -> str:
    """Remove ANSI/control sequences and normalize text to one line."""
    without_ansi = _ANSI_PATTERN.sub("", value)
    printable = "".join(character if character.isprintable() else " " for character in without_ansi)
    return " ".join(printable.split())
