import tempfile
import unittest
from pathlib import Path

from pollutrace import config
from pollutrace.agents import localizer
from pollutrace.trajectory import Trajectory
from tests.fakes import FakeProject
from tests.test_static_state import POLLUTER, VICTIM


def setup(n=30, pol_index=11):
    tests = [f"com.acme.OtherTest#t{i}" for i in range(n)]
    pol = "com.acme.PolluterTest#writes"
    prefix = tests[:pol_index] + [pol] + tests[pol_index:]
    v = "com.acme.VictimTest#readsRegistry"
    d = Path(tempfile.mkdtemp())
    for name, src in (("VictimTest", VICTIM), ("PolluterTest", POLLUTER),
                      ("OtherTest", "package com.acme;\npublic class OtherTest { void t0() { int a = 1; } }")):
        (d / f"{name}.java").write_text(src)
    srcs = {f"com.acme.{k}": d / f"{k}.java" for k in ("VictimTest", "PolluterTest", "OtherTest")}
    return FakeProject(prefix + [v], v, {pol}, srcs), prefix + [v], v, pol


class LocalizerTest(unittest.TestCase):
    def test_every_strategy_finds_the_polluter(self):
        for strat in ("ranked", "one_by_one", "bisect", "random"):
            proj, order, v, pol = setup()
            cfg = config.get("full", localizer=strat, llm_rank=False, max_local_runs=40)
            res = localizer.localize(proj, v, order, "", Trajectory(), cfg, seed=3)
            self.assertEqual(res["polluter"], pol, strat)

    def test_ranked_needs_fewer_runs_than_one_by_one(self):
        proj, order, v, pol = setup(pol_index=20)
        r1 = localizer.localize(proj, v, order, "", Trajectory(), config.get("full", llm_rank=False))
        proj2, order2, _, _ = setup(pol_index=20)
        r2 = localizer.localize(proj2, v, order2, "", Trajectory(), config.get("full", localizer="one_by_one"))
        self.assertEqual(r1["runs"], 1)  # shared Registry/System state puts it first
        self.assertGreater(r2["runs"], r1["runs"])

    def test_budget_is_respected(self):
        proj, order, v, pol = setup(pol_index=25)
        res = localizer.localize(proj, v, order, "", Trajectory(), config.get("full", localizer="one_by_one",
                                                                               max_local_runs=5))
        self.assertIsNone(res["polluter"])
        self.assertEqual(res["runs"], 5)
        self.assertTrue(res["budget_hit"])

    def test_parse_name_list(self):
        allowed = {"a.B#x", "a.C#y"}
        self.assertEqual(localizer.parse_name_list('Sure: ["a.C#y", "a.B.x", "zz#q"]', allowed), ["a.C#y", "a.B#x"])
        self.assertEqual(localizer.parse_name_list("1. a.B#x\n2. a.C#y", allowed), ["a.B#x", "a.C#y"])


if __name__ == "__main__":
    unittest.main()
