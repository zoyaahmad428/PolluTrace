"""Run the whole Phase 1 pipeline, step by step, logging to <work>/logs/phase1.log.

    python run_phase1.py                 # everything
    python run_phase1.py setup manifest  # selected steps
Steps: setup manifest reproduce retry split probe b1 b2 summary
"""
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
from pollutrace import env  # noqa: E402

STEPS = {
    "setup": ["scripts/setup_tools.py"],
    "manifest": ["scripts/build_manifest.py"],
    "reproduce": ["scripts/reproduce.py"],
    "retry": ["scripts/reproduce.py", "--retry", "victim_fails_alone"],
    "split": ["scripts/split.py"],
    "probe": ["scripts/probe_orders.py"],
    "b1": ["baselines/b1_single_call.py"],
    "b2": ["baselines/b2_ifixflakies.py"],
    "summary": ["eval/summarize.py"],
}


def keep_awake():
    """Ask Windows not to idle-sleep while this process runs (released automatically on exit).
    Closing the lid or a manual sleep still pauses the run; rerunning resumes it."""
    if sys.platform == "win32":
        import ctypes
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)


def main():
    keep_awake()
    steps = sys.argv[1:] or list(STEPS)
    log = env.WORK / "logs" / "phase1.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    for s in steps:
        t0 = time.time()
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"\n===== {s} started {time.ctime()} =====\n")
            f.flush()
            p = subprocess.run([sys.executable, "-u", str(REPO / STEPS[s][0])] + STEPS[s][1:],
                               cwd=REPO, stdout=f, stderr=subprocess.STDOUT)
            f.write(f"===== {s} finished exit={p.returncode} in {(time.time() - t0) / 60:.1f} min =====\n")
        print(f"{s}: exit {p.returncode} ({(time.time() - t0) / 60:.1f} min)", flush=True)
        if p.returncode != 0 and s in ("setup", "manifest"):
            break


if __name__ == "__main__":
    main()
