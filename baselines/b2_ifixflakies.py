"""Baseline B2: iFixFlakies (Shi et al., ESEC/FSE 2019), the original tool.

iFixFlakies is not on Maven Central, so it is built from source (github.com/winglam/iFixFlakies)
with JDK 8 / Maven 3.6.3. It is added to the module pom as a dependency of
testrunner-maven-plugin and run as published: iDFlakies random-class-method detection
(20 rounds), minimization, cleaner search and patch generation. iFixFlakies verifies its
own patch in the failing order and restores the source afterwards; its status per victim
is read from .dtfixingtools/fixer/<victim>.json.

    python baselines/b2_ifixflakies.py [--set dev_set.csv] [--timeout 60]
"""
import argparse
import csv
import json
import os
import shutil
import sys
import time
import xml.etree.ElementTree as ET
from collections import OrderedDict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pollutrace import env  # noqa: E402
from pollutrace.project import Project, SKIP_FLAGS  # noqa: E402

SRC = "https://github.com/winglam/iFixFlakies"
FIELDS = ["id", "victim", "outcome", "ifix_status", "fix", "module_secs", "runner", "detail"]
NS = "http://maven.apache.org/POM/4.0.0"


def install_tool():
    d = env.TOOLS / "ifixflakies-src"
    marker = env.TOOLS / "ifixflakies.installed"
    if marker.exists():
        return True, marker.read_text()
    if not d.exists():
        r = env.run(["git", "clone", "--depth", "1", SRC, str(d)], timeout=600)
        if not r.ok:
            return False, "clone failed: " + r.out[-300:]
    r = env.run([env.mvn_bin("3.6.3"), "-B", "install", "-DskipTests"], cwd=d, env=env.toolchain_env("8"),
                timeout=1800, log=env.WORK / "logs" / "ifixflakies-build.log")
    if not r.ok:
        return False, "build failed: " + " | ".join(l for l in r.out.splitlines() if "[ERROR]" in l)[:600]
    rev = env.run(["git", "rev-parse", "HEAD"], cwd=d, timeout=60).out.strip()
    marker.write_text(rev)
    return True, rev


def add_plugin(pom):
    ET.register_namespace("", NS)
    tree = ET.parse(pom)
    root = tree.getroot()
    q = lambda t: f"{{{NS}}}{t}"  # noqa: E731
    build = root.find(q("build"))
    if build is None:
        build = ET.SubElement(root, q("build"))
    plugins = build.find(q("plugins"))
    if plugins is None:
        plugins = ET.SubElement(build, q("plugins"))
    p = ET.SubElement(plugins, q("plugin"))
    for k, v in (("groupId", "edu.illinois.cs"), ("artifactId", "testrunner-maven-plugin"), ("version", "1.0")):
        ET.SubElement(p, q(k)).text = v
    deps = ET.SubElement(ET.SubElement(p, q("dependencies")), q("dependency"))
    for k, v in (("groupId", "edu.illinois.cs"), ("artifactId", "ifixflakies"), ("version", "1.0.0-SNAPSHOT")):
        ET.SubElement(deps, q(k)).text = v
    ET.SubElement(ET.SubElement(p, q("configuration")), q("className")).text = \
        "edu.illinois.cs.dt.tools.fixer.CleanerFixerPlugin"
    tree.write(pom, xml_declaration=True, encoding="UTF-8")


IMAGES = {"8": "maven:3.6.3-jdk-8", "11": "maven:3.6.3-jdk-11", "17": "maven:3.9.9-eclipse-temurin-17"}
_DOCKER = None


def use_docker():
    """Use Docker (Linux) on Windows when Docker is running; POLLUTRACE_B2_DOCKER=0/1 forces it."""
    global _DOCKER
    if _DOCKER is None:
        force = os.environ.get("POLLUTRACE_B2_DOCKER")
        if force in ("0", "1"):
            _DOCKER = force == "1"
        else:
            _DOCKER = env.IS_WIN and env.run(["docker", "info"], timeout=120).ok
        print("B2 runner:", "docker (Linux container)" if _DOCKER else "native", flush=True)
    return _DOCKER


def _mvn_cmd(proj, args):
    m = proj.mod()
    if use_docker():
        return ["docker", "run", "--rm", "-v", f"{proj.root}:/w", "-v", f"{Path.home() / '.m2'}:/root/.m2",
                "-w", "/w", IMAGES[m["jdk"]], "mvn", "-B"] + args, {}
    return [env.mvn_bin(m["maven"]), "-B"] + args, {"cwd": proj.root, "env": env.toolchain_env(m["jdk"])}


def ensure_surefire_reports(proj, timeout):
    """iFixFlakies takes the original test order from surefire reports of a normal `mvn test` run.
    Our builds skip tests, so run the module's suite once (failures ignored) before iFixFlakies."""
    rep = proj.mdir / "target" / "surefire-reports"
    if rep.exists() and any(rep.glob("*.xml")):
        return True, 0.0
    pl = [] if proj.module == "." else ["-pl", proj.module]
    cmd, kw = _mvn_cmd(proj, ["test"] + pl + SKIP_FLAGS[1:] + ["-Dmaven.test.failure.ignore=true",
                                                               "-DfailIfNoTests=false"])
    r = env.run(cmd, timeout=timeout, log=env.WORK / "logs" / f"b2_{proj.root.name}.log", **kw)
    return rep.exists() and any(rep.glob("*.xml")), r.secs


def run_victim(proj, victim, timeout):
    m = proj.mod()
    dotted = victim.replace("#", ".")
    # iFixFlakies writes .dtfixingtools/original-order without creating the folder first
    (proj.mdir / ".dtfixingtools").mkdir(exist_ok=True)
    pl = [] if proj.module == "." else ["-pl", proj.module]
    args = ["testrunner:testplugin"] + pl + SKIP_FLAGS[1:] + [
        f"-Ddt.minimizer.dependent.test={dotted}", "-Ddetector.detector_type=random-class-method",
        "-Ddt.randomize.rounds=20", "-Ddt.detector.original_order.all_must_pass=false"]
    log = env.WORK / "logs" / f"b2_{proj.root.name}.log"
    if use_docker():
        # iFixFlakies' test runner deletes temp files that Windows still has open; under Linux it works.
        # Same checkout and Maven cache, mounted into a container with the project's JDK.
        cmd = ["docker", "run", "--rm", "-v", f"{proj.root}:/w", "-v", f"{Path.home() / '.m2'}:/root/.m2",
               "-w", "/w", IMAGES[m["jdk"]], "mvn", "-B"] + args
        r = env.run(cmd, timeout=timeout, log=log)
    else:
        r = env.run([env.mvn_bin(m["maven"]), "-B"] + args, cwd=proj.root, env=env.toolchain_env(m["jdk"]),
                    timeout=timeout, log=log)
    res = proj.mdir / ".dtfixingtools" / "fixer" / f"{dotted}.json"
    status = ""
    if res.exists():
        try:
            data = json.loads(res.read_text(encoding="utf-8"))
            status = data.get("status", "")
        except Exception:
            status = "unreadable"
    return r, status


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="dev_set.csv")
    ap.add_argument("--timeout", type=int, default=60, help="minutes per victim")
    a = ap.parse_args()
    out = env.RESULTS / "b2_ifixflakies.csv"
    done = set()
    if out.exists():  # keep finished rows; redo tool errors and timeouts
        with open(out, encoding="utf-8") as f:
            old = list(csv.DictReader(f))
        keep = [x for x in old if x["outcome"] not in ("tool_error", "tool_unavailable")]
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            for x in keep:
                w.writerow({k: x.get(k, "") for k in FIELDS})
        done = {x["id"] for x in keep}
    with open(env.REPO / "data" / a.set, encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["id"] not in done]
    ok, info = install_tool()
    print("iFixFlakies:", "built @" + info if ok else info, flush=True)
    groups = OrderedDict()
    for r in rows:
        groups.setdefault((r["project_url"], r["sha"], r["module"]), []).append(r)
    for (url, sha, module), vs in groups.items():
        proj = Project(url, sha, module)
        recs = []
        if not ok:
            recs = [{"id": r["id"], "victim": r["victim"], "outcome": "tool_unavailable", "detail": info[:300]} for r in vs]
        else:
            pom = proj.mdir / "pom.xml"
            backup = pom.with_suffix(".xml.pt-bak")
            if backup.exists():  # a previous run was killed: put the original pom back
                shutil.move(backup, pom)
            proj.revert()
            shutil.copy(pom, backup)
            try:
                add_plugin(pom)
                ok_rep, rep_secs = ensure_surefire_reports(proj, a.timeout * 60)
                print(f"  surefire reports for {proj.root.name}/{proj.module}: "
                      f"{'ok' if ok_rep else 'missing'} ({rep_secs:.0f} s)", flush=True)
                for r in vs:
                    t0 = time.time()
                    res, status = run_victim(proj, r["victim"], a.timeout * 60)
                    fixed = status.startswith("FIX_") and status != "FIX_INVALID"
                    if status:
                        outcome = "fixed" if fixed else "not_fixed"
                    elif res.timed_out:
                        outcome = "timeout"
                    elif "Dependent test name is specificed but could not find" in res.out:
                        outcome = "victim_not_detected"
                    else:
                        outcome = "tool_error"
                    err = " | ".join(l for l in res.out.splitlines() if "[ERROR]" in l or "Exception" in l)[:300]
                    recs.append({"id": r["id"], "victim": r["victim"], "outcome": outcome, "ifix_status": status,
                                 "fix": fixed, "module_secs": round(time.time() - t0, 1),
                                 "runner": "docker" if use_docker() else "native", "detail": err})
            finally:
                shutil.move(backup, pom)
                proj.revert()
        new = not out.exists()
        with open(out, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            if new:
                w.writeheader()
            for rec in recs:
                w.writerow({k: rec.get(k, "") for k in FIELDS})
                print(f"{rec['id']} {rec['victim'][-60:]}: {rec['outcome']} {rec.get('ifix_status', '')}", flush=True)


if __name__ == "__main__":
    main()
