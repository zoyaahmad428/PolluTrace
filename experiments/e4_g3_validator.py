"""E4-G3: does the validator reject bad patches that a weak validator accepts?

Part 1, seeded bad patches. For every victim, four mutants of its test class that make the
test "pass" without fixing anything: assertions removed, @Ignore/@Disabled added, body wrapped
in try/catch(Throwable) {}, early return. Each mutant is compiled and judged by the strict
validator (PolluTrace) and the weak one (passes the failing order once). The polluter given
to both is the confirmed one, so only the validator differs.

Part 2, N sweep (--sweep, no test runs): for every patch that a system accepted but the final
100-order evaluation exposed as a false fix, the share caught within the first N randomized
orders, N in {1, 5, 10, 20, 50, 100}. Read from the E1/E2/E3/E5 dossiers.

    python experiments/e4_g3_validator.py [--set test_subset.csv]        # part 1
    python experiments/e4_g3_validator.py --sweep                         # part 2
Output: results/E4_G3/seeded.csv, results/E4_G3/n_sweep.csv
"""
import csv
import json
import re
from pathlib import Path

from common import ids, parser

from pollutrace import config, env, harness
from pollutrace import static_state as ss
from pollutrace.agents import validator
from pollutrace.project import Project
from pollutrace.trajectory import LOGS, Trajectory

ASSERT_STMT = re.compile(r"^[ \t]*(?:Assert\.|Assertions\.)?(?:assert\w*|fail)\s*\((?:[^;]|\n)*?\)\s*;[ \t]*$", re.M)
MUTANTS = ["remove_assertions", "ignore", "swallow", "early_return"]


def mutate(src, method, kind):
    body = ss.method_source(src, method)
    if not body:
        return None
    brace = body.index("{")
    head, inner = body[:brace], body[brace + 1:-1]
    if kind == "remove_assertions":
        new_inner = ASSERT_STMT.sub("", inner)
        if new_inner == inner:
            return None
        new = head + "{" + new_inner + "}"
    elif kind == "ignore":
        ann = "@org.junit.jupiter.api.Disabled " if "org.junit.jupiter" in src else "@org.junit.Ignore "
        new = ann + body
    elif kind == "swallow":
        new = head + "{ try {" + inner + "} catch (Throwable pollutraceIgnored) { } }"
    elif kind == "early_return":
        new = head + "{ if (true) return;" + inner + "}"
    else:
        raise ValueError(kind)
    return src.replace(body, new, 1)


def seeded(a):
    out = env.RESULTS / "E4_G3" / "seeded.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = ["id", "victim", "mutant", "compiled", "weak", "strict", "strict_reasons"]
    done = set()
    if out.exists():
        with open(out, encoding="utf-8") as f:
            done = {(r["id"], r["mutant"]) for r in csv.DictReader(f)}
    rows = harness.shard_rows(harness.load_set(a.set), a.shard)
    if ids(a):
        rows = [r for r in rows if r["id"] in ids(a)]
    for row in rows[:a.limit] if a.limit else rows:
        proj = Project(row["project_url"], row["sha"], row["module"])
        if not proj.build():
            continue
        fo = harness.failing_order(proj, row)
        src_path = proj.test_source(row["victim"])
        if not fo.get("order") or not src_path:
            continue
        orig = src_path.read_text(encoding="utf-8", errors="replace")
        for kind in MUTANTS:
            if (row["id"], kind) in done:
                continue
            new = mutate(orig, row["victim"].split("#")[1], kind)
            rec = {"id": row["id"], "victim": row["victim"], "mutant": kind}
            if new is None:
                rec.update(compiled="n/a", weak="n/a", strict="n/a", strict_reasons="mutant not applicable")
            else:
                try:
                    src_path.write_text(new, encoding="utf-8")
                    comp = proj.recompile()
                    rec["compiled"] = comp.ok
                    if comp.ok:
                        for mode in ("weak", "strict"):
                            cfg = config.get("full", validator=mode)
                            traj = Trajectory(LOGS / "trajectories" / "E4_G3" / mode / f"{row['id']}_{kind}.jsonl")
                            v = validator.validate(proj, row["victim"], {src_path: (orig, new)}, fo["order"],
                                                   [row["confirmed_polluter"]], traj, cfg, seed=1,
                                                   baseline=fo["statuses"])
                            rec[mode] = v["verdict"]
                            if mode == "strict":
                                rec["strict_reasons"] = ";".join(v["reasons"])
                finally:
                    proj.revert()
                    proj.recompile()
            new_file = not out.exists()
            with open(out, "a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=fields)
                if new_file:
                    w.writeheader()
                w.writerow({k: rec.get(k, "") for k in fields})
            print(f"{row['id']} {kind}: weak={rec.get('weak')} strict={rec.get('strict')}", flush=True)


def sweep():
    ns = [1, 5, 10, 20, 50, 100]
    rows = []
    for d in sorted(Path(env.RESULTS).glob("E*/*/dossiers/run*/*.json")):
        try:
            x = json.loads(d.read_text(encoding="utf-8"))
        except Exception:
            continue
        rr = (x.get("final_evaluation") or {}).get("random_orders")
        if not rr or not rr.get("first_fail_index"):
            continue
        rows.append({"system": x["system"], "id": x["id"], "run": x["run"], "first_fail_index": rr["first_fail_index"],
                     "fail_rate": round((rr["fails"] + rr["errors"]) / max(1, rr["n_run"]), 3), "n_run": rr["n_run"],
                     **{f"caught_N{n}": rr["first_fail_index"] <= n for n in ns}})
    out = env.RESULTS / "E4_G3" / "n_sweep.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = ["system", "id", "run", "first_fail_index", "fail_rate", "n_run"] + [f"caught_N{n}" for n in ns]
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} false fixes found in dossiers")
    for n in ns:
        if rows:
            print(f"  N={n:>3}: caught {sum(r[f'caught_N{n}'] for r in rows)}/{len(rows)}")


def main():
    ap = parser(__doc__, runs=1)
    ap.add_argument("--sweep", action="store_true")
    a = ap.parse_args()
    sweep() if a.sweep else seeded(a)


if __name__ == "__main__":
    main()
