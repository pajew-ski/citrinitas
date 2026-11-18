#!/usr/bin/env python3
"""Check SPEC.md against itself and against the code.

- every requirement (`**C12 Title.**`) has a unique ID and a status
- every ID marked built or partial has at least one marker `Spec <ID>` in code, tests or deploy files
- every marker names an ID that exists
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ID = r"[CF]\d+"
MARKER = re.compile(rf"Spec ((?:{ID})(?:,\s*{ID})*)")


def main() -> int:
    spec = (ROOT / "SPEC.md").read_text(encoding="utf-8")
    defined = re.findall(rf"^\*\*({ID}) ", spec, re.M)
    errors = [f"{i} is defined twice" for i in sorted({i for i in defined if defined.count(i) > 1})]
    status_block = spec.split("## Status", 1)[1].split("## Decided", 1)[0]
    status: dict[str, str] = {}
    for line in status_block.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 2 and cells[0] in ("built, tested", "partial", "planned", "external"):
            for i in re.findall(rf"\b{ID}\b", cells[1]):
                if i in status:
                    errors.append(f"{i} has two statuses")
                status[i] = cells[0]
    errors += [f"{i} has no status" for i in defined if i not in status]
    errors += [f"status names {i}, which is not defined" for i in status if i not in defined]
    marked: set[str] = set()
    for pattern in ("citrinitas/**/*.py", "tests/**/*.py", "deploy/**/*", "catalog/*.yaml"):
        for f in ROOT.glob(pattern):
            if f.is_file() and f.suffix != ".zip":
                for m in MARKER.findall(f.read_text(encoding="utf-8", errors="replace")):
                    for i in re.split(r",\s*", m):
                        marked.add(i)
                        if i not in defined:
                            errors.append(f"{f.relative_to(ROOT)}: marker for {i}, which is not defined")
    errors += [f"{i} is {s} but no file carries 'Spec {i}'" for i, s in status.items()
               if s in ("built, tested", "partial") and i not in marked]
    for e in errors:
        print(f"::error::{e}")
    if not errors:
        print(f"spec is sound: {len(defined)} requirements, {sum(s == 'built, tested' for s in status.values())} built, "
              f"{sum(s == 'partial' for s in status.values())} partial, {sum(s == 'planned' for s in status.values())} planned")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
