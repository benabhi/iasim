#!/usr/bin/env python3
"""Refresh the versioned Beads snapshot and publish the Git repository.

The snapshot is issue-level portability, not a full Dolt backup. The script
refuses to push when the branch or working tree is unsafe, exports the current
issues, commits the snapshot only when it changed, and then pushes Git.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

DEFAULT_SNAPSHOT = "beads/issues.jsonl"
DEFAULT_GIT_REMOTE = "origin"
DEFAULT_BRANCH = "main"


def main(argv: Sequence[str] | None = None) -> int:
    """Export Beads issues, commit the snapshot, and push Git."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print commands only")
    parser.add_argument("--snapshot", default=DEFAULT_SNAPSHOT)
    parser.add_argument("--git-remote", default=DEFAULT_GIT_REMOTE)
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    args = parser.parse_args(argv)

    root = Path(__file__).resolve().parents[1]
    snapshot = Path(args.snapshot)
    if snapshot.is_absolute() or ".." in snapshot.parts:
        print("error: --snapshot must be a repository-relative path", file=sys.stderr)
        return 1
    snapshot_path = root / snapshot

    try:
        bd = _require_tool("bd")
        git = _require_tool("git")
        _require_branch(git, root, args.branch)
        _require_clean_except_snapshot(git, root, snapshot)

        _run([bd, "export", "-o", str(snapshot_path)], root, args.dry_run)
        if not args.dry_run and not snapshot_path.is_file():
            raise RuntimeError(f"Beads export did not create {snapshot_path}")

        _run([git, "add", "--", snapshot.as_posix()], root, args.dry_run)
        if args.dry_run or _has_staged_changes(git, root, snapshot):
            _run(
                [
                    git,
                    "commit",
                    "-m",
                    "chore(beads): refresh issue snapshot",
                    "--",
                    snapshot.as_posix(),
                ],
                root,
                args.dry_run,
            )
        _run([git, "push", args.git_remote, args.branch], root, args.dry_run)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except (subprocess.CalledProcessError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        print("Dry run complete: no commands executed.")
    else:
        print("Done: Beads snapshot and Git are published.")
    return 0


def _require_tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        raise FileNotFoundError(f"required tool is not on PATH: {name}")
    return path


def _run(command: list[str], cwd: Path, dry_run: bool) -> None:
    print("+ " + subprocess.list2cmdline(command), flush=True)
    if dry_run:
        return
    executable = list(command)
    if os.name == "nt" and Path(executable[0]).suffix.lower() in {".cmd", ".bat"}:
        executable = ["cmd.exe", "/d", "/s", "/c", subprocess.list2cmdline(executable)]
    subprocess.run(executable, cwd=cwd, check=True)


def _require_branch(git: str, root: Path, branch: str) -> None:
    current = subprocess.run(
        [git, "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    if current != branch:
        raise RuntimeError(f"publish from {branch!r}; current branch is {current!r}")


def _require_clean_except_snapshot(git: str, root: Path, snapshot: Path) -> None:
    output = subprocess.run(
        [git, "status", "--porcelain"],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    snapshot_text = snapshot.as_posix()
    for line in output.splitlines():
        if snapshot_text not in line:
            raise RuntimeError(
                "working tree has changes outside the Beads snapshot; commit or stash them first"
            )


def _has_staged_changes(git: str, root: Path, snapshot: Path) -> bool:
    result = subprocess.run(
        [git, "diff", "--cached", "--quiet", "--", snapshot.as_posix()],
        cwd=root,
        check=False,
    )
    return result.returncode != 0


if __name__ == "__main__":
    raise SystemExit(main())
