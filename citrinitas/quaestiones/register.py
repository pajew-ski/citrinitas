"""Quaestiones: the questions that steer collection, each with indicators, thresholds and base rates (Spec C18, C19, C22)."""
from __future__ import annotations

from ..athanor import guard
from ..athanor.core import Paths, append_jsonl, iso, utcnow, write_json
from ..fontes import catalog


def _number(con, sql: str):
    res = guard.run(con, sql, max_rows=1, timeout_s=30)
    if not res["rows"] or res["rows"][0][0] is None:
        return None
    return float(res["rows"][0][0])


def evaluate(p: Paths, con, run_id: str = "") -> dict:
    """Evaluate every indicator of every open question. Nothing here sends a message (Spec C15, F11): the result is state."""
    now = utcnow()
    qs = catalog.load_quaestiones(p)
    rows = []
    for qid, q in qs.items():
        if q.get("status", "open") not in ("open", "extended"):
            continue
        for ind in q.get("indicators") or []:
            row = {"quaestio": qid, "indicator": ind["id"], "seen_at": iso(now)[:-1], "value": None, "base_rate": None,
                   "threshold": float(ind["threshold"]), "direction": ind["direction"], "triggered": False,
                   "state": "ok", "error": None, "run_id": run_id}
            try:
                row["value"] = _number(con, ind["sql"])
                br = ind.get("base_rate") or {}
                row["base_rate"] = _number(con, br["sql"]) if br.get("sql") else br.get("value")
                if row["value"] is None:
                    row["state"] = "no_data"
                else:
                    row["triggered"] = (row["value"] > row["threshold"]) if ind["direction"] == "above" \
                        else (row["value"] < row["threshold"])
            except Exception as e:  # noqa: BLE001  one broken indicator never hides the others
                row["state"], row["error"] = "error", f"{type(e).__name__}: {e}"[:240]
            rows.append(row)
    append_jsonl(p.data / "_quaestiones" / "indicators" / f"dt={now:%Y-%m-%d}" / "indicators.jsonl", rows)
    summary = {"at": iso(now), "open": sum(1 for q in qs.values() if q.get("status", "open") in ("open", "extended")),
               "overdue": catalog.overdue(qs, now.date()),
               "triggered": [f"{r['quaestio']}/{r['indicator']}" for r in rows if r["triggered"]],
               "no_data": [f"{r['quaestio']}/{r['indicator']}" for r in rows if r["state"] == "no_data"],
               "errors": [f"{r['quaestio']}/{r['indicator']}: {r['error']}" for r in rows if r["state"] == "error"]}
    write_json(p.state / "quaestiones.json", summary)
    return summary
