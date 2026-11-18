"""Tabula: the coverage matrix domain x level x time x class. An empty cell is a blind spot (Spec C7)."""
from __future__ import annotations

from datetime import timedelta

from ..athanor.core import CLASSES, DOMAINS, LEVELS, TIMES, Paths, append_jsonl, iso, utcnow, write_json
from ..fontes import catalog

LIVE_DAYS, HISTORIC_DAYS = 3, 365


def observed(con) -> set[tuple]:
    """Which (fons, domain, class, level, time) cells have rows in the lake."""
    now = utcnow()
    live, hist = now - timedelta(days=LIVE_DAYS), now - timedelta(days=HISTORIC_DAYS)
    rows = con.execute("""SELECT fons, domain, classis,
        count(*) FILTER (recorded_at >= $live), count(iso3) FILTER (recorded_at >= $live),
        count(adm1) FILTER (recorded_at >= $live), count(h3_5) FILTER (recorded_at >= $live),
        count(*) FILTER (t_from < $hist), count(iso3) FILTER (t_from < $hist),
        count(adm1) FILTER (t_from < $hist), count(h3_5) FILTER (t_from < $hist),
        count(*) FILTER (t_from > $now), count(iso3) FILTER (t_from > $now),
        count(adm1) FILTER (t_from > $now), count(h3_5) FILTER (t_from > $now)
        FROM facta GROUP BY 1, 2, 3""", {"live": live, "hist": hist, "now": now}).fetchall()
    out = set()
    for fons, domain, classis, *counts in rows:
        for ti, t in enumerate(TIMES):
            for li, level in enumerate(LEVELS):
                if counts[ti * 4 + li]:
                    out.add((fons, domain, classis, level, t))
    return out


def build(fontes: dict, seen: set[tuple]) -> list[dict]:
    cells = catalog.cells(fontes)
    rows = []
    for domain in DOMAINS:
        for level in LEVELS:
            for t in TIMES:
                for classis in CLASSES:
                    here = [c for c in cells if (c["domain"], c["level"], c["time"], c["classis"]) == (domain, level, t, classis)]
                    declared = sorted(c["fons"] for c in here if c["status"] == "active")
                    planned = sorted(c["fons"] for c in here if c["status"] == "planned")
                    obs = sorted(f for f in declared if (f, domain, classis, level, t) in seen)
                    state = "ok" if obs else "unobserved" if declared else "planned" if planned else "empty"
                    rows.append({"domain": domain, "level": level, "time": t, "classis": classis,
                                 "declared": declared, "planned": planned, "observed": obs, "state": state})
    return rows


def verdict(rows: list[dict], domain: str, level: str, t: str) -> dict:
    """A (domain, level, time) is blind without any observed class, thin with one source or with reports only."""
    cell = [r for r in rows if (r["domain"], r["level"], r["time"]) == (domain, level, t)]
    classes = sorted(r["classis"] for r in cell if r["state"] == "ok")
    sources = sorted({f for r in cell for f in r["observed"]})
    if not classes:
        v = "blind"
    elif len(sources) == 1 or classes == ["reported"]:
        v = "thin"
    else:
        v = "covered"
    return {"verdict": v, "classes": classes, "fontes": sources,
            "planned": sorted({f for r in cell for f in r["planned"]})}


def run(p: Paths, con) -> dict:
    now = utcnow()
    fontes = catalog.load_fontes()
    rows = build(fontes, observed(con))
    append_jsonl(p.data / "_tabula" / f"dt={now:%Y-%m-%d}" / "matrix.jsonl", [{"seen_at": iso(now)[:-1], **r} for r in rows])
    triples = [(d, lv, t) for d in DOMAINS for lv in LEVELS for t in TIMES]
    verdicts = {k: verdict(rows, *k)["verdict"] for k in triples}
    by_q = {}
    for qid, q in catalog.load_quaestiones(p).items():
        if q.get("status", "open") in ("open", "extended"):
            by_q[qid] = {d: verdict(rows, d, q["level"], q["time"]) for d in q.get("domains", [])}
    summary = {"at": iso(now), "cells": len(triples),
               "covered": sum(v == "covered" for v in verdicts.values()),
               "thin": sum(v == "thin" for v in verdicts.values()),
               "blind": sum(v == "blind" for v in verdicts.values()), "quaestiones": by_q}
    write_json(p.state / "tabula.json", summary)
    return summary
