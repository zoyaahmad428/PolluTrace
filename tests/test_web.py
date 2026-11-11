"""The web console must report exactly what the paper reports.

The console computes its metrics through eval/stats.py, so these tests compare what the API
serves against results/phase2_tables.md — the file the paper's tables are generated from. If
an experiment is re-run and the tables change, these tests follow; if the console ever starts
rounding or counting differently, they fail.

Tests that need saved results skip themselves when results/ is empty, so a fresh clone still
passes `python run_phase2.py tests`.
"""
import json
import re
import sys
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "web"))

import server as web_server  # noqa: E402
import webapi  # noqa: E402

TABLES = REPO / "results" / "phase2_tables.md"
HAVE_RESULTS = TABLES.exists() and bool(list((REPO / "results").glob("E*/*/run*.csv")))
PAPER_LABEL = {
    "B1": "B1 single LLM call",
    "B4": r"B4 NIODebugger-style \(base paper, ours\)",
    "PolluTrace": r"PolluTrace \(full\)",
    "A1_no_localizer": r"A1 without localizer \(G1\)",
    "A2_no_statediff": r"A2 without state diff \(G2\)",
    "A3_no_validator": r"A3 weak validator \(G3\)",
}


def tables():
    return TABLES.read_text(encoding="utf-8")


@unittest.skipUnless(HAVE_RESULTS, "no saved results to compare against")
class ConsoleMatchesPaperTest(unittest.TestCase):
    def test_main_table_rates_match(self):
        md = tables()
        for s in webapi.overview()["systems"]:
            # label | runs | victims | fixed | fix rate | precision | false-fix rate
            row = re.search(rf"\| {PAPER_LABEL[s['key']]} \| \d+ \| \d+ \| [\d.]+ \| "
                            rf"([\d.]+%) \| ([\d.]+%) \| ([\d.]+%) \|", md)
            self.assertIsNotNone(row, f"{s['key']} is missing from phase2_tables.md")
            for got, want, what in ((s["fix_rate"], row.group(1), "fix rate"),
                                    (s["precision"], row.group(2), "precision"),
                                    (s["false_fix_rate"], row.group(3), "false-fix rate")):
                self.assertEqual(f"{got * 100:.1f}%", want, f"{s['key']} {what}")

    def test_g1_localization_matches(self):
        md = tables()
        for s in webapi.g1_strategies():
            row = re.search(rf"\| {s['strategy']} \| \d+ \| [^|]+\| [^|]+\| ([\d.]+) \(\d+\) \| (\d+) \|", md)
            self.assertIsNotNone(row, f"{s['strategy']} is missing from phase2_tables.md")
            self.assertEqual(f"{s['mean_runs']:.1f}", row.group(1), f"{s['strategy']} order runs")
            self.assertEqual(f"{s['mean_execs']:.0f}", row.group(2), f"{s['strategy']} test executions")

    def test_g2_counts_match(self):
        md = tables()
        g2 = webapi.g2_summary()
        self.assertEqual(f"{g2['ok']} of {g2['total']}",
                         re.search(r"Victims with a diff computed \| (\d+ of \d+)", md).group(1))
        self.assertEqual(str(g2["with_change"]),
                         re.search(r"changed field or property \| (\d+)", md).group(1))

    def test_every_attempted_victim_has_an_outcome(self):
        for v in webapi.victims()["victims"]:
            if v["attempted"]:
                self.assertTrue(all(v["outcomes"].values()), f"{v['id']} has an empty outcome")


class ApiTest(unittest.TestCase):
    """Start the real server on a free port and call it over HTTP."""

    @classmethod
    def setUpClass(cls):
        class Quiet(web_server.Handler):
            def log_message(self, *a):
                pass

        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def get(self, path, expect=200):
        try:
            with urllib.request.urlopen(self.base + path, timeout=20) as r:
                self.assertEqual(r.status, expect, path)
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, expect, f"{path} returned {e.code}")
            return json.loads(e.read())

    def test_pages_and_assets_are_served(self):
        for path in ("/", "/app.js", "/style.css"):
            with urllib.request.urlopen(self.base + path, timeout=20) as r:
                self.assertEqual(r.status, 200, path)
                self.assertTrue(r.read())

    def test_endpoints_answer(self):
        for path in ("/api/health", "/api/overview", "/api/victims", "/api/gaps",
                     "/api/efficiency", "/api/trajectories", "/api/runs"):
            self.assertIsInstance(self.get(path), dict, path)

    def test_health_reports_whether_this_machine_can_run(self):
        h = self.get("/api/health")
        self.assertIsInstance(h["can_run"], bool)
        self.assertEqual(h["can_run"], not h["blockers"])

    def test_unknown_victim_is_a_404_not_a_crash(self):
        self.assertIn("error", self.get("/api/victims/NOPE", expect=404))

    def test_paths_cannot_escape_the_static_directory(self):
        for path in ("/../webapi.py", "/%2e%2e/webapi.py", "/../../pollutrace/llm.py"):
            try:
                with urllib.request.urlopen(self.base + path, timeout=20) as r:
                    self.fail(f"{path} was served with status {r.status}")
            except urllib.error.HTTPError as e:
                self.assertIn(e.code, (400, 404), path)

    def test_run_requests_are_validated(self):
        body = json.dumps({"victim_id": "../etc", "system": "PolluTrace"}).encode()
        req = urllib.request.Request(self.base + "/api/runs", data=body,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                self.fail(f"a bad victim id was accepted with status {r.status}")
        except urllib.error.HTTPError as e:
            self.assertEqual(e.code, 400)
            self.assertIn("error", json.loads(e.read()))


class ViewHelpersTest(unittest.TestCase):
    def test_test_names_split_for_display(self):
        self.assertEqual(webapi.short_test("a.b.CTest#m"),
                         {"full": "a.b.CTest#m", "pkg": "a.b", "cls": "CTest", "method": "m"})
        self.assertEqual(webapi.short_test("")["cls"], "")


if __name__ == "__main__":
    unittest.main()
