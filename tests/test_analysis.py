"""Questions, expectations, assessments, coverage and the probe."""
from datetime import timedelta

from citrinitas.athanor import core, lake
from citrinitas.fontes import catalog
from citrinitas.quaestiones import ledger, register, relatio
from citrinitas.specillum import probe
from citrinitas.tabula import matrix

from .util import HomeCase


class Indicators(HomeCase):
    def test_every_indicator_yields_a_value_or_says_no_data(self):
        # Spec C19: an indicator has a value, or the state no_data; never silence
        self.parse_fama()
        con = lake.connect(self.p, guard=True)
        summary = register.evaluate(self.p, con)
        self.assertEqual(summary["errors"], [])
        self.assertEqual(summary["open"], 3)
        con = lake.connect(self.p, guard=True)
        rows = con.execute("SELECT indicator, state, threshold, direction FROM indicators").fetchall()
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r[1] in ("ok", "no_data") and r[2] is not None for r in rows))

    def test_private_questions_are_read_from_the_node(self):
        d = self.p.etc / "quaestiones.d"
        d.mkdir(parents=True)
        (d / "mine.yaml").write_text("quaestiones:\n  q-private:\n    text: x\n")
        self.assertIn("q-private", catalog.load_quaestiones(self.p))


class Ledger(HomeCase):
    def test_expectations_are_resolved_and_scored(self):
        # Spec C29: no expectation without a criterion; every source of expectations gets a Brier score
        with self.assertRaises(ValueError):
            ledger.add(self.p, source="me", statement="s", criterion=" ", probability=0.7, due="2026-12-01")
        a = ledger.add(self.p, source="me", statement="s", criterion="c", probability=0.8, due="2026-12-01")
        b = ledger.add(self.p, source="me", statement="s", criterion="c", probability=0.3, due="2026-12-01")
        c = ledger.add(self.p, source="market", statement="s", criterion="c", probability=0.5, due="2020-01-01")
        ledger.resolve(self.p, a, True, "kev:CVE-2026-0001")
        ledger.resolve(self.p, b, True, "https://example.org/evidence")
        s = ledger.scores(self.p)
        self.assertEqual(s["brier"]["me"], {"n": 2, "score": round((0.04 + 0.49) / 2, 4)})
        self.assertEqual(s["due_unresolved"], [c])
        con = lake.connect(self.p)
        self.assertEqual(con.execute("SELECT count(*) FROM expectations WHERE event = 'resolved'").fetchone()[0], 2)


class Assessment(HomeCase):
    def test_fixed_words_with_their_number(self):
        # Spec C30: only the seven terms, each with a percentage inside its band
        self.assertEqual(relatio.estimative("An escalation is likely (60 %). Eine Einigung ist sehr unwahrscheinlich (10 %)."), [])
        self.assertTrue(relatio.estimative("An escalation is likely."))
        self.assertTrue(relatio.estimative("An escalation is likely (30 %)."))
        self.assertTrue(relatio.estimative("Vielleicht kommt es zu einer Einigung."))
        self.assertTrue(relatio.estimative("There is a serious possibility of a strike."))
        self.assertEqual(relatio.estimative("Eine Einigung ist unwahrscheinlich (30 %)."), [])

    def test_every_figure_needs_a_row(self):
        # Spec C31: a figure without a returned row is named; both notations are read; band percentages are judgements
        results = {"q": {"columns": ["n", "share"], "rows": [[1400, 0.904], [9.9, None]]}}
        text = "PortWatch zählte 1.400 Durchfahrten, 90,4 % weniger [fama:e:1]. An opening is unlikely (30 %) by 2026-12-01."
        self.assertEqual(relatio.unsupported(text, results), [])
        self.assertEqual(relatio.unsupported("Es waren 1.500 Durchfahrten und 9.9 je Tag.", results), ["1.500"])

    def doc(self, **over):
        d = {"title": "t", "quaestio": "q-force-reporting", "asof": (core.utcnow() + timedelta(minutes=1)).isoformat(),
             "queries": {"n": "SELECT count(*) AS n FROM facta WHERE fons = 'fama'"},
             "hypotheses": [{"text": "A", "weakened_by": ["fama:e:1"]}, {"text": "B", "weakened_by": []}],
             "assumptions": ["GDELT volume follows the monitored outlets"], "text": "Die Basis zählt 125 Zeilen."}
        d.update(over)
        return d

    def test_two_hypotheses_and_reproducible_figures(self):
        # Spec C32, C39: an assessment needs alternatives and evidence against them, and computes again to the same figures
        self.parse_fama()
        connect = lambda asof: lake.connect(self.p, guard=True, asof=asof.replace("T", " "))  # noqa: E731
        n = lake.connect(self.p).execute("SELECT count(*) FROM facta WHERE fons = 'fama'").fetchone()[0]
        good = relatio.check(self.doc(text=f"Die Basis zählt {n} Zeilen."), connect)
        self.assertEqual(good["problems"], [])
        again = relatio.check(self.doc(text=f"Die Basis zählt {n} Zeilen.", results_hash=good["results_hash"]), connect)
        self.assertTrue(again["ok"])
        self.assertFalse(relatio.check(self.doc(text=f"Die Basis zählt {n} Zeilen.", results_hash="0" * 64), connect)["ok"])
        self.assertTrue(any("at least two" in p for p in relatio.structure(self.doc(hypotheses=[{"text": "A", "weakened_by": []}]))))
        self.assertTrue(any("no evidence against" in p for p in relatio.structure(self.doc(
            hypotheses=[{"text": "A", "weakened_by": []}, {"text": "B", "weakened_by": []}]))))
        self.assertTrue(any("assumptions" in p for p in relatio.structure(self.doc(assumptions=[]))))
        early = relatio.check(self.doc(asof="2020-01-01T00:00:00", text="Die Basis zählt 0 Zeilen."), connect)
        self.assertEqual(early["results"]["n"]["rows"], [[0]])                                       # Spec C20


class Coverage(HomeCase):
    def test_blind_thin_and_covered(self):
        # Spec C7: no class is blind; one source or reports only is thin; two classes from two sources is covered
        fontes = {"a": {"cells": [{"domain": "security", "classis": "reported", "levels": ["country"], "times": ["live"]}]},
                  "b": {"cells": [{"domain": "security", "classis": "measured", "levels": ["country"], "times": ["live"]}]},
                  "c": {"status": "planned", "cells": [{"domain": "energy", "classis": "measured", "levels": ["country"], "times": ["live"]}]}}
        seen = {("a", "security", "reported", "country", "live")}
        rows = matrix.build(fontes, seen)
        self.assertEqual(len(rows), 15 * 4 * 3 * 4)
        self.assertEqual(matrix.verdict(rows, "security", "country", "live")["verdict"], "thin")
        self.assertEqual(matrix.verdict(rows, "energy", "country", "live"), {"verdict": "blind", "classes": [], "fontes": [], "planned": ["c"]})
        rows = matrix.build(fontes, seen | {("b", "security", "measured", "country", "live")})
        self.assertEqual(matrix.verdict(rows, "security", "country", "live")["verdict"], "covered")

    def test_matrix_and_probe_on_the_lake(self):
        # Spec C7, C8: the matrix is measured on the lake and per question; dense reporting without hard facts is a candidate
        self.parse_fama()
        con = lake.connect(self.p, guard=True)
        summary = matrix.run(self.p, con)
        self.assertEqual(summary["cells"], 180)
        self.assertEqual(summary["quaestiones"]["q-force-reporting"]["security"]["verdict"], "thin")
        self.assertEqual(summary["quaestiones"]["q-exploited-vulnerabilities"]["network"]["verdict"], "blind")
        found = probe.run(self.p, con)
        self.assertGreater(found["candidates"], 0)
        con = lake.connect(self.p, guard=True)
        self.assertEqual(con.execute("SELECT count(*) FROM tabula").fetchone()[0], 720)
        self.assertEqual(con.execute("SELECT max(hard_facts) FROM specillum").fetchone()[0], 0)
