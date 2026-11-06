"""Failure analysis: why victims were not fixed, and example trajectories.

Each non-fixed result is put in one category from its dossier (first match wins):
    no_failing_order     the constructed failing order did not fail (excluded from rates)
    llm_error            the provider failed after retries
    localization_failed  no polluter found within budget (PolluTrace systems with a localizer)
    wrong_polluter       a polluter was found but it is not an IDoFT polluter
    compile_errors       every attempt failed to compile
    integrity_rejected   the validator rejected attempts for weakening the test
    second_polluter      attempts fixed the found polluter but randomized orders exposed another
    still_failing        attempts did not make the victim pass after the polluter
    budget_exhausted     LLM, run or time budget ran out
    false_fix            accepted, but failed in the final randomized orders
    partial_fix          accepted, fixed the confirmed polluter but not every known polluter
    integrity_final      accepted, but the final integrity check failed (weak validator)
    not_fixed_final      accepted, but the victim still fails after its confirmed polluter
    no_code              the LLM reply had no usable code
Writes results/failure_analysis.md with counts per system, and 2 success + 2 failure
trajectories of PolluTrace (condensed) for the paper.

    python eval/failure_analysis.py [--system PolluTrace]
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pollutrace import env  # noqa: E402

CATS = ["localization_failed", "wrong_polluter", "compile_errors", "integrity_rejected", "second_polluter",
        "still_failing", "budget_exhausted", "false_fix", "partial_fix", "integrity_final", "not_fixed_final",
        "no_code", "llm_error", "no_failing_order", "other"]


def categorize(d):
    r = d.get("result", {})
    o = r.get("outcome")
    so = d.get("system_output", {})
    if o == "fixed":
        return None
    if o in ("no_failing_order", "llm_error"):
        return o
    if o == "false_fix":
        return "false_fix"
    if o == "partial_fix":
        return "partial_fix"
    if o == "fix_but_integrity":
        return "integrity_final"
    if o in ("not_fixed", "compile_error"):
        return "not_fixed_final" if o == "not_fixed" else "compile_errors"
    loc = so.get("localization")
    if loc is not None and not loc.get("polluter"):
        return "localization_failed"
    if str(r.get("polluter_correct")) == "False":
        return "wrong_polluter"
    verdicts = [a.get("verdict") for a in so.get("attempts", [])]
    reasons = [x for a in so.get("attempts", []) for x in a.get("reasons", [])]
    if verdicts and all(v == "compile_error" for v in verdicts):
        return "compile_errors"
    if "fails in random order" in reasons:
        return "second_polluter"
    if reasons and all(x == "integrity" for x in reasons):
        return "integrity_rejected"
    if any(x.startswith(("still fails", "fails after")) for x in reasons):
        return "still_failing"
    if "budget" in str(so.get("stop_reason", "")):
        return "budget_exhausted"
    if not verdicts:
        return "no_code"
    return "other"


def load(system=None):
    for p in sorted(env.RESULTS.glob("E*/*/dossiers/run*/*.json")):
        if system and p.parts[-4] != system:
            continue
        try:
            yield p, json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue


def condensed(traj_path, limit=40):
    p = env.REPO / traj_path if traj_path else None
    if not p or not p.exists():
        return ["(trajectory file not found)"]
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        s = json.loads(line)
        k, a = s["kind"], s["agent"]
        if k == "tool_call" and s.get("tool") == "run_order":
            bad = ", ".join(f"{t.split('#')[-1]}={v}" for t, v in list(s.get("statuses", {}).items())[:3])
            out.append(f"{s['t']:>7.1f}s {a}: run {s['n_tests']} tests ({s.get('purpose')}) -> {bad or 'all pass'}")
        elif k == "tool_call":
            out.append(f"{s['t']:>7.1f}s {a}: {s.get('tool')} ok={s.get('ok')}")
        elif k == "llm_call":
            out.append(f"{s['t']:>7.1f}s {a}: LLM {s.get('purpose')} ({s.get('prompt_tokens')}+{s.get('completion_tokens')} tok)")
        elif k in ("decision", "observation", "error"):
            keep = {x: s[x] for x in s if x not in ("i", "t", "agent", "kind", "ranked", "changes", "checks", "top")}
            if "changes" in s:
                keep["changes"] = [f"{c['key']}: {c['before']} -> {c['after']}" for c in s["changes"][:3]]
            out.append(f"{s['t']:>7.1f}s {a} {k}: {json.dumps(keep, default=str)[:300]}")
    if len(out) > limit:
        out = out[:limit // 2] + [f"... {len(out) - limit} steps ..."] + out[-limit // 2:]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--system", default="PolluTrace", help="system for the example trajectories")
    a = ap.parse_args()
    counts = defaultdict(Counter)
    totals = Counter()
    successes, failures = [], []
    for p, d in load():
        s = p.parts[-4]
        totals[s] += 1
        c = categorize(d)
        if c:
            counts[s][c] += 1
        if s == a.system:
            (failures if c and c not in ("no_failing_order", "llm_error") else successes if not c else []).append(d)
    md = ["# Failure analysis\n", "Generated by `eval/failure_analysis.py`. Categories are defined in its docstring.\n",
          "| Category | " + " | ".join(sorted(counts)) + " |", "|---|" + "---|" * len(counts)]
    for c in CATS:
        if any(counts[s][c] for s in counts):
            md.append(f"| {c} | " + " | ".join(str(counts[s][c]) for s in sorted(counts)) + " |")
    md.append("| (all results) | " + " | ".join(str(totals[s]) for s in sorted(counts)) + " |\n")
    # examples: successes that needed feedback first, failures from different categories
    successes.sort(key=lambda d: -int(d["result"].get("iterations") or 0))
    seen, picked_f = set(), []
    for d in failures:
        c = categorize(d)
        if c not in seen:
            seen.add(c)
            picked_f.append(d)
    for title, items in (("Success", successes[:2]), ("Failure", picked_f[:2])):
        for d in items:
            r = d["result"]
            md += [f"## {title}: {d['id']} {d['victim']} (run {d['run']}, outcome {r.get('outcome')}"
                   + (f", category {categorize(d)}" if title == "Failure" else "") + ")\n",
                   f"Iterations {r.get('iterations')}, LLM calls {r.get('llm_calls')}, test runs {r.get('test_runs')}, "
                   f"agent time {r.get('agent_secs')} s. Trajectory: `{d.get('trajectory')}`\n", "```"]
            md += condensed(d.get("trajectory")) + ["```", ""]
    out = env.RESULTS / "failure_analysis.md"
    out.write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md[:30]))


if __name__ == "__main__":
    main()
