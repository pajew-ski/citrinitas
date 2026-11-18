"""Shared helpers for the tests: a temporary home with the fixtures in the spool."""
import shutil
import tempfile
import unittest
from pathlib import Path

from citrinitas.athanor import core

FIXTURES = Path(__file__).parent / "fixtures"


class HomeCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="citrinitas-test-")
        self.p = core.paths(self._tmp).ensure()
        self.addCleanup(shutil.rmtree, self._tmp, True)

    def spool_fixtures(self, fons="fama"):
        d = self.p.spool / fons
        d.mkdir(parents=True, exist_ok=True)
        for f in FIXTURES.glob("*.zip"):
            shutil.copy(f, d / f.name)

    def parse_fama(self):
        from citrinitas.fontes.fama import Fama
        self.spool_fixtures()
        run = core.Run(self.p, "fama", "parse")
        info = Fama().parse(self.p, run)
        run.close()
        return info
