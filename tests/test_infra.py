import tempfile
import unittest
import zipfile
from pathlib import Path

from pollutrace import config, harness
from pollutrace.project import _pathing_jar, to_runner_name


class InfraTest(unittest.TestCase):
    def test_pathing_jar_manifest_lines_are_at_most_72_bytes(self):
        d = Path(tempfile.mkdtemp())
        jar = d / "cp.jar"
        _pathing_jar(jar, [d / ("x" * 50) / f"lib{i}.jar" for i in range(40)] + [d])
        mf = zipfile.ZipFile(jar).read("META-INF/MANIFEST.MF")
        self.assertTrue(all(len(l) <= 72 for l in mf.split(b"\r\n")))
        joined = mf.replace(b"\r\n ", b"").decode()
        self.assertIn("lib39.jar", joined)

    def test_runner_name(self):
        self.assertEqual(to_runner_name("a.b.CTest.m"), "a.b.CTest#m")

    def test_presets_switch_one_component_each(self):
        full = config.get("full")
        self.assertEqual(config.get("no_localizer").localizer, "none")
        self.assertFalse(config.get("no_statediff").statediff)
        self.assertEqual(config.get("no_validator").validator, "weak")
        self.assertEqual(config.get("no_statediff").validator, full.validator)
        with self.assertRaises(KeyError):
            config.get("nope")

    def test_shards_partition_projects(self):
        rows = [{"id": str(i), "project_url": f"u{i % 5}"} for i in range(20)]
        a, b = harness.shard_rows(rows, "0/2"), harness.shard_rows(rows, "1/2")
        self.assertEqual(len(a) + len(b), 20)
        self.assertFalse({r["project_url"] for r in a} & {r["project_url"] for r in b})

    def test_stable_seed(self):
        self.assertEqual(harness.stable_seed("V1", 2), harness.stable_seed("V1", 2))
        self.assertNotEqual(harness.stable_seed("V1", 1), harness.stable_seed("V1", 2))


if __name__ == "__main__":
    unittest.main()


class FinalEvalTest(unittest.TestCase):
    def test_final_eval_uses_ground_truth_and_restores_file(self):
        from tests.fakes import FakeProject
        d = Path(tempfile.mkdtemp())
        f = d / "VTest.java"
        orig = "class VTest { @Test void victim() { assertEquals(1, X.n); } }"
        f.write_text(orig)
        v, p1, p2 = "p.VTest#victim", "p.A#a", "p.B#b"
        proj = FakeProject([f"p.O#t{i}" for i in range(5)] + [p1, p2, v], v, {p1, p2})
        proj.revert = lambda: f.write_text(orig)
        proj.fixed = True
        row = {"victim": v, "confirmed_polluter": p1, "polluters": f"{p1};{p2}"}
        new = orig.replace("{ assertEquals", "{ X.n = 1; assertEquals")
        out, detail = harness.final_eval(proj, row, {str(f): new}, n_final=10, final_secs=60, seed=1)
        self.assertEqual(out["outcome"], "fixed")
        self.assertEqual(out["rand_n"], 10)
        self.assertEqual(f.read_text(), orig)
        proj.fixed = False
        out, _ = harness.final_eval(proj, row, {str(f): new}, n_final=10, final_secs=60, seed=1)
        self.assertEqual(out["outcome"], "not_fixed")
