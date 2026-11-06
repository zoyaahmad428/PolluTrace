"""Fixed Phase 2 test subset, chosen by a rule decided before any Phase 2 run.

Rule: from data/test_set.csv (75 held-out victims), drop projects whose median time per
randomized order on the development set (results/probe_orders.csv, Phase 1) was over
--max-order-secs (default 10 s: admiral, Dubbo, c2mon, JHipster, spring-boot), then keep at
most --per-project victims per project (default 3), chosen with seed 2026. The 75-victim
set at 3 runs does not fit the Phase 2 time budget; the rule and the dropped projects are
reported in the paper.

    python scripts/make_subset.py  ->  data/test_subset.csv
"""
import argparse
import csv
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pollutrace import env  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-order-secs", type=float, default=10.0)
    ap.add_argument("--per-project", type=int, default=3)
    ap.add_argument("--seed", type=int, default=2026)
    a = ap.parse_args()
    data = env.REPO / "data"
    with open(data / "dev_set.csv", encoding="utf-8") as f:
        dev = {r["id"]: r["project_url"] for r in csv.DictReader(f)}
    slow = defaultdict(list)
    with open(env.RESULTS / "probe_orders.csv", encoding="utf-8") as f:
        rd = csv.reader(f)
        next(rd)
        for row in rd:  # rows differ in column count (budget_hit added later); mean_order_secs is 2nd to last
            if row and row[0] in dev:
                try:
                    slow[dev[row[0]]].append(float(row[-2]))
                except (ValueError, IndexError):
                    pass
    dropped = {p for p, v in slow.items() if statistics.median(v) > a.max_order_secs}
    with open(data / "test_set.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    by = defaultdict(list)
    for r in rows:
        if r["project_url"] not in dropped:
            by[r["project_url"]].append(r)
    rng = random.Random(a.seed)
    keep = []
    for p in sorted(by):
        v = by[p][:]
        rng.shuffle(v)
        keep += v[:a.per_project]
    keep.sort(key=lambda r: r["id"])
    with open(data / "test_subset.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(keep)
    print(f"test_subset.csv: {len(keep)} victims from {len(by)} projects")
    print("dropped (slow):", ", ".join(sorted(p.rsplit('/', 1)[-1] for p in dropped)) or "none")


if __name__ == "__main__":
    main()
