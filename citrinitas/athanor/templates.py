"""Named queries with typed parameters (Spec F6). Cards, automations and scripts use these; free SQL is for analysts (Spec C9)."""
from __future__ import annotations

from datetime import datetime, timedelta

from .core import CLASSES, DOMAINS, utcnow

MAX_ROWS = 500
TIMEOUT_S = 20


class BadRequest(Exception):
    pass


def _ts(v, name: str) -> datetime:
    if isinstance(v, datetime):
        return v
    try:
        return datetime.fromisoformat(str(v).replace("Z", "")).replace(tzinfo=None)
    except ValueError as e:
        raise BadRequest(f"{name}: not an ISO timestamp: {v!r}") from e


def _window(q: dict, default_days: int = 7) -> tuple[datetime, datetime]:
    to = _ts(q["to"], "to") if q.get("to") else utcnow()
    frm = _ts(q["from"], "from") if q.get("from") else to - timedelta(days=default_days)
    if frm >= to:
        raise BadRequest("from must lie before to")
    return frm, to


def _choice(q: dict, key: str, allowed, default=None):
    v = q.get(key, default)
    if v is not None and v not in allowed:
        raise BadRequest(f"{key}: one of {', '.join(map(str, allowed))}")
    return v


def _known(q: dict, allowed: set) -> None:
    extra = set(q) - allowed
    if extra:
        raise BadRequest(f"unknown parameter: {', '.join(sorted(extra))}")


def _facta_filters(q: dict) -> tuple[str, list]:
    sql, args = "", []
    _choice(q, "domain", DOMAINS)
    _choice(q, "classis", CLASSES)
    for key in ("fons", "domain", "classis", "iso3", "measure"):
        if q.get(key) is not None:
            sql += f" AND {key} = ?"
            args.append(str(q[key]))
    return sql, args


def series(q: dict):
    """Sum and count over time. Classes stay in separate rows: they are never added up (Spec C3)."""
    _known(q, {"from", "to", "bucket", "time", "fons", "domain", "classis", "iso3", "measure"})
    frm, to = _window(q)
    bucket = _choice(q, "bucket", ("hour", "day", "week", "month"), "day")
    col = "t_reported" if _choice(q, "time", ("reported", "reference"), "reported") == "reported" else "t_from"
    where, args = _facta_filters(q)
    prune = " AND dt >= ? AND dt <= ?" if col == "t_reported" else ""
    pargs = [(frm - timedelta(days=1)).date(), (to + timedelta(days=1)).date()] if prune else []
    return (f"SELECT date_trunc('{bucket}', {col}) AS t, classis, sum(value) AS value, count(*) AS n "
            f"FROM facta WHERE {col} >= ? AND {col} < ?{prune}{where} GROUP BY 1, 2 ORDER BY 1, 2",
            [frm, to, *pargs, *args])


def ranking(q: dict):
    _known(q, {"from", "to", "by", "limit", "fons", "domain", "classis", "iso3", "measure"})
    frm, to = _window(q)
    by = _choice(q, "by", ("iso3", "domain", "fons", "measure", "adm1", "h3_5"), "iso3")
    limit = max(1, min(int(q.get("limit", 50)), MAX_ROWS))
    where, args = _facta_filters(q)
    return (f"SELECT {by}, classis, sum(value) AS value, count(*) AS n FROM facta "
            f"WHERE t_reported >= ? AND t_reported < ? AND dt >= ? AND dt <= ? AND {by} IS NOT NULL{where} "
            f"GROUP BY 1, 2 ORDER BY value DESC LIMIT {limit}",
            [frm, to, (frm - timedelta(days=1)).date(), (to + timedelta(days=1)).date(), *args])


def lang_gap(q: dict):
    """Countries by documents in all other languages against one language: covered elsewhere, absent here."""
    _known(q, {"from", "to", "lang", "min_docs", "limit"})
    frm, to = _window(q, 1)
    lang = str(q.get("lang", "deu"))
    limit = max(1, min(int(q.get("limit", 100)), MAX_ROWS))
    return ("SELECT iso3, sum(n_docs) FILTER (lang <> ?) AS docs_elsewhere, coalesce(sum(n_docs) FILTER (lang = ?), 0) AS docs_lang, "
            "count(DISTINCT lang) AS languages FROM fama_hourly_geo "
            "WHERE hour >= ? AND hour < ? AND dt >= ? AND dt <= ? AND iso3 IS NOT NULL GROUP BY 1 "
            f"HAVING docs_elsewhere >= ? ORDER BY docs_lang ASC, docs_elsewhere DESC LIMIT {limit}",
            [lang, lang, frm, to, frm.date(), to.date(), int(q.get("min_docs", 20))])


def articles(q: dict):
    _known(q, {"from", "to", "theme", "fips", "lang", "source", "limit"})
    frm, to = _window(q, 1)
    limit = max(1, min(int(q.get("limit", 100)), MAX_ROWS))
    where, args = "", []
    if q.get("theme"):
        where += " AND list_contains(themes, ?)"
        args.append(str(q["theme"]))
    if q.get("fips"):
        where += " AND list_contains(loc_fips, ?)"
        args.append(str(q["fips"]))
    if q.get("lang"):
        where += " AND lang = ?"
        args.append(str(q["lang"]))
    if q.get("source"):
        where += " AND source_name = ?"
        args.append(str(q["source"]))
    return ("SELECT 'fama:g:' || record_id AS row_id, ts, source_name, lang, tone, url, themes[:12] AS themes, loc_fips "
            f"FROM fama_gkg WHERE ts >= ? AND ts < ? AND dt >= ? AND dt <= ?{where} ORDER BY ts DESC LIMIT {limit}",
            [frm, to, frm.date(), to.date(), *args])


def anomalies(q: dict):
    """Spec C27: a country stands out only against the baseline of the same source, as a share of the day's total.

    A day with twice the volume and the same shares yields nothing; that is the point.
    """
    _known(q, {"day", "days", "z", "min_articles", "roots"})
    day = _ts(q["day"], "day").date() if q.get("day") else (utcnow() - timedelta(days=1)).date()
    days = max(7, min(int(q.get("days", 28)), 120))
    where, args = "", []
    if q.get("roots"):
        roots = [str(r) for r in q["roots"]]
        where = " AND root_code IN (" + ",".join("?" * len(roots)) + ")"
        args = roots
    start = day - timedelta(days=days)
    return (f"""WITH d AS (SELECT CAST(hour AS DATE) AS day, iso3, sum(n_articles) AS n FROM fama_hourly_events
                  WHERE dt >= ? AND dt <= ? AND iso3 IS NOT NULL{where} GROUP BY 1, 2),
             t AS (SELECT day, sum(n) AS total FROM d GROUP BY 1),
             s AS (SELECT d.day, d.iso3, d.n, d.n / t.total AS share FROM d JOIN t USING (day)),
             b AS (SELECT iso3, median(share) AS base, mad(share) AS spread, count(*) AS days FROM s WHERE day < ? GROUP BY 1)
        SELECT s.iso3, s.day, s.n AS articles, round(s.share, 6) AS share, round(b.base, 6) AS base_share,
               round(0.6745 * (s.share - b.base) / NULLIF(b.spread, 0), 2) AS z, b.days AS base_days
        FROM s JOIN b USING (iso3) WHERE s.day = ? AND b.days >= 7 AND s.n >= ?
          AND 0.6745 * (s.share - b.base) / NULLIF(b.spread, 0) > ? ORDER BY z DESC LIMIT {MAX_ROWS}""",
            [start, day, *args, day, day, int(q.get("min_articles", 50)), float(q.get("z", 3.5))])


def provenance(q: dict):
    """Spec C21: from a row back to the run, the code commit and the raw files with their hashes."""
    _known(q, {"row_id"})
    if not q.get("row_id"):
        raise BadRequest("row_id is required")
    return ("SELECT f.row_id, f.fons, f.run_id, r.commit, r.started_at, i.url AS input_url, i.sha256 AS input_sha256, "
            "i.fetched_at AS input_fetched_at FROM facta_all f JOIN prov_runs r USING (run_id), "
            "LATERAL (SELECT unnest(r.inputs, recursive := true)) i WHERE f.row_id = ? LIMIT 200", [str(q["row_id"])])


def _latest(view: str, order: str):
    def fn(q: dict):
        _known(q, set())
        return (f"SELECT * FROM {view} WHERE seen_at = (SELECT max(seen_at) FROM {view}) ORDER BY {order} "
                f"LIMIT {MAX_ROWS}", [])
    return fn


def fontes(q: dict):
    _known(q, set())
    return "SELECT * FROM fontes ORDER BY status, id", []


TEMPLATES = {"series": series, "ranking": ranking, "lang_gap": lang_gap, "articles": articles, "anomalies": anomalies,
             "provenance": provenance, "fontes": fontes,
             "coverage": _latest("tabula", "domain, level, time, classis"),
             "indicators": _latest("indicators", "quaestio, indicator"),
             "probe": _latest("specillum", "rank")}


def render(name: str, params: dict | None):
    if name not in TEMPLATES:
        raise BadRequest(f"unknown template {name!r}; known: {', '.join(sorted(TEMPLATES))}, status")
    if params is not None and not isinstance(params, dict):
        raise BadRequest("params must be an object")
    return TEMPLATES[name](params or {})
