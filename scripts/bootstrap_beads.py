#!/usr/bin/env python3
"""Initialize Beads from the versioned issue snapshot in a fresh clone."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    """Initialize the local database and import the tracked snapshot."""
    root = Path(__file__).resolve().parents[1]
    snapshot = root / "beads" / "issues.jsonl"
    if not snapshot.is_file():
        print(f"error: missing snapshot {snapshot}", file=sys.stderr)
        return 1
    if (root / ".beads" / "embeddeddolt").exists():
        print(
            f"Beads database already exists; run 'bd import {snapshot}' to refresh it.",
        )
        return 0

    try:
        bd = _require_tool("bd")
        git = shutil.which("git")
        if git is not None and (root / ".git").exists():
            _run([git, "config", "beads.role", "maintainer"], root)
        _run(
            [
                bd,
                "init",
                "--quiet",
                "--non-interactive",
                "--skip-agents",
                "--skip-hooks",
            ],
            root,
        )
        _run([bd, "import", str(snapshot)], root)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        print(f"error: bootstrap command failed with exit code {exc.returncode}", file=sys.stderr)
        return 1

    print("Done: Beads issues imported from beads/issues.jsonl.")
    return 0


def _require_tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise FileNotFoundError(f"required tool is not on PATH: {name}")
    return path


def _run(command: list[str], cwd: Path) -> None:
    print("+ " + subprocess.list2cmdline(command), flush=True)
    executable = list(command)
    if os.name == "nt" and Path(executable[0]).suffix.lower() in {".cmd", ".bat"}:
        executable = ["cmd.exe", "/d", "/s", "/c", subprocess.list2cmdline(executable)]
    subprocess.run(executable, cwd=cwd, check=True)


if __name__ == "__main__":
    raise SystemExit(main())
