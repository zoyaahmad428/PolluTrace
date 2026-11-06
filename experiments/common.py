"""Command-line options shared by the experiment scripts."""
import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def parser(desc, runs=3):
    ap = argparse.ArgumentParser(description=desc)
    ap.add_argument("--set", default="test_subset.csv", help="victim set under data/ (fixed; never tuned on)")
    ap.add_argument("--runs", type=int, default=runs, help="independent runs (mean and std are reported)")
    ap.add_argument("--first-run", type=int, default=1)
    ap.add_argument("--n-final", type=int, default=100, help="randomized orders in the final evaluation")
    ap.add_argument("--final-secs", type=int, default=900, help="time cap for the final randomized orders")
    ap.add_argument("--shard", default=None, help="i/k: run only projects with index mod k == i (two machines)")
    ap.add_argument("--limit", type=int, default=None, help="first L victims only (smoke tests)")
    ap.add_argument("--ids", default=None, help="comma-separated victim ids")
    return ap


def runs(a):
    return list(range(a.first_run, a.first_run + a.runs))


def ids(a):
    return set(a.ids.split(",")) if a.ids else None
