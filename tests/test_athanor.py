"""Athanor: the read-only guard, templates, licences, upkeep, state and the HTTP door."""
import json
import threading
import urllib.error
import urllib.request
from datetime import timedelta
from http.server import ThreadingHTTPServer

from citrinitas.athanor import core, guard, lake, licenses, server, status, templates, upkeep
from citrinitas.fontes import catalog

from .util import HomeCase


class Guard(HomeCase):
    def test_only_one_select(self):
        # Spec C9: one read-only statement, nothing else
        con = lake.connect(self.p, guard=True)
        self.assertEqual(guard.run(con, "SELECT 1 AS a")["rows"], [[1]])
        for sql in ("INSERT INTO x VALUES (1)", "SELECT 1; SELECT 2", "COPY (SELECT 1) TO '/tmp/x.csv'",
                    "ATTACH '/tmp/x.db'", "SET memory_limit='10GB'", "CREATE TABLE t AS SELECT 1", "PRAGMA version"):
            with self.assertRaises(guard.Refused, msg=sql):
                guard.run(con, sql)

    def test_no_file_outside_the_lake(self):
        # Spec C9: the token and the system are out of reach of a query
        (self.p.etc).mkdir(parents=True, exist_ok=True)
        (self.p.etc / "token").write_text("secret-secret-secret-secret-secret")
        con = lake.connect(self.p, guard=True)
        for sql in (f"SELECT * FROM read_text('{self.p.etc / 'token'}')", "SELECT * FROM read_csv('/etc/passwd')",
                    "SELECT * FROM glob('/etc/*')"):
            with self.assertRaises(guard.Refused, msg=sql):
                guard.run(con, sql)

    def test_row_cap_and_timeout(self):
        # Spec C9: bounded rows and bounded time
        con = lake.connect(self.p, guard=True)
        res = guard.run(con, "SELECT * FROM range(100)", max_rows=10)
        self.assertEqual((res["row_count"], res["truncated"]), (10, True))
        with self.assertRaises(guard.Refused) as cm:
            guard.run(con, "SELECT count(*) FROM range(100000000000) a, range(1000) b", timeout_s=0.5)
        self.assertIn("exceeded", str(cm.exception))


class Licences(HomeCase):
    def test_derived_row_inherits_every_restriction(self):
        # Spec C36: CC0 joined with non-commercial data is non-commercial; share-alike and NC never leave as open data
        self.assertEqual(licenses.combine(["CC0-1.0", "CC-BY-NC-4.0"]), "CC-BY-NC-4.0")
        self.assertEqual(licenses.combine(["CC-BY-4.0", "ODbL-1.0", "CC-BY-NC-4.0"]), "CC-BY-NC-SA-4.0")
        self.assertEqual(licenses.combine(["CC0-1.0", "something unknown"]), "restricted")
        self.assertTrue(licenses.publishable("CC-BY-4.0"))
        for lic in ("CC-BY-NC-4.0", "ODbL-1.0", "CC-BY-ND-4.0", "restricted", "unknown"):
            self.assertFalse(licenses.publishable(lic), lic)
        con = lake.connect(self.p)
        rows = dict(con.execute("SELECT license, publishable FROM licentiae").fetchall())
        self.assertTrue(rows["CC0-1.0"])
        self.assertFalse(rows["CC-BY-NC-4.0"])
        self.assertIn("JOIN licentiae", con.execute("SELECT sql FROM duckdb_views() WHERE view_name = 'facta_public'").fetchone()[0])


class Templates(HomeCase):
    def test_series_keeps_classes_apart_and_refuses_unknown_parameters(self):
        # Spec C3, F6
        self.parse_fama()
        con = lake.connect(self.p, guard=True)
        sql, args = templates.render("series", {"from": "2026-11-18T00:00:00Z", "to": "2026-11-19T00:00:00Z", "bucket": "hour"})
        res = guard.run(con, sql, args)
        self.assertIn("classis", res["columns"])
        self.assertGreater(res["row_count"], 0)
        with self.assertRaises(templates.BadRequest):
            templates.render("series", {"sql": "DROP TABLE x"})
        with self.assertRaises(templates.BadRequest):
            templates.render("nope", {})
        for name in ("ranking", "lang_gap", "articles", "fontes", "coverage", "indicators", "probe"):
            sql, args = templates.render(name, {"from": "2026-11-18T00:00:00Z", "to": "2026-11-19T00:00:00Z"}
                                         if name in ("ranking", "lang_gap", "articles") else {})
            guard.run(con, sql, args)
        sql, args = templates.render("provenance", {"row_id": con.execute("SELECT row_id FROM facta LIMIT 1").fetchone()[0]})
        self.assertGreater(guard.run(con, sql, args)["row_count"], 0)                               # Spec C21

    def test_anomaly_needs_a_changed_share_not_more_volume(self):
        # Spec C27: twice the total volume at the same share is no anomaly; a doubled share is one
        import duckdb
        day = core.utcnow().date() - timedelta(days=1)
        c = duckdb.connect()

        def write(scale_total, share_x):
            rows = []
            for i in range(1, 30):
                d = day - timedelta(days=i)
                jitter = 1 + 0.02 * ((i * 7) % 5 - 2)
                rows.append((d, "AAA", int(1000 * 0.10 * jitter)))
                rows.append((d, "BBB", int(1000 * (1 - 0.10 * jitter))))
            rows.append((day, "AAA", int(1000 * scale_total * share_x)))
            rows.append((day, "BBB", int(1000 * scale_total * (1 - share_x))))
            root = self.p.data / "fama" / "hourly_events"
            import shutil
            shutil.rmtree(root, ignore_errors=True)
            for d, iso, n in rows:
                dest = root / f"dt={d.isoformat()}" / f"{iso}.parquet"
                dest.parent.mkdir(parents=True, exist_ok=True)
                c.execute(f"""COPY (SELECT TIMESTAMP '{d} 12:00:00' AS hour, 'en' AS stream, '{iso}' AS iso3, '19' AS root_code,
                    CAST(4 AS TINYINT) AS quad_class, CAST(1 AS BIGINT) AS n_events, CAST({n} AS BIGINT) AS n_articles,
                    0.0 AS tone_sum, TIMESTAMP '{d} 12:00:00' AS slot, 'r' AS run_id, TIMESTAMP '{d} 12:00:00' AS fetched_at)
                    TO '{dest}' (FORMAT parquet)""")

        def flagged():
            con = lake.connect(self.p, guard=True)
            sql, args = templates.render("anomalies", {"day": day.isoformat()})
            return [r[0] for r in guard.run(con, sql, args)["rows"]]

        write(scale_total=2.0, share_x=0.10)
        self.assertEqual(flagged(), [])
        write(scale_total=1.0, share_x=0.25)
        self.assertEqual(flagged(), ["AAA"])


class Upkeep(HomeCase):
    def test_drift_becomes_a_state(self):
        # Spec C28: a collapsed row count, a changed schema or a column turning null marks the source as disturbed
        hist = [{"fons": "fama", "tabula": "events", "day": f"2026-11-{d:02d}", "n_rows": 100000, "schema_hash": "a",
                 "max_null_pct": 5.0, "worst_column": "x"} for d in range(1, 8)]
        ok = {"fons": "fama", "tabula": "events", "day": "2026-11-08", "n_rows": 90000, "schema_hash": "a",
              "max_null_pct": 6.0, "worst_column": "x"}
        self.assertEqual(upkeep.judge_drift(hist, [ok]), {})
        for change in ({"n_rows": 100}, {"schema_hash": "b"}, {"max_null_pct": 80.0}):
            self.assertEqual(list(upkeep.judge_drift(hist, [{**ok, **change}])), ["fama"], change)
        self.assertEqual(status.fons_state({"parse": {"ok": True}}, ["schema changed"], []), "disturbed")

    def test_measured_drift_and_budget(self):
        # Spec C28, C42: yesterday's partitions are measured; a source over its budget is named
        self.parse_fama()
        root = self.p.data / "fama"
        yesterday = (core.utcnow().date() - timedelta(days=1)).isoformat()
        for table in ("events", "gkg"):
            src = next((root / table).glob("dt=*"))
            if src.name != f"dt={yesterday}":
                src.rename(root / table / f"dt={yesterday}")
        con = lake.connect(self.p)
        rows = upkeep.measure_drift(self.p, con)
        self.assertEqual({r["tabula"] for r in rows}, {"events", "gkg"})
        self.assertTrue(all(r["n_rows"] > 0 and len(r["schema_hash"]) == 16 for r in rows))
        fontes = {"fama": {"budget": {"disk_gb": 0.000001, "runtime_s_day": 9999, "download_mb_day": 9999}}}
        budget = upkeep.measure_budget(self.p, lake.connect(self.p), fontes)
        self.assertEqual(budget["fama"]["over"], ["disk_gb"])
        self.assertEqual(status.fons_state({"parse": {"ok": True}}, [], ["disk_gb"]), "over_budget")

    def test_a_failed_phase_marks_only_that_source(self):
        # Spec C10: each source fails alone
        core.set_fons_state(self.p, "fama", "fetch", False, "en: HTTP 503")
        core.set_fons_state(self.p, "kev", "fetch", True)
        doc = status.build(self.p, logs=False)
        self.assertEqual(doc["fontes"]["fama"]["state"], "error")
        self.assertEqual(doc["fontes"]["kev"]["state"], "ok")
        self.assertIn("HTTP 503", doc["fontes"]["fama"]["phases"]["fetch"]["error"])


class Door(HomeCase):
    TOKEN = "t" * 40

    def setUp(self):
        super().setUp()
        self.parse_fama()
        catalog.dump_meta(self.p)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(self.p, self.TOKEN))
        self.httpd.RequestHandlerClass.log_message = lambda *a, **k: None
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def call(self, path, body=None, token=TOKEN):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(req, timeout=20) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def test_token_is_the_gate(self):
        # Spec F8: without the token there is only the health line
        self.assertEqual(self.call("/status", token="wrong")[0], 401)
        self.assertEqual(self.call("/query", {"sql": "SELECT 1"}, token="")[0], 401)
        code, doc = self.call("/health", token="")
        self.assertEqual((code, doc["ok"]), (200, True))

    def test_state_replaces_the_shell(self):
        # Spec C17: commit, rejected commit, disk, memory and the state of every source in one document
        code, doc = self.call("/status")
        self.assertEqual(code, 200)
        for key in ("commit", "rejected", "sandbox", "disk", "memory", "fontes", "logs", "schema_version"):
            self.assertIn(key, doc)
        self.assertEqual(set(doc["fontes"]), {"fama", "kev"})
        self.assertEqual(self.call("/query", {"template": "status"})[1]["commit"], doc["commit"])

    def test_query_by_template_and_by_sql(self):
        # Spec C9, F6: templates for everyone, read-only SQL with limits; every answer carries origin columns
        code, res = self.call("/query", {"template": "ranking", "params": {"from": "2026-11-18T00:00:00Z", "to": "2026-11-19T00:00:00Z"}})
        self.assertEqual((code, res["ok"]), (200, True))
        self.assertGreater(res["row_count"], 0)
        code, res = self.call("/query", {"sql": "SELECT row_id, iso3, t_from, domain, classis, fons, license, url, reliability FROM facta LIMIT 3"})
        self.assertEqual((code, res["row_count"]), (200, 3))
        self.assertEqual(res["rows"][0][5], "fama")
        self.assertEqual(res["rows"][0][8], "C")                                                     # Spec C23
        code, res = self.call("/query", {"sql": "DELETE FROM facta"})
        self.assertEqual(code, 400)
        self.assertIn("only SELECT", res["error"])
        self.assertEqual(self.call("/query", {"sql": "SELECT 1", "template": "series"})[0], 400)
        self.assertEqual(self.call("/query", {"template": "series", "params": {"oops": 1}})[0], 400)
