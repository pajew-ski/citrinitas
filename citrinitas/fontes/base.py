"""Fontes: the sources. One adapter per source, each in two phases.

fetch  talks to the network and only writes raw files into the spool.
parse  has no network (Spec C37) and turns spooled files into Parquet.
"""
from __future__ import annotations

import urllib.error
import urllib.request
from pathlib import Path

from ..athanor.core import Paths, Run

USER_AGENT = "citrinitas/0.1 (+https://github.com/pajew-ski/citrinitas)"


class Fons:
    id = ""
    revisable = False                     # True: rows can be corrected by later rows (Spec C20)
    tables: dict[str, tuple] = {}         # table name -> ((column, type), ...)

    def fetch(self, p: Paths, run: Run) -> dict: raise NotImplementedError
    def parse(self, p: Paths, run: Run) -> dict: raise NotImplementedError
    def facta_sql(self) -> str: raise NotImplementedError
    def maintain(self, p: Paths, con) -> dict: return {}


class TooLarge(Exception):
    pass


def http_get(url: str, *, timeout: float = 60, headers: dict | None = None, limit: int = 8 << 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise TooLarge(f"{url}: more than {limit} bytes")
    return data


def http_download(url: str, dest: Path, *, timeout: float = 180, limit: int = 256 << 20) -> int:
    """Stream a file to disk with a size cap. Raises urllib.error.HTTPError on 4xx/5xx."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    tmp = dest.with_name(dest.name + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    total = 0
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r, open(tmp, "wb") as out:
            while chunk := r.read(1 << 20):
                total += len(chunk)
                if total > limit:
                    raise TooLarge(f"{url}: more than {limit} bytes")
                out.write(chunk)
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)
    return total


def registry() -> dict[str, Fons]:
    from .fama import Fama
    from .kev import Kev
    return {f.id: f for f in (Fama(), Kev())}
