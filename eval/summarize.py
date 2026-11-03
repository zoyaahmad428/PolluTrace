"""Turn results/*.csv into results/summary.md (the tables reported in the Phase 1 PDF).

    python eval/summarize.py
"""
import csv
import statistics as st
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pollutrace import env  # noqa: E402

R = env.RESULTS


def load(name):
    p = R / name
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def med(xs):
    xs = [x for x in xs if x is not None]
    return round(st.median(xs), 1) if xs else "-"


def table(header, rows):
    s = "| " + " | ".join(header) + " |\n|" + "---|" * len(header) + "\n"
    for r in rows:
        s += "| " + " | ".join(str(c) for c in r) + " |\n"
    return s + "\n"


def main():
    md = ["# Phase 1 results\n"]
    rep = load("reproduction.csv")
    if rep:
        c = Counter(r["status"] for r in rep)
        md.append(f"## Reproduction ({len(rep)} IDoFT OD victims attempted)\n")
        md.append(table(["Status", "Victims"], sorted(c.items(), key=lambda x: -x[1])))
        by = defaultdict(Counter)
        jdk = {}
        bsecs = {}
        for r in rep:
            by[r["project"]][r["status"]] += 1
            if r.get("jdk"):
                jdk[r["project"]] = r["jdk"]
                bsecs[r["project"]] = fnum(r["build_secs"])
        rows = []
        for p in sorted(by):
            tot = sum(by[p].values())
            rows.append([p, tot, by[p]["reproduced"], jdk.get(p, "-"),
                         f"{bsecs[p] / 60:.1f}" if bsecs.get(p) else "-",
                         ", ".join(f"{k} {v}" for k, v in by[p].items() if k != "reproduced") or "-"])
        md.append(table(["Project", "Victims", "Reproduced", "JDK", "Build (min)", "Other outcomes"], rows))
        ok = [r for r in rep if r["status"] == "reproduced"]
        md.append(f"Median time per single-JVM order: alone {med(fnum(r['secs_alone_order']) for r in ok)} s, "
                  f"polluter->victim {med(fnum(r['secs_pair_order']) for r in ok)} s.\n\n")

    probe = load("probe_orders.csv")
    if probe:
        md.append("## Order sensitivity of unpatched dev victims (N = %s random orders)\n" % probe[0]["n"])
        rows = [[r["id"], r["victim"].split(".")[-1], r["fail_rate"], r["first_fail_index"] or "-",
                 r["mean_order_secs"], r["total_secs"]] for r in probe]
        md.append(table(["ID", "Victim", "Fail rate", "First failing order", "s/order", "Total s"], rows))
        rates = [fnum(r["fail_rate"]) for r in probe]
        so = [fnum(r["mean_order_secs"]) for r in probe]
        md.append(f"Median fail rate {med(rates)}; minimum {min(rates)}; median {med(so)} s per order.\n\n")
        md.append("Probability that N random orders expose a patch that still fails at rate p: 1-(1-p)^N\n\n")
        ps = sorted({min(rates), med(rates) if isinstance(med(rates), float) else 0.1, 0.05, 0.1})
        rows = [[n] + [f"{1 - (1 - p) ** n:.3f}" for p in ps] + [f"{n * med(so) / 60:.1f}" if so else "-"]
                for n in (1, 5, 10, 20, 50, 100)]
        md.append(table(["N"] + [f"p={p}" for p in ps] + ["min/victim"], rows))

    for name, title in (("b1_single_call.csv", "B1 single LLM call"), ("b2_ifixflakies.csv", "B2 iFixFlakies")):
        rows = load(name)
        if not rows:
            continue
        n = len(rows)
        c = Counter(r["outcome"] for r in rows)
        md.append(f"## {title} ({n} dev victims)\n")
        md.append(table(["Outcome", "Victims"], sorted(c.items(), key=lambda x: -x[1])))
        fix = sum(1 for r in rows if r.get("fix") == "True")
        acc = [r for r in rows if r.get("accepted") == "True"]
        ff = sum(1 for r in acc if r.get("false_fix") == "True")
        line = f"Fix rate (passes after polluter): {fix}/{n} = {100 * fix / n:.1f}%. "
        if acc:
            line += (f"Accepted: {len(acc)}; false fixes under {acc[0]['rand_n']} random orders: {ff}/{len(acc)}"
                     f" = {100 * ff / len(acc):.1f}%. First failing order of false fixes: "
                     f"{[r['first_fail_index'] for r in acc if r.get('false_fix') == 'True']}. ")
        if "victim_secs" in rows[0]:
            line += f"Median time per victim {med(fnum(r['victim_secs']) for r in rows)} s"
            line += f" (of which random-order revalidation {med(fnum(r['rand_secs']) for r in acc)} s). " if acc else ". "
        if "prompt_tokens" in rows[0]:
            toks = [fnum(r["prompt_tokens"]) + fnum(r["completion_tokens"]) for r in rows
                    if fnum(r["prompt_tokens"]) is not None and fnum(r["completion_tokens"]) is not None]
            line += f"Median tokens per victim {med(toks)}; model {rows[0]['model']}."
        if "module_secs" in rows[0]:
            line += f"Median time per victim {med(fnum(r['module_secs']) for r in rows)} s."
        md.append(line + "\n\n")
    (R / "summary.md").write_text("".join(md), encoding="utf-8")
    print("".join(md))


if __name__ == "__main__":
    main()
