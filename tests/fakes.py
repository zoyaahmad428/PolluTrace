"""A fake Project for unit tests: no Java, no Maven. The victim fails if one of the
polluters ran before it in the same 'JVM', unless `fixed` is set (simulating a patch)."""
from pathlib import Path


class R:
    def __init__(self, ok=True, out=""):
        self.ok, self.out, self.secs, self.timed_out = ok, out, 0.1, False


class FakeProject:
    def __init__(self, tests, victim, polluters, sources=None, root=None):
        self.tests, self.victim, self.polluters = list(tests), victim, set(polluters)
        self.fixed = False
        self.broken_alone = False
        self.sources = sources or {}
        self.root = Path(root or "/tmp/fake__proj__0")
        self.runs = []

    def list_tests(self):
        return self.tests

    def run_order(self, order, timeout=600):
        self.runs.append(list(order))
        res, seen = {}, set()
        for t in order:
            st = "PASS"
            if t == self.victim:
                if self.broken_alone or (not self.fixed and seen & self.polluters):
                    st = "FAIL"
            res[t] = {"status": st, "trace": "java.lang.AssertionError: expected 1 but was 2" if st == "FAIL" else ""}
            seen.add(t)
        return {"order": list(order), "secs": 0.01, "timeout": False, "results": res}

    def status(self, res, test):
        return res["results"].get(test, {}).get("status", "ERROR")

    def test_source(self, test):
        cls = test.split("#")[0]
        return self.sources.get(cls)

    def recompile(self):
        return R()

    def diff(self):
        return ""

    def revert(self):
        pass
