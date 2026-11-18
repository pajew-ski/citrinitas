"""Relatio: checks on a written assessment before it counts as one.

- fixed words of estimative probability with their number (Spec C30)
- every figure backed by a returned row (Spec C31)
- at least two hypotheses, the assumptions, and what weakens each hypothesis (Spec C32)
- stored as queries plus a point in time, so the same figures can be computed again (Spec C39)
"""
from __future__ import annotations

import hashlib
import json
import re

from ..athanor import guard

# ICD 203 bands in percent; German and English terms for the same seven bands.
BANDS = (
    ((1, 5), ("almost no chance", "remote", "fast ausgeschlossen")),
    ((5, 20), ("very unlikely", "highly improbable", "sehr unwahrscheinlich")),
    ((20, 45), ("unlikely", "improbable", "unwahrscheinlich")),
    ((45, 55), ("roughly even chance", "roughly even odds", "etwa gleich wahrscheinlich")),
    ((55, 80), ("likely", "probable", "probably", "wahrscheinlich")),
    ((80, 95), ("very likely", "highly probable", "sehr wahrscheinlich")),
    ((95, 99), ("almost certain", "almost certainly", "nearly certain", "fast sicher")),
)
VAGUE = ("possibly", "perhaps", "maybe", "conceivably", "presumably", "serious possibility", "cannot be ruled out",
         "can't be ruled out", "möglicherweise", "vielleicht", "eventuell", "vermutlich", "womöglich",
         "voraussichtlich", "nicht auszuschließen", "nicht ausgeschlossen")
_TERMS = sorted(((t, band) for band, terms in BANDS for t in terms), key=lambda x: -len(x[0]))
_TERM_RE = re.compile(r"(?<!\w)(" + "|".join(re.escape(t) for t, _ in _TERMS) + r")(?!\w)", re.I)
_VAGUE_RE = re.compile(r"(?<!\w)(" + "|".join(re.escape(t) for t in VAGUE) + r")(?!\w)", re.I)
_PCT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:%|percent|prozent)", re.I)
_SENT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-ZÄÖÜ\"„(\[])|\n+")
_NUM_RE = re.compile(r"(?<![\w.,:/#-])[-−]?\d[\d.,  ']*(?:\d)?(?![\w/-])")


def estimative(text: str) -> list[str]:
    """Problems with probability language: vague words, band words without a number, numbers outside the band."""
    problems = []
    for sentence in _SENT_RE.split(text):
        for m in _VAGUE_RE.finditer(sentence):
            problems.append(f"vague probability word {m.group(1)!r}: use one of the seven fixed terms with a number")
        pcts = [float(x.replace(",", ".")) for x in _PCT_RE.findall(sentence)]
        for m in _TERM_RE.finditer(sentence):
            lo, hi = dict(_TERMS)[m.group(1).lower()]
            if not pcts:
                problems.append(f"{m.group(1)!r} without a percentage in the same sentence")
            elif not any(lo <= x <= hi for x in pcts):
                problems.append(f"{m.group(1)!r} stands for {lo} to {hi} %, the sentence says {pcts}")
    return problems


def _readings(token: str) -> list[tuple[float, int]]:
    """A number written in German or English notation can mean two things; return every reading with its decimals."""
    t = token.replace("−", "-").replace(" ", "").replace(" ", "").replace("'", "").rstrip(".,")
    out = []
    for dec, tho in ((".", ","), (",", ".")):
        s = t.replace(tho, "")
        if s.count(dec) > 1:
            continue
        try:
            out.append((float(s.replace(dec, ".")), len(s.split(dec)[1]) if dec in s else 0))
        except ValueError:
            pass
    return out


def _numbers_in(value, acc: set) -> None:
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        acc.add(float(value))
    elif isinstance(value, str):
        for tok in re.findall(r"-?\d+(?:\.\d+)?", value):
            acc.add(float(tok))
    elif isinstance(value, (list, tuple)):
        for v in value:
            _numbers_in(v, acc)
    elif isinstance(value, dict):
        for v in value.values():
            _numbers_in(v, acc)


def unsupported(text: str, results: dict) -> list[str]:
    """Figures in the text that appear in no returned row. Percentages next to a band word are judgements, not facts."""
    have: set[float] = set()
    for res in results.values():
        _numbers_in(res.get("rows", []), have)
    clean = re.sub(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?Z?)?|\d{1,2}\.\d{1,2}\.\d{4}|\d{1,2}:\d{2}(?::\d{2})?", " ", text)
    clean = re.sub(r"\[[^\]]*\]|`[^`]*`", " ", clean)                      # row references and code
    judged = set()
    for sentence in _SENT_RE.split(clean):
        if _TERM_RE.search(sentence):
            judged.update(_PCT_RE.findall(sentence))
    missing = []
    for m in _NUM_RE.finditer(clean):
        tok = m.group(0)
        if tok.rstrip(".,") in judged:
            continue
        ok = False
        for val, decimals in _readings(tok):
            for h in have:
                if round(h, decimals) == val or round(h * 100, decimals) == val:
                    ok = True
        if not ok:
            missing.append(tok.rstrip(".,"))
    return missing


def structure(doc: dict) -> list[str]:
    problems = []
    for key in ("title", "quaestio", "text", "asof"):
        if not doc.get(key):
            problems.append(f"{key} is required")
    if not isinstance(doc.get("queries"), dict) or not doc["queries"]:
        problems.append("queries: at least one named query is required")
    hyp = doc.get("hypotheses") or []
    if len(hyp) < 2:
        problems.append("hypotheses: at least two are required")
    for i, h in enumerate(hyp):
        if not h.get("text"):
            problems.append(f"hypotheses[{i}]: text is required")
        if not isinstance(h.get("weakened_by"), list):
            problems.append(f"hypotheses[{i}]: weakened_by must list the evidence against it, or be an empty list")
    if hyp and all(not h.get("weakened_by") for h in hyp if isinstance(h, dict)):
        problems.append("hypotheses: no evidence against any hypothesis was looked for")
    if not doc.get("assumptions"):
        problems.append("assumptions: name the assumptions the assessment rests on")
    return problems


def check(doc: dict, connect) -> dict:
    """Run a draft through all checks. `connect(asof)` returns a guarded lake connection as of that time."""
    problems = structure(doc)
    results: dict = {}
    if isinstance(doc.get("queries"), dict) and doc.get("asof"):
        con = connect(doc["asof"])
        try:
            for name, sql in doc["queries"].items():
                try:
                    results[name] = guard.run(con, sql)
                except guard.Refused as e:
                    problems.append(f"queries.{name}: {e}")
        finally:
            con.close()
    text = doc.get("text") or ""
    problems += estimative(text)
    for tok in unsupported(text, results):
        problems.append(f"figure {tok} is backed by no returned row")
    digest = hashlib.sha256(json.dumps({k: [v["columns"], v["rows"]] for k, v in sorted(results.items())},
                                       sort_keys=True, default=str).encode()).hexdigest()
    if doc.get("results_hash") and doc["results_hash"] != digest:
        problems.append("results differ from the stored ones: the assessment does not reproduce")
    return {"ok": not problems, "problems": problems, "results_hash": digest, "results": results}
