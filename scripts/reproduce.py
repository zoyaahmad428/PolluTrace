"""Reproduce every manifest victim: clone at the IDoFT SHA, build with JDK 8 -> 11 -> 17,
then check (a) the victim passes alone and (b) it fails right after a known polluter.
Both checks run twice. Results are appended to results/reproduction.csv (resumable).

    python scripts/reproduce.py                      # all victims
    python scripts/reproduce.py --projects http-request,marine-api
    python scripts/reproduce.py --build-timeout 30   # minutes per build attempt
"""
import argparse
import csv
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pollutrace import env  # noqa: E402
from pollutrace.project import Project  # noqa: E402

FIELDS = ["id", "project", "module", "victim", "status", "jdk", "maven", "build_secs", "n_module_tests",
          "alone", "confirmed_polluter", "polluters_tried", "secs_alone_order", "secs_pair_order", "detail"]


def load_manifest(projects=None):
    with open(env.REPO / "data" / "manifest.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if projects:
        rows = [r for r in rows if any(p.lower() in r["project_url"].lower() for p in projects)]
    return rows


def done_ids(path):
    if not path.exists():
        return set()
    with open(path, encoding="utf-8") as f:
        return {r["id"] for r in csv.DictReader(f)}


def append(path, row):
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in FIELDS})


def reproduce(r, build_timeout):
    proj = Project(r["project_url"], r["sha"], r["module"])
    out = {"id": r["id"], "project": r["project_url"].split("/")[-1], "module": r["module"], "victim": r["victim"]}
    if not proj.clone():
        return {**out, "status": "clone_failed", "detail": proj.meta.get("clone_error", "")[:300]}
    m = proj.mod()
    if not m.get("built") and m.get("attempts"):
        pass  # already failed earlier for another victim of this module
    elif not proj.build(timeout=build_timeout):
        m = proj.mod()
    m = proj.mod()
    if not m.get("built"):
        att = m.get("attempts", [])
        timed = any(a.get("timeout") for a in att)
        return {**out, "status": "build_timeout" if timed else "build_failed",
                "detail": " || ".join(f"jdk{a['jdk']}: {a.get('error', '')[:150]}" for a in att)[:600]}
    out.update(jdk=m["jdk"], maven=m["maven"], build_secs=m["build_secs"])
    tests = proj.list_tests()
    out["n_module_tests"] = len(tests)
    v = r["victim"]
    alone = [proj.run_order([v]) for _ in range(2)]
    st = [proj.status(a, v) for a in alone]
    out["alone"] = "/".join(st)
    out["secs_alone_order"] = round(sum(a["secs"] for a in alone) / 2, 2)
    if "NOT_FOUND" in st or ("ERROR" in st and v not in tests):
        return {**out, "status": "victim_not_found", "detail": alone[0]["results"].get(v, {}).get("trace", alone[0].get("error", ""))[:300]}
    if st != ["PASS", "PASS"]:
        return {**out, "status": "victim_fails_alone", "detail": alone[0]["results"].get(v, {}).get("trace", "")[:300]}
    tried = 0
    pair_secs = []
    for p in r["polluters"].split(";")[:5]:
        tried += 1
        runs = [proj.run_order([p, v]) for _ in range(2)]
        pair_secs += [x["secs"] for x in runs]
        sts = [proj.status(x, v) for x in runs]
        if sts == ["FAIL", "FAIL"]:
            out.update(status="reproduced", confirmed_polluter=p, polluters_tried=tried,
                       secs_pair_order=round(sum(pair_secs) / len(pair_secs), 2),
                       detail=runs[0]["results"][v]["trace"].splitlines()[0][:200] if runs[0]["results"][v]["trace"] else "")
            return out
    return {**out, "status": "not_reproduced", "polluters_tried": tried,
            "secs_pair_order": round(sum(pair_secs) / max(1, len(pair_secs)), 2),
            "detail": "victim still passes after every known polluter tried"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--projects", default="")
    ap.add_argument("--build-timeout", type=int, default=40, help="minutes per build attempt")
    a = ap.parse_args()
    rows = load_manifest([p for p in a.projects.split(",") if p])
    out = env.RESULTS / "reproduction.csv"
    done = done_ids(out)
    t0 = time.time()
    for i, r in enumerate(rows, 1):
        if r["id"] in done:
            continue
        ts = time.time()
        try:
            res = reproduce(r, a.build_timeout * 60)
        except Exception as e:  # keep going; record the crash
            res = {"id": r["id"], "project": r["project_url"].split("/")[-1], "module": r["module"],
                   "victim": r["victim"], "status": "harness_error", "detail": repr(e)[:300]}
        append(out, res)
        print(f"[{i}/{len(rows)}] {r['id']} {res['project']} {r['victim'][-60:]} -> {res['status']} "
              f"({time.time() - ts:.0f}s, total {(time.time() - t0) / 60:.0f} min)", flush=True)


if __name__ == "__main__":
    main()
