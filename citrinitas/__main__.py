"""Command line of Citrinitas. `python -m citrinitas <command>`."""
from __future__ import annotations

import argparse
import json
import sys
import unittest
from datetime import timedelta

from .athanor import lake, status, templates, upkeep
from .athanor import guard as _guard
from .athanor.core import REPO, Paths, Run, paths, read_json, set_fons_state, utcnow
from .fontes import catalog
from .fontes.base import registry


def _active(names: list[str]) -> list:
    cat = catalog.load_fontes()
    reg = registry()
    ids = names or [k for k, v in cat.items() if v.get("status", "active") == "active"]
    unknown = [i for i in ids if i not in reg]
    if unknown:
        raise SystemExit(f"no adapter for: {', '.join(unknown)}")
    return [reg[i] for i in ids]


def _phase(p: Paths, phase: str, names: list[str]) -> int:
    """Run one phase for every source. A source that fails is recorded and the others still run (Spec C10)."""
    failed = 0
    for fons in _active(names):
        run = Run(p, fons.id, phase)
        try:
            info = getattr(fons, phase)(p, run) or {}
            errors = info.get("errors") or []
            run.close(ok=not errors, error="; ".join(errors)[:500] or None)
            set_fons_state(p, fons.id, phase, not errors, "; ".join(errors)[:500] or None,
                           **{k: v for k, v in info.items() if k != "errors"})
            failed += bool(errors)
            print(json.dumps({"fons": fons.id, "phase": phase, **info}, default=str), flush=True)
        except Exception as e:  # noqa: BLE001
            msg = f"{type(e).__name__}: {e}"[:500]
            run.close(ok=False, error=msg)
            set_fons_state(p, fons.id, phase, False, msg)
            failed += 1
            print(json.dumps({"fons": fons.id, "phase": phase, "error": msg}), flush=True)
    return 0 if not failed else 1


def _daily(p: Paths) -> int:
    from .quaestiones import register
    from .specillum import probe
    from .tabula import matrix
    con = lake.connect(p)
    out = {"upkeep": upkeep.run(p, con)}
    con.close()
    con = lake.connect(p, guard=True)        # views are bound again: compaction changed the files
    out["quaestiones"] = register.evaluate(p, con)
    last = (read_json(p.state / "tabula.json", {}) or {}).get("at", "")
    if last[:10] < (utcnow() - timedelta(days=28)).date().isoformat():  # Spec C7, C8: monthly
        out["tabula"] = matrix.run(p, con)
        out["specillum"] = probe.run(p, con)
    con.close()
    print(json.dumps(out, default=str), flush=True)
    return 0


def _selftest() -> int:
    errors = catalog.lint(catalog.load_fontes(), catalog.load_quaestiones())
    for e in errors:
        print(f"catalogue: {e}")
    suite = unittest.defaultTestLoader.discover(str(REPO / "tests"), top_level_dir=str(REPO))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() and not errors else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="citrinitas", description=__doc__)
    ap.add_argument("--home", help="data home, default $CITRINITAS_HOME or /srv/citrinitas")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="run the HTTP API")
    s.add_argument("--host", default="0.0.0.0")  # noqa: S104
    s.add_argument("--port", type=int, default=8765)
    for name, text in (("fetch", "download raw files into the spool (network)"),
                       ("parse", "turn spooled files into Parquet (no network)")):
        s = sub.add_parser(name, help=text)
        s.add_argument("fontes", nargs="*")
    sub.add_parser("daily", help="upkeep, drift, budget, indicators; monthly coverage and probe")
    sub.add_parser("lint", help="check the catalogue of sources and the register of questions")
    sub.add_parser("selftest", help="lint plus the test suite; a new commit only goes live if this passes")
    sub.add_parser("status", help="print the state document")
    s = sub.add_parser("query", help="run a template or read-only SQL against the lake")
    s.add_argument("--sql")
    s.add_argument("--template")
    s.add_argument("--params", default="{}")
    s.add_argument("--asof")
    s = sub.add_parser("check", help="check a written assessment (JSON file)")
    s.add_argument("file")
    a = ap.parse_args(argv)
    p = paths(a.home)
    if a.cmd == "selftest":
        return _selftest()
    if a.cmd == "lint":
        errors = catalog.lint(catalog.load_fontes(), catalog.load_quaestiones(p))
        print("\n".join(errors) or "catalogue is sound")
        return 1 if errors else 0
    p.ensure()
    if a.cmd == "serve":
        from .athanor import server
        catalog.dump_meta(p)
        server.serve(p, a.host, a.port)
    elif a.cmd in ("fetch", "parse"):
        return _phase(p, a.cmd, a.fontes)
    elif a.cmd == "daily":
        return _daily(p)
    elif a.cmd == "status":
        print(json.dumps(status.build(p, logs=False), indent=1, default=str))
    elif a.cmd == "query":
        from .athanor import server
        body = {"sql": a.sql} if a.sql else {"template": a.template, "params": json.loads(a.params)}
        if a.asof:
            body["asof"] = a.asof
        try:
            print(json.dumps(server.answer(p, body), default=str))
        except (_guard.Refused, templates.BadRequest) as e:
            print(json.dumps({"ok": False, "error": str(e)}))
            return 1
    elif a.cmd == "check":
        from .athanor import server
        from .quaestiones import relatio
        doc = json.loads(open(a.file, encoding="utf-8").read())
        v = relatio.check(doc, lambda asof: lake.connect(p, guard=True, asof=server._asof(asof)))
        print(json.dumps({k: v[k] for k in ("ok", "problems", "results_hash")}, indent=1))
        return 0 if v["ok"] else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
