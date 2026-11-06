"""E4-G2: is the state diff informative, and does it help repair?

Part 1 (runs Java, no LLM): for each victim, the state diff of its confirmed polluter --
how many classes and fields were snapshotted, how many changed, and whether a changed field
belongs to a class the victim's code or trace refers to (the diff points at the right state).
Part 2 (no runs): paired comparison of E3 (with diff) and E5 A2 (without): fix rate and
repair iterations per victim; computed by eval/stats.py from the saved results.

    python experiments/e4_g2_statediff.py [--set test_subset.csv]
Output: results/E4_G2/diffs.csv
"""
import csv

from common import ids, parser

from pollutrace import env, harness
from pollutrace import static_state as ss
from pollutrace.agents import statediff
from pollutrace.project import Project
from pollutrace.trajectory import LOGS, Trajectory

FIELDS = ["id", "project", "victim", "polluter", "ok", "n_classes", "n_fields", "n_changed", "app_changes",
          "sysprop_changes", "points_at_victim_state", "top_changes", "secs", "error"]


def main():
    a = parser(__doc__, runs=1).parse_args()
    out = env.RESULTS / "E4_G2" / "diffs.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out.exists():
        with open(out, encoding="utf-8") as f:
            done = {r["id"] for r in csv.DictReader(f)}
    rows = harness.shard_rows(harness.load_set(a.set), a.shard)
    if ids(a):
        rows = [r for r in rows if r["id"] in ids(a)]
    for row in rows[:a.limit] if a.limit else rows:
        if row["id"] in done:
            continue
        proj = Project(row["project_url"], row["sha"], row["module"])
        if not proj.build():
            continue
        fo = harness.failing_order(proj, row)
        traj = Trajectory(LOGS / "trajectories" / "E4_G2" / f"{row['id']}.jsonl")
        d = statediff.compute(proj, row["victim"], row["confirmed_polluter"], fo.get("trace", ""), traj)
        vp = proj.test_source(row["victim"])
        vinfo = ss.analyse(vp.read_text(encoding="utf-8", errors="replace") if vp else "")
        vtypes = set(vinfo["types"]) | ss.trace_types(fo.get("trace", ""))
        ch = d.get("changes", [])
        app = [c for c in ch if not c["key"].startswith(("System.property:", "Locale.", "TimeZone."))]
        hit = any(c["key"].rsplit(".", 2)[-2].split("$")[0] in vtypes for c in app) or \
            any(c["key"].startswith("System.property:") and c["key"].split(":", 1)[1] in
                (vp.read_text(encoding="utf-8", errors="replace") if vp else "") for c in ch)
        rec = {"id": row["id"], "project": proj.root.name.split("__")[1], "victim": row["victim"],
               "polluter": row["confirmed_polluter"], "ok": d.get("ok"), "n_classes": d.get("n_classes", ""),
               "n_fields": d.get("n_fields", ""), "n_changed": d.get("n_changed", 0), "app_changes": len(app),
               "sysprop_changes": len(ch) - len(app), "points_at_victim_state": hit,
               "top_changes": " | ".join(c["key"] for c in ch[:5]), "secs": d.get("secs", ""),
               "error": d.get("error", "")[:200]}
        new = not out.exists()
        with open(out, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            if new:
                w.writeheader()
            w.writerow(rec)
        print(f"{row['id']}: {rec['n_changed']} changed of {rec['n_fields']} fields; points at victim state: {hit}",
              flush=True)


if __name__ == "__main__":
    main()
