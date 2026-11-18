"""The state of the node in one document. It replaces the shell (Spec C17) and carries the state of every source (Spec C10)."""
from __future__ import annotations

import subprocess

from .. import SCHEMA_VERSION, __version__
from ..fontes import catalog
from . import upkeep
from .core import Paths, commit, disk, iso, read_json, utcnow

UNITS = ("citrinitas-athanor", "citrinitas-fetch", "citrinitas-parse", "citrinitas-daily", "citrinitas-pull")


def _memory() -> dict:
    try:
        with open("/proc/meminfo", encoding="ascii") as f:
            kv = dict(line.split(":", 1) for line in f)
        total, avail = int(kv["MemTotal"].split()[0]), int(kv["MemAvailable"].split()[0])
        return {"total_mb": total // 1024, "available_mb": avail // 1024}
    except (OSError, KeyError, ValueError):
        return {}


def _journal(unit: str, lines: int = 50) -> list[str]:
    try:
        r = subprocess.run(["journalctl", "-u", unit, "-n", str(lines), "--no-pager", "-o", "short-iso"],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.splitlines()[-lines:] if r.returncode == 0 else [f"journalctl: {r.stderr.strip()[:200]}"]
    except (OSError, subprocess.SubprocessError) as e:
        return [f"journalctl: {type(e).__name__}"]


def fons_state(st: dict, drift: list, over: list) -> str:
    if not st:
        return "idle"
    if any(not ph.get("ok", True) for ph in st.values() if isinstance(ph, dict)):
        return "error"
    if drift:
        return "disturbed"
    if over:
        return "over_budget"
    return "ok"


def build(p: Paths, *, logs: bool = True) -> dict:
    up = upkeep.last(p)
    fontes = {}
    for fid, f in catalog.load_fontes().items():
        if f.get("status", "active") != "active":
            continue
        st = read_json(p.state / "fontes" / f"{fid}.json", {})
        drift = (up.get("drift") or {}).get(fid, [])
        budget = (up.get("budget") or {}).get(fid, {})
        fontes[fid] = {"state": fons_state(st, drift, budget.get("over", [])), "phases": st, "drift": drift,
                       "budget": budget}
    doc = {"ok": True, "at": iso(utcnow()), "version": __version__, "schema_version": SCHEMA_VERSION,
           "commit": commit(), "rejected": read_json(p.state / "rejected.json", None),
           "sandbox": read_json(p.state / "sandbox.json", None), "disk": disk(p), "memory": _memory(),
           "fontes": fontes, "quaestiones": read_json(p.state / "quaestiones.json", None),
           "tabula": read_json(p.state / "tabula.json", None), "upkeep_at": up.get("at")}
    if logs:
        doc["logs"] = {u: _journal(u) for u in UNITS}
    return doc
