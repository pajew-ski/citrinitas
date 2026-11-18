"""Sources: Fama (GDELT) and KEV, the catalogue and the register of questions."""
import io
import json
import shutil
import urllib.error
import zipfile
from datetime import date, datetime, timedelta

from citrinitas.athanor import core, lake
from citrinitas.athanor.core import CLASSES, DOMAINS
from citrinitas.fontes import catalog, kev
from citrinitas.fontes.base import TooLarge
from citrinitas.fontes.fama import GAP_SLOTS_PER_RUN, KINDS, SLOT_FMT, Fama

from .util import HomeCase


class FamaParse(HomeCase):
    def test_rows_carry_place_time_domain_class_and_origin(self):
        info = self.parse_fama()
        self.assertEqual(info["errors"], [])
        con = lake.connect(self.p, guard=True)
        n, with_iso, with_h3 = con.execute("SELECT count(*), count(iso3), count(h3_5) FROM fama_events").fetchone()
        self.assertEqual(n, 100)
        self.assertGreater(with_iso / n, 0.8)
        self.assertGreater(with_h3 / n, 0.8)
        # Spec C1, C4, C21: every row of the uniform view has time, origin, licence and run
        bad = con.execute("""SELECT count(*) FROM facta WHERE fons IS NULL OR t_from IS NULL OR t_fetched IS NULL
            OR recorded_at IS NULL OR license IS NULL OR run_id IS NULL OR schema_version IS NULL""").fetchone()[0]
        self.assertEqual(bad, 0)
        # Spec C2, C3: only the fixed domains and classes
        for domain, classis in con.execute("SELECT DISTINCT domain, classis FROM facta").fetchall():
            self.assertIn(domain, DOMAINS)
            self.assertIn(classis, CLASSES)
        # Spec F10: GDELT is reports about the world, never measurement
        self.assertEqual(con.execute("SELECT DISTINCT classis FROM facta WHERE fons = 'fama'").fetchall(), [("reported",)])
        # Spec C23: the reliability of the source and the credibility of the fact are two columns
        cols = [r[0] for r in con.execute("DESCRIBE facta").fetchall()]
        self.assertIn("reliability", cols)
        self.assertIn("credibility", cols)

    def test_no_person_columns_are_stored(self):
        # Spec C11, C35: neither actor names nor the person columns of the GKG reach the lake
        self.parse_fama()
        con = lake.connect(self.p)
        for table in ("fama_events", "fama_gkg", "fama_mentions"):
            cols = {r[0] for r in con.execute(f"DESCRIBE {table}").fetchall()}
            self.assertFalse({c for c in cols if "person" in c or "name" in c} - {"source_name", "geo_name"}, table)

    def test_languages_and_hourly_counts(self):
        self.parse_fama()
        con = lake.connect(self.p)
        langs = dict(con.execute("SELECT stream, count(DISTINCT lang) FROM fama_gkg GROUP BY 1").fetchall())
        self.assertEqual(langs["en"], 1)
        self.assertGreater(langs["tr"], 1)
        docs, geo = con.execute("SELECT (SELECT count(*) FROM fama_gkg), (SELECT count(*) FROM fama_hourly_geo)").fetchone()
        self.assertEqual(docs, 50)
        self.assertGreater(geo, 10)

    def test_provenance_leads_to_raw_file_and_commit(self):
        # Spec C21: from a row to the run, the commit and the hash of the input file
        self.parse_fama()
        con = lake.connect(self.p, guard=True)
        row = con.execute("""SELECT r.commit, len(r.inputs), r.inputs[1].sha256 FROM facta f
                             JOIN prov_runs r USING (run_id) LIMIT 1""").fetchone()
        self.assertTrue(row[0])
        self.assertEqual(row[1], 5)
        self.assertEqual(len(row[2]), 64)

    def test_zip_bomb_stops_at_the_cap(self):
        # Spec C37: the cap holds on the bytes actually unpacked
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("x.csv", b"0" * (4 << 20))
        f = self.p.spool / "bomb.zip"
        f.write_bytes(buf.getvalue())
        with self.assertRaises(TooLarge):
            Fama.extract(f, self.p.spool / "bomb.tsv", 1 << 20)

    def test_broken_file_is_an_error_not_a_gap(self):
        # Spec C28: a file with the wrong shape is rejected and set aside; the others still load
        d = self.p.spool / "fama"
        d.mkdir(parents=True)
        with zipfile.ZipFile(d / "20261118194500.en.export.zip", "w") as z:
            z.writestr("x.CSV", "only\tthree\tcolumns\n" * 50)
        shutil.copy(next(self.fixtures_dir().glob("*.en.mentions.zip")), d)
        run = core.Run(self.p, "fama", "parse")
        info = Fama().parse(self.p, run)
        self.assertEqual(len(info["errors"]), 1)
        self.assertEqual(info["files"], 1)
        self.assertTrue((d / "bad" / "20261118194500.en.export.zip").exists())

    def fixtures_dir(self):
        from .util import FIXTURES
        return FIXTURES

    def test_upkeep_merges_days_and_keeps_hourly_counts(self):
        # Spec F4, F5: old GKG days go, hourly counts stay; merging slot files keeps every row
        self.parse_fama()
        root = self.p.data / "fama"
        old = (core.utcnow().date() - timedelta(days=45)).isoformat()
        for table in ("gkg", "hourly_geo"):
            src = next((root / table).glob("dt=*"))
            shutil.copytree(src, root / table / f"dt={old}")
        con = lake.connect(self.p)
        before = con.execute("SELECT count(*) FROM fama_events").fetchone()[0]
        info = Fama().maintain(self.p, con)
        self.assertFalse((root / "gkg" / f"dt={old}").exists())
        self.assertTrue((root / "hourly_geo" / f"dt={old}").exists())
        self.assertGreaterEqual(info["compacted"], 1)
        con = lake.connect(self.p)
        self.assertEqual(con.execute("SELECT count(*) FROM fama_events").fetchone()[0], before)


class FamaFetch(HomeCase):
    def setUp(self):
        super().setUp()
        self.now = core.utcnow()
        self.latest = self.now.replace(minute=self.now.minute // 15 * 15, second=0)
        self.calls = []

    def listing(self, name):
        s = self.latest.strftime(SLOT_FMT)
        suffix = ".translation" if "translation" in name else ""
        return "\n".join(f"1 {'0' * 32} http://x/{s}{suffix}.{KINDS[k][0]}.zip" for k in KINDS).encode()

    def get(self, url, **kw):
        return self.listing(url)

    def download(self, url, dest, **kw):
        self.calls.append(url)
        with zipfile.ZipFile(dest, "w") as z:
            z.writestr("a.csv", "x\n")
        return dest.stat().st_size

    def fetch(self, **kw):
        fama = Fama()
        fama.verify = lambda path, md5: None
        run = core.Run(self.p, "fama", "fetch")
        return fama.fetch(self.p, run, get=kw.get("get", self.get), download=kw.get("download", self.download))

    def test_each_file_is_fetched_once_and_gaps_are_bounded(self):
        # Spec F1, F2: at most the latest slot plus twelve gaps per run and stream; a second run asks for other files
        info = self.fetch()
        self.assertEqual(info["files"], 2 * 3 * (GAP_SLOTS_PER_RUN + 1))
        first = set(self.calls)
        self.calls.clear()
        self.fetch()
        self.assertFalse(first & set(self.calls))

    def test_newest_slot_first(self):
        done = {}
        slots = Fama.wanted(self.latest, done, self.now)
        self.assertEqual(slots[0], self.latest.strftime(SLOT_FMT))
        self.assertEqual(slots, sorted(slots, reverse=True))

    def test_missing_file_waits_then_counts_as_empty(self):
        # Spec F2: a 404 on a fresh slot is asked again, on an old slot it counts as empty
        def missing(url, dest, **kw):
            raise urllib.error.HTTPError(url, 404, "nf", {}, None)
        self.fetch(download=missing)
        state = json.loads((self.p.state / "fama" / "slots.json").read_text())["en"]
        young = self.latest.strftime(SLOT_FMT)
        old = (self.latest - timedelta(hours=7)).strftime(SLOT_FMT)
        self.assertEqual(state[young]["gkg"], "pending")
        # ask until the old slot comes into the window of this run
        for _ in range(4):
            self.fetch(download=missing)
        state = json.loads((self.p.state / "fama" / "slots.json").read_text())["en"]
        self.assertEqual(state[old]["gkg"], "empty")

    def test_standing_stream_is_an_error_of_that_stream(self):
        # Spec F3: a stream without a new file for three hours is reported; the other keeps running
        stale = (self.latest - timedelta(hours=5)).strftime(SLOT_FMT)

        def get(url, **kw):
            if "translation" in url:
                return f"1 {'0' * 32} http://x/{stale}.translation.export.CSV.zip".encode()
            return self.listing(url)
        info = self.fetch(get=get)
        self.assertTrue(info["streams"]["tr"]["stale"])
        self.assertFalse(info["streams"]["en"]["stale"])
        self.assertTrue(any(e.startswith("tr: stream stands still") for e in info["errors"]))

    def test_md5_mismatch_is_refused(self):
        # Spec F1
        f = self.p.spool / "a.zip"
        f.write_bytes(b"abc")
        with self.assertRaises(ValueError):
            Fama.verify(f, "0" * 32)


class KevBitemporal(HomeCase):
    def catalogue(self, due):
        return {"catalogVersion": "t", "vulnerabilities": [
            {"cveID": "CVE-2026-0001", "vendorProject": "Acme", "product": "Router", "vulnerabilityName": "x",
             "dateAdded": "2026-11-01", "shortDescription": "d", "requiredAction": "a", "dueDate": due,
             "knownRansomwareCampaignUse": "Unknown"}]}

    def load(self, doc):
        d = self.p.spool / "kev"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{core.utcnow():%Y%m%dT%H%M%S}-{len(list(d.iterdir()))}.json").write_text(json.dumps(doc))
        run = core.Run(self.p, "kev", "parse")
        out = kev.Kev().parse(self.p, run)
        run.close()
        return out

    def test_correction_is_a_new_row_and_the_past_stays_readable(self):
        # Spec C20: a revision adds a row; facta shows the newest, facta_asof() what was known before
        self.assertEqual(self.load(self.catalogue("2026-11-22"))["rows"], 1)
        self.assertEqual(self.load(self.catalogue("2026-11-22"))["rows"], 0)
        files = sorted((self.p.data / "kev" / "entries").rglob("*.parquet"))
        con = lake.connect(self.p)
        first_seen = con.execute("SELECT max(recorded_at) FROM facta_all").fetchone()[0]
        con.close()
        # the second version is recorded later
        import duckdb
        c = duckdb.connect()
        later = first_seen + timedelta(hours=2)
        c.execute(f"""COPY (SELECT * REPLACE (DATE '2026-12-24' AS due_date, TIMESTAMP '{later}' AS fetched_at)
                      FROM read_parquet('{files[0]}')) TO '{files[0].parent / 'rev.parquet'}' (FORMAT parquet)""")
        con = lake.connect(self.p, guard=True)
        self.assertEqual(con.execute("SELECT count(*) FROM facta_all").fetchone()[0], 2)
        self.assertEqual(con.execute("SELECT count(*), max(recorded_at) FROM facta").fetchone(), (1, later))
        asof = con.execute(f"SELECT recorded_at FROM facta_asof(TIMESTAMP '{first_seen + timedelta(minutes=1)}')").fetchall()
        self.assertEqual(asof, [(first_seen,)])
        con.close()
        con = lake.connect(self.p, guard=True, asof=first_seen + timedelta(minutes=1))
        self.assertEqual(con.execute("SELECT recorded_at FROM facta").fetchall(), [(first_seen,)])

    def test_changed_schema_is_an_error(self):
        # Spec C28: a missing key stops the load instead of filling a column with nulls
        doc = self.catalogue("2026-11-22")
        del doc["vulnerabilities"][0]["dateAdded"]
        with self.assertRaises(ValueError):
            self.load(doc)


class Catalogue(HomeCase):
    def test_shipped_catalogue_is_sound(self):
        # Spec C18, C19, C22, C23, C42
        self.assertEqual(catalog.lint(catalog.load_fontes(), catalog.load_quaestiones()), [])

    def test_source_without_question_and_indicator_without_threshold_fail(self):
        fontes = catalog.load_fontes()
        qs = catalog.load_quaestiones()
        f = dict(fontes["kev"], quaestiones=[])
        self.assertTrue(any("refers to no question" in e for e in catalog.lint({"kev": f}, qs)))   # Spec C18
        q = json.loads(json.dumps(qs["q-exploited-vulnerabilities"], default=str))
        del q["indicators"][0]["threshold"]
        q["indicators"][0]["base_rate"] = {}
        errs = catalog.lint({}, {"q": q})
        self.assertTrue(any("threshold" in e for e in errs))                                        # Spec C19
        self.assertTrue(any("base_rate" in e for e in errs))
        f = dict(fontes["kev"], reliability=None)
        self.assertTrue(any("reliability" in e for e in catalog.lint({"kev": f}, qs)))              # Spec C23

    def test_overdue_question_is_named(self):
        # Spec C22
        qs = {"a": {"status": "open", "due": "2026-01-01"}, "b": {"status": "answered", "due": "2026-01-01"}}
        self.assertEqual(catalog.overdue(qs, date(2026, 11, 18)), ["a"])
