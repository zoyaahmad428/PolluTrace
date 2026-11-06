"""Run the Phase 2 pipeline end to end (each step resumes where it stopped).

    python run_phase2.py                         # every step, in order
    python run_phase2.py e3 e5 --shard 0/2       # some steps; this machine takes half the projects
    python run_phase2.py smoke                   # 2 dev victims through E3, 1 run (checks the setup)

Steps: setup subset tests e1 e2 e3 e5 e4g1 e4g2 e4g3 sweep e6 stats failures
Options after the steps are passed to every experiment script (--runs, --shard, --limit, ...).
"""
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent
STEPS = {
    "setup": ["scripts/setup_tools.py"],   # recompiles OrderRunner (state mode is new in Phase 2)
    "subset": ["scripts/make_subset.py"],
    "tests": ["-m", "unittest", "discover", "-s", "tests", "-t", "."],
    "e1": ["experiments/e1_baselines.py"],
    "e2": ["experiments/e2_base_paper.py"],
    "e3": ["experiments/e3_pollutrace.py"],
    "e5": ["experiments/e5_ablation.py"],
    "e4g1": ["experiments/e4_g1_localization.py"],
    "e4g2": ["experiments/e4_g2_statediff.py"],
    "e4g3": ["experiments/e4_g3_validator.py"],
    "sweep": ["experiments/e4_g3_validator.py", "--sweep"],
    "e6": ["experiments/e6_efficiency.py"],
    "stats": ["eval/stats.py"],
    "failures": ["eval/failure_analysis.py"],
}
EXP = {"e1", "e2", "e3", "e5", "e4g1", "e4g2", "e4g3"}


def keep_awake():
    if sys.platform == "win32":  # stop Windows sleeping during long runs
        import ctypes
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)


def main():
    args = sys.argv[1:]
    steps = [a for a in args if a in STEPS or a == "smoke"]
    opts = [a for a in args if a not in steps]
    if not steps:
        steps = list(STEPS)
    elif "setup" not in steps:
        steps = ["setup"] + steps
    keep_awake()
    log = REPO.parent / "work" / "logs" / "phase2.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    for s in steps:
        if s == "smoke":
            cmd = [sys.executable, "experiments/e3_pollutrace.py", "--set", "dev_set.csv", "--limit", "2", "--runs", "1",
                   "--n-final", "10", "--final-secs", "120", "--first-run", "99"]
        else:
            cmd = [sys.executable] + STEPS[s] + (opts if s in EXP else [])
        t0 = time.time()
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"\n==== {time.ctime()} {s}: {' '.join(cmd[1:])}\n")
        print(f"==== {s}", flush=True)
        r = subprocess.run(cmd, cwd=REPO)
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"==== {s} exit {r.returncode} after {time.time() - t0:.0f} s\n")


if __name__ == "__main__":
    main()
