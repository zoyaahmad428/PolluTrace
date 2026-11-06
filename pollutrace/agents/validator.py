"""Validator agent (gap G3): decides whether a candidate patch really fixes the victim.

The patch is already applied and compiled when validate() is called. Strict mode (PolluTrace):
  1. integrity of every touched test file (no fewer assertions, no @Ignore/assume, no swallowed
     assertion errors, victim method kept and not short-circuited);
  2. the victim passes in the original failing order and right after every polluter found so far;
  3. the victim still passes alone, and the polluter itself still passes;
  4. N randomized orders (cfg.n_loop, time-capped) of a pool made of the victim, the polluters
     found so far and 20 other module tests; the first failing order is returned so the
     supervisor can localize a second polluter (backtracking).
Weak mode (ablation A3, and most prior tools): accept if the victim passes the failing order once.

Only polluters found by the localizer are used here; IDoFT ground truth is reserved for the
final evaluation in pollutrace/harness.py.
"""
import random
import time

from ..validate import POOL_EXTRA, integrity

AGENT = "validator"


def check_integrity(patches, victim):
    """patches: {path: (original_src, new_src)}. The victim's own file gets method-level checks."""
    vcls, vm = victim.split("#")
    simple = vcls.split(".")[-1].split("$")[0]
    issues = []
    for path, (orig, new) in patches.items():
        is_victim_file = str(path).replace("\\", "/").endswith("/" + simple + ".java")
        r = integrity(orig, new, vm if is_victim_file else None)
        issues += [f"{getattr(path, 'name', path)}: {i}" for i in r["issues"]]
    return issues


def validate(proj, victim, patches, failing_order, polluters, traj, cfg, seed=0, baseline=None):
    """Returns dict(verdict ACCEPT|REJECT, reasons, feedback, failing_order (for backtracking), checks)."""
    baseline = baseline or {}
    checks, reasons, feedback = {}, [], []
    traj.step(AGENT, "plan", mode=cfg.validator, polluters=polluters, n_loop=cfg.n_loop)

    def reject(why, fb, order=None):
        reasons.append(why)
        feedback.append(fb)
        out = {"verdict": "REJECT", "reasons": reasons, "feedback": "\n\n".join(feedback), "checks": checks,
               "failing_order": order}
        traj.step(AGENT, "decision", verdict="REJECT", reasons=reasons)
        return out

    if cfg.validator == "strict":
        issues = check_integrity(patches, victim)
        checks["integrity"] = issues or "ok"
        if issues:
            return reject("integrity", "The patch weakens or skips the test, which is not allowed: "
                          + "; ".join(issues) + ". Keep every assertion and fix the shared state instead.")

    r = traj.run_order(proj, failing_order, AGENT, "failing order")
    st = proj.status(r, victim)
    checks["failing_order"] = st
    if st != "PASS":
        tr = r["results"].get(victim, {}).get("trace", "")[:2500]
        return reject("still fails in failing order",
                      f"The victim still fails ({st}) when run in the original failing order. New failure:\n{tr}",
                      failing_order)
    if cfg.validator == "weak":
        traj.step(AGENT, "decision", verdict="ACCEPT", mode="weak")
        return {"verdict": "ACCEPT", "reasons": [], "feedback": "", "checks": checks, "failing_order": None}

    for p in polluters:
        r = traj.run_order(proj, [p, victim], AGENT, "polluter then victim")
        st, pst = proj.status(r, victim), proj.status(r, p)
        checks[f"after {p}"] = st
        if st != "PASS":
            tr = r["results"].get(victim, {}).get("trace", "")[:2500]
            return reject("fails after polluter", f"The victim still fails ({st}) when run right after {p}:\n{tr}",
                          [p, victim])
        if pst != "PASS" and baseline.get(p, "PASS") == "PASS":
            tr = r["results"].get(p, {}).get("trace", "")[:2000]
            return reject("breaks polluter", f"The patch makes {p} itself fail ({pst}):\n{tr}")
    r = traj.run_order(proj, [victim], AGENT, "victim alone")
    checks["alone"] = proj.status(r, victim)
    if checks["alone"] != "PASS":
        tr = r["results"].get(victim, {}).get("trace", "")[:2500]
        return reject("fails alone", f"After the patch the victim fails even when run alone:\n{tr}")

    rr = loop_random_orders(proj, victim, polluters, cfg.n_loop, seed, traj, cfg.loop_secs)
    checks["random_orders"] = {k: rr[k] for k in ("n_run", "fails", "budget_hit")}
    if rr["fails"]:
        tr = rr["trace"][:2500]
        return reject("fails in random order",
                      f"The victim failed in {rr['fails']} of {rr['n_run']} randomized orders. "
                      f"Some other test also leaves state behind. Failure:\n{tr}", rr["failing_order"])
    traj.step(AGENT, "decision", verdict="ACCEPT", checks=checks)
    return {"verdict": "ACCEPT", "reasons": [], "feedback": "", "checks": checks, "failing_order": None}


def loop_random_orders(proj, victim, polluters, n, seed, traj, max_secs):
    """In-loop randomized orders; stops at the first failure and returns that order."""
    rng = random.Random(seed)
    others = [t for t in proj.list_tests() if t != victim and t not in polluters]
    rng.shuffle(others)
    pool = [victim] + list(polluters) + others[:POOL_EXTRA]
    out = {"n_run": 0, "fails": 0, "budget_hit": False, "failing_order": None, "trace": ""}
    t0 = time.time()
    for i in range(n):
        if time.time() - t0 > max_secs:
            out["budget_hit"] = True
            break
        order = pool[:]
        rng.shuffle(order)
        r = traj.run_order(proj, order, AGENT, f"random order {i + 1}/{n}")
        out["n_run"] = i + 1
        if proj.status(r, victim) != "PASS":
            out["fails"] = 1
            out["failing_order"] = order[:order.index(victim) + 1]
            out["trace"] = r["results"].get(victim, {}).get("trace", "")
            break
    return out
