"""Specillum: the probe for gaps nobody listed (Spec C8).

Where media report densely and no measured or official fact exists, a source is missing. The probe ranks
those places per domain. It names where to look, never what is true there.
"""
from __future__ import annotations

from datetime import timedelta

from ..athanor.core import Paths, append_jsonl, iso, utcnow

DAYS = 30
TOP = 50


def run(p: Paths, con) -> dict:
    now = utcnow()
    since = now - timedelta(days=DAYS)
    rows = con.execute(f"""
        WITH c AS (SELECT domain, iso3, sum(value) FILTER (classis = 'reported') AS reported,
                          count(*) FILTER (classis IN ('measured', 'official')) AS hard_facts
                   FROM facta WHERE recorded_at >= ? AND dt >= ? AND iso3 IS NOT NULL GROUP BY 1, 2),
             q AS (SELECT domain, quantile_cont(reported, 0.75) AS q75 FROM c WHERE reported IS NOT NULL GROUP BY 1)
        SELECT c.domain, c.iso3, c.reported, c.hard_facts,
               row_number() OVER (PARTITION BY c.domain ORDER BY c.reported DESC) AS rank
        FROM c JOIN q USING (domain) WHERE c.hard_facts = 0 AND c.reported >= q.q75
        QUALIFY rank <= {TOP} ORDER BY c.domain, rank""", [since, since.date()]).fetchall()
    out = [{"seen_at": iso(now)[:-1], "domain": r[0], "iso3": r[1], "reported": r[2], "hard_facts": r[3], "rank": r[4]}
           for r in rows]
    append_jsonl(p.data / "_specillum" / f"dt={now:%Y-%m-%d}" / "probe.jsonl", out)
    return {"at": iso(now), "candidates": len(out)}
