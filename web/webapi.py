"""Read-only data layer for the PolluTrace web console.

Every number served here comes from the files the experiments wrote under results/ and
logs/. Metrics reuse eval/stats.py, so the console and results/phase2_tables.md can never
disagree. Standard library only, like the rest of PolluTrace.
"""
import csv
import json
import os
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "eval"))

from pollutrace import env  # noqa: E402
import stats  # eval/stats.py  # noqa: E402

LOGS = REPO / "logs" / "trajectories"

# One entry per system shown in the console: where its rows live and what to call it.
SYSTEMS = [
    {"key": "B1", "experiment": "E1", "label": "B1 single LLM call",
     "note": "One LLM call with the victim class and the trace. No tools, no loop."},
    {"key": "B4", "experiment": "E2", "label": "B4 NIODebugger-style",
     "note": "Base paper re-implemented here: delta-debugging polluter search, no state diff, weak acceptance."},
    {"key": "PolluTrace", "experiment": "E3", "label": "PolluTrace",
     "note": "Localizer, state diff and strict validator, with backtracking."},
    {"key": "A1_no_localizer", "experiment": "E5", "label": "A1 no localizer",
     "note": "Ablation of G1: repair sees only the trace and the failing order."},
    {"key": "A2_no_statediff", "experiment": "E5", "label": "A2 no state diff",
     "note": "Ablation of G2: no JVM state evidence in the repair prompt."},
    {"key": "A3_no_validator", "experiment": "E5", "label": "A3 weak validator",
     "note": "Ablation of G3: accept as soon as the victim passes the failing order once."},
]
SYS_BY_KEY = {s["key"]: s for s in SYSTEMS}
WEB_EXPERIMENT = "WEB"  # runs launched from the console never touch the paper's results


def _read_csv(path):
    path = Path(path)
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return default


def _f(x, default=None):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _i(x, default=None):
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return default


def short_test(name):
    """'a.b.C#m' -> {'pkg': 'a.b', 'cls': 'C', 'method': 'm'} so the UI can dim the package."""
    name = name or ""
    cls, _, method = name.partition("#")
    pkg, _, simple = cls.rpartition(".")
    return {"full": name, "pkg": pkg, "cls": simple or cls, "method": method}


# ----------------------------------------------------------------- environment
def health():
    """What this machine can do: show saved results, and/or start new runs."""
    work = env.WORK
    jdks = {v: bool(env.jdk_home(v)) for v in env.JDKS}
    runner = (env.runner_dir() / "OrderRunner.class").exists()
    key_file = work / "secrets" / "llm_key.txt"
    has_key = bool(os.environ.get("POLLUTRACE_LLM_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
                   or os.environ.get("GEMINI_API_KEY") or os.environ.get("OPENAI_API_KEY")
                   or (key_file.exists() and key_file.read_text(encoding="utf-8").strip()))
    projects = sorted(p.name for p in (env.PROJECTS.iterdir() if env.PROJECTS.exists() else []) if p.is_dir())
    blockers = []
    if not all(jdks.values()):
        blockers.append("Portable JDKs are missing. Run: python scripts/setup_tools.py")
    if not runner:
        blockers.append("OrderRunner is not compiled. Run: python scripts/setup_tools.py")
    if not projects:
        blockers.append("No project is checked out. Run: python scripts/prepare.py --set test_subset.csv")
    if not has_key:
        blockers.append(f"No LLM key. Put one in {key_file} or set POLLUTRACE_LLM_API_KEY.")
    return {
        "llm_model": os.environ.get("POLLUTRACE_LLM_MODEL", "") or "(auto: newest flash)",
        "projects_ready": len(projects),
        "results_present": bool(list((REPO / "results").glob("E*/*/run*.csv"))),
        "can_run": not blockers, "blockers": blockers,
    }


# -------------------------------------------------------------------- overview
def _runs_by_system():
    """{system key: {run: rows}} — same source eval/stats.py reads."""
    return stats.load_runs()


def overview():
    data = _runs_by_system()
    systems = []
    for spec in SYSTEMS:
        runs = data.get(spec["key"], {})
        if not runs:
            continue
        mets = [stats.run_metrics(rows) for rows in runs.values()]
        first = mets[0]
        systems.append({
            **spec, "runs": len(runs),
            "victims": first["n"], "fixed": first["fixed"],
            "fix_rate": first["fix_rate"], "precision": first["precision"],
            "false_fix_rate": first["false_fix_rate"], "outcomes": first["outcomes"],
        })
    pv = {s["key"]: stats.per_victim(data[s["key"]]) for s in systems}
    base = "PolluTrace"
    paired = []
    if base in pv:
        for s in systems:
            if s["key"] == base:
                continue
            w, l, t, p = stats.sign_test(pv[base], pv[s["key"]])
            paired.append({"against": s["key"], "label": s["label"], "better": w, "worse": l, "ties": t, "p": p})
    hero = _hero()
    full = next((s for s in systems if s["key"] == base), None)
    return {
        "systems": systems, "paired": paired, "hero": hero,
        "headline": {
            "fixed": full["fixed"] if full else 0,
            "victims": full["victims"] if full else 0,
            "fix_rate": full["fix_rate"] if full else None,
            "false_fixes": (full["outcomes"].get("false_fix", 0) if full else 0),
            "weak_false_fixes": next((s["outcomes"].get("false_fix", 0) for s in systems
                                      if s["key"] == "A3_no_validator"), 0),
        },
        "gaps": gap_cards(systems),
    }


def _hero():
    """A real failing order for the hero, chosen to show the phenomenon: the one where the most
    tests run between the polluter and the victim it breaks."""
    best = None
    for row in victim_rows():
        fo = _read_json(REPO / "results" / "failing_orders" / f"{row['id']}.json")
        if not fo or not fo.get("order"):
            continue
        pos = fo.get("polluter_position")
        if pos is None:
            continue
        cand = {"id": row["id"], "project": row["project"], "victim": short_test(row["victim"]),
                "polluter": short_test(row.get("confirmed_polluter", "")),
                "order_len": len(fo["order"]), "polluter_position": pos,
                "trace": (fo.get("trace") or "").strip().splitlines()[:6]}
        cand["distance"] = cand["order_len"] - 1 - pos
        if best is None or cand["distance"] > best["distance"]:
            best = cand
    return best


def gap_cards(systems):
    """The three gaps, each with the measurement that speaks to it."""
    by = {s["key"]: s for s in systems}
    g1 = g1_strategies()
    ranked = next((r for r in g1 if r["strategy"] == "ranked_llm"), None)
    one = next((r for r in g1 if r["strategy"] == "one_by_one"), None)
    g2 = g2_summary()
    full, a1 = by.get("PolluTrace"), by.get("A1_no_localizer")
    a2, a3 = by.get("A2_no_statediff"), by.get("A3_no_validator")
    return [
        {"gap": "G1", "title": "Finding the polluter",
         "claim": "Ranking shared static state, then confirming by execution, finds a polluter in far fewer order runs than trying tests one by one.",
         "evidence": f"{ranked['mean_runs']:.1f} order runs vs {one['mean_runs']:.1f}" if ranked and one else "–",
         "second": (f"fix rate {full['fix_rate']:.0%} with the localizer vs {a1['fix_rate']:.0%} without"
                    if full and a1 else "–"),
         "status": "Partly addressed", "view": "gaps"},
        {"gap": "G2", "title": "Evidence of what was polluted",
         "claim": "Diffing the JVM between a clean run and a polluted run names the field that changed.",
         "evidence": f"a changed field in {g2['with_change']} of {g2['total']} victims" if g2 else "–",
         "second": (f"fix rate {full['fix_rate']:.0%} with the diff vs {a2['fix_rate']:.0%} without"
                    if full and a2 else "–"),
         "status": "Not addressed", "view": "gaps"},
        {"gap": "G3", "title": "Deciding a patch is real",
         "claim": "Re-running the one failing order accepts patches that still fail in other orders. The strict validator does not.",
         "evidence": (f"false-fix rate {full['false_fix_rate']:.0%} strict vs {a3['false_fix_rate']:.0%} weak"
                      if full and a3 and a3["false_fix_rate"] is not None else "–"),
         "second": "every seeded bad patch rejected by the strict validator",
         "status": "Addressed", "view": "gaps"},
    ]


# --------------------------------------------------------------------- victims
def victim_rows():
    """The evaluation subset, with the project name the results use."""
    rows = _read_csv(REPO / "data" / "test_subset.csv")
    for r in rows:
        url = r.get("project_url", "")
        r["project"] = url.rstrip("/").split("/")[-1]
        r["polluter_list"] = [p for p in (r.get("polluters") or "").split(";") if p]
    return rows


def victims():
    rows = victim_rows()
    data = _runs_by_system()
    outcome = defaultdict(dict)  # id -> system -> outcome
    for key, runs in data.items():
        first = runs.get(min(runs)) if runs else []
        for r in first:
            outcome[r["id"]][key] = r["outcome"]
    orders = {}
    for r in rows:
        fo = _read_json(REPO / "results" / "failing_orders" / f"{r['id']}.json", {})
        orders[r["id"]] = {"len": len(fo.get("order") or []), "polluter_position": fo.get("polluter_position")}
    out = []
    for r in rows:
        out.append({
            "id": r["id"], "project": r["project"], "module": r.get("module", ""),
            "victim": short_test(r["victim"]),
            "confirmed_polluter": short_test(r.get("confirmed_polluter", "")),
            "order": orders[r["id"]],
            "outcomes": outcome.get(r["id"], {}),
            "attempted": r["id"] in outcome,
        })
    return {"victims": out, "systems": [{"key": s["key"], "label": s["label"]} for s in SYSTEMS]}


def victim_detail(vid):
    row = next((r for r in victim_rows() if r["id"] == vid), None)
    if row is None:
        return None
    fo = _read_json(REPO / "results" / "failing_orders" / f"{vid}.json", {}) or {}
    data = _runs_by_system()
    per_system = []
    for spec in SYSTEMS:
        runs = data.get(spec["key"], {})
        if not runs:
            continue
        run = min(runs)
        rec = next((r for r in runs[run] if r["id"] == vid), None)
        if not rec:
            continue
        dpath = env.RESULTS / spec["experiment"] / spec["key"] / "dossiers" / f"run{run}" / f"{vid}.json"
        dos = _read_json(dpath, {}) or {}
        per_system.append({
            "key": spec["key"], "label": spec["label"], "experiment": spec["experiment"], "run": run,
            "outcome": rec.get("outcome"), "summary": _dossier_summary(dos),
            "has_trajectory": (LOGS / spec["experiment"] / spec["key"] / f"run{run}" / f"{vid}.jsonl").exists(),
        })
    return {
        "id": vid, "project": row["project"], "project_url": row.get("project_url", ""),
        "sha": row.get("sha", ""), "module": row.get("module", ""),
        "victim": short_test(row["victim"]),
        "confirmed_polluter": short_test(row.get("confirmed_polluter", "")),
        "known_polluters": [short_test(p) for p in row["polluter_list"]],
        "failing_order": {
            "order": [short_test(t) for t in (fo.get("order") or [])],
            "polluter_position": fo.get("polluter_position"),
            "statuses": fo.get("statuses") or {},
            "secs": fo.get("secs"),
            "trace": fo.get("trace") or "",
        },
        "systems": per_system,
    }


def _dossier_summary(dos):
    """The parts of a dossier the detail view shows without downloading the whole thing."""
    if not dos:
        return {}
    out = dos.get("system_output") or {}
    loc = out.get("localization") or {}
    sd = out.get("state_diff") or {}
    changes = []
    for polluter, d in sd.items():
        for c in (d.get("changes") or [])[:12]:
            changes.append({"polluter": polluter, **c})
    patches = dos.get("final_patch") or {}
    fe = dos.get("final_evaluation") or {}
    attempts = []
    for a in out.get("attempts") or []:
        attempts.append({
            "attempt": a.get("attempt"), "target": a.get("target"), "verdict": a.get("verdict"),
            "reason": a.get("reason"), "reasons": a.get("reasons") or [],
            "checks": a.get("checks") or {},
        })
    usage = dos.get("usage") or {}
    final = fe.get("random_orders") or {}
    return {
        "polluter": out.get("polluter"),
        "iterations": out.get("iterations"), "stop_reason": out.get("stop_reason"),
        "localization": {"strategy": loc.get("strategy"), "runs": loc.get("runs"),
                         "rank_of_found": loc.get("rank_of_found")},
        "state_diff": {"n_changed": sum((d.get("n_changed") or 0) for d in sd.values()),
                       "n_fields": sum((d.get("n_fields") or 0) for d in sd.values()),
                       "changes": changes},
        "attempts": attempts,
        "patch_files": [{"name": Path(p.replace("\\", "/")).name, "path": p, "chars": len(src)}
                        for p, src in patches.items()],
        "final_orders": {k: final.get(k) for k in ("n_run", "pool_size", "passes", "fails", "budget_hit")}
                        if final else {},
        "usage": {k: usage.get(k) for k in ("llm_calls", "prompt_tokens", "completion_tokens",
                                            "test_runs", "test_executions", "wall_secs")},
    }


def patch_text(experiment, system, run, vid, index=0):
    dos = _read_json(env.RESULTS / experiment / system / "dossiers" / f"run{run}" / f"{vid}.json", {}) or {}
    patches = list((dos.get("final_patch") or {}).items())
    if not patches:
        return None
    path, src = patches[min(index, len(patches) - 1)]
    return {"path": path, "name": Path(path.replace("\\", "/")).name, "source": src}


# ---------------------------------------------------------------- trajectories
def trajectory_index():
    """Every trajectory on disk, grouped experiment -> system -> run -> [victims]."""
    tree = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    if LOGS.exists():
        for p in sorted(LOGS.glob("*/*/run*/*.jsonl")):
            run = p.parent.name[3:]
            tree[p.parents[2].name][p.parents[1].name][run].append(p.stem)
    return {e: {s: {r: sorted(v) for r, v in runs.items()} for s, runs in systems.items()}
            for e, systems in tree.items()}


def trajectory(experiment, system, run, vid, limit=400):
    path = LOGS / experiment / system / f"run{run}" / f"{vid}.jsonl"
    if not path.exists():
        return None
    steps = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                steps.append(json.loads(line))
            except ValueError:
                continue
    agents = sorted({s.get("agent", "?") for s in steps})
    return {"steps": steps[:limit], "total": len(steps), "agents": agents,
            "elapsed": steps[-1].get("t") if steps else 0}


# ------------------------------------------------------------------ G1, G2, G3
def g1_strategies():
    rows = _read_csv(env.RESULTS / "E4_G1" / "localization.csv")
    by = defaultdict(list)
    for r in rows:
        by[r["strategy"]].append(r)
    out = []
    for strategy, rs in by.items():
        runs = [_f(r["runs"], 0) for r in rs]
        execs = [_f(r["test_executions"], 0) for r in rs]
        ranks = [_i(r.get("rank_first_known")) for r in rs]
        ranked = [x for x in ranks if x and x > 0]
        # Rounded here, with Python's half-even rule, so the console prints exactly what
        # eval/stats.py prints into results/phase2_tables.md.
        out.append({
            "strategy": strategy, "trials": len(rs),
            "correct": sum(1 for r in rs if str(r.get("correct")).lower() == "true"),
            "mean_runs": round(st.mean(runs), 1) if runs else 0,
            "mean_execs": round(st.mean(execs)) if execs else 0,
            "top1": sum(1 for x in ranked if x == 1), "top5": sum(1 for x in ranked if x <= 5),
            "has_ranking": bool(ranked),
        })
    order = ["ranked_llm", "ranked_static", "one_by_one", "bisect", "random"]
    out.sort(key=lambda d: order.index(d["strategy"]) if d["strategy"] in order else 99)
    return out


def g2_summary():
    rows = _read_csv(env.RESULTS / "E4_G2" / "diffs.csv")
    if not rows:
        return None
    ok = [r for r in rows if str(r.get("ok")).lower() == "true"]
    changed = [r for r in ok if _i(r.get("n_changed"), 0) > 0]
    points = [r for r in ok if str(r.get("points_at_victim_state")).lower() == "true"]
    fields = sorted(_f(r.get("n_fields"), 0) for r in ok)
    return {"total": len(rows), "ok": len(ok), "with_change": len(changed), "points_at_victim": len(points),
            "median_fields": fields[len(fields) // 2] if fields else 0,
            "rows": [{"id": r["id"], "victim": short_test(r["victim"]),
                      "n_fields": _i(r.get("n_fields"), 0), "n_changed": _i(r.get("n_changed"), 0),
                      "points": str(r.get("points_at_victim_state")).lower() == "true",
                      "top_changes": r.get("top_changes", "")} for r in rows]}


def g3_summary():
    seeded = _read_csv(env.RESULTS / "E4_G3" / "seeded.csv")
    by = defaultdict(lambda: {"applicable": 0, "weak": 0, "strict": 0})
    for r in seeded:
        if str(r.get("compiled")).lower() != "true":
            continue
        m = by[r["mutant"]]
        m["applicable"] += 1
        m["weak"] += r.get("weak") == "REJECT"
        m["strict"] += r.get("strict") == "REJECT"
    mutants = [{"mutant": k, **v} for k, v in by.items()]
    sweep = _read_csv(env.RESULTS / "E4_G3" / "n_sweep.csv")
    caught = {}
    for n in (1, 5, 10, 20, 50, 100):
        col = f"caught_N{n}"
        caught[n] = sum(1 for r in sweep if str(r.get(col)).lower() == "true")
    return {"mutants": mutants, "sweep_total": len(sweep), "caught": caught}


def gaps():
    return {"g1": {"strategies": g1_strategies(),
                   "rows": _g1_rows()},
            "g2": g2_summary(),
            "g3": g3_summary()}


def _g1_rows():
    rows = _read_csv(env.RESULTS / "E4_G1" / "localization.csv")
    return [{"id": r["id"], "strategy": r["strategy"],
             "correct": str(r.get("correct")).lower() == "true",
             "runs": _i(r.get("runs"), 0), "execs": _i(r.get("test_executions"), 0),
             "rank": _i(r.get("rank_first_known")), "secs": _f(r.get("secs"), 0)}
            for r in rows]


# ------------------------------------------------------------------ efficiency
def efficiency(usd_in=0.30, usd_out=2.50):
    rows = _read_csv(env.RESULTS / "E6" / "efficiency.csv")
    out = []
    for r in rows:
        spec = SYS_BY_KEY.get(r["system"], {"label": r["system"], "note": ""})
        out.append({
            "key": r["system"], "label": spec.get("label", r["system"]), "note": spec.get("note", ""),
            "runs": _i(r.get("runs"), 1),
            "llm_calls": _f(r.get("llm_calls"), 0), "prompt_tokens": _f(r.get("prompt_tokens"), 0),
            "completion_tokens": _f(r.get("completion_tokens"), 0),
            "test_runs": _f(r.get("test_runs"), 0), "test_executions": _f(r.get("test_executions"), 0),
            "agent_secs": _f(r.get("agent_secs"), 0), "final_secs": _f(r.get("final_secs"), 0),
            "usd": _f(r.get("usd"), 0), "same_outcome_all_runs": r.get("same_outcome_all_runs", ""),
            "fix_rate": r.get("fix_rate", ""),
        })
    order = [s["key"] for s in SYSTEMS]
    out.sort(key=lambda d: order.index(d["key"]) if d["key"] in order else 99)
    return {"systems": out, "price": {"usd_in": usd_in, "usd_out": usd_out}}
