"""Split reproduced victims into a development set and a held-out test set.

Dev set: 15 victims, at most 3 per project, chosen with a fixed seed so the split is
reproducible. Everything else that reproduced is held out for Phase 2.

    python scripts/split.py [--dev 15] [--per-project 3] [--seed 2026]
"""
import argparse
import csv
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pollutrace import env  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dev", type=int, default=15)
    ap.add_argument("--per-project", type=int, default=3)
    ap.add_argument("--seed", type=int, default=2026)
    a = ap.parse_args()
    with open(env.RESULTS / "reproduction.csv", encoding="utf-8") as f:
        rep = [r for r in csv.DictReader(f) if r["status"] == "reproduced"]
    with open(env.REPO / "data" / "manifest.csv", encoding="utf-8") as f:
        man = {r["id"]: r for r in csv.DictReader(f)}
    by = defaultdict(list)
    for r in rep:
        by[r["project"]].append(r)
    rng = random.Random(a.seed)
    for v in by.values():
        rng.shuffle(v)
    projects = sorted(by)
    rng.shuffle(projects)
    dev = []
    for k in range(a.per_project):  # round-robin across projects
        for p in projects:
            if len(dev) < a.dev and len(by[p]) > k:
                dev.append(by[p][k])
    dev_ids = {r["id"] for r in dev}
    for name, ids in (("dev_set.csv", [r["id"] for r in dev]),
                      ("test_set.csv", [r["id"] for r in rep if r["id"] not in dev_ids])):
        with open(env.REPO / "data" / name, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["id", "project_url", "sha", "module", "victim", "confirmed_polluter", "polluters"])
            for i in ids:
                m = man[i]
                cp = next(r["confirmed_polluter"] for r in rep if r["id"] == i)
                w.writerow([i, m["project_url"], m["sha"], m["module"], m["victim"], cp, m["polluters"]])
        print(f"{name}: {len(ids)} victims")


if __name__ == "__main__":
    main()
