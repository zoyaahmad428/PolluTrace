"""E2: base paper (NIODebugger-style pipeline, baselines/b4_niodebugger.py), 3 runs.

    python experiments/e2_base_paper.py [--set test_subset.csv] [--runs 3] [--shard 0/2]
"""
from common import ids, parser, runs

from baselines import b4_niodebugger
from pollutrace import harness


def main():
    a = parser(__doc__).parse_args()
    harness.run_experiment("E2", "B4", b4_niodebugger.CONFIG, a.set, runs(a), a.n_final, a.final_secs, a.shard,
                           a.limit, ids(a))


if __name__ == "__main__":
    main()
