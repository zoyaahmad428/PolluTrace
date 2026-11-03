"""Build data/manifest.csv from IDoFT: OD victims with known polluters.

Source: IDoFT odr-tests.csv (OD test + relevant polluter tests, type 'victim') joined
with pr-data.csv (project status, fix PR). One row per (project, module, victim) with
all known polluters, so polluters serve as localization ground truth.

    python scripts/build_manifest.py [--idoft PATH_TO_IDOFT_CHECKOUT]
"""
import argparse
import csv
import subprocess
import sys
from collections import OrderedDict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pollutrace import env  # noqa: E402
from pollutrace.project import to_runner_name  # noqa: E402

IDOFT_URL = "https://github.com/TestingResearchIllinois/idoft"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--idoft", default=str(env.WORK / "idoft"))
    a = ap.parse_args()
    idoft = Path(a.idoft)
    if not (idoft / "odr-tests.csv").exists():
        subprocess.run(["git", "clone", "--depth", "1", IDOFT_URL, str(idoft)], check=True)
    rev = subprocess.run(["git", "rev-parse", "HEAD"], cwd=idoft, capture_output=True, text=True).stdout.strip()

    pr = {}
    with open(idoft / "pr-data.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            k = (r["Project URL"], r["Module Path"], r["Fully-Qualified Test Name (packageName.ClassName.methodName)"])
            pr[k] = r

    rows = OrderedDict()
    with open(idoft / "odr-tests.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["OD-test-type"] != "victim":
                continue
            k = (r["Project URL"], r["Module Path"], r["OD-test"])
            row = rows.setdefault(k, {"project_url": k[0], "sha": r["SHA Detected"], "module": k[1] or ".",
                                      "victim": to_runner_name(k[2]), "polluters": [], "cleaners": []})
            p = r["Relevant-test(if it is VP/BSS)"].strip()
            if p and to_runner_name(p) not in row["polluters"]:
                row["polluters"].append(to_runner_name(p))
            c = r["Relevant-test(if it is VPC)"].strip()
            if c and to_runner_name(c) not in row["cleaners"]:
                row["cleaners"].append(to_runner_name(c))

    out = env.REPO / "data" / "manifest.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "project_url", "sha", "module", "victim", "polluters", "cleaners", "idoft_status", "pr_link"])
        for i, (k, r) in enumerate(rows.items(), 1):
            p = pr.get(k, {})
            w.writerow([f"V{i:03d}", r["project_url"], r["sha"], r["module"], r["victim"], ";".join(r["polluters"]),
                        ";".join(r["cleaners"]), p.get("Status", ""), p.get("PR Link", "")])
    projects = {k[0] for k in rows}
    (env.REPO / "data" / "IDOFT_VERSION").write_text(f"{IDOFT_URL}@{rev}\n")
    print(f"{len(rows)} OD victims with known polluters from {len(projects)} projects -> {out}")


if __name__ == "__main__":
    main()
