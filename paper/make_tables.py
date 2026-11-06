"""Generate the LaTeX tables in paper/tables/ from the saved results (results/), so every
number in the paper comes from the repository.

    python paper/make_tables.py          # after eval/stats.py and eval/failure_analysis.py

Tables: main.tex (E1/E2/E3/E5), g1.tex (E4-G1), g2.tex (E4-G2), g3.tex (E4-G3),
gap.tex (gap-resolution table), efficiency.tex (E6), failures.tex (failure categories).
A table whose results do not exist yet is written as a placeholder that says so.
"""
import re
import statistics as st
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from eval import stats  # noqa: E402
from pollutrace import env  # noqa: E402

OUT = HERE / "tables"


def tex(s):
    s = str(s)
    s = s.replace("\\", "\\textbackslash{}")
    for a, b in (("&", "\\&"), ("%", "\\%"), ("_", "\\_"), ("#", "\\#")):
        s = s.replace(a, b)
    return s.replace(" ± ", " $\\pm$ ").replace("±", "$\\pm$").replace("–", "--")


def table(name, caption, label, header, rows, colspec=None, wide=False, note=None):
    env_ = "table*" if wide else "table"
    colspec = colspec or ("l" + "r" * (len(header) - 1))
    lines = [f"\\begin{{{env_}}}[t]", "\\centering", "\\footnotesize", f"\\caption{{{caption}}}",
             f"\\label{{{label}}}", f"\\begin{{tabular}}{{{colspec}}}", "\\toprule",
             " & ".join(f"\\textbf{{{tex(h)}}}" for h in header) + " \\\\", "\\midrule"]
    if rows:
        lines += [" & ".join(tex(c) for c in r) + " \\\\" for r in rows]
    else:
        lines.append(f"\\multicolumn{{{len(header)}}}{{c}}{{\\textit{{results not yet generated}}}} \\\\")
    lines += ["\\bottomrule", "\\end{tabular}"]
    if note:
        lines.append(f"\\\\[2pt]\\parbox{{0.95\\{'textwidth' if wide else 'columnwidth'}}}{{\\scriptsize {tex(note)}}}")
    lines.append(f"\\end{{{env_}}}")
    OUT.mkdir(exist_ok=True)
    (OUT / f"{name}.tex").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main_rows(data):
    rows = []
    for s in ["B1", "B2", "B4", "PolluTrace", "A1_no_localizer", "A2_no_statediff", "A3_no_validator"]:
        if s not in data:
            continue
        m = [stats.run_metrics(r) for r in data[s].values()]
        rows.append([stats.LABEL.get(s, s), len(m), m[0]["n"], stats.ms([x["fixed"] for x in m]),
                     stats.ms([x["fix_rate"] for x in m], True), stats.ms([x["precision"] for x in m], True),
                     stats.ms([x["false_fix_rate"] for x in m], True)])
    return rows


def g1_rows():
    rows = stats.read(env.RESULTS / "E4_G1" / "localization.csv")
    by = defaultdict(list)
    for r in rows:
        by[r["strategy"]].append(r)
    out = []
    names = {"ranked_llm": "Ranked + LLM (PolluTrace)", "ranked_static": "Ranked, static only",
             "one_by_one": "One-by-one (iDFlakies-style)", "bisect": "Delta debugging (iFixFlakies-style)",
             "random": "Random order"}
    for s, label in names.items():
        v = by.get(s)
        if not v:
            continue
        runs = [stats.num(r["runs"]) for r in v]
        out.append([label, len(v), f"{100 * sum(1 for r in v if r['correct'] == 'True') / len(v):.0f}%",
                    f"{st.mean(runs):.1f}", f"{st.median(runs):.0f}",
                    f"{st.mean(stats.num(r['test_executions']) for r in v):.0f}"])
    return out


def g2_rows(data):
    rows = stats.read(env.RESULTS / "E4_G2" / "diffs.csv")
    out = []
    ok = [r for r in rows if r["ok"] == "True"]
    if ok:
        out += [["Victims with a state diff", f"{len(ok)} / {len(rows)}"],
                ["Diff shows a changed field or property",
                 f"{sum(stats.num(r['n_changed']) > 0 for r in ok)} / {len(ok)}"],
                ["Changed field in state the victim uses",
                 f"{sum(r['points_at_victim_state'] == 'True' for r in ok)} / {len(ok)}"],
                ["Fields snapshotted per victim (median)", f"{st.median(stats.num(r['n_fields']) for r in ok):.0f}"]]
    for s, label in (("PolluTrace", "Fix rate with diff"), ("A2_no_statediff", "Fix rate without diff")):
        if s in data:
            out.append([label, stats.ms([stats.run_metrics(r)["fix_rate"] for r in data[s].values()], True)])
    return out


def g3_rows():
    rows = stats.read(env.RESULTS / "E4_G3" / "seeded.csv")
    out = []
    names = {"remove_assertions": "Assertions removed", "ignore": "@Ignore / @Disabled added",
             "swallow": "Body wrapped in catch(Throwable)", "early_return": "Early return"}
    for m, label in names.items():
        v = [r for r in rows if r["mutant"] == m and r["compiled"] == "True"]
        if v:
            out.append([label, len(v), sum(r["weak"] == "REJECT" for r in v), sum(r["strict"] == "REJECT" for r in v)])
    return out


def gap_rows(data):
    def fr(s):
        return stats.ms([stats.run_metrics(r)["fix_rate"] for r in data[s].values()], True) if s in data else "–"

    def ffr(s):
        return stats.ms([stats.run_metrics(r)["false_fix_rate"] for r in data[s].values()], True) if s in data else "–"
    loc = stats.read(env.RESULTS / "E4_G1" / "localization.csv")

    def runs(s):
        v = [stats.num(r["runs"]) for r in loc if r["strategy"] == s]
        return f"{st.mean(v):.1f}" if v else "–"
    return [["G1", "Localizer", "Order runs to find polluter", f"{runs('bisect')} (delta debugging)",
             f"{runs('ranked_llm')}", "\\todo{}"],
            ["G1", "Localizer (ablation A1)", "Fix rate", fr("B4"), f"{fr('PolluTrace')} vs {fr('A1_no_localizer')} w/o", "\\todo{}"],
            ["G2", "State diff (ablation A2)", "Fix rate", fr("B4"), f"{fr('PolluTrace')} vs {fr('A2_no_statediff')} w/o", "\\todo{}"],
            ["G3", "Validator (ablation A3)", "False-fix rate", ffr("B4"), f"{ffr('PolluTrace')} vs {ffr('A3_no_validator')} weak", "\\todo{}"]]


def eff_rows(data):
    out = []
    for r in stats.efficiency(data):
        out.append([stats.LABEL.get(r["system"], r["system"]), r.get("llm_calls", "–"),
                    r.get("prompt_tokens", "–"), r.get("completion_tokens", "–"), r.get("usd", "–"),
                    r.get("test_runs", "–"), r.get("agent_secs", "–"), r.get("same_outcome_all_runs", "–")])
    return out


def failure_rows():
    p = env.RESULTS / "failure_analysis.md"
    if not p.exists():
        return [], []
    lines = p.read_text(encoding="utf-8").splitlines()
    head = next((l for l in lines if l.startswith("| Category")), None)
    if not head:
        return [], []
    cols = [c.strip() for c in head.strip("|").split("|")]
    rows = []
    for l in lines[lines.index(head) + 2:]:
        if not l.startswith("|"):
            break
        rows.append([c.strip() for c in l.strip("|").split("|")])
    return cols, rows


def main():
    data = stats.load_runs()
    table("main", "Repair results on the test subset (mean $\\pm$ std over runs).", "tab:main",
          ["System", "Runs", "Victims", "Fixed", "Fix rate", "Precision", "False-fix rate"], main_rows(data),
          wide=True, note="Fix rate = fixed / attempted victims; precision = fixed / victims with a patch; "
                          "false-fix rate = patches passing the failing order that fail a final randomized order. "
                          "B4 is the NIODebugger-style pipeline reproduced by us.")
    table("g1", "E4-G1: cost of finding the polluter in the failing order (same orders and run budget).", "tab:g1",
          ["Strategy", "Trials", "Known polluter found", "Runs (mean)", "Runs (median)", "Test executions"],
          g1_rows(), colspec="lrrrrr", wide=True)
    table("g2", "E4-G2: state diff of the confirmed polluter, and its effect on repair.", "tab:g2",
          ["Measure", "Value"], g2_rows(data), colspec="lr")
    table("g3", "E4-G3: seeded bad patches rejected by the weak and the strict validator.", "tab:g3",
          ["Mutant", "Compiled", "Weak rejects", "Strict rejects"], g3_rows(), colspec="lrrr")
    table("gap", "Gap-resolution table.", "tab:gap",
          ["Gap", "Component", "Metric", "Base paper (B4, ours)", "PolluTrace", "Addressed?"], gap_rows(data),
          colspec="lllrrl", wide=True)
    table("efficiency", "E6: cost per victim and reliability across runs (mean $\\pm$ std over runs).", "tab:eff",
          ["System", "LLM calls", "Prompt tok.", "Compl. tok.", "USD", "Test runs", "Agent s", "Same outcome"],
          eff_rows(data), wide=True)
    cols, rows = failure_rows()
    table("failures", "Failure categories per system (counts over all runs).", "tab:fail",
          cols or ["Category", "Count"], rows, colspec="l" + "r" * (max(len(cols), 2) - 1), wide=True)
    print("tables written to", OUT)


if __name__ == "__main__":
    main()
