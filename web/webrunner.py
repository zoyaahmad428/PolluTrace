"""Start, watch and stop PolluTrace runs launched from the web console.

One run = one victim through one configuration, as a child process of the server. The
console polls for the console output and for the trajectory the agents are writing, so the
same step stream the experiments record is what you watch live.
"""
import re
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

import webapi
from pollutrace import env

REPO = Path(__file__).resolve().parent.parent
LAUNCHER = REPO / "web" / "run_victim.py"
MAX_CONCURRENT = 2

_runs = {}
_lock = threading.Lock()
_counter = 0


def _next_run_number(system):
    """A run number nothing has used, so the harness never resumes over an earlier run."""
    base = env.RESULTS / webapi.WEB_EXPERIMENT / system
    used = {0}
    for p in base.glob("run*.csv"):
        m = re.fullmatch(r"run(\d+)", p.stem)
        if m:
            used.add(int(m.group(1)))
    for p in (webapi.LOGS / webapi.WEB_EXPERIMENT / system).glob("run*"):
        m = re.fullmatch(r"run(\d+)", p.name)
        if m:
            used.add(int(m.group(1)))
    return max(used) + 1


def _pump(rid, proc):
    """Collect the child's output and notice when it ends."""
    rec = _runs[rid]
    try:
        for line in iter(proc.stdout.readline, ""):
            rec["output"].append(line.rstrip("\n"))
    finally:
        proc.stdout.close()
        code = proc.wait()
        with _lock:
            rec["returncode"] = code
            rec["finished"] = time.time()
            if rec["state"] != "stopped":
                rec["state"] = "finished" if code == 0 else "failed"


def start(victim_id, system, n_final=20, final_secs=300):
    """Launch a run. Returns the run record, or raises ValueError the console can show."""
    global _counter
    health = webapi.health()
    if not health["can_run"]:
        raise ValueError(health["blockers"][0])
    if system not in _SYSTEMS:
        raise ValueError(f"Unknown system {system}. Choose one of: {', '.join(_SYSTEMS)}")
    if not any(r["id"] == victim_id for r in webapi.victim_rows()):
        raise ValueError(f"{victim_id} is not in the evaluation subset.")
    with _lock:
        live = [r for r in _runs.values() if r["state"] == "running"]
        if len(live) >= MAX_CONCURRENT:
            raise ValueError(f"{MAX_CONCURRENT} runs are already going. Wait for one to finish.")
        if any(r["victim_id"] == victim_id and r["system"] == system for r in live):
            raise ValueError(f"{victim_id} is already running under {system}.")
        _counter += 1
        rid = f"r{_counter}"
        run_no = _next_run_number(system)
    cmd = [sys.executable, "-u", str(LAUNCHER), "--id", victim_id, "--system", system,
           "--run", str(run_no), "--n-final", str(n_final), "--final-secs", str(final_secs)]
    proc = subprocess.Popen(cmd, cwd=str(REPO), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1, encoding="utf-8", errors="replace")
    rec = {
        "id": rid, "victim_id": victim_id, "system": system, "run": run_no,
        "state": "running", "started": time.time(), "finished": None, "returncode": None,
        "cmd": " ".join(cmd[1:]), "output": deque(maxlen=400), "proc": proc,
        "n_final": n_final, "final_secs": final_secs,
    }
    with _lock:
        _runs[rid] = rec
    threading.Thread(target=_pump, args=(rid, proc), daemon=True).start()
    return public(rec)


_SYSTEMS = ["PolluTrace", "A1_no_localizer", "A2_no_statediff", "A3_no_validator", "B4", "B1"]


def systems():
    """What the console offers to run, with the one-line description of each."""
    out = []
    for key in _SYSTEMS:
        spec = webapi.SYS_BY_KEY.get(key, {})
        out.append({"key": key, "label": spec.get("label", key), "note": spec.get("note", "")})
    return out


def public(rec, after=0):
    """The run as the console sees it: status, console output, and the live trajectory."""
    traj = webapi.trajectory(webapi.WEB_EXPERIMENT, rec["system"], rec["run"], rec["victim_id"],
                             after=after, limit=200) or {"steps": [], "total": 0, "after": after}
    result = None
    if rec["state"] in ("finished", "failed", "stopped"):
        rows = webapi._read_csv(env.RESULTS / webapi.WEB_EXPERIMENT / rec["system"] / f"run{rec['run']}.csv")
        result = next((r for r in rows if r["id"] == rec["victim_id"]), None)
    return {
        "id": rec["id"], "victim_id": rec["victim_id"], "system": rec["system"], "run": rec["run"],
        "state": rec["state"], "started": rec["started"], "finished": rec["finished"],
        "returncode": rec["returncode"], "cmd": rec["cmd"],
        "elapsed": round((rec["finished"] or time.time()) - rec["started"], 1),
        "output": list(rec["output"]), "trajectory": traj, "result": result,
        "n_final": rec["n_final"],
    }


def get(rid, after=0):
    rec = _runs.get(rid)
    return public(rec, after) if rec else None


def listing():
    with _lock:
        recs = sorted(_runs.values(), key=lambda r: r["started"], reverse=True)
    return [{"id": r["id"], "victim_id": r["victim_id"], "system": r["system"], "run": r["run"],
             "state": r["state"], "elapsed": round((r["finished"] or time.time()) - r["started"], 1)}
            for r in recs]


def stop(rid):
    rec = _runs.get(rid)
    if not rec:
        return None
    if rec["state"] == "running":
        rec["state"] = "stopped"
        try:
            rec["proc"].terminate()
        except OSError:
            pass
    return public(rec)


def shutdown():
    for rec in list(_runs.values()):
        if rec["state"] == "running":
            try:
                rec["proc"].terminate()
            except OSError:
                pass
