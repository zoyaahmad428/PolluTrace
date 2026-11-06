"""E1: baselines on the test set.

B1 (single LLM call) runs through the shared harness, 3 runs by default. B2 (iFixFlakies) has
no LLM and is deterministic, so it runs once through its own driver (baselines/b2_ifixflakies.py).

    python experiments/e1_baselines.py [--set test_subset.csv] [--runs 3] [--shard 0/2] [--skip-b2]
"""
import subprocess
import sys

from common import REPO, ids, parser, runs

from pollutrace import harness


def main():
    ap = parser(__doc__)
    ap.add_argument("--skip-b2", action="store_true")
    ap.add_argument("--b2-timeout", type=int, default=30, help="minutes per victim for iFixFlakies")
    a = ap.parse_args()
    harness.run_experiment("E1", "B1", "full", a.set, runs(a), a.n_final, a.final_secs, a.shard, a.limit, ids(a))
    if not a.skip_b2:
        subprocess.run([sys.executable, str(REPO / "baselines" / "b2_ifixflakies.py"), "--set", a.set,
                        "--timeout", str(a.b2_timeout), "--out", "E1/B2/run1.csv"], check=False)


if __name__ == "__main__":
    main()
