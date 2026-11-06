"""Phase 2 tables from the saved results: mean +- std over runs, paired comparisons,
E4 per-gap tables, efficiency, and the gap-resolution table.

    python eval/stats.py   ->  results/phase2_tables.md
"""
import csv
import math
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pollutrace import env  # noqa: E402

NOT_ATTEMPTED = {"build_failed", "no_failing_order"}
NO_PATCH = {"no_patch", "llm_error"}
ORDER = ["B1", "B4", "PolluTrace", "A1_no_localizer", "A2_no_statediff", "A3_no_validator"]
LABEL = {"B1": "B1 single LLM call", "B4": "B4 NIODebugger-style (base paper, ours)", "PolluTrace": "PolluTrace (full)",
         "A1_no_localizer": "A1 without localizer (G1)", "A2_no_statediff": "A2 without state diff (G2)",
         "A3_no_validator": "A3 weak validator (G3)", "B2": "B2 iFixFlakies"}


def read(path):
    if not Path(path).exists():
        return []
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_runs():
    """{system: {run: [rows]}} from results/E*/<system>/run<k>.csv (B2 included if present)."""
    out = defaultdict(dict)
    for p in sorted(env.RESULTS.glob("E*/*/run*.csv")):
        system, run = p.parent.name, int(p.stem[3:])
        out[system][run] = read(p)
    return dict(out)


def num(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def ms(vals, pct=False, digits=1):
    vals = [v for v in vals if v is not None]
    if not vals:
        return "–"
    m = st.mean(vals)
    s = st.stdev(vals) if len(vals) > 1 else 0.0
    f = (lambda v: f"{100 * v:.{digits}f}%") if pct else (lambda v: f"{v:.{digits}f}")
    return f"{f(m)} ± {f(s).rstrip('%')}{'' if not pct else ' pp'}" if len(vals) > 1 else f(m)


def run_metrics(rows):
    """Metrics for one run of one system. B2 rows use their own outcome names."""
    att = [r for r in rows if r.get("outcome") not in NOT_ATTEMPTED]
    n = len(att)
    oc = defaultdict(int)
    for r in att:
        oc[r["outcome"]] += 1
    submitted = n - sum(oc[o] for o in NO_PATCH) - oc.get("tool_error", 0) - oc.get("timeout", 0)
    passed_fix = oc["fixed"] + oc["false_fix"] + oc["partial_fix"]
    return {"n": n, "fixed": oc["fixed"], "fix_rate": oc["fixed"] / n if n else None,
            "submitted": submitted, "precision": oc["fixed"] / submitted if submitted else None,
            "false_fix_rate": oc["false_fix"] / passed_fix if passed_fix else None,
            "outcomes": dict(oc)}


def per_victim(runs):
    """{id: mean fixed over runs}"""
    acc = defaultdict(list)
    for rows in runs.values():
        for r in rows:
            if r.get("outcome") not in NOT_ATTEMPTED:
                acc[r["id"]].append(1.0 if r["outcome"] == "fixed" else 0.0)
    return {k: st.mean(v) for k, v in acc.items()}


def sign_test(a, b):
    """Paired two-sided exact sign test on per-victim fix rates of systems a and b."""
    common = set(a) & set(b)
    wins = sum(1 for k in common if a[k] > b[k])
    losses = sum(1 for k in common if a[k] < b[k])
    n = wins + losses
    if n == 0:
        return wins, losses, len(common) - n, 1.0
    k = min(wins, losses)
    p = min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)
    return wins, losses, len(common) - n, p


def main_table(data):
    lines = ["## Main results (test subset; mean ± std over runs)\n",
             "| System | Runs | Victims | Fixed | Fix rate | Precision (fixed / patches) | False-fix rate | Outcomes (run 1) |",
             "|---|---|---|---|---|---|---|---|"]
    for s in ORDER + sorted(set(data) - set(ORDER)):
        if s not in data:
            continue
        mets = [run_metrics(rows) for rows in data[s].values()]
        lines.append(f"| {LABEL.get(s, s)} | {len(mets)} | {mets[0]['n']} | {ms([m['fixed'] for m in mets])} | "
                     f"{ms([m['fix_rate'] for m in mets], True)} | {ms([m['precision'] for m in mets], True)} | "
                     f"{ms([m['false_fix_rate'] for m in mets], True)} | "
                     f"{', '.join(f'{k} {v}' for k, v in sorted(mets[0]['outcomes'].items()))} |")
    lines.append("\nFix rate = fixed / attempted victims. Precision = fixed / victims for which the system "
                 "produced a patch. False-fix rate = patches that pass the failing order but fail at least one "
                 "of the final randomized orders, over all patches that pass the failing order.\n")
    return lines


def paired_table(data):
    lines = ["## Paired comparisons (per-victim fix rate averaged over runs; exact sign test)\n",
             "| Comparison | Victims | A better | B better | Ties | p |", "|---|---|---|---|---|---|"]
    pv = {s: per_victim(data[s]) for s in data}
    for a, b in [("PolluTrace", "B1"), ("PolluTrace", "B4"), ("PolluTrace", "A1_no_localizer"),
                 ("PolluTrace", "A2_no_statediff"), ("PolluTrace", "A3_no_validator")]:
        if a in pv and b in pv:
            w, l, t, p = sign_test(pv[a], pv[b])
            lines.append(f"| A = {LABEL[a]} vs B = {LABEL[b]} | {w + l + t} | {w} | {l} | {t} | {p:.3f} |")
    return lines + [""]


def g1_table():
    rows = read(env.RESULTS / "E4_G1" / "localization.csv")
    if not rows:
        return []
    by = defaultdict(list)
    for r in rows:
        by[r["strategy"]].append(r)
    lines = ["## E4-G1: localization (same failing orders and run budget)\n",
             "| Strategy | Trials | Found a polluter | Found a known polluter | Order runs, mean (median) | "
             "Test executions, mean | Top-1 / Top-5 known polluter in ranking |", "|---|---|---|---|---|---|---|"]
    for s in ("ranked_llm", "ranked_static", "one_by_one", "bisect", "random"):
        v = by.get(s)
        if not v:
            continue
        found = sum(1 for r in v if r["found"])
        corr = sum(1 for r in v if r["correct"] == "True")
        runs = [num(r["runs"]) for r in v]
        ex = [num(r["test_executions"]) for r in v]
        rk = [int(r["rank_first_known"]) for r in v if r["rank_first_known"]]
        top = f"{sum(1 for x in rk if x == 1)}/{len(v)} / {sum(1 for x in rk if x <= 5)}/{len(v)}" if s.startswith("ranked") else "–"
        lines.append(f"| {s} | {len(v)} | {found} ({100 * found / len(v):.0f}%) | {corr} ({100 * corr / len(v):.0f}%) | "
                     f"{st.mean(runs):.1f} ({st.median(runs):.0f}) | {st.mean(ex):.0f} | {top} |")
    return lines + [""]


def g2_table(data):
    rows = read(env.RESULTS / "E4_G2" / "diffs.csv")
    lines = []
    if rows:
        ok = [r for r in rows if r["ok"] == "True"]
        nz = [r for r in ok if num(r["n_changed"]) > 0]
        hit = [r for r in ok if r["points_at_victim_state"] == "True"]
        lines += ["## E4-G2: state diff\n", "| Measure | Value |", "|---|---|",
                  f"| Victims with a diff computed | {len(ok)} of {len(rows)} |",
                  f"| Diff shows at least one changed field or property | {len(nz)} ({100 * len(nz) / max(1, len(ok)):.0f}%) |",
                  f"| A changed field belongs to state the victim refers to | {len(hit)} ({100 * len(hit) / max(1, len(ok)):.0f}%) |",
                  f"| Fields snapshotted per victim, median | {st.median([num(r['n_fields']) for r in ok]) if ok else '–'} |",
                  f"| Changed entries per victim, median | {st.median([num(r['n_changed']) for r in ok]) if ok else '–'} |", ""]
    if "PolluTrace" in data and "A2_no_statediff" in data:
        def iters(sys_):
            return [num(r["iterations"]) for rows in data[sys_].values() for r in rows if r["outcome"] == "fixed"]
        lines += [f"Repair iterations for fixed victims: with diff {ms(iters('PolluTrace'), digits=2)}, "
                  f"without {ms(iters('A2_no_statediff'), digits=2)} (mean ± std over fixed victims).", ""]
    return lines


def g3_table():
    rows = read(env.RESULTS / "E4_G3" / "seeded.csv")
    lines = []
    if rows:
        lines += ["## E4-G3: seeded bad patches (rejected / applicable mutants that compile)\n",
                  "| Mutant | Applicable | Weak validator rejects | Strict validator rejects |", "|---|---|---|---|"]
        for m in ("remove_assertions", "ignore", "swallow", "early_return"):
            v = [r for r in rows if r["mutant"] == m and r["compiled"] == "True"]
            if v:
                lines.append(f"| {m} | {len(v)} | {sum(r['weak'] == 'REJECT' for r in v)} | "
                             f"{sum(r['strict'] == 'REJECT' for r in v)} |")
        lines.append("")
    sw = read(env.RESULTS / "E4_G3" / "n_sweep.csv")
    if sw:
        lines += ["False fixes from all systems caught within the first N randomized orders:\n",
                  "| N | " + " | ".join(k[8:] for k in sw[0] if k.startswith("caught_N")) + " |",
                  "|---|" + "---|" * sum(k.startswith("caught_N") for k in sw[0]),
                  f"| caught (of {len(sw)}) | " + " | ".join(str(sum(r[k] == "True" for r in sw))
                                                         for k in sw[0] if k.startswith("caught_N")) + " |", ""]
    return lines


def efficiency(data, usd_in=0.30, usd_out=2.50):
    out = []
    for s in ORDER + sorted(set(data) - set(ORDER)):
        if s not in data or s == "B2":
            continue
        per_run = defaultdict(list)
        for run, rows in data[s].items():
            att = [r for r in rows if r.get("outcome") not in NOT_ATTEMPTED]
            if not att:
                continue
            for k in ("llm_calls", "prompt_tokens", "completion_tokens", "test_executions", "test_runs", "agent_secs",
                      "final_secs"):
                per_run[k].append(st.mean(num(r.get(k)) for r in att))
            per_run["usd"].append(st.mean(num(r["prompt_tokens"]) * usd_in / 1e6 + num(r["completion_tokens"]) * usd_out / 1e6
                                          for r in att))
        outcomes = defaultdict(set)
        for rows in data[s].values():
            for r in rows:
                if r.get("outcome") not in NOT_ATTEMPTED:
                    outcomes[r["id"]].add(r["outcome"] == "fixed")
        stable = sum(1 for v in outcomes.values() if len(v) == 1)
        out.append({"system": s, "runs": len(data[s]), **{k: ms(v, digits=1 if k != "usd" else 4) for k, v in per_run.items()},
                    "same_outcome_all_runs": f"{stable}/{len(outcomes)}",
                    "fix_rate": ms([run_metrics(r)["fix_rate"] for r in data[s].values()], True)})
    return out


def eff_table(data):
    rows = efficiency(data)
    if not rows:
        return []
    cols = ["llm_calls", "prompt_tokens", "completion_tokens", "usd", "test_runs", "test_executions", "agent_secs",
            "final_secs", "same_outcome_all_runs", "fix_rate"]
    lines = ["## E6: efficiency and reliability (per victim; mean ± std over runs)\n",
             "| System | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
    for r in rows:
        lines.append(f"| {LABEL.get(r['system'], r['system'])} | " + " | ".join(str(r.get(c, "–")) for c in cols) + " |")
    return lines + ["\nCost uses $0.30 / $2.50 per million input / output tokens; change it in experiments/e6_efficiency.py.", ""]


def gap_table(data):
    fr = {s: ms([run_metrics(r)["fix_rate"] for r in data[s].values()], True) for s in data}
    ffr = {s: ms([run_metrics(r)["false_fix_rate"] for r in data[s].values()], True) for s in data}
    loc = read(env.RESULTS / "E4_G1" / "localization.csv")
    mean_runs = {s: st.mean(num(r["runs"]) for r in loc if r["strategy"] == s) for s in {r["strategy"] for r in loc}}
    return ["## Gap-resolution table\n", "| Gap | Component | Evidence | Result |", "|---|---|---|---|",
            f"| G1 polluter search | Localizer | E4-G1; E5 A1 | order runs to find a polluter: ranked+LLM "
            f"{mean_runs.get('ranked_llm', float('nan')):.1f} vs one-by-one {mean_runs.get('one_by_one', float('nan')):.1f}; "
            f"fix rate {fr.get('PolluTrace', '–')} with vs {fr.get('A1_no_localizer', '–')} without |",
            f"| G2 missing state evidence | State diff | E4-G2; E5 A2 | fix rate {fr.get('PolluTrace', '–')} with vs "
            f"{fr.get('A2_no_statediff', '–')} without |",
            f"| G3 weak acceptance | Validator | E4-G3; E5 A3 | false-fix rate {ffr.get('PolluTrace', '–')} strict vs "
            f"{ffr.get('A3_no_validator', '–')} weak |", ""]


def main():
    data = load_runs()
    md = ["# PolluTrace Phase 2 results\n", "Generated by `eval/stats.py` from `results/`. Do not edit by hand.\n"]
    md += main_table(data) + paired_table(data) + g1_table() + g2_table(data) + g3_table() + eff_table(data) + gap_table(data)
    out = env.RESULTS / "phase2_tables.md"
    out.write_text("\n".join(md), encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
