"""The ledger of expectations: every forecast is stored with a criterion and scored after its date (Spec C29).

A forecast that is never scored is an opinion. The Brier score is the mean squared distance between the stated
probability and the outcome (0 or 1): 0 is perfect, 0.25 is what always saying 50 % earns.
"""
from __future__ import annotations

import json
import uuid
from datetime import date

from ..athanor.core import Paths, append_jsonl, iso, utcnow


def _file(p: Paths):
    return p.data / "_quaestiones" / "expectations" / "dt=all" / "ledger.jsonl"


def _events(p: Paths) -> list[dict]:
    f = _file(p)
    return [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()] if f.exists() else []


def add(p: Paths, *, source: str, statement: str, criterion: str, probability: float, due: str,
        quaestio: str | None = None) -> str:
    if not 0.0 <= float(probability) <= 1.0:
        raise ValueError("probability must lie between 0 and 1")
    if not criterion or not criterion.strip():
        raise ValueError("an expectation needs a resolution criterion")
    date.fromisoformat(due)
    eid = uuid.uuid4().hex[:12]
    append_jsonl(_file(p), [{"event": "made", "id": eid, "quaestio": quaestio, "source": source,
                             "statement": statement, "criterion": criterion, "probability": float(probability),
                             "made_at": iso(utcnow())[:-1], "due": due, "outcome": None, "resolved_at": None,
                             "evidence": None}])
    return eid


def resolve(p: Paths, eid: str, outcome: bool, evidence: str) -> None:
    made = {e["id"]: e for e in _events(p) if e["event"] == "made"}
    if eid not in made:
        raise KeyError(eid)
    if not evidence:
        raise ValueError("a resolution needs evidence: a row_id or a URL")
    append_jsonl(_file(p), [{**made[eid], "event": "resolved", "outcome": int(bool(outcome)),
                             "resolved_at": iso(utcnow())[:-1], "evidence": evidence}])


def current(p: Paths) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for e in _events(p):
        out[e["id"]] = e
    return out


def scores(p: Paths) -> dict:
    """Brier score per source over all resolved expectations, and what is due without a resolution."""
    by: dict[str, list[float]] = {}
    unresolved_due = []
    today = utcnow().date().isoformat()
    for e in current(p).values():
        if e["event"] == "resolved":
            by.setdefault(e["source"], []).append((e["probability"] - e["outcome"]) ** 2)
        elif e["due"] < today:
            unresolved_due.append(e["id"])
    return {"brier": {s: {"n": len(v), "score": round(sum(v) / len(v), 4)} for s, v in by.items()},
            "due_unresolved": unresolved_due}
