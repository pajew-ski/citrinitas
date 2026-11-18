"""Athanor core: paths, the shared vocabulary, run records and the Parquet store.

Athanor is the furnace of the opus: the part that runs steadily and keeps everything else alive.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from .. import SCHEMA_VERSION

REPO = Path(__file__).resolve().parents[2]

# Spec C2: fifteen fixed domains. A new one is added here and in SPEC.md, nowhere else.
DOMAINS = ("security", "politics", "economy", "finance", "energy", "climate", "health", "food",
           "population", "network", "mobility", "space", "science", "information", "society")
# Spec C3: exactly one class per fact; classes are never averaged into one number.
CLASSES = ("measured", "official", "reported", "expected")
LEVELS = ("world", "country", "region", "place")
TIMES = ("live", "historic", "future")
RELIABILITY = ("A", "B", "C", "D", "E", "F")  # Spec C23: Admiralty scale for the source

# Spec C1, C3, C4, C20, C21, C23, C26: every row of the uniform view carries these columns.
FACTA_COLUMNS = (
    ("row_id", "VARCHAR"), ("fons", "VARCHAR"), ("domain", "VARCHAR"), ("classis", "VARCHAR"),
    ("iso3", "VARCHAR"), ("adm1", "VARCHAR"), ("h3_5", "VARCHAR"), ("lat", "DOUBLE"), ("lon", "DOUBLE"),
    ("t_from", "TIMESTAMP"), ("t_to", "TIMESTAMP"), ("t_reported", "TIMESTAMP"), ("t_fetched", "TIMESTAMP"),
    ("recorded_at", "TIMESTAMP"), ("measure", "VARCHAR"), ("value", "DOUBLE"), ("unit", "VARCHAR"),
    ("label", "VARCHAR"), ("url", "VARCHAR"), ("license", "VARCHAR"), ("credibility", "TINYINT"),
    ("run_id", "VARCHAR"), ("schema_version", "INTEGER"), ("dt", "DATE"),
)


@dataclass(frozen=True)
class Paths:
    home: Path

    @property
    def data(self) -> Path: return self.home / "data"
    @property
    def spool(self) -> Path: return self.home / "spool"
    @property
    def state(self) -> Path: return self.home / "state"
    @property
    def etc(self) -> Path: return self.home / "etc"
    @property
    def keys(self) -> Path: return self.home / "etc" / "keys"
    @property
    def meta(self) -> Path: return self.home / "data" / "_meta"

    def ensure(self) -> "Paths":
        for d in (self.data, self.spool, self.state, self.meta):
            d.mkdir(parents=True, exist_ok=True)
        return self


def paths(home: str | os.PathLike | None = None) -> Paths:
    return Paths(Path(home or os.environ.get("CITRINITAS_HOME", "/srv/citrinitas")))


def utcnow() -> datetime:
    """Naive UTC, second resolution: every timestamp in the store is UTC without offset (Spec C1)."""
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def iso(ts: datetime | None) -> str | None:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ") if ts else None


def commit() -> str:
    """The code version that produced a row (Spec C21)."""
    if os.environ.get("CITRINITAS_COMMIT"):
        return os.environ["CITRINITAS_COMMIT"]
    marker = REPO / "COMMIT"
    if marker.exists():
        return marker.read_text().strip()
    try:
        return subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True,
                              text=True, timeout=5, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str), encoding="utf-8")
    os.replace(tmp, path)


def append_jsonl(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, separators=(",", ":"), default=str) + "\n")


class Run:
    """One activity in the sense of W3C PROV: code commit, start, inputs with SHA-256 (Spec C21)."""

    def __init__(self, p: Paths, fons: str, phase: str):
        self.p, self.fons, self.phase = p, fons, phase
        self.started = utcnow()
        self.id = f"{self.started:%Y%m%dT%H%M%S}-{fons}-{phase}-{uuid.uuid4().hex[:8]}"
        self.inputs: list[dict] = []
        self.rows = 0
        self.rejected = 0
        self.bytes_in = 0

    def used(self, url: str, sha256: str, size: int, fetched_at: datetime | str | None = None) -> None:
        self.inputs.append({"url": url, "sha256": sha256, "bytes": size,
                            "fetched_at": iso(fetched_at) if isinstance(fetched_at, datetime) else fetched_at})
        self.bytes_in += size

    def log_raw(self, url: str, sha256: str, size: int, **extra) -> None:
        """Spec C38: every fetched raw file is logged with hash, URL and fetch time."""
        now = utcnow()
        append_jsonl(self.p.data / "_prov" / "raw" / f"dt={now:%Y-%m-%d}" / f"raw-{self.fons}.jsonl",
                     [{"fons": self.fons, "url": url, "sha256": sha256, "bytes": size,
                       "fetched_at": iso(now), "run_id": self.id, **extra}])
        self.used(url, sha256, size, now)

    def close(self, ok: bool = True, error: str | None = None) -> dict:
        ended = utcnow()
        rec = {"run_id": self.id, "fons": self.fons, "phase": self.phase, "commit": commit(),
               "started_at": iso(self.started), "ended_at": iso(ended),
               "seconds": (ended - self.started).total_seconds(), "ok": ok, "error": error,
               "n_rows": self.rows, "n_rejected": self.rejected, "bytes_in": self.bytes_in,
               "schema_version": SCHEMA_VERSION, "inputs": self.inputs}
        append_jsonl(self.p.data / "_prov" / "runs" / f"dt={self.started:%Y-%m-%d}" / f"runs-{self.fons}.jsonl", [rec])
        return rec


def set_fons_state(p: Paths, fons: str, phase: str, ok: bool, error: str | None = None, **extra) -> None:
    """Spec C10: each source fails alone; its state lives in its own file."""
    path = p.state / "fontes" / f"{fons}.json"
    st = read_json(path, {})
    st[phase] = {"ok": ok, "at": iso(utcnow()), "error": error, **extra}
    write_json(path, st)


def sql_str(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def write_parquet(con, select_sql: str, dest: Path) -> int:
    """Write a query result as one Parquet file, atomically. Returns the row count."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    con.execute(f"COPY ({select_sql}) TO {sql_str(tmp)} (FORMAT parquet, COMPRESSION zstd)")
    n = con.execute(f"SELECT count(*) FROM read_parquet({sql_str(tmp)})").fetchone()[0]
    if n:
        os.replace(tmp, dest)
    else:
        tmp.unlink(missing_ok=True)
    return n


def partitions(table_dir: Path) -> list[tuple[date, Path]]:
    out = []
    if table_dir.is_dir():
        for d in table_dir.iterdir():
            if d.is_dir() and d.name.startswith("dt="):
                try:
                    out.append((date.fromisoformat(d.name[3:]), d))
                except ValueError:
                    continue
    return sorted(out)


def compact(con, table_dir: Path, before: date) -> int:
    """Merge the slot files of each finished day into one file, so the lake does not drown in small files.

    Crash-safe: a manifest lists the files a merged file replaces; an interrupted run is finished on the next.
    """
    merged = 0
    for dt, d in partitions(table_dir):
        for man in d.glob("*.manifest"):
            m = read_json(man, {})
            final = d / m.get("final", "")
            if m.get("final") and final.exists():
                for name in m.get("replaces", []):
                    (d / name).unlink(missing_ok=True)
            man.unlink(missing_ok=True)
        files = sorted(f for f in d.glob("*.parquet"))
        if dt >= before or len(files) < 2:
            continue
        final = d / f"c-{utcnow():%Y%m%dT%H%M%S}.parquet"
        tmp = final.with_name(final.name + ".tmp")
        src = "[" + ",".join(sql_str(f) for f in files) + "]"
        con.execute(f"COPY (SELECT * FROM read_parquet({src}, union_by_name=true)) TO {sql_str(tmp)} "
                    "(FORMAT parquet, COMPRESSION zstd)")
        man = d / (final.name + ".manifest")
        write_json(man, {"final": final.name, "replaces": [f.name for f in files]})
        os.replace(tmp, final)
        for f in files:
            f.unlink(missing_ok=True)
        man.unlink(missing_ok=True)
        merged += 1
    return merged


def prune_before(table_dir: Path, before: date) -> int:
    n = 0
    for dt, d in partitions(table_dir):
        if dt < before:
            shutil.rmtree(d, ignore_errors=True)
            n += 1
    return n


def disk(p: Paths) -> dict:
    u = shutil.disk_usage(p.data if p.data.exists() else p.home)
    return {"total_gb": round(u.total / 1e9, 2), "used_gb": round(u.used / 1e9, 2),
            "used_pct": round(100 * u.used / u.total, 1)}


def tree_bytes(d: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(d):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total
