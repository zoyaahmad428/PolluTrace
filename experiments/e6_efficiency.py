"""E6: efficiency and reliability, from the saved E1-E5 results (no new runs).

Per system: mean and std over runs of LLM calls, tokens, estimated cost, test executions,
agent time and final-evaluation time per victim; reliability = share of victims with the same
outcome in every run, and the std of the fix rate across runs.

    python experiments/e6_efficiency.py [--usd-per-mtok-in 0.30] [--usd-per-mtok-out 2.50]
Output: results/E6/efficiency.csv (also included in results/phase2_tables.md by eval/stats.py)
"""
import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from eval import stats  # noqa: E402
from pollutrace import env  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--usd-per-mtok-in", type=float, default=0.30)
    ap.add_argument("--usd-per-mtok-out", type=float, default=2.50)
    a = ap.parse_args()
    rows = stats.efficiency(stats.load_runs(), a.usd_per_mtok_in, a.usd_per_mtok_out)
    out = env.RESULTS / "E6" / "efficiency.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    if rows:
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    for r in rows:
        print(r)


if __name__ == "__main__":
    main()
