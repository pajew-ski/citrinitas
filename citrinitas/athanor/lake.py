"""The lake: one DuckDB connection with a view per table and the uniform view `facta` over all sources."""
from __future__ import annotations

import tempfile
from pathlib import Path

import duckdb

from ..fontes.base import registry
from . import licenses
from .core import FACTA_COLUMNS, Paths, sql_str

_JSONL = {
    "prov_runs": ("_prov/runs", (("run_id", "VARCHAR"), ("fons", "VARCHAR"), ("phase", "VARCHAR"), ("commit", "VARCHAR"),
                                 ("started_at", "TIMESTAMP"), ("ended_at", "TIMESTAMP"), ("seconds", "DOUBLE"),
                                 ("ok", "BOOLEAN"), ("error", "VARCHAR"), ("n_rows", "BIGINT"), ("n_rejected", "BIGINT"),
                                 ("bytes_in", "BIGINT"), ("schema_version", "INTEGER"),
                                 ("inputs", "STRUCT(url VARCHAR, sha256 VARCHAR, bytes BIGINT, fetched_at VARCHAR)[]"))),
    "prov_raw": ("_prov/raw", (("fons", "VARCHAR"), ("url", "VARCHAR"), ("sha256", "VARCHAR"), ("bytes", "BIGINT"),
                               ("fetched_at", "TIMESTAMP"), ("run_id", "VARCHAR"))),
    "indicators": ("_quaestiones/indicators", (("quaestio", "VARCHAR"), ("indicator", "VARCHAR"), ("seen_at", "TIMESTAMP"),
                                               ("value", "DOUBLE"), ("base_rate", "DOUBLE"), ("threshold", "DOUBLE"),
                                               ("direction", "VARCHAR"), ("triggered", "BOOLEAN"), ("state", "VARCHAR"),
                                               ("error", "VARCHAR"), ("run_id", "VARCHAR"))),
    "expectations": ("_quaestiones/expectations", (("id", "VARCHAR"), ("quaestio", "VARCHAR"), ("source", "VARCHAR"),
                                                    ("statement", "VARCHAR"), ("criterion", "VARCHAR"),
                                                    ("probability", "DOUBLE"), ("made_at", "TIMESTAMP"), ("due", "DATE"),
                                                    ("outcome", "INTEGER"), ("resolved_at", "TIMESTAMP"),
                                                    ("evidence", "VARCHAR"), ("event", "VARCHAR"))),
    "tabula": ("_tabula", (("seen_at", "TIMESTAMP"), ("domain", "VARCHAR"), ("level", "VARCHAR"), ("time", "VARCHAR"),
                           ("classis", "VARCHAR"), ("declared", "VARCHAR[]"), ("planned", "VARCHAR[]"),
                           ("observed", "VARCHAR[]"), ("state", "VARCHAR"))),
    "specillum": ("_specillum", (("seen_at", "TIMESTAMP"), ("domain", "VARCHAR"), ("iso3", "VARCHAR"),
                                 ("reported", "DOUBLE"), ("hard_facts", "BIGINT"), ("rank", "INTEGER"))),
    "drift": ("_meta/drift", (("seen_at", "TIMESTAMP"), ("fons", "VARCHAR"), ("tabula", "VARCHAR"), ("day", "DATE"),
                              ("n_rows", "BIGINT"), ("schema_hash", "VARCHAR"), ("max_null_pct", "DOUBLE"),
                              ("worst_column", "VARCHAR"))),
}
_META = {
    "fontes": (("id", "VARCHAR"), ("name", "VARCHAR"), ("status", "VARCHAR"), ("license", "VARCHAR"),
               ("access", "VARCHAR"), ("cadence", "VARCHAR"), ("reliability", "VARCHAR"),
               ("reliability_reason", "VARCHAR"), ("homepage", "VARCHAR"), ("quaestiones", "VARCHAR[]")),
    "cells": (("fons", "VARCHAR"), ("status", "VARCHAR"), ("domain", "VARCHAR"), ("classis", "VARCHAR"),
              ("level", "VARCHAR"), ("time", "VARCHAR")),
    "quaestiones": (("id", "VARCHAR"), ("text", "VARCHAR"), ("status", "VARCHAR"), ("domains", "VARCHAR[]"),
                    ("level", "VARCHAR"), ("time", "VARCHAR"), ("due", "VARCHAR")),
}


def _empty(cols) -> str:
    return "SELECT " + ", ".join(f"CAST(NULL AS {t}) AS {c}" for c, t in cols) + " WHERE false"


def _has_files(d: Path, suffix: str) -> bool:
    if not d.is_dir():
        return False
    for sub in d.iterdir():
        if sub.is_dir():
            if any(f.name.endswith(suffix) for f in sub.iterdir()):
                return True
        elif sub.name.endswith(suffix):
            return True
    return False


def _coldef(cols) -> str:
    return "{" + ",".join(f"'{c}':'{t}'" for c, t in cols) + "}"


def _facta_branch(fons, where: str = "") -> str:
    cast = ", ".join(f"CAST({c} AS {t}) AS {c}" for c, t in FACTA_COLUMNS)
    sql = f"SELECT {cast} FROM ({fons.facta_sql()}) {where}"
    if fons.revisable:  # Spec C20: the newest recorded version of a row is the current one
        sql += " QUALIFY row_number() OVER (PARTITION BY row_id ORDER BY recorded_at DESC) = 1"
    return sql


def connect(p: Paths, *, guard: bool = False, memory: str = "2GB", threads: int = 2, asof=None):
    """Open the lake. With guard=True the connection can read the lake and nothing else (Spec C9).

    With asof, `facta` shows what the lake held at that time (Spec C20, C39).
    """
    con = duckdb.connect(":memory:")
    con.execute("SET TimeZone='UTC'")
    con.execute(f"SET memory_limit='{memory}'")
    con.execute(f"SET threads={int(threads)}")
    fontes = registry()
    for fons in fontes.values():
        for table, cols in fons.tables.items():
            d = p.data / fons.id / table
            cols = tuple(cols) + (("dt", "DATE"),)
            if _has_files(d, ".parquet"):
                names = ", ".join(c for c, _ in cols)
                sql = (f"SELECT {names} FROM read_parquet({sql_str(d / '*' / '*.parquet')}, "
                       "hive_partitioning=true, union_by_name=true)")
            else:
                sql = _empty(cols)
            con.execute(f"CREATE VIEW {fons.id}_{table} AS {sql}")
    for name, (sub, cols) in _JSONL.items():
        d = p.data / sub
        if _has_files(d, ".jsonl"):
            sql = (f"SELECT * FROM read_json({sql_str(d / '*' / '*.jsonl')}, format='newline_delimited', "
                   f"columns={_coldef(cols)})")
        else:
            sql = _empty(cols)
        con.execute(f"CREATE VIEW {name} AS {sql}")
    for name, cols in _META.items():
        f = p.meta / f"{name}.json"
        sql = (f"SELECT * FROM read_json({sql_str(f)}, format='array', columns={_coldef(cols)})"
               if f.exists() and f.stat().st_size > 2 else _empty(cols))
        con.execute(f"CREATE VIEW {name} AS {sql}")
    con.execute(f"CREATE VIEW licentiae AS {licenses.values_sql()}")
    rel = "SELECT x.*, m.reliability FROM ({}) x LEFT JOIN fontes m ON m.id = x.fons"
    union = " UNION ALL ".join(_facta_branch(f) for f in fontes.values())
    con.execute("CREATE VIEW facta AS " + rel.format(union))
    cast = ", ".join(f"CAST({c} AS {t}) AS {c}" for c, t in FACTA_COLUMNS)
    con.execute("CREATE VIEW facta_all AS " + " UNION ALL ".join(
        f"SELECT {cast} FROM ({f.facta_sql()})" for f in fontes.values()))
    then = " UNION ALL ".join(_facta_branch(f, "WHERE recorded_at <= CAST(asof_ts AS TIMESTAMP)") for f in fontes.values())
    con.execute("CREATE MACRO facta_asof(asof_ts) AS TABLE " + rel.format(then))
    if asof is not None:
        con.execute(f"CREATE OR REPLACE VIEW facta AS SELECT * FROM facta_asof(TIMESTAMP {sql_str(asof)})")
    # Spec C36: what may leave the system as open data
    con.execute("CREATE VIEW facta_public AS SELECT f.* FROM facta f JOIN licentiae l USING (license) WHERE l.publishable")
    spill = Path(tempfile.gettempdir()) / "citrinitas-duckdb"
    spill.mkdir(exist_ok=True)
    con.execute(f"SET temp_directory={sql_str(spill)}")
    if guard:
        con.execute(f"SET allowed_directories=[{sql_str(p.data)}, {sql_str(spill)}]")
        con.execute("SET enable_external_access=false")
        con.execute("SET lock_configuration=true")
    return con
