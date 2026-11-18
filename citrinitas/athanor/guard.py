"""Read-only SQL with hard limits (Spec C9): one SELECT, bounded time, rows and memory, no file access outside the lake."""
from __future__ import annotations

import datetime as _dt
import decimal
import threading
import time

import duckdb

MAX_ROWS = 5000
TIMEOUT_S = 60


class Refused(Exception):
    """The request is not a single read-only statement or broke a limit."""


def _plain(v):
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    if isinstance(v, (_dt.datetime, _dt.date, _dt.time)):
        return v.isoformat() + ("Z" if isinstance(v, _dt.datetime) else "")
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, (bytes, bytearray)):
        return bytes(v).hex()
    if isinstance(v, (list, tuple)):
        return [_plain(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _plain(x) for k, x in v.items()}
    return str(v)


def check(con, sql: str):
    try:
        stmts = con.extract_statements(sql)
    except duckdb.Error as e:
        raise Refused(f"parse error: {e}") from e
    if len(stmts) != 1:
        raise Refused("exactly one statement is allowed")
    if stmts[0].type != duckdb.StatementType.SELECT:
        raise Refused(f"only SELECT is allowed, got {stmts[0].type.name}")
    return stmts[0]


def run(con, sql: str, params=None, *, max_rows: int = MAX_ROWS, timeout_s: float = TIMEOUT_S) -> dict:
    check(con, sql)
    timed_out = threading.Event()

    def _stop():
        timed_out.set()
        con.interrupt()

    timer = threading.Timer(timeout_s, _stop)
    t0 = time.monotonic()
    timer.start()
    try:
        cur = con.execute(sql, params or [])
        cols = [d[0] for d in cur.description]
        rows = cur.fetchmany(max_rows + 1)
    except duckdb.Error as e:
        if timed_out.is_set():
            raise Refused(f"query exceeded {timeout_s:g} s") from e
        raise Refused(str(e).split("\n")[0][:400]) from e
    finally:
        timer.cancel()
    truncated = len(rows) > max_rows
    return {"columns": cols, "rows": [[_plain(v) for v in r] for r in rows[:max_rows]],
            "row_count": min(len(rows), max_rows), "truncated": truncated,
            "elapsed_ms": int((time.monotonic() - t0) * 1000)}
