"""Experiment harness shared by every system (baselines, base paper, PolluTrace, ablations).

For each victim and run k:
  1. load the victim's fixed failing order (built once, cached in results/failing_orders/):
     30 random module tests plus the confirmed polluter at a random position, then the victim,
     verified to fail. Systems get only this order and the failure trace -- never the IDoFT
     polluter list.
  2. call the system: system(ctx) -> {"patches": {path: new_source} or None, ...}
  3. apply the final patch, recompile and run the FINAL evaluation, identical for all systems:
     victim after every known polluter (ground truth), assertion integrity, and N_final
     randomized orders (default 100, 15-minute cap; Phase 1, Section B.12).
  4. write one CSV row, the dossier and the trajectory; restore the checkout.

Results: results/<experiment>/<system>/run<k>.csv, dossiers under .../dossiers/run<k>/,
trajectories under logs/trajectories/<experiment>/<system>/run<k>/.
"""
import csv
import hashlib
import random
import time
import traceback
from pathlib import Path

from . import config as cfgmod
from . import env, llm
from .agents.validator import check_integrity
from .project import Project
from .trajectory import LOGS, BudgetExceeded, Trajectory
from .validate import random_orders

SYSTEMS = {}
PREFIX_LEN = 30
FIELDS = ["id", "project", "victim", "system", "config", "run", "outcome", "compiled", "fix", "all_known_polluters",
          "integrity", "rand_n", "rand_fails", "false_fix", "polluter_found", "polluter_correct", "loc_runs",
          "iterations", "llm_calls", "prompt_tokens", "completion_tokens", "llm_secs", "test_runs",
          "test_executions", "test_secs", "agent_secs", "final_secs", "model", "temperature", "seed", "target",
          "stop_reason", "detail"]


def register(name):
    def deco(fn):
        SYSTEMS[name] = fn
        return fn
    return deco


def load_set(name):
    with open(env.REPO / "data" / name, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def stable_seed(*parts):
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


# ------------------------------------------------------------ failing order
def failing_order(proj, row):
    """Fixed failing order for a victim (cached; identical for every system and run)."""
    path = env.RESULTS / "failing_orders" / f"{row['id']}.json"
    cached = env.read_json(path, None)
    if cached:
        return cached
    v, cp = row["victim"], row["confirmed_polluter"]
    known = {p for p in row["polluters"].split(";") if p}
    rng = random.Random(stable_seed(row["id"], "failing-order"))
    others = [t for t in proj.list_tests() if t != v and t not in known]
    rng.shuffle(others)
    prefix = others[:PREFIX_LEN]
    rec = None
    for pos in (rng.randint(0, len(prefix)), len(prefix)):  # random position; else right before the victim
        order = prefix[:pos] + [cp] + prefix[pos:] + [v]
        r = proj.run_order(order)
        if proj.status(r, v) == "FAIL":
            rec = {"id": row["id"], "order": order, "trace": r["results"][v]["trace"],
                   "polluter_position": pos, "statuses": {t: x["status"] for t, x in r["results"].items()},
                   "secs": r["secs"]}
            break
    if rec is None:
        rec = {"id": row["id"], "order": None, "error": "victim does not fail in the constructed order"}
    env.write_json(path, rec)
    return rec


# ------------------------------------------------------------ final evaluation
def final_eval(proj, row, patches, n_final, final_secs, seed):
    """Apply patches, recompile, evaluate against IDoFT ground truth. Returns (fields, detail)."""
    v, cp = row["victim"], row["confirmed_polluter"]
    known = [p for p in row["polluters"].split(";") if p]
    pmap = {Path(k): new for k, new in patches.items()}
    originals = {}
    out = {}
    try:
        for path, new in pmap.items():
            originals[path] = path.read_text(encoding="utf-8", errors="replace")
            path.write_text(new, encoding="utf-8")
        comp = proj.recompile()
        out["compiled"] = comp.ok
        if not comp.ok:
            return {**out, "outcome": "compile_error"}, {"compile": comp.out[-1500:]}
        detail = {"diff": proj.diff()[:20000]}
        res = [(p, proj.status(proj.run_order([p, v]), v)) for p in [cp] + [p for p in known if p != cp]]
        detail["known_polluters"] = res
        out["fix"] = res[0][1] == "PASS"
        out["all_known_polluters"] = all(s == "PASS" for _, s in res)
        issues = check_integrity({p: (originals[p], pmap[p]) for p in pmap}, v)
        out["integrity"] = "ok" if not issues else ";".join(issues)
        if not out["fix"]:
            return {**out, "outcome": "not_fixed"}, detail
        if issues:
            return {**out, "outcome": "fix_but_integrity"}, detail
        rr = random_orders(proj, v, known, n_final, seed=seed, max_secs=final_secs)
        detail["random_orders"] = rr
        out.update(rand_n=rr["n_run"], rand_fails=rr["fails"] + rr["errors"])
        out["false_fix"] = out["rand_fails"] > 0
        if out["false_fix"]:
            return {**out, "outcome": "false_fix"}, detail
        if not out["all_known_polluters"]:
            return {**out, "outcome": "partial_fix"}, detail
        return {**out, "outcome": "fixed"}, detail
    finally:
        proj.revert()
        proj.recompile()


# ------------------------------------------------------------ experiment loop
def out_paths(experiment, system, run):
    base = env.RESULTS / experiment / system
    return base / f"run{run}.csv", base / "dossiers" / f"run{run}", LOGS / "trajectories" / experiment / system / f"run{run}"


def done_ids(csv_path, retry=("error", "llm_error")):
    if not csv_path.exists():
        return set()
    with open(csv_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    keep = [r for r in rows if r["outcome"] not in retry]
    if len(keep) != len(rows):
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            for r in keep:
                w.writerow({k: r.get(k, "") for k in FIELDS})
    return {r["id"] for r in keep}


def append_row(csv_path, rec):
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    new = not csv_path.exists()
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow({k: rec.get(k, "") for k in FIELDS})


def shard_rows(rows, shard):
    """'i/k': keep projects whose index mod k == i, so two machines never share a checkout."""
    if not shard:
        return rows
    i, k = map(int, shard.split("/"))
    projects = sorted({r["project_url"] for r in rows})
    mine = {p for j, p in enumerate(projects) if j % k == i}
    return [r for r in rows if r["project_url"] in mine]


def run_one(system, cfg, row, run, experiment, n_final, final_secs):
    fn = SYSTEMS[system]
    csv_path, dos_dir, traj_dir = out_paths(experiment, system, run)
    proj = Project(row["project_url"], row["sha"], row["module"])
    base = {"id": row["id"], "project": proj.root.name.split("__")[1], "victim": row["victim"], "system": system,
            "config": cfg.name, "run": run,
            "temperature": cfg.temperature if llm.sends_temperature() else "default(1.0)", "seed": stable_seed(row["id"], run)}
    if not proj.build():
        return {**base, "outcome": "build_failed"}, {}
    if proj.diff().strip():  # an interrupted run left a patch behind
        proj.revert()
        proj.recompile()
    fo = failing_order(proj, row)
    if not fo.get("order"):
        return {**base, "outcome": "no_failing_order", "detail": fo.get("error", "")}, {"failing_order": fo}
    traj = Trajectory(traj_dir / f"{row['id']}.jsonl", max_llm_calls=cfg.max_llm_calls, temperature=cfg.temperature)
    ctx = {"proj": proj, "victim": row["victim"], "failing_order": fo["order"], "trace": fo["trace"],
           "baseline_statuses": fo["statuses"], "cfg": cfg, "traj": traj, "seed": base["seed"], "id": row["id"]}
    t0 = time.time()
    try:
        res = fn(ctx) or {}
    except BudgetExceeded as e:
        res = {"patches": None, "stop_reason": "llm budget: " + str(e)}
    except Exception as e:
        traj.step("harness", "error", error=traceback.format_exc()[-2000:])
        res = {"patches": None, "stop_reason": "error", "error": str(e)[:300]}
    finally:
        if proj.diff().strip():  # systems must leave the checkout clean; make sure
            proj.revert()
            proj.recompile()
    agent_secs = round(time.time() - t0, 1)
    usage = traj.summary()
    known = {p for p in row["polluters"].split(";") if p}
    rec = {**base, **{k: usage[k] for k in ("llm_calls", "prompt_tokens", "completion_tokens", "llm_secs",
                                            "test_runs", "test_executions", "test_secs")},
           "agent_secs": agent_secs, "model": llm.MODEL or "", "iterations": res.get("iterations", ""),
           "polluter_found": res.get("polluter") or "", "loc_runs": res.get("loc_runs", ""),
           "polluter_correct": (res.get("polluter") in known) if res.get("polluter") else "",
           "target": res.get("target", ""), "stop_reason": res.get("stop_reason", ""), "detail": res.get("error", "")}
    detail = {}
    if res.get("stop_reason") == "error" and "LLM call failed" in res.get("error", ""):
        rec["outcome"] = "llm_error"
    elif not res.get("patches"):
        rec["outcome"] = "no_patch"
    else:
        t1 = time.time()
        ev, detail = final_eval(proj, row, res["patches"], n_final, final_secs, seed=7 + run)
        rec.update(ev)
        rec["final_secs"] = round(time.time() - t1, 1)
    dossier = {"system": system, "config": cfg.asdict(), "run": run, "victim": row["victim"], "id": row["id"],
               "project": row["project_url"], "sha": row["sha"], "module": row["module"],
               "failing_order": fo["order"], "llm": {"base_url": llm.BASE, "model": llm.MODEL},
               "result": rec, "system_output": {k: v for k, v in res.items() if k != "patches"},
               "final_patch": res.get("patches"), "final_evaluation": detail, "usage": usage,
               "trajectory": str(traj.path.relative_to(env.REPO)) if traj.path else None}
    env.write_json(dos_dir / f"{row['id']}.json", dossier)
    return rec, dossier


def run_experiment(experiment, system, cfg_name, set_name, runs, n_final=100, final_secs=900, shard=None,
                   limit=None, ids=None, **cfg_overrides):
    cfg = cfgmod.get(cfg_name, **cfg_overrides)
    rows = shard_rows(load_set(set_name), shard)
    if ids:
        rows = [r for r in rows if r["id"] in ids]
    if limit:
        rows = rows[:limit]
    print(f"[{experiment}] {system} ({cfg.name}) on {set_name}: {len(rows)} victims x {len(runs)} runs; "
          f"LLM {llm.BASE} {llm.MODEL or '(auto)'}", flush=True)
    for run in runs:
        csv_path = out_paths(experiment, system, run)[0]
        done = done_ids(csv_path)
        for row in rows:
            if row["id"] in done:
                continue
            rec, _ = run_one(system, cfg, row, run, experiment, n_final, final_secs)
            append_row(csv_path, rec)
            print(f"  run{run} {row['id']} {row['victim'][-55:]}: {rec['outcome']} "
                  f"(llm {rec.get('llm_calls', 0)}, tests {rec.get('test_runs', 0)}, {rec.get('agent_secs', 0)} s)",
                  flush=True)


# ------------------------------------------------------------ B1 as a system
@register("B1")
def b1_system(ctx):
    """Baseline B1: one LLM call with the victim class and the trace; no tools, no loop."""
    from baselines.b1_single_call import PROMPT, SYSTEM, extract_java
    proj, v, traj = ctx["proj"], ctx["victim"], ctx["traj"]
    src_path = proj.test_source(v)
    if not src_path:
        return {"patches": None, "stop_reason": "source not found"}
    original = src_path.read_text(encoding="utf-8", errors="replace")
    msg = PROMPT.format(victim=v, trace=ctx["trace"][:4000], file=src_path.name, source=original[:60000])
    try:
        resp = traj.llm([{"role": "system", "content": SYSTEM}, {"role": "user", "content": msg}], "B1", "repair")
    except RuntimeError as e:
        return {"patches": None, "stop_reason": "error", "error": str(e)[:300]}
    code = extract_java(resp["text"])
    if not code:
        return {"patches": None, "stop_reason": "no code in reply", "iterations": 1}
    return {"patches": {str(src_path): code}, "iterations": 1, "target": "victim", "stop_reason": "single call"}
