import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pollutrace import config, harness, supervisor  # noqa: F401
from pollutrace.agents import repair, statediff
from pollutrace.trajectory import BudgetExceeded, Trajectory
from tests.fakes import FakeProject

VSRC = """package p;
import org.junit.Test;
import static org.junit.Assert.assertEquals;
public class VTest {
    @Test public void victim() { assertEquals(0, Registry.NAMES.size()); }
}
"""
PSRC = """package p;
import org.junit.Test;
public class PTest {
    @Test public void pollute() { Registry.NAMES.add("a"); }
}
"""
FIXED = VSRC.replace("    @Test public void victim", "    @org.junit.Before public void reset() { Registry.NAMES.clear(); }\n    @Test public void victim")


class StateDiffTest(unittest.TestCase):
    def test_diff_filters_noise_and_orders_app_state_first(self):
        clean = {"p.Registry.NAMES": "ArrayList(size=0){}", "System.property:sun.java.command": "a",
                 "System.property:x": None, "p.Registry.n": "0"}
        dirty = {"p.Registry.NAMES": 'ArrayList(size=1){"a"}', "System.property:sun.java.command": "b",
                 "System.property:x": "1", "p.Registry.n": "0"}
        ch = statediff.diff(clean, dirty)
        self.assertEqual([c["key"] for c in ch], ["p.Registry.NAMES", "System.property:x"])
        txt = statediff.render({"ok": True, "changes": ch, "n_changed": 2, "n_fields": 4, "n_classes": 1})
        self.assertIn('ArrayList(size=0){}  ->  ArrayList(size=1){"a"}', txt)

    def test_classes_for_uses_sources_and_trace(self):
        d = Path(tempfile.mkdtemp())
        (d / "VTest.java").write_text(VSRC)
        (d / "PTest.java").write_text(PSRC)
        proj = FakeProject([], "p.VTest#victim", set(), {"p.VTest": d / "VTest.java", "p.PTest": d / "PTest.java"})
        cls = statediff.classes_for(proj, "p.VTest#victim", "p.PTest#pollute",
                                    "\tat com.lib.Cache.get(Cache.java:3)\n\tat java.util.HashMap.get(HashMap.java:1)")
        self.assertIn("p.Registry", cls)
        self.assertIn("com.lib.Cache", cls)
        self.assertFalse(any(c.startswith("java.") for c in cls))


class RepairParseTest(unittest.TestCase):
    def test_parse(self):
        t = {"victim": Path("V.java"), "polluter": Path("P.java")}
        p = repair.parse("FILE: polluter\n```java\nclass P {}\n```\nREASON: clean up in @After", t)
        self.assertEqual((p["target"], p["code"].strip(), p["reason"]), ("polluter", "class P {}", "clean up in @After"))
        self.assertEqual(repair.parse("```java\nclass V {}\n```", t)["target"], "victim")
        self.assertIsNone(repair.parse("no code", t)["code"])


class SupervisorTest(unittest.TestCase):
    def make(self, replies, statediff_on=True, validator="strict"):
        d = Path(tempfile.mkdtemp())
        vpath, ppath = d / "VTest.java", d / "PTest.java"
        vpath.write_text(VSRC)
        ppath.write_text(PSRC)
        tests = [f"p.OTest#t{i}" for i in range(12)]
        v, pol = "p.VTest#victim", "p.PTest#pollute"
        proj = FakeProject(tests + [pol, v], v, {pol}, {"p.VTest": vpath, "p.PTest": ppath})
        proj.run_state = lambda classes, t: {"ok": True, "secs": 0.1, "missing": [], "state": {
            "p.Registry.NAMES": 'ArrayList(size=1){"a"}' if t else "ArrayList(size=0){}"}}

        def recompile():  # the "patch" works when the victim file resets the registry
            proj.fixed = "NAMES.clear()" in vpath.read_text()
            from tests.fakes import R
            return R(ok="SYNTAX ERROR" not in vpath.read_text())
        proj.recompile = recompile
        cfg = config.get("full", llm_rank=False, statediff=statediff_on, validator=validator, n_loop=5)
        traj = Trajectory(max_llm_calls=cfg.max_llm_calls)
        order = tests[:6] + [pol] + tests[6:] + [v]
        ctx = {"proj": proj, "victim": v, "failing_order": order, "trace": "AssertionError", "cfg": cfg,
               "traj": traj, "seed": 1, "baseline_statuses": {}}
        it = iter(replies)
        fake_llm = lambda messages, temperature, max_tokens: {  # noqa: E731
            "text": next(it), "prompt_tokens": 100, "completion_tokens": 50, "secs": 0.1, "model": "fake"}
        return ctx, vpath, fake_llm

    def test_feedback_loop_then_accept(self):
        replies = ["FILE: victim\n```java\nSYNTAX ERROR\n```\nREASON: x",
                   "FILE: victim\n```java\n" + VSRC.replace("assertEquals(0, Registry.NAMES.size());", "") + "\n```",
                   "FILE: victim\n```java\n" + FIXED + "\n```\nREASON: reset the registry"]
        ctx, vpath, fake = self.make(replies)
        with mock.patch("pollutrace.llm.chat", side_effect=fake) as m:
            out = supervisor.solve(ctx)
        self.assertEqual(out["stop_reason"], "accepted")
        self.assertEqual(out["polluter"], "p.PTest#pollute")
        self.assertEqual([a["verdict"] for a in out["attempts"]], ["compile_error", "REJECT", "ACCEPT"])
        self.assertEqual(out["attempts"][1]["reasons"], ["integrity"])
        self.assertIn(str(vpath), out["patches"])
        self.assertEqual(vpath.read_text(), VSRC)  # checkout restored
        prompts = [c.args[0][1]["content"] for c in m.call_args_list]
        self.assertIn("does not compile", prompts[1])
        self.assertIn("weakens or skips", prompts[2])
        self.assertIn("Registry.NAMES", prompts[0])  # the state diff reached the prompt

    def test_no_statediff_prompt_has_no_diff(self):
        ctx, _, fake = self.make(["FILE: victim\n```java\n" + FIXED + "\n```"], statediff_on=False)
        with mock.patch("pollutrace.llm.chat", side_effect=fake) as m:
            out = supervisor.solve(ctx)
        self.assertEqual(out["stop_reason"], "accepted")
        self.assertNotIn("Shared state changed", m.call_args_list[0].args[0][1]["content"])

    def test_gives_up_after_max_iters(self):
        ctx, vpath, fake = self.make(["FILE: victim\n```java\n" + VSRC + "\n```"] * 4)
        with mock.patch("pollutrace.llm.chat", side_effect=fake):
            out = supervisor.solve(ctx)
        self.assertIsNone(out["patches"])
        self.assertEqual(out["iterations"], 4)
        self.assertEqual(vpath.read_text(), VSRC)

    def test_llm_budget(self):
        t = Trajectory(max_llm_calls=0)
        with self.assertRaises(BudgetExceeded):
            t.llm([{"role": "user", "content": "x"}], "a", "b")

    def test_systems_registered(self):
        for s in ("B1", "B4", "PolluTrace", "A1_no_localizer", "A2_no_statediff", "A3_no_validator"):
            self.assertIn(s, harness.SYSTEMS)


if __name__ == "__main__":
    unittest.main()
