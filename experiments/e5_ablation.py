"""E5: ablations. Each removes one gap component from full PolluTrace; everything else is equal.

    A1_no_localizer   G1 off: repair from the trace and failing order only, no polluter
    A2_no_statediff   G2 off: no state diff in the repair prompt
    A3_no_validator   G3 off: accept when the victim passes the failing order once

    python experiments/e5_ablation.py [--only A2_no_statediff] [--set test_subset.csv] [--runs 3]
"""
from common import ids, parser, runs

from pollutrace import harness, supervisor  # noqa: F401

ABLATIONS = [("A1_no_localizer", "no_localizer"), ("A2_no_statediff", "no_statediff"),
             ("A3_no_validator", "no_validator")]


def main():
    ap = parser(__doc__)
    ap.add_argument("--only", default=None, help="one ablation name")
    a = ap.parse_args()
    for system, cfg in ABLATIONS:
        if a.only and a.only != system:
            continue
        harness.run_experiment("E5", system, cfg, a.set, runs(a), a.n_final, a.final_secs, a.shard, a.limit, ids(a))


if __name__ == "__main__":
    main()
