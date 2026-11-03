"""Patch validation used for every system (baselines and PolluTrace alike).

* failing-order check: the victim must PASS when run right after its polluter;
* randomized orders: the victim must PASS in each of N random orders of a pool made of
  the victim, all known polluters for it, and K other tests from the same module;
* assertion integrity: the patch must not skip, ignore or weaken the victim.

The known polluters come from IDoFT ground truth and are used only for evaluation;
no system under test sees them.
"""
import random
import re
import time

POOL_EXTRA = 20  # other module tests mixed into every randomized order


def failing_order_check(proj, victim, polluters):
    out = []
    for p in polluters:
        r = proj.run_order([p, victim])
        out.append({"polluter": p, "status": proj.status(r, victim), "secs": r["secs"]})
    return out


def random_orders(proj, victim, polluters, n, seed=0, extra=POOL_EXTRA, stop_on_fail=False):
    rng = random.Random(seed)
    others = [t for t in proj.list_tests() if t != victim and t not in polluters]
    rng.shuffle(others)
    pool = [victim] + list(polluters) + others[:extra]
    rec = {"n": n, "pool_size": len(pool), "passes": 0, "fails": 0, "errors": 0,
           "first_fail_index": None, "order_secs": [], "fail_indices": []}
    t0 = time.time()
    for i in range(n):
        order = pool[:]
        rng.shuffle(order)
        r = proj.run_order(order)
        st = proj.status(r, victim)
        rec["order_secs"].append(r["secs"])
        if st == "PASS":
            rec["passes"] += 1
        else:
            rec["fails" if st == "FAIL" else "errors"] += 1
            rec["fail_indices"].append(i + 1)
            if rec["first_fail_index"] is None:
                rec["first_fail_index"] = i + 1
            if stop_on_fail:
                break
    rec["total_secs"] = round(time.time() - t0, 1)
    rec["mean_order_secs"] = round(sum(rec["order_secs"]) / max(1, len(rec["order_secs"])), 2)
    return rec


ASSERT_RE = re.compile(r"\b(assert\w*|fail|verify|expect\w*)\s*\(")
SKIP_RE = re.compile(r"@(Ignore|Disabled)\b|Assume\.|assume\w*\s*\(")


def integrity(original_src, patched_src, method):
    """Heuristic check that the victim was not skipped, ignored or weakened."""
    issues = []
    if patched_src is None:
        return {"ok": False, "issues": ["no patched source"]}
    if len(ASSERT_RE.findall(patched_src)) < len(ASSERT_RE.findall(original_src)):
        issues.append("fewer assertions")
    if len(SKIP_RE.findall(patched_src)) > len(SKIP_RE.findall(original_src)):
        issues.append("adds ignore/disable/assume")
    if not re.search(r"\b" + re.escape(method) + r"\s*\(", patched_src):
        issues.append("victim method removed or renamed")
    body = _method_body(patched_src, method)
    if body is not None and re.match(r"\s*\{\s*(if\s*\([^)]*\)\s*)?return\s*;", body):
        issues.append("early return at start of victim")
    return {"ok": not issues, "issues": issues}


def _method_body(src, method):
    m = re.search(r"\b" + re.escape(method) + r"\s*\([^)]*\)[^{;]*\{", src)
    if not m:
        return None
    i, depth = m.end() - 1, 0
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[i:j + 1]
    return None
