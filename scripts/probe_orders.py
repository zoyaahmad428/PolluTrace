"""How often does a random order expose each UNPATCHED dev victim, and what does one
order cost? This is the empirical basis for choosing N (randomized-order reruns).

For each dev victim: run N random orders (pool = victim + known polluters + 20 other
module tests) and record the fraction that fail and the time per order.

    python scripts/probe_orders.py [--n 100]
"""
import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pollutrace import env  # noqa: E402
from pollutrace.project import Project  # noqa: E402
from pollutrace.validate import random_orders  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--set", default="dev_set.csv")
    a = ap.parse_args()
    with open(env.REPO / "data" / a.set, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = env.RESULTS / "probe_orders.csv"
    done = set()
    if out.exists():
        with open(out, encoding="utf-8") as f:
            done = {r["id"] for r in csv.DictReader(f)}
    for r in rows:
        if r["id"] in done:
            continue
        proj = Project(r["project_url"], r["sha"], r["module"])
        pol = [p for p in r["polluters"].split(";") if p]
        rec = random_orders(proj, r["victim"], pol, a.n, seed=1)
        n_run = max(1, rec["n_run"])
        row = {"id": r["id"], "victim": r["victim"], "n": n_run, "budget_hit": rec["budget_hit"],
               "pool_size": rec["pool_size"],
               "fails": rec["fails"], "errors": rec["errors"], "fail_rate": round(rec["fails"] / n_run, 3),
               "first_fail_index": rec["first_fail_index"] or "", "mean_order_secs": rec["mean_order_secs"],
               "total_secs": rec["total_secs"]}
        new = not out.exists()
        with open(out, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(row))
            if new:
                w.writeheader()
            w.writerow(row)
        print(f"{r['id']}: fail rate {row['fail_rate']}, {row['mean_order_secs']} s/order, {row['total_secs']} s total",
              flush=True)


if __name__ == "__main__":
    main()
