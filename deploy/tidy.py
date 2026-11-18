#!/usr/bin/env python3
"""Remove old releases and unused virtual environments. Called by install.sh after a successful switch.

Deletes only directories below <home>/releases and <home>/venvs whose names look like a commit or a lock
hash, never the release `current` points to, and keeps the three newest releases.
"""
import re
import shutil
import sys
from pathlib import Path

KEEP = 3
COMMIT = re.compile(r"[0-9a-f]{40}")
LEFTOVER = re.compile(r"[0-9a-f]{40}\.old\.\d+")
LOCK = re.compile(r"[0-9a-f]{16}")


def main(home: str) -> int:
    root = Path(home).resolve()
    releases_dir, venvs_dir = root / "releases", root / "venvs"
    if root == Path("/") or not releases_dir.is_dir():
        return 1
    current = (root / "current").resolve()
    releases = sorted((d for d in releases_dir.iterdir() if d.is_dir() and COMMIT.fullmatch(d.name)),
                      key=lambda d: d.stat().st_mtime, reverse=True)
    keep = {current} | {d.resolve() for d in releases[:KEEP]}
    for d in releases_dir.iterdir():
        if not d.is_dir():
            continue
        if LEFTOVER.fullmatch(d.name) or (COMMIT.fullmatch(d.name) and d.resolve() not in keep):
            shutil.rmtree(d, ignore_errors=True)
    used = {(d / ".venv").resolve() for d in releases_dir.iterdir() if (d / ".venv").exists()}
    if venvs_dir.is_dir():
        for v in venvs_dir.iterdir():
            if v.is_dir() and LOCK.fullmatch(v.name) and v.resolve() not in used:
                shutil.rmtree(v, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "/srv/citrinitas"))
