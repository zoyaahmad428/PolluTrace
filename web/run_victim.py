"""Run one victim through one PolluTrace configuration, for the web console.

Results are written under results/WEB/ and logs/trajectories/WEB/ with a fresh run number,
so a run started from the console never touches the experiment results the paper reports.

    python web/run_victim.py --id V113 --system PolluTrace --run 1
"""
import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from baselines import b4_niodebugger  # noqa: E402,F401  (registers "B4")
from pollutrace import harness, supervisor  # noqa: E402,F401  (registers the agent systems)

# system name -> config preset, matching the experiment scripts
CONFIGS = {
    "PolluTrace": "full",
    "A1_no_localizer": "no_localizer",
    "A2_no_statediff": "no_statediff",
    "A3_no_validator": "no_validator",
    "B4": "b4_niodebugger",
    "B1": "full",
}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--id", required=True, help="victim id, e.g. V113")
    ap.add_argument("--system", default="PolluTrace", choices=sorted(CONFIGS))
    ap.add_argument("--run", type=int, required=True, help="run number under results/WEB/")
    ap.add_argument("--set", default="test_subset.csv")
    ap.add_argument("--n-final", type=int, default=20,
                    help="randomized orders in the final evaluation (the paper uses 100)")
    ap.add_argument("--final-secs", type=int, default=300)
    a = ap.parse_args()
    print(f"[WEB] {a.system} ({CONFIGS[a.system]}) on {a.id}, run {a.run}", flush=True)
    harness.run_experiment("WEB", a.system, CONFIGS[a.system], a.set, [a.run],
                           a.n_final, a.final_secs, None, None, {a.id})
    print("[WEB] done", flush=True)


if __name__ == "__main__":
    main()
