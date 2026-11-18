"""The catalogue of sources and the register of questions, loaded from YAML and checked (Spec C2, C3, C6, C12, C18, C19, C23)."""
from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

from ..athanor import licenses
from ..athanor.core import CLASSES, DOMAINS, LEVELS, RELIABILITY, REPO, TIMES, Paths, write_json

CATALOG = REPO / "catalog"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_fontes(path: Path | None = None) -> dict:
    return _load(path or CATALOG / "fontes.yaml").get("fontes", {})


def load_quaestiones(p: Paths | None = None, path: Path | None = None) -> dict:
    """Questions shipped with the repository plus private ones under etc/quaestiones.d on the node."""
    q = dict(_load(path or CATALOG / "quaestiones.yaml").get("quaestiones", {}))
    if p is not None and (p.etc / "quaestiones.d").is_dir():
        for f in sorted((p.etc / "quaestiones.d").glob("*.yaml")):
            q.update(_load(f).get("quaestiones", {}))
    return q


def lint(fontes: dict, quaestiones: dict) -> list[str]:
    """Everything that can be checked without judgement. An empty list means the catalogue is sound."""
    err: list[str] = []
    for fid, f in fontes.items():
        where = f"fontes.{fid}"
        status = f.get("status", "active")
        if status not in ("active", "planned"):
            err.append(f"{where}: status must be active or planned")
        if not f.get("name") or not f.get("homepage"):
            err.append(f"{where}: name and homepage are required")
        if f.get("license") not in licenses.LICENSES:
            err.append(f"{where}: unknown license {f.get('license')!r}")
        if f.get("access") not in ("open", "key", "account"):
            err.append(f"{where}: access must be open, key or account")
        cells = f.get("cells") or []
        if not cells:
            err.append(f"{where}: no cells declared")
        for c in cells:
            if c.get("domain") not in DOMAINS:
                err.append(f"{where}: unknown domain {c.get('domain')!r}")
            if c.get("classis") not in CLASSES:
                err.append(f"{where}: unknown class {c.get('classis')!r}")
            if not c.get("levels") or set(c["levels"]) - set(LEVELS):
                err.append(f"{where}: levels must be a subset of {LEVELS}")
            if not c.get("times") or set(c["times"]) - set(TIMES):
                err.append(f"{where}: times must be a subset of {TIMES}")
        if status != "active":
            continue
        # Spec C23: the source is rated on its own, with a reason and a date
        if f.get("reliability") not in RELIABILITY or not f.get("reliability_reason"):
            err.append(f"{where}: reliability A to F with a reason is required")
        # Spec C18: a source without a question only fills storage
        qs = f.get("quaestiones") or []
        if not qs:
            err.append(f"{where}: refers to no question")
        for q in qs:
            if q not in quaestiones:
                err.append(f"{where}: refers to unknown question {q!r}")
        b = f.get("budget") or {}
        for k in ("disk_gb", "runtime_s_day", "download_mb_day"):  # Spec C42
            if not isinstance(b.get(k), (int, float)):
                err.append(f"{where}: budget.{k} is required")
    for qid, q in quaestiones.items():
        where = f"quaestiones.{qid}"
        if not q.get("text"):
            err.append(f"{where}: text is required")
        if q.get("status", "open") not in ("open", "answered", "extended", "dropped"):
            err.append(f"{where}: status must be open, answered, extended or dropped")
        for d in q.get("domains") or [None]:
            if d not in DOMAINS:
                err.append(f"{where}: unknown domain {d!r}")
        if q.get("level") not in LEVELS or q.get("time") not in TIMES:
            err.append(f"{where}: level and time are required")
        try:  # Spec C22: every question has a day on which it is answered, extended or dropped
            date.fromisoformat(str(q.get("due")))
        except ValueError:
            err.append(f"{where}: due date (YYYY-MM-DD) is required")
        inds = q.get("indicators") or []
        if not inds:
            err.append(f"{where}: no indicator")
        for i in inds:  # Spec C19: a warning is only testable if its trigger is fixed beforehand
            iw = f"{where}.{i.get('id')}"
            if not i.get("id") or not i.get("sql"):
                err.append(f"{iw}: id and sql are required")
            if not isinstance(i.get("threshold"), (int, float)) or i.get("direction") not in ("above", "below"):
                err.append(f"{iw}: threshold and direction (above or below) are required")
            br = i.get("base_rate") or {}
            if not (br.get("sql") or (isinstance(br.get("value"), (int, float)) and br.get("source"))):
                err.append(f"{iw}: base_rate needs sql, or value with source")
    return err


def overdue(quaestiones: dict, today: date) -> list[str]:
    return sorted(q for q, v in quaestiones.items()
                  if v.get("status", "open") in ("open", "extended") and str(v.get("due")) < today.isoformat())


def cells(fontes: dict) -> list[dict]:
    out = []
    for fid, f in fontes.items():
        for c in f.get("cells") or []:
            for level in c.get("levels", []):
                for t in c.get("times", []):
                    out.append({"fons": fid, "status": f.get("status", "active"), "domain": c["domain"],
                                "classis": c["classis"], "level": level, "time": t})
    return out


def dump_meta(p: Paths, fontes: dict | None = None, quaestiones: dict | None = None) -> None:
    """Write the catalogue where SQL can read it."""
    fontes = load_fontes() if fontes is None else fontes
    quaestiones = load_quaestiones(p) if quaestiones is None else quaestiones
    write_json(p.meta / "fontes.json", [
        {"id": k, "name": v.get("name"), "status": v.get("status", "active"), "license": v.get("license"),
         "access": v.get("access"), "cadence": v.get("cadence"), "reliability": v.get("reliability"),
         "reliability_reason": v.get("reliability_reason"), "homepage": v.get("homepage"),
         "quaestiones": v.get("quaestiones") or []} for k, v in fontes.items()])
    write_json(p.meta / "cells.json", cells(fontes))
    write_json(p.meta / "quaestiones.json", [
        {"id": k, "text": v.get("text"), "status": v.get("status", "open"), "domains": v.get("domains") or [],
         "level": v.get("level"), "time": v.get("time"), "due": str(v.get("due"))} for k, v in quaestiones.items()])
