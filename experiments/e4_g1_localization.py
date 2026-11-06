"""E4-G1: polluter localization. How many test-order executions does each strategy need to
find a real polluter inside the failing order, and how often is the found test a known
(IDoFT) polluter?

Strategies (pollutrace/agents/localizer.py): ranked+LLM (PolluTrace), ranked static only,
one_by_one (iDFlakies-style), bisect (iFixFlakies delta debugging), random. All share the same
failing order and run budget. LLM-ranked and random repeat for --runs; the deterministic
strategies run once.

Also reported without any execution: the rank of the first known polluter in the static
and the LLM ranking (top-1 / top-5 accuracy).

    python experiments/e4_g1_localization.py [--set test_subset.csv] [--runs 3] [--budget 40]
Output: results/E4_G1/localization.csv
"""
import csv
import time

from common import ids, parser, runs

from pollutrace import config, env, harness
from pollutrace.agents import localizer
from pollutrace.project import Project
from pollutrace.trajectory import LOGS, Trajectory

FIELDS = ["id", "project", "victim", "strategy", "run", "found", "correct", "runs", "test_executions", "test_secs",
          "llm_calls", "prompt_tokens", "completion_tokens", "rank_first_known", "prefix_len", "polluter_position",
          "secs"]
STRATEGIES = [("ranked_llm", "ranked", True, True), ("ranked_static", "ranked", False, False),
              ("one_by_one", "one_by_one", False, False), ("bisect", "bisect", False, False),
              ("random", "random", False, True)]   # (label, strategy, llm_rank, repeat per run)


def main():
    ap = parser(__doc__)
    ap.add_argument("--budget", type=int, default=40, help="max test-order executions per strategy")
    a = ap.parse_args()
    out = env.RESULTS / "E4_G1" / "localization.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out.exists():
        with open(out, encoding="utf-8") as f:
            done = {(r["id"], r["strategy"], r["run"]) for r in csv.DictReader(f)}
    rows = harness.shard_rows(harness.load_set(a.set), a.shard)
    if ids(a):
        rows = [r for r in rows if r["id"] in ids(a)]
    rows = rows[:a.limit] if a.limit else rows
    for row in rows:
        proj = Project(row["project_url"], row["sha"], row["module"])
        if not proj.build():
            continue
        fo = harness.failing_order(proj, row)
        if not fo.get("order"):
            continue
        known = {p for p in row["polluters"].split(";") if p}
        for label, strat, llm_rank, repeat in STRATEGIES:
            for run in (runs(a) if repeat else runs(a)[:1]):
                if (row["id"], label, str(run)) in done:
                    continue
                cfg = config.get("full", localizer=strat, llm_rank=llm_rank, max_local_runs=a.budget)
                traj = Trajectory(LOGS / "trajectories" / "E4_G1" / label / f"run{run}" / f"{row['id']}.jsonl",
                                  max_llm_calls=2, temperature=cfg.temperature)
                t0 = time.time()
                res = localizer.localize(proj, row["victim"], fo["order"], fo["trace"], traj, cfg,
                                         seed=harness.stable_seed(row["id"], run))
                u = traj.summary()
                rk = next((i + 1 for i, t in enumerate(res["ranked"]) if t in known), "") if strat == "ranked" else ""
                rec = {"id": row["id"], "project": proj.root.name.split("__")[1], "victim": row["victim"],
                       "strategy": label, "run": run, "found": res["polluter"] or "",
                       "correct": (res["polluter"] in known) if res["polluter"] else False, "runs": res["runs"],
                       "test_executions": u["test_executions"], "test_secs": u["test_secs"],
                       "llm_calls": u["llm_calls"], "prompt_tokens": u["prompt_tokens"],
                       "completion_tokens": u["completion_tokens"], "rank_first_known": rk,
                       "prefix_len": len(fo["order"]) - 1, "polluter_position": fo["polluter_position"],
                       "secs": round(time.time() - t0, 1)}
                new = not out.exists()
                with open(out, "a", newline="", encoding="utf-8") as f:
                    w = csv.DictWriter(f, fieldnames=FIELDS)
                    if new:
                        w.writeheader()
                    w.writerow(rec)
                print(f"{row['id']} {label} run{run}: found={bool(rec['found'])} correct={rec['correct']} "
                      f"runs={rec['runs']} rank={rk}", flush=True)


if __name__ == "__main__":
    main()
