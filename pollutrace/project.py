"""One IDoFT project checkout: clone at SHA, build with a pinned JDK, compute the test
classpath, list tests, run a test order through OrderRunner, and patch/revert files."""
import json
import random
import re
import time
import zipfile
from pathlib import Path

from . import env

SKIP_FLAGS = ["-DskipTests", "-Dmaven.javadoc.skip=true", "-Drat.skip=true", "-Dcheckstyle.skip=true",
              "-Denforcer.skip=true", "-Dspotbugs.skip=true", "-Dfindbugs.skip=true", "-Dlicense.skip=true",
              "-Djacoco.skip=true", "-Danimal.sniffer.skip=true", "-Dgpg.skip=true", "-Dmaven.source.skip=true",
              "-Dpmd.skip=true", "-Dcobertura.skip=true", "-Dskip.npm", "-Dskip.yarn", "-Dfrontend.skip=true",
              "-Dlicense.skipCheckLicense=true", "-Dformatter.skip=true", "-Dspotless.check.skip=true",
              "-Dimpsort.skip=true", "-Dmaven.site.skip=true", "-Dbasepom.check.skip-all=true"]

# (jdk, maven) attempts, oldest first: IDoFT SHAs are mostly 2018-2021
ATTEMPTS = [("8", "3.6.3"), ("11", "3.6.3"), ("17", "3.9.9")]


def slug(url, sha):
    owner, name = url.rstrip("/").split("/")[-2:]
    return f"{owner}__{name}__{sha[:8]}"


def to_runner_name(fq):
    """IDoFT 'pkg.Class.method' -> 'pkg.Class#method'."""
    i = fq.rfind(".")
    return fq[:i] + "#" + fq[i + 1:]


class Project:
    def __init__(self, url, sha, module):
        self.url, self.sha, self.module = url, sha, (module or ".")
        self.root = env.PROJECTS / slug(url, sha)
        self.mdir = self.root if self.module == "." else self.root / self.module
        self.meta_path = self.root.parent / (self.root.name + ".meta.json")
        self.log = env.WORK / "logs" / (self.root.name + ".log")
        self.meta = env.read_json(self.meta_path, {}) or {}

    # --------------------------------------------------------------- state
    def save(self):
        env.write_json(self.meta_path, self.meta)

    def mkey(self):
        return self.module.replace("/", "_")

    def mod(self):
        return self.meta.setdefault("modules", {}).setdefault(self.mkey(), {})

    # --------------------------------------------------------------- clone
    def clone(self):
        if self.meta.get("cloned"):
            return True
        self.root.mkdir(parents=True, exist_ok=True)
        g = ["git", "-c", "core.longpaths=true", "-c", "advice.detachedHead=false"]
        steps = [g + ["init", "-q"], g + ["remote", "add", "origin", self.url],
                 g + ["fetch", "-q", "--depth", "1", "origin", self.sha], g + ["checkout", "-q", "FETCH_HEAD"]]
        t0 = time.time()
        for s in steps:
            r = env.run(s, cwd=self.root, timeout=1800, log=self.log)
            if not r.ok and "already exists" not in r.out:
                self.meta["clone_error"] = r.out[-500:]
                self.save()
                return False
        self.meta.update(cloned=True, clone_secs=round(time.time() - t0, 1))
        self.save()
        return True

    # --------------------------------------------------------------- build
    def _mvn(self, jdk, mv, args, timeout, offline=False):
        cmd = [env.mvn_bin(mv), "-B", "-e"] + (["-o"] if offline else []) + args
        return env.run(cmd, cwd=self.root, env=env.toolchain_env(jdk), timeout=timeout, log=self.log)

    def _pl(self):
        return [] if self.module == "." else ["-pl", self.module]

    def build(self, timeout=2400):
        """Try JDK 8, 11, 17 until install + classpath succeed. Records which one worked."""
        m = self.mod()
        if m.get("built"):
            return True
        tries = []
        for jdk, mv in ATTEMPTS:
            if not env.jdk_home(jdk) or not env.maven_home(mv):
                continue
            pl = [] if self.module == "." else ["-pl", self.module, "-am"]
            r = self._mvn(jdk, mv, ["install"] + pl + SKIP_FLAGS, timeout)
            entry = {"jdk": jdk, "maven": mv, "secs": round(r.secs, 1), "ok": r.ok, "timeout": r.timed_out}
            if r.ok:
                ok, why = self._classpath(jdk, mv)
                entry["classpath_ok"] = ok
                if ok:
                    tries.append(entry)
                    m.update(built=True, jdk=jdk, maven=mv, build_secs=entry["secs"], attempts=tries)
                    self.save()
                    return True
                entry["error"] = why
            else:
                entry["error"] = _err_summary(r.out)
            tries.append(entry)
            if r.timed_out:
                break  # a timeout will not get faster on a newer JDK
        m.update(built=False, attempts=tries)
        self.save()
        return False

    def _classpath(self, jdk, mv):
        out = env.WORK / "cp" / f"{self.root.name}__{self.mkey()}.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        r = self._mvn(jdk, mv, ["dependency:build-classpath", f"-Dmdep.outputFile={out}",
                                "-Dmdep.includeScope=test"] + self._pl(), 900)
        if not r.ok or not out.exists():
            return False, _err_summary(r.out)
        deps = [p for p in out.read_text(encoding="utf-8").strip().split(_cp_sep(out)) if p]
        need_launcher = None
        if not any("junit-platform-launcher" in d for d in deps):
            for d in deps:
                mm = re.search(r"junit-platform-engine-([0-9.]+(?:-[A-Za-z0-9]+)?)\.jar", d)
                if mm:
                    need_launcher = mm.group(1)
        if need_launcher:
            ldir = env.WORK / "cp" / "launcher" / need_launcher
            if not list(ldir.glob("*.jar")):
                self._mvn(jdk, mv, ["dependency:copy",
                                    f"-Dartifact=org.junit.platform:junit-platform-launcher:{need_launcher}",
                                    f"-DoutputDirectory={ldir}"], 600)
            deps += [str(p) for p in ldir.glob("*.jar")]
        entries = [env.runner_dir(), self.mdir / "target" / "test-classes", self.mdir / "target" / "classes"]
        entries += [Path(d) for d in deps]
        jar = env.WORK / "cp" / f"{self.root.name}__{self.mkey()}.jar"
        _pathing_jar(jar, entries)
        self.mod().update(pathing_jar=str(jar))
        return True, ""

    def recompile(self):
        """Recompile test sources after a patch (offline, upstream modules already installed)."""
        m = self.mod()
        r = self._mvn(m["jdk"], m["maven"], ["test-compile"] + self._pl() + SKIP_FLAGS, 900, offline=True)
        return r

    # --------------------------------------------------------------- tests
    def list_tests(self):
        m = self.mod()
        if m.get("tests"):
            return m["tests"]
        out = env.WORK / "tmp" / f"{self.root.name}__{self.mkey()}__tests.txt"
        out.parent.mkdir(parents=True, exist_ok=True)
        r = env.run([env.java_bin(m["jdk"]), "-cp", m["pathing_jar"], "OrderRunner", "list", str(out),
                     str(self.mdir / "target" / "test-classes")], cwd=self.mdir,
                    env=env.toolchain_env(m["jdk"]), timeout=600, log=self.log)
        tests = out.read_text(encoding="utf-8").split() if out.exists() else []
        m["tests"] = tests
        self.save()
        return tests

    def run_order(self, order, timeout=600):
        """Run test methods (pkg.Cls#m) in order in one fresh JVM. Returns dict."""
        m = self.mod()
        out = env.WORK / "tmp" / f"run_{self.root.name}_{int(time.time() * 1000)}_{random.randint(0, 9999)}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        cmd = [env.java_bin(m["jdk"]), "-Xmx1g"] + _open_flags(m["jdk"]) + \
              ["-cp", m["pathing_jar"], "OrderRunner", "run", str(out)] + list(order)
        r = env.run(cmd, cwd=self.mdir, env=env.toolchain_env(m["jdk"]), timeout=timeout)
        res = {"order": list(order), "secs": round(r.secs, 2), "timeout": r.timed_out, "results": {}}
        if out.exists():
            try:
                data = json.loads(out.read_text(encoding="utf-8"))
                for x in data["results"]:
                    res["results"][x["test"]] = {"status": x["status"], "trace": x["trace"]}
            except Exception as e:  # truncated output after a crash
                res["error"] = str(e)
            out.unlink()
        else:
            res["error"] = r.out[-2000:]
        return res

    def status(self, res, test):
        return res["results"].get(test, {}).get("status", "ERROR" if not res.get("timeout") else "TIMEOUT")

    # ------------------------------------------------------------ patching
    def test_source(self, test):
        cls = test.split("#")[0]
        top = cls.split("$")[0]
        rel = Path(*top.split(".")).with_suffix(".java")
        cand = self.mdir / "src" / "test" / "java" / rel
        if cand.exists():
            return cand
        hits = [p for p in self.mdir.rglob(rel.name) if str(rel.parent).replace("\\", "/") in str(p).replace("\\", "/")]
        return hits[0] if hits else None

    def diff(self):
        r = env.run(["git", "diff"], cwd=self.root, timeout=120)
        return r.out

    def revert(self):
        env.run(["git", "checkout", "-q", "--", "."], cwd=self.root, timeout=300)


OPENS = ["java.base/java.lang", "java.base/java.lang.reflect", "java.base/java.util", "java.base/java.io",
         "java.base/java.net", "java.base/java.nio", "java.base/sun.nio.ch", "java.base/java.util.concurrent",
         "java.base/java.lang.invoke", "java.base/java.text", "java.base/java.math", "java.base/java.time",
         "java.base/jdk.internal.misc", "java.base/sun.security.x509", "java.rmi/sun.rmi.transport"]


def _open_flags(jdk):
    """JDK 9+ blocks reflective access that pre-2020 libraries (FST, Javassist, cglib) rely on.
    Opening the packages restores JDK 8 behaviour so a newer JDK does not cause failures of its own."""
    if jdk == "8":
        return []
    return [f"--add-opens={p}=ALL-UNNAMED" for p in OPENS]


def _cp_sep(path):
    # maven-dependency-plugin joins entries with the JVM's File.pathSeparator
    return ";" if env.IS_WIN else ":"


def _pathing_jar(jar, entries):
    """A jar whose manifest Class-Path lists every entry. Avoids Windows' 32k command-line
    limit and works on Java 8 (which has no @argfiles)."""
    urls = []
    for e in entries:
        e = Path(e).resolve()
        u = e.as_uri()
        if e.is_dir() and not u.endswith("/"):
            u += "/"
        urls.append(u)
    line = "Class-Path: " + " ".join(urls)
    raw = line.encode("utf-8")
    chunks, first = [], True
    while raw:
        n = 72 if first else 71
        chunks.append((b"" if first else b" ") + raw[:n])
        raw, first = raw[n:], False
    manifest = b"Manifest-Version: 1.0\r\n" + b"\r\n".join(chunks) + b"\r\n\r\n"
    jar.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(jar, "w") as z:
        z.writestr("META-INF/MANIFEST.MF", manifest)


def _err_summary(out):
    lines = [l for l in out.splitlines() if ("[FATAL]" in l or "[ERROR]" in l)
             and "Re-run Maven" not in l and "[Help" not in l and l.strip() not in ("[ERROR]", "[ERROR] [ERROR]")]
    lines.sort(key=lambda l: "[FATAL]" not in l)  # root cause first
    return " | ".join(lines[:4])[:600] or out[-400:]
