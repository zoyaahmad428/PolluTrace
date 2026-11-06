"""E3: full PolluTrace (localizer + state diff + strict validator, with backtracking), 3 runs.

    python experiments/e3_pollutrace.py [--set test_subset.csv] [--runs 3] [--shard 0/2]
"""
from common import ids, parser, runs

from pollutrace import harness, supervisor  # noqa: F401  (registers the systems)


def main():
    a = parser(__doc__).parse_args()
    harness.run_experiment("E3", "PolluTrace", "full", a.set, runs(a), a.n_final, a.final_secs, a.shard, a.limit,
                           ids(a))


if __name__ == "__main__":
    main()
