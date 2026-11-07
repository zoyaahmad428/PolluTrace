"""Clone, build and list the tests of every project in a victim set, before the experiments.
Builds take most of the setup time; doing them first means the experiment runs start at once.

    python scripts/prepare.py [--set test_subset.csv] [--shard 0/2]
"""
import argparse
import csv
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pollutrace import env, harness  # noqa: E402
from pollutrace.project import Project  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="test_subset.csv")
    ap.add_argument("--shard", default=None)
    a = ap.parse_args()
    rows = harness.shard_rows(harness.load_set(a.set), a.shard)
    seen = set()
    for r in rows:
        key = (r["project_url"], r["sha"], r["module"])
        if key in seen:
            continue
        seen.add(key)
        t0 = time.time()
        p = Project(*key)
        ok = p.build()
        n = len(p.list_tests()) if ok else 0
        print(f"{p.root.name}/{p.module}: {'built' if ok else 'BUILD FAILED'} jdk={p.mod().get('jdk')} "
              f"tests={n} ({time.time() - t0:.0f} s)", flush=True)
    print(f"{len(seen)} project modules prepared; work folder {env.WORK}")


if __name__ == "__main__":
    main()
