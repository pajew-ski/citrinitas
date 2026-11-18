"""Fama: GDELT 2.0 as the first source.

Named after Ovid's house of Fama (Metamorphoses XII), where every report arrives and none is checked.
GDELT counts what media report about the world, not the world: every row here is class `reported`
and never stands on the measured side of a derived signal (Spec F10).

Person names are not stored: the actor names of the event files and the person columns of the GKG are
dropped at parse time (Spec C11, C35).
"""
from __future__ import annotations

import codecs
import hashlib
import shutil
import time
import urllib.error
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .. import SCHEMA_VERSION
from ..athanor.core import (Paths, Run, compact, disk, partitions, prune_before, read_json, sha256_file, sql_str,
                            utcnow, write_json, write_parquet)
from . import fips
from .base import Fons, TooLarge, http_download, http_get

BASE = "https://data.gdeltproject.org/gdeltv2/"
STREAMS = {"en": ("lastupdate.txt", "masterfilelist.txt", ""),
           "tr": ("lastupdate-translation.txt", "masterfilelist-translation.txt", ".translation")}
# kind -> (file suffix, column count, cap for the unpacked size in bytes)
KINDS = {"export": ("export.CSV", 61, 256 << 20), "mentions": ("mentions.CSV", 16, 384 << 20),
         "gkg": ("gkg.csv", 27, 1024 << 20)}
WINDOW_SLOTS = 96          # Spec F2: look back 24 hours for gaps
GAP_SLOTS_PER_RUN = 12     # Spec F2: at most twelve missing quarter hours per run and stream
STALE_AFTER = timedelta(hours=3)      # Spec F3
PENDING_FOR = timedelta(hours=6)      # a listed file can answer 404 for a while before it appears
FETCH_BUDGET_S = 540
KEEP_GKG_DAYS = 30         # Spec F4
KEEP_EVENT_DAYS = 400      # Spec F4
DISK_LIMIT_PCT = 80.0      # Spec F5
# Share of physical lines that may fail to load before the file counts as drifted. A changed format fails on
# nearly every line. Single GDELT records with line breaks inside a field are real: on 2026-11-18 one record
# spread over 130 of 2 789 lines of a knowledge graph file. Rejected lines are counted in the run.
MAX_REJECT_SHARE = 0.2
SLOT_FMT = "%Y%m%d%H%M%S"

_TAIL = (("stream", "VARCHAR"), ("slot", "TIMESTAMP"), ("run_id", "VARCHAR"), ("fetched_at", "TIMESTAMP"),
         ("schema_version", "INTEGER"))


class Fama(Fons):
    id = "fama"
    revisable = False
    tables = {
        "events": (("event_id", "BIGINT"), ("day", "DATE"), ("actor1_code", "VARCHAR"), ("actor1_country", "VARCHAR"),
                   ("actor1_type", "VARCHAR"), ("actor2_code", "VARCHAR"), ("actor2_country", "VARCHAR"),
                   ("actor2_type", "VARCHAR"), ("is_root", "BOOLEAN"), ("event_code", "VARCHAR"),
                   ("base_code", "VARCHAR"), ("root_code", "VARCHAR"), ("quad_class", "TINYINT"),
                   ("goldstein", "DOUBLE"), ("n_mentions", "INTEGER"), ("n_sources", "INTEGER"),
                   ("n_articles", "INTEGER"), ("avg_tone", "DOUBLE"), ("geo_type", "TINYINT"),
                   ("geo_name", "VARCHAR"), ("geo_fips", "VARCHAR"), ("geo_adm1", "VARCHAR"), ("lat", "DOUBLE"),
                   ("lon", "DOUBLE"), ("added_at", "TIMESTAMP"), ("url", "VARCHAR"), ("iso3", "VARCHAR"),
                   ("h3_5", "VARCHAR")) + _TAIL,
        "mentions": (("event_id", "BIGINT"), ("event_time", "TIMESTAMP"), ("mention_time", "TIMESTAMP"),
                     ("mention_type", "TINYINT"), ("source_name", "VARCHAR"), ("url", "VARCHAR"),
                     ("in_raw_text", "BOOLEAN"), ("confidence", "INTEGER"), ("doc_len", "INTEGER"),
                     ("doc_tone", "DOUBLE"), ("lang", "VARCHAR")) + _TAIL,
        "gkg": (("record_id", "VARCHAR"), ("ts", "TIMESTAMP"), ("source_name", "VARCHAR"), ("url", "VARCHAR"),
                ("themes", "VARCHAR[]"), ("orgs", "VARCHAR[]"), ("loc_fips", "VARCHAR[]"), ("loc_adm1", "VARCHAR[]"),
                ("tone", "DOUBLE"), ("polarity", "DOUBLE"), ("word_count", "INTEGER"), ("lang", "VARCHAR")) + _TAIL,
        "hourly_geo": (("hour", "TIMESTAMP"), ("stream", "VARCHAR"), ("lang", "VARCHAR"), ("fips", "VARCHAR"),
                       ("iso3", "VARCHAR"), ("n_docs", "BIGINT"), ("tone_sum", "DOUBLE"), ("slot", "TIMESTAMP"),
                       ("run_id", "VARCHAR"), ("fetched_at", "TIMESTAMP")),
        "hourly_theme": (("hour", "TIMESTAMP"), ("stream", "VARCHAR"), ("lang", "VARCHAR"), ("theme", "VARCHAR"),
                         ("n_docs", "BIGINT"), ("tone_sum", "DOUBLE"), ("slot", "TIMESTAMP"), ("run_id", "VARCHAR"),
                         ("fetched_at", "TIMESTAMP")),
        "hourly_events": (("hour", "TIMESTAMP"), ("stream", "VARCHAR"), ("iso3", "VARCHAR"), ("root_code", "VARCHAR"),
                          ("quad_class", "TINYINT"), ("n_events", "BIGINT"), ("n_articles", "BIGINT"),
                          ("tone_sum", "DOUBLE"), ("slot", "TIMESTAMP"), ("run_id", "VARCHAR"),
                          ("fetched_at", "TIMESTAMP")),
    }

    # ---- fetch (network) ---------------------------------------------------------------------------

    @staticmethod
    def url(slot: str, stream: str, kind: str) -> str:
        return f"{BASE}{slot}{STREAMS[stream][2]}.{KINDS[kind][0]}.zip"

    @staticmethod
    def parse_listing(text: str) -> dict[str, str]:
        """Lines of `size md5 url` -> {file name: md5}."""
        out = {}
        for line in text.splitlines():
            parts = line.split()
            if len(parts) == 3 and len(parts[1]) == 32:
                out[parts[2].rsplit("/", 1)[-1]] = parts[1]
        return out

    @staticmethod
    def wanted(latest: datetime, done: dict, now: datetime) -> list[str]:
        """Slots to ask for, newest first.

        Slots never asked before are bounded: the latest one plus GAP_SLOTS_PER_RUN older gaps. Slots whose files
        answered 404 while fresh are asked again without counting, so a late file never blocks older gaps.
        """
        out, fresh = [], 0
        for i in range(WINDOW_SLOTS):
            slot = (latest - timedelta(minutes=15 * i)).strftime(SLOT_FMT)
            marks = done.get(slot, {})
            if any(marks.get(k) is None for k in KINDS):
                if fresh <= GAP_SLOTS_PER_RUN:
                    out.append(slot)
                    fresh += 1
            elif any(marks.get(k) == "pending" for k in KINDS):
                out.append(slot)
        return out

    def fetch(self, p: Paths, run: Run, *, get=http_get, download=http_download, clock=time.monotonic) -> dict:
        spool = p.spool / self.id
        spool.mkdir(parents=True, exist_ok=True)
        state_path = p.state / self.id / "slots.json"
        state: dict = read_json(state_path, {})
        deadline = clock() + FETCH_BUDGET_S
        now = utcnow()
        info: dict = {"streams": {}, "files": 0, "bytes": 0}
        errors: list[str] = []
        for stream, (last_name, master_name, _suffix) in STREAMS.items():
            done = state.setdefault(stream, {})
            try:
                listing = self.parse_listing(get(BASE + last_name, timeout=30).decode("utf-8", "replace"))
                slots = sorted({name[:14] for name in listing if name[:14].isdigit()})
                if not slots:
                    raise ValueError(f"{last_name} lists no file")
                latest = datetime.strptime(slots[-1], SLOT_FMT)
            except Exception as e:  # noqa: BLE001
                errors.append(f"{stream}: {type(e).__name__}: {e}"[:200])
                continue
            age = now - latest
            info["streams"][stream] = {"latest": latest.isoformat() + "Z", "age_s": int(age.total_seconds()),
                                       "stale": age > STALE_AFTER}
            if age > STALE_AFTER:  # Spec F3: a stream that stands still is an error of that stream only
                errors.append(f"{stream}: stream stands still since {latest.isoformat()}Z")
            todo = self.wanted(latest, done, now)
            if len(todo) > 1:  # MD5 sums of older files come from the tail of the master list
                try:
                    tail = get(BASE + master_name, timeout=60, headers={"Range": "bytes=-600000"}, limit=2 << 20)
                    listing.update(self.parse_listing(tail.decode("utf-8", "replace")))
                except Exception:  # noqa: BLE001  the zip check below still guards integrity
                    pass
            for slot in todo:
                slot_age = now - datetime.strptime(slot, SLOT_FMT)
                marks = done.setdefault(slot, {})
                for kind in KINDS:
                    if marks.get(kind) in ("got", "empty"):
                        continue
                    if clock() > deadline:
                        break
                    url = self.url(slot, stream, kind)
                    dest = spool / f"{slot}.{stream}.{kind}.zip"
                    try:
                        size = download(url, dest, limit=256 << 20)
                        self.verify(dest, listing.get(url.rsplit("/", 1)[-1]))
                        run.log_raw(url, sha256_file(dest), size, slot=slot, stream=stream, kind=kind)
                        marks[kind] = "got"
                        info["files"] += 1
                        info["bytes"] += size
                    except urllib.error.HTTPError as e:
                        dest.unlink(missing_ok=True)
                        if e.code == 404:  # Spec F2: a missing file counts as empty once it is old enough
                            marks[kind] = "pending" if slot_age < PENDING_FOR else "empty"
                        else:
                            errors.append(f"{stream} {slot} {kind}: HTTP {e.code}")
                    except Exception as e:  # noqa: BLE001
                        dest.unlink(missing_ok=True)
                        errors.append(f"{stream} {slot} {kind}: {type(e).__name__}: {e}"[:200])
            cutoff = (now - timedelta(days=3)).strftime(SLOT_FMT)
            for slot in [s for s in done if s < cutoff]:
                del done[slot]
        write_json(state_path, state)
        info["errors"] = errors
        return info

    @staticmethod
    def verify(path: Path, md5: str | None) -> None:
        """Spec F1: check against the MD5 of the listing; without one, the zip must at least be intact."""
        if md5:
            h = hashlib.md5()  # noqa: S324  GDELT publishes MD5; SHA-256 goes into the raw log
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            if h.hexdigest() != md5:
                raise ValueError(f"MD5 mismatch for {path.name}")
        else:
            with zipfile.ZipFile(path) as z:
                if z.testzip() is not None:
                    raise ValueError(f"corrupt zip {path.name}")

    # ---- parse (no network) ------------------------------------------------------------------------

    @staticmethod
    def extract(zip_path: Path, dest: Path, limit: int) -> int:
        """Unpack the single member as clean UTF-8, refusing anything larger than `limit` (Spec C37).

        The declared size of a zip member can lie, so the cap is enforced on the bytes actually read.
        Returns the number of lines.
        """
        with zipfile.ZipFile(zip_path) as z:
            members = z.infolist()
            if len(members) != 1:
                raise ValueError(f"{zip_path.name}: expected one member, found {len(members)}")
            if members[0].file_size > limit:
                raise TooLarge(f"{zip_path.name}: declares {members[0].file_size} bytes unpacked")
            dec = codecs.getincrementaldecoder("utf-8")(errors="replace")
            total = lines = 0
            last = "\n"
            with z.open(members[0]) as src, open(dest, "wb") as out:
                while chunk := src.read(1 << 20):
                    total += len(chunk)
                    if total > limit:
                        raise TooLarge(f"{zip_path.name}: more than {limit} bytes unpacked")
                    text = dec.decode(chunk).replace("\x00", "")
                    if text:
                        lines += text.count("\n")
                        last = text[-1]
                        out.write(text.encode("utf-8"))
            return lines + (0 if last == "\n" else 1)

    @staticmethod
    def _csv(path: Path, n_cols: int) -> str:
        cols = "{" + ",".join(f"'c{i}':'VARCHAR'" for i in range(n_cols)) + "}"
        return (f"read_csv({sql_str(path)}, delim='\t', header=false, quote='', escape='', auto_detect=false, "
                f"columns={cols}, ignore_errors=true, max_line_size=33554432)")

    @staticmethod
    def connection():
        import duckdb
        import h3

        def cell(lat, lon):
            if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
                return None
            return h3.latlng_to_cell(lat, lon, 5)

        con = duckdb.connect()
        con.execute("SET TimeZone='UTC'")
        con.execute("SET threads=2")
        con.create_function("h3_5", cell, ["DOUBLE", "DOUBLE"], "VARCHAR", null_handling="special",
                            exception_handling="return_null")
        con.execute(f"CREATE TEMP TABLE fips AS {fips.values_sql()}")
        return con

    def select(self, kind: str, csv: Path, stream: str) -> str:
        src = self._csv(csv, KINDS[kind][1])
        lang = "coalesce(NULLIF(regexp_extract(coalesce({c}, ''), 'srclc:([a-z]{{3}})', 1), ''), 'eng')"
        if kind == "export":
            return f"""SELECT TRY_CAST(c0 AS BIGINT) AS event_id, CAST(TRY_STRPTIME(c1, '%Y%m%d') AS DATE) AS day,
                NULLIF(c5, '') AS actor1_code, NULLIF(c7, '') AS actor1_country, NULLIF(c12, '') AS actor1_type,
                NULLIF(c15, '') AS actor2_code, NULLIF(c17, '') AS actor2_country, NULLIF(c22, '') AS actor2_type,
                c25 = '1' AS is_root, c26 AS event_code, c27 AS base_code, c28 AS root_code,
                TRY_CAST(c29 AS TINYINT) AS quad_class, TRY_CAST(c30 AS DOUBLE) AS goldstein,
                TRY_CAST(c31 AS INTEGER) AS n_mentions, TRY_CAST(c32 AS INTEGER) AS n_sources,
                TRY_CAST(c33 AS INTEGER) AS n_articles, TRY_CAST(c34 AS DOUBLE) AS avg_tone,
                TRY_CAST(c51 AS TINYINT) AS geo_type, NULLIF(c52, '') AS geo_name, NULLIF(c53, '') AS geo_fips,
                NULLIF(c54, '') AS geo_adm1, TRY_CAST(c56 AS DOUBLE) AS lat, TRY_CAST(c57 AS DOUBLE) AS lon,
                TRY_STRPTIME(c59, '%Y%m%d%H%M%S') AS added_at, NULLIF(c60, '') AS url, f.iso3 AS iso3,
                h3_5(TRY_CAST(c56 AS DOUBLE), TRY_CAST(c57 AS DOUBLE)) AS h3_5
                FROM {src} r LEFT JOIN fips f ON f.fips = r.c53 WHERE TRY_CAST(c0 AS BIGINT) IS NOT NULL"""
        if kind == "mentions":
            return f"""SELECT TRY_CAST(c0 AS BIGINT) AS event_id, TRY_STRPTIME(c1, '%Y%m%d%H%M%S') AS event_time,
                TRY_STRPTIME(c2, '%Y%m%d%H%M%S') AS mention_time, TRY_CAST(c3 AS TINYINT) AS mention_type,
                NULLIF(c4, '') AS source_name, NULLIF(c5, '') AS url, c10 = '1' AS in_raw_text,
                TRY_CAST(c11 AS INTEGER) AS confidence, TRY_CAST(c12 AS INTEGER) AS doc_len,
                TRY_CAST(c13 AS DOUBLE) AS doc_tone, {lang.format(c='c14')} AS lang
                FROM {src} WHERE TRY_CAST(c0 AS BIGINT) IS NOT NULL"""
        # gkg: c11, c12 (persons), c22 (quotations), c23 (all names), c24 (amounts), c26 (extras) are not read
        return f"""SELECT c0 AS record_id, TRY_STRPTIME(c1, '%Y%m%d%H%M%S') AS ts, NULLIF(c3, '') AS source_name,
            NULLIF(c4, '') AS url,
            list_distinct(list_filter(string_split(c7, ';'), lambda x: x <> '')) AS themes,
            list_distinct(list_filter(string_split(c13, ';'), lambda x: x <> '')) AS orgs,
            list_distinct(list_filter(list_transform(string_split(c9, ';'), lambda x: split_part(x, '#', 3)), lambda x: x <> '')) AS loc_fips,
            list_distinct(list_filter(list_transform(string_split(c9, ';'), lambda x: split_part(x, '#', 4)), lambda x: x <> '')) AS loc_adm1,
            TRY_CAST(split_part(c15, ',', 1) AS DOUBLE) AS tone, TRY_CAST(split_part(c15, ',', 4) AS DOUBLE) AS polarity,
            TRY_CAST(split_part(c15, ',', 7) AS INTEGER) AS word_count, {lang.format(c='c25')} AS lang
            FROM {src} WHERE c0 IS NOT NULL AND TRY_STRPTIME(c1, '%Y%m%d%H%M%S') IS NOT NULL"""

    def parse_file(self, p: Paths, con, zip_path: Path, run: Run) -> int:
        slot, stream, kind, _ext = zip_path.name.split(".")
        if stream not in STREAMS or kind not in KINDS:
            raise ValueError(f"unexpected spool file {zip_path.name}")
        slot_ts = datetime.strptime(slot, SLOT_FMT)
        fetched = datetime.fromtimestamp(int(zip_path.stat().st_mtime), timezone.utc).replace(tzinfo=None)
        tmp = zip_path.with_suffix(".tsv")
        try:
            lines = self.extract(zip_path, tmp, KINDS[kind][2])
            tail = (f"{sql_str(stream)} AS stream, TIMESTAMP {sql_str(slot_ts)} AS slot, {sql_str(run.id)} AS run_id, "
                    f"TIMESTAMP {sql_str(fetched)} AS fetched_at, {SCHEMA_VERSION} AS schema_version")
            table = {"export": "events", "mentions": "mentions", "gkg": "gkg"}[kind]
            part = f"dt={slot_ts:%Y-%m-%d}"
            name = f"{slot}.{stream}.parquet"
            dest = p.data / self.id / table / part / name
            n = write_parquet(con, f"SELECT *, {tail} FROM ({self.select(kind, tmp, stream)})", dest)
            rejected = lines - n
            if lines and rejected / lines > MAX_REJECT_SHARE:  # Spec C28: drift is an error, not a gap
                dest.unlink(missing_ok=True)
                raise ValueError(f"{zip_path.name}: {rejected} of {lines} lines rejected")
            run.rejected += max(rejected, 0)
            if n and kind == "gkg":
                src = f"read_parquet({sql_str(dest)})"
                write_parquet(con, f"""SELECT date_trunc('hour', ts) AS hour, stream, lang, x.fips AS fips, f.iso3 AS iso3,
                    count(*) AS n_docs, sum(tone) AS tone_sum, any_value(slot) AS slot, any_value(run_id) AS run_id, any_value(fetched_at) AS fetched_at
                    FROM (SELECT ts, stream, lang, tone, slot, run_id, fetched_at, unnest(loc_fips) AS fips FROM {src}) x
                    LEFT JOIN fips f ON f.fips = x.fips GROUP BY ALL""", p.data / self.id / "hourly_geo" / part / name)
                write_parquet(con, f"""SELECT date_trunc('hour', ts) AS hour, stream, lang, theme, count(*) AS n_docs,
                    sum(tone) AS tone_sum, any_value(slot) AS slot, any_value(run_id) AS run_id,
                    any_value(fetched_at) AS fetched_at
                    FROM (SELECT ts, stream, lang, tone, slot, run_id, fetched_at, unnest(themes) AS theme FROM {src})
                    GROUP BY ALL""", p.data / self.id / "hourly_theme" / part / name)
            if n and kind == "export":
                write_parquet(con, f"""SELECT date_trunc('hour', added_at) AS hour, stream, iso3, root_code, quad_class,
                    count(*) AS n_events, sum(n_articles) AS n_articles, sum(avg_tone) AS tone_sum,
                    any_value(slot) AS slot, any_value(run_id) AS run_id, any_value(fetched_at) AS fetched_at
                    FROM read_parquet({sql_str(dest)}) GROUP BY ALL""", p.data / self.id / "hourly_events" / part / name)
            run.used(self.url(slot, stream, kind), sha256_file(zip_path), zip_path.stat().st_size, fetched)
            return n
        finally:
            tmp.unlink(missing_ok=True)

    def parse(self, p: Paths, run: Run) -> dict:
        spool = p.spool / self.id
        files = sorted(spool.glob("*.zip")) if spool.is_dir() else []
        info = {"files": 0, "rows": 0, "rejected_lines": 0, "errors": []}
        before = run.rejected
        if not files:
            return info
        con = self.connection()
        bad = spool / "bad"
        for f in files:
            try:
                n = self.parse_file(p, con, f, run)
                run.rows += n
                info["rows"] += n
                info["files"] += 1
                f.unlink()
            except Exception as e:  # noqa: BLE001  one bad file never blocks the others
                info["errors"].append(f"{f.name}: {type(e).__name__}: {e}"[:240])
                bad.mkdir(exist_ok=True)
                shutil.move(str(f), bad / f.name)
        for old in sorted(bad.glob("*.zip"))[:-50] if bad.is_dir() else []:
            old.unlink()
        con.close()
        info["rejected_lines"] = run.rejected - before
        return info

    # ---- upkeep --------------------------------------------------------------------------------------

    def maintain(self, p: Paths, con) -> dict:
        today = utcnow().date()
        root = p.data / self.id
        info = {"compacted": 0, "pruned": 0, "pruned_for_space": 0}
        for table in self.tables:
            info["compacted"] += compact(con, root / table, today - timedelta(days=1))
        info["pruned"] += prune_before(root / "gkg", today - timedelta(days=KEEP_GKG_DAYS))
        for table in ("events", "mentions"):
            info["pruned"] += prune_before(root / table, today - timedelta(days=KEEP_EVENT_DAYS))
        # Spec F5: above the disk limit the oldest GKG days go first, then events and mentions; never the hourly counts
        for table in ("gkg", "events", "mentions"):
            while disk(p)["used_pct"] > DISK_LIMIT_PCT:
                parts = partitions(root / table)
                if len(parts) <= 2:
                    break
                shutil.rmtree(parts[0][1], ignore_errors=True)
                info["pruned_for_space"] += 1
        return info

    # ---- the uniform view ----------------------------------------------------------------------------

    def facta_sql(self) -> str:
        """Events as reports on security and politics; documents per country, hour and language as the information domain."""
        return f"""SELECT 'fama:e:' || event_id AS row_id, 'fama' AS fons,
            CASE WHEN root_code IN ('14', '15', '17', '18', '19', '20') THEN 'security' ELSE 'politics' END AS domain,
            'reported' AS classis, iso3, geo_adm1 AS adm1, h3_5, lat, lon,
            CAST(day AS TIMESTAMP) AS t_from, CAST(day AS TIMESTAMP) + INTERVAL 1 DAY AS t_to,
            added_at AS t_reported, fetched_at AS t_fetched, fetched_at AS recorded_at,
            'articles' AS measure, CAST(n_articles AS DOUBLE) AS value, 'articles' AS unit,
            'CAMEO ' || event_code || coalesce(' @ ' || geo_name, '') AS label, url, 'GDELT-terms' AS license,
            6 AS credibility, run_id, schema_version, dt FROM fama_events
          UNION ALL
          SELECT 'fama:g:' || strftime(slot, '%Y%m%d%H%M') || ':' || stream || ':' || lang || ':' || fips || ':' || strftime(hour, '%Y%m%d%H'),
            'fama', 'information', 'reported', iso3, NULL, NULL, NULL, NULL, hour, hour + INTERVAL 1 HOUR, hour,
            fetched_at, fetched_at, 'documents', CAST(n_docs AS DOUBLE), 'documents', 'language ' || lang, NULL,
            'GDELT-terms', 6, run_id, {SCHEMA_VERSION}, dt FROM fama_hourly_geo"""
