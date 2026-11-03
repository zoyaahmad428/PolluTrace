"""Baseline B1: one LLM call, no loop, no tools.

Input to the model: the victim's test-class source and the stack trace from the failing
order. The model is NOT told which test is the polluter. Output: the full updated test
class. The patch is then validated exactly like every other system:
  1. compiles;  2. victim passes right after its confirmed polluter (fix);
  3. assertion integrity;  4. accepted patches are re-run in N=100 randomized orders.

    python baselines/b1_single_call.py [--set dev_set.csv] [--n 100]
"""
import argparse
import csv
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pollutrace import env, llm  # noqa: E402
from pollutrace.project import Project  # noqa: E402
from pollutrace.validate import failing_order_check, integrity, random_orders  # noqa: E402

SYSTEM = "You are an expert Java developer who fixes flaky tests."
PROMPT = """The JUnit test `{victim}` passes when run on its own, but fails when the test suite runs in a certain order.

Stack trace of the failure:
```
{trace}
```

Complete source of the test class `{file}`:
```java
{source}
```

Fix the test so it passes regardless of which tests run before it. Do not delete, skip, ignore or weaken any assertion, and do not change what the test checks.
Reply with the complete updated file in a single ```java code block, followed by at most one sentence explaining the fix."""

FIELDS = ["id", "victim", "outcome", "compiled", "fix", "passes_all_known_polluters", "integrity", "accepted",
          "rand_n", "rand_fails", "false_fix", "first_fail_index", "mean_order_secs", "rand_secs",
          "prompt_tokens", "completion_tokens", "llm_secs", "victim_secs", "model", "detail"]


def extract_java(text):
    blocks = re.findall(r"```(?:java)?\s*\n(.*?)```", text, flags=re.S)
    return max(blocks, key=len) if blocks else None


def run_one(r, n):
    v, cp = r["victim"], r["confirmed_polluter"]
    pol = [p for p in r["polluters"].split(";") if p]
    proj = Project(r["project_url"], r["sha"], r["module"])
    rec = {"id": r["id"], "victim": v, "model": llm.MODEL}
    dossier = {"system": "B1", "victim": v, "project": r["project_url"], "sha": r["sha"], "module": r["module"],
               "failing_order": [cp, v], "llm": llm.info(), "runs": [], "patches": []}
    fail = proj.run_order([cp, v])
    dossier["runs"].append({"order": [cp, v], "result": proj.status(fail, v), "secs": fail["secs"]})
    if proj.status(fail, v) != "FAIL":
        return {**rec, "outcome": "not_failing_now", "detail": proj.status(fail, v)}, dossier
    trace = fail["results"][v]["trace"][:4000]
    src_path = proj.test_source(v)
    if not src_path:
        return {**rec, "outcome": "source_not_found"}, dossier
    original = src_path.read_text(encoding="utf-8", errors="replace")
    msg = PROMPT.format(victim=v, trace=trace, file=src_path.name, source=original[:60000])
    try:
        resp = llm.chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": msg}])
    except RuntimeError as e:
        return {**rec, "outcome": "llm_error", "detail": str(e)[:300]}, dossier
    rec.update(prompt_tokens=resp["prompt_tokens"], completion_tokens=resp["completion_tokens"], llm_secs=resp["secs"])
    code = extract_java(resp["text"])
    if not code:
        return {**rec, "outcome": "no_code_in_reply", "detail": resp["text"][:200]}, dossier
    try:
        src_path.write_text(code, encoding="utf-8")
        comp = proj.recompile()
        rec["compiled"] = comp.ok
        patch = {"id": "p1", "site": "victim_file", "diff": proj.diff()[:20000]}
        if not comp.ok:
            patch["verdict"] = "REJECT"
            patch["reason"] = "compile error"
            dossier["patches"].append(patch)
            return {**rec, "outcome": "compile_error", "detail": comp.out[-300:]}, dossier
        foc = failing_order_check(proj, v, [cp] + [p for p in pol if p != cp])
        rec["fix"] = foc[0]["status"] == "PASS"
        rec["passes_all_known_polluters"] = all(x["status"] == "PASS" for x in foc)
        integ = integrity(original, code, v.split("#")[1])
        rec["integrity"] = "ok" if integ["ok"] else ";".join(integ["issues"])
        rec["accepted"] = rec["fix"] and integ["ok"]
        if rec["accepted"]:
            rr = random_orders(proj, v, pol, n, seed=7)
            rec.update(rand_n=n, rand_fails=rr["fails"] + rr["errors"], false_fix=(rr["fails"] + rr["errors"]) > 0,
                       first_fail_index=rr["first_fail_index"] or "", mean_order_secs=rr["mean_order_secs"],
                       rand_secs=rr["total_secs"])
            dossier["validation"] = rr
        patch.update(verdict="ACCEPT" if rec["accepted"] else "REJECT", failing_order_check=foc, integrity=integ)
        dossier["patches"].append(patch)
        outcome = "fixed" if rec["accepted"] else ("fix_but_integrity" if rec["fix"] else "not_fixed")
        if rec["accepted"] and rec.get("false_fix"):
            outcome = "false_fix"
        rec["outcome"] = outcome
        return rec, dossier
    finally:
        proj.revert()
        proj.recompile()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="dev_set.csv")
    ap.add_argument("--n", type=int, default=100)
    a = ap.parse_args()
    with open(env.REPO / "data" / a.set, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = env.RESULTS / "b1_single_call.csv"
    done = set()
    if out.exists():
        with open(out, encoding="utf-8") as f:
            done = {x["id"] for x in csv.DictReader(f)}
    for r in rows:
        if r["id"] in done:
            continue
        t0 = time.time()
        rec, dossier = run_one(r, a.n)
        rec["victim_secs"] = round(time.time() - t0, 1)
        env.write_json(env.RESULTS / "dossiers" / "B1" / f"{r['id']}.json", dossier)
        new = not out.exists()
        with open(out, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            if new:
                w.writeheader()
            w.writerow({k: rec.get(k, "") for k in FIELDS})
        print(f"{r['id']} {r['victim'][-60:]}: {rec['outcome']} ({rec.get('victim_secs', '?')} s)", flush=True)


if __name__ == "__main__":
    main()
