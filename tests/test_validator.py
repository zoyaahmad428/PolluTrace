import sys
import tempfile
import unittest
from pathlib import Path

from pollutrace import config
from pollutrace.agents import validator
from pollutrace.trajectory import Trajectory
from pollutrace.validate import integrity
from tests.fakes import FakeProject

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "experiments"))
from e4_g3_validator import MUTANTS, mutate  # noqa: E402

SRC = """package p;
import org.junit.Test;
import static org.junit.Assert.assertEquals;
public class VTest {
    @Test
    public void victim() throws Exception {
        int n = Registry.size();
        assertEquals(0, n);
        assertEquals("a",
                     Registry.name());
    }
}
"""


class IntegrityTest(unittest.TestCase):
    def test_every_seeded_mutant_is_flagged(self):
        for kind in MUTANTS:
            new = mutate(SRC, "victim", kind)
            self.assertIsNotNone(new, kind)
            self.assertFalse(integrity(SRC, new, "victim")["ok"], kind)

    def test_a_real_fix_passes(self):
        new = SRC.replace("    @Test\n", "    @org.junit.Before public void reset() { Registry.clear(); }\n    @Test\n")
        self.assertTrue(integrity(SRC, new, "victim")["ok"])

    def test_polluter_file_checks(self):
        self.assertFalse(integrity(SRC, SRC.replace("assertEquals(0, n);", ""), None)["ok"])
        self.assertTrue(integrity(SRC, SRC + "\n// cleanup\n", None)["ok"])


class ValidatorTest(unittest.TestCase):
    def setUp(self):
        self.tests = [f"p.O#t{i}" for i in range(25)]
        self.v, self.pol = "p.VTest#victim", "p.PTest#pollute"
        self.order = self.tests[:5] + [self.pol] + [self.v]
        self.path = Path(tempfile.mkdtemp()) / "VTest.java"

    def proj(self, extra_polluters=()):
        return FakeProject(self.tests + [self.pol, self.v], self.v, {self.pol, *extra_polluters})

    def good_patch(self):
        return {self.path: (SRC, SRC.replace("int n", "Registry.clear(); int n"))}

    def test_strict_accepts_real_fix(self):
        p = self.proj()
        p.fixed = True
        r = validator.validate(p, self.v, self.good_patch(), self.order, [self.pol], Trajectory(), config.get("full"))
        self.assertEqual(r["verdict"], "ACCEPT")

    def test_rejects_when_still_failing(self):
        r = validator.validate(self.proj(), self.v, self.good_patch(), self.order, [self.pol], Trajectory(),
                               config.get("full"))
        self.assertEqual(r["verdict"], "REJECT")
        self.assertIn("still fails in failing order", r["reasons"])

    def test_strict_rejects_mutant_weak_accepts(self):
        p = self.proj()
        p.fixed = True  # the mutant makes the victim pass, but by deleting assertions
        patch = {self.path: (SRC, mutate(SRC, "victim", "remove_assertions"))}
        self.assertEqual(validator.validate(p, self.v, patch, self.order, [self.pol], Trajectory(),
                                            config.get("full", validator="weak"))["verdict"], "ACCEPT")
        r = validator.validate(p, self.v, patch, self.order, [self.pol], Trajectory(), config.get("full"))
        self.assertEqual(r["verdict"], "REJECT")
        self.assertEqual(r["reasons"], ["integrity"])

    def test_random_orders_expose_second_polluter(self):
        p = self.proj()
        hidden = "p.O#t17"

        def run_order(order, timeout=600, _orig=p.run_order):
            # patch fixes the first polluter only; t17 still pollutes
            p.fixed = True
            r = _orig(order)
            if self.v in order and hidden in order[:order.index(self.v)]:
                r["results"][self.v] = {"status": "FAIL", "trace": "second polluter"}
            return r
        p.run_order = run_order
        r = validator.validate(p, self.v, self.good_patch(), self.order, [self.pol], Trajectory(),
                               config.get("full", n_loop=20))
        self.assertEqual(r["verdict"], "REJECT")
        self.assertIn(hidden, r["failing_order"])
        self.assertEqual(r["failing_order"][-1], self.v)


if __name__ == "__main__":
    unittest.main()
