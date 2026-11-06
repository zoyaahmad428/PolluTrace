"""Supervisor: orchestrates the PolluTrace agents for one victim.

    localize (G1) -> state diff (G2) -> [repair -> compile -> validate (G3)] x max_iters
Budgets: LLM calls (cfg.max_llm_calls, enforced by the trajectory), localization runs
(cfg.max_local_runs), wall time (cfg.victim_secs). Recovery and backtracking:
  * compile error, integrity issue or new failure -> fed back to the repair agent;
  * the validator finds a randomized order where the patched victim still fails -> the
    localizer searches that order for a second polluter, its state diff is added, and the
    repair agent retries with both polluters (cfg.relocalize);
  * no polluter found -> repair still runs from the trace and the failing order.
Every component is switchable through pollutrace/config.py, which is how A1-A3 and the
NIODebugger-style base paper (B4) are run with the same code.
"""
import dataclasses
import time
from pathlib import Path

from . import harness
from .agents import localizer, repair, statediff, validator
from .trajectory import BudgetExceeded

AGENT = "supervisor"


def solve(ctx):
    proj, v, cfg, traj = ctx["proj"], ctx["victim"], ctx["cfg"], ctx["traj"]
    order, trace, seed = ctx["failing_order"], ctx["trace"], ctx["seed"]
    deadline = time.time() + cfg.victim_secs
    traj.step(AGENT, "plan", config=cfg.asdict(), failing_order_len=len(order))
    out = {"polluter": None, "loc_runs": 0, "iterations": 0, "target": "", "polluters": [], "attempts": []}

    polluters = []
    if cfg.localizer != "none":
        loc = localizer.localize(proj, v, order, trace, traj, cfg, seed=seed)
        out["loc_runs"] = loc["runs"]
        out["localization"] = loc
        if loc["polluter"]:
            polluters.append(loc["polluter"])
            out["polluter"] = loc["polluter"]
        else:
            traj.step(AGENT, "decision", what="no polluter found; repair from trace and failing order only")
    diffs = {}
    if cfg.statediff:
        for p in polluters:
            diffs[p] = statediff.compute(proj, v, p, trace, traj)
        out["state_diff"] = {p: {k: d.get(k) for k in ("ok", "n_classes", "n_fields", "n_changed", "changes")}
                             for p, d in diffs.items()}

    history = []
    stop = "max iterations"
    for it in range(1, cfg.max_iters + 1):
        if time.time() > deadline:
            stop = "time budget"
            break
        out["iterations"] = it
        try:
            prop = repair.propose(proj, v, trace, polluters, diffs, history, traj, order if not polluters else None)
        except BudgetExceeded:
            stop = "llm budget"
            break
        except RuntimeError as e:  # provider failure after retries
            out.update(stop_reason="error", error=str(e)[:300])
            return out
        if prop is None:
            stop = "victim source not found"
            break
        if not prop["code"]:
            history.append({"attempt": it, "target": prop["target"], "reason": prop["reason"],
                            "feedback": "Your reply had no ```java code block with the complete file."})
            continue
        path = Path(prop["path"])
        orig = path.read_text(encoding="utf-8", errors="replace")
        try:
            path.write_text(prop["code"], encoding="utf-8")
            comp = traj.compile(proj, AGENT)
            att = {"attempt": it, "target": prop["target"], "reason": prop["reason"], "diff": proj.diff()[:4000]}
            if not comp.ok:
                from .trajectory import compile_errors
                att["feedback"] = "The file does not compile:\n" + compile_errors(comp.out)
                history.append(att)
                out["attempts"].append({**att, "verdict": "compile_error"})
                continue
            ver = validator.validate(proj, v, {path: (orig, prop["code"])}, order, polluters, traj, cfg,
                                     seed=seed + it, baseline=ctx.get("baseline_statuses"))
            out["attempts"].append({**att, "verdict": ver["verdict"], "reasons": ver["reasons"],
                                    "checks": ver["checks"]})
            if ver["verdict"] == "ACCEPT":
                out.update(patches={str(path): prop["code"]}, target=prop["target"], polluters=polluters,
                           stop_reason="accepted")
                return out
            att["feedback"] = ver["feedback"]
            history.append(att)
            # backtracking: a randomized order still fails -> find the other polluter in it
            if cfg.relocalize and "fails in random order" in ver["reasons"] and ver.get("failing_order") \
                    and time.time() < deadline:
                sub = dataclasses.replace(cfg, max_local_runs=max(8, cfg.max_local_runs // 2), llm_rank=False)
                fo = [t for t in ver["failing_order"] if t not in polluters]
                loc2 = localizer.localize(proj, v, fo, ver["feedback"], traj, sub, seed=seed + 100 + it)
                out["loc_runs"] += loc2["runs"]
                if loc2["polluter"] and loc2["polluter"] not in polluters:
                    polluters.append(loc2["polluter"])
                    traj.step(AGENT, "decision", what="backtrack: second polluter", polluter=loc2["polluter"])
                    if cfg.statediff:
                        diffs[loc2["polluter"]] = statediff.compute(proj, v, loc2["polluter"], trace, traj)
        finally:
            path.write_text(orig, encoding="utf-8")
    proj.recompile()
    out.update(patches=None, stop_reason=stop, polluters=polluters)
    traj.step(AGENT, "decision", what="give up", reason=stop)
    return out


for _name in ("PolluTrace", "A1_no_localizer", "A2_no_statediff", "A3_no_validator", "B4"):
    harness.register(_name)(solve)
