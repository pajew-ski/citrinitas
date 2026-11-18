"""Daily upkeep: compaction and pruning, drift (Spec C28) and budget (Spec C42)."""
from __future__ import annotations

import hashlib
import json
import statistics
from datetime import timedelta

from ..fontes import catalog
from ..fontes.base import registry
from .core import Paths, append_jsonl, iso, partitions, read_json, sql_str, tree_bytes, utcnow, write_json

ROWS_LOW, ROWS_HIGH, NULL_JUMP = 0.2, 5.0, 30.0


def measure_drift(p: Paths, con) -> list[dict]:
    """Row count, schema hash and worst null share of yesterday's partition of every table."""
    now = utcnow()
    day = now.date() - timedelta(days=1)
    rows = []
    for fons in registry().values():
        for table in fons.tables:
            d = p.data / fons.id / table / f"dt={day.isoformat()}"
            if not d.is_dir() or not any(d.glob("*.parquet")):
                continue
            src = f"read_parquet({sql_str(d / '*.parquet')}, union_by_name=true)"
            desc = con.execute(f"DESCRIBE SELECT * FROM {src}").fetchall()
            schema = hashlib.sha256(";".join(f"{r[0]}:{r[1]}" for r in desc).encode()).hexdigest()[:16]
            n = con.execute(f"SELECT count(*) FROM {src}").fetchone()[0]
            summ = con.execute(f"SELECT column_name, CAST(null_percentage AS DOUBLE) FROM (SUMMARIZE SELECT * FROM {src})").fetchall()
            worst = max(summ, key=lambda r: r[1] or 0.0) if summ else (None, 0.0)
            rows.append({"seen_at": iso(now)[:-1], "fons": fons.id, "tabula": table, "day": day.isoformat(), "n_rows": n,
                         "schema_hash": schema, "max_null_pct": float(worst[1] or 0.0), "worst_column": worst[0]})
    append_jsonl(p.meta / "drift" / f"dt={now:%Y-%m-%d}" / "drift.jsonl", rows)
    return rows


def judge_drift(history: list[dict], today: list[dict]) -> dict[str, list[str]]:
    """Compare today's measurements with up to seven earlier ones per table. Returns {fons: [findings]}."""
    out: dict[str, list[str]] = {}
    for row in today:
        prev = [h for h in history if h["fons"] == row["fons"] and h["tabula"] == row["tabula"] and h["day"] < row["day"]]
        prev = sorted(prev, key=lambda h: h["day"])[-7:]
        if not prev:
            continue
        found = []
        med = statistics.median(h["n_rows"] for h in prev)
        if med and not (ROWS_LOW * med <= row["n_rows"] <= ROWS_HIGH * med):
            found.append(f"{row['tabula']}: {row['n_rows']} rows against a median of {med:g}")
        if row["schema_hash"] != prev[-1]["schema_hash"]:
            found.append(f"{row['tabula']}: schema changed")
        base_null = statistics.median(h["max_null_pct"] for h in prev)
        if row["max_null_pct"] - base_null > NULL_JUMP:
            found.append(f"{row['tabula']}: {row['worst_column']} is {row['max_null_pct']:.0f} % null, was {base_null:.0f} %")
        if found:
            out.setdefault(row["fons"], []).extend(found)
    return out


def measure_budget(p: Paths, con, fontes: dict) -> dict:
    """Disk, run time and download volume of each source over 24 hours against its budget."""
    out = {}
    since = utcnow() - timedelta(days=1)
    used = {r[0]: r[1:] for r in con.execute(
        "SELECT fons, sum(seconds), sum(bytes_in) FILTER (phase = 'fetch') FROM prov_runs WHERE started_at >= ? GROUP BY 1",
        [since]).fetchall()}
    for fid, f in fontes.items():
        if f.get("status", "active") != "active":
            continue
        b = f.get("budget") or {}
        secs, down = used.get(fid, (0.0, 0))
        m = {"disk_gb": round(tree_bytes(p.data / fid) / 1e9, 6), "runtime_s_day": round(secs or 0.0, 1),
             "download_mb_day": round((down or 0) / 1e6, 1)}
        m["over"] = [k for k in ("disk_gb", "runtime_s_day", "download_mb_day") if k in b and m[k] > b[k]]
        m["budget"] = {k: b.get(k) for k in ("disk_gb", "runtime_s_day", "download_mb_day")}
        out[fid] = m
    return out


def run(p: Paths, con) -> dict:
    fontes = catalog.load_fontes()
    catalog.dump_meta(p, fontes)
    info = {"at": iso(utcnow()), "maintain": {}, "drift": {}, "budget": {}}
    for fons in registry().values():
        try:
            info["maintain"][fons.id] = fons.maintain(p, con)
        except Exception as e:  # noqa: BLE001
            info["maintain"][fons.id] = {"error": f"{type(e).__name__}: {e}"[:200]}
    history = []
    for _dt, d in partitions(p.meta / "drift")[-10:]:
        for line in (d / "drift.jsonl").read_text(encoding="utf-8").splitlines() if (d / "drift.jsonl").exists() else []:
            history.append(json.loads(line))
    try:
        info["drift"] = judge_drift(history, measure_drift(p, con))
    except Exception as e:  # noqa: BLE001
        info["drift_error"] = f"{type(e).__name__}: {e}"[:200]
    try:
        info["budget"] = measure_budget(p, con, fontes)
    except Exception as e:  # noqa: BLE001
        info["budget_error"] = f"{type(e).__name__}: {e}"[:200]
    write_json(p.state / "upkeep.json", info)
    return info


def last(p: Paths) -> dict:
    return read_json(p.state / "upkeep.json", {})
