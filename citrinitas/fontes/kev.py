"""CISA Known Exploited Vulnerabilities catalogue: official, CC0, revisable.

The catalogue is republished whole. Only new or changed entries become rows, so earlier states stay
readable and facta_asof() answers what the catalogue said on a given day (Spec C20).
"""
from __future__ import annotations

import hashlib
import json

from .. import SCHEMA_VERSION
from ..athanor.core import Paths, Run, iso, read_json, sha256_file, sql_str, utcnow, write_json, write_parquet
from .base import Fons, http_download

URL = "https://raw.githubusercontent.com/cisagov/kev-data/develop/known_exploited_vulnerabilities.json"
REQUIRED = ("cveID", "vendorProject", "product", "vulnerabilityName", "dateAdded", "shortDescription",
            "requiredAction", "dueDate")


class Kev(Fons):
    id = "kev"
    revisable = True
    tables = {"entries": (("cve_id", "VARCHAR"), ("vendor", "VARCHAR"), ("product", "VARCHAR"),
                          ("name", "VARCHAR"), ("date_added", "DATE"), ("due_date", "DATE"),
                          ("ransomware", "VARCHAR"), ("description", "VARCHAR"), ("catalog_version", "VARCHAR"),
                          ("entry_hash", "VARCHAR"), ("run_id", "VARCHAR"), ("fetched_at", "TIMESTAMP"),
                          ("schema_version", "INTEGER"))}

    def fetch(self, p: Paths, run: Run) -> dict:
        spool = p.spool / self.id
        dest = spool / f"{utcnow():%Y%m%dT%H%M%S}.json"
        size = http_download(URL, dest, limit=64 << 20)
        digest = sha256_file(dest)
        st = read_json(p.state / self.id / "fetch.json", {})
        if st.get("sha256") == digest:
            dest.unlink()
            return {"changed": False}
        run.log_raw(URL, digest, size)
        write_json(p.state / self.id / "fetch.json", {"sha256": digest, "at": iso(utcnow())})
        return {"changed": True, "bytes": size}

    def parse(self, p: Paths, run: Run) -> dict:
        import duckdb
        spool = p.spool / self.id
        hashes_path = p.state / self.id / "hashes.json"
        hashes: dict = read_json(hashes_path, {})
        total = 0
        for f in sorted(spool.glob("*.json")):
            doc = json.loads(f.read_text(encoding="utf-8"))
            vulns = doc.get("vulnerabilities")
            if not isinstance(vulns, list) or not vulns:
                raise ValueError("kev: no 'vulnerabilities' list in the catalogue")
            fetched = utcnow()
            rows = []
            for v in vulns:
                missing = [k for k in REQUIRED if k not in v]
                if missing:  # Spec C28: a changed schema is an error, never a column of nulls
                    raise ValueError(f"kev: entry {v.get('cveID')} lacks {missing}")
                h = hashlib.sha256(json.dumps(v, sort_keys=True).encode()).hexdigest()[:16]
                if hashes.get(v["cveID"]) == h:
                    continue
                hashes[v["cveID"]] = h
                rows.append({"cve_id": v["cveID"], "vendor": v["vendorProject"], "product": v["product"],
                             "name": v["vulnerabilityName"], "date_added": v["dateAdded"],
                             "due_date": v["dueDate"] or None,
                             "ransomware": v.get("knownRansomwareCampaignUse"),
                             "description": v["shortDescription"], "catalog_version": doc.get("catalogVersion"),
                             "entry_hash": h, "run_id": run.id, "fetched_at": iso(fetched)[:-1],
                             "schema_version": SCHEMA_VERSION})
            run.used(URL, sha256_file(f), f.stat().st_size)
            if rows:
                tmp = spool / "rows.jsonl.tmp"
                tmp.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
                con = duckdb.connect()
                cols = "{" + ",".join(f"'{c}':'{t}'" for c, t in self.tables["entries"]) + "}"
                n = write_parquet(con, f"SELECT * FROM read_json({sql_str(tmp)}, format='newline_delimited', columns={cols})",
                                  p.data / self.id / "entries" / f"dt={fetched:%Y-%m-%d}" / f"{run.id}.parquet")
                con.close()
                tmp.unlink()
                total += n
            write_json(hashes_path, hashes)
            f.unlink()
        run.rows += total
        return {"rows": total}

    def facta_sql(self) -> str:
        return """SELECT 'kev:' || cve_id AS row_id, 'kev' AS fons, 'network' AS domain, 'official' AS classis,
            NULL AS iso3, NULL AS adm1, NULL AS h3_5, NULL AS lat, NULL AS lon,
            CAST(date_added AS TIMESTAMP) AS t_from, NULL AS t_to, CAST(date_added AS TIMESTAMP) AS t_reported,
            fetched_at AS t_fetched, fetched_at AS recorded_at, 'kev_entry' AS measure, 1.0 AS value,
            'entry' AS unit, cve_id || ' ' || vendor || ' ' || product AS label,
            'https://nvd.nist.gov/vuln/detail/' || cve_id AS url, 'CC0-1.0' AS license, 6 AS credibility,
            run_id, schema_version, dt FROM kev_entries"""
