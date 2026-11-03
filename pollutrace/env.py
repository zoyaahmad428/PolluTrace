"""Paths, portable toolchains (JDK 8/11/17 + Maven) and a subprocess helper.

Everything runs natively on the host (Windows, Linux or macOS). Each project is built
and run with a pinned, portable JDK and Maven unpacked under WORK/tools, so results do
not depend on whatever Java the machine happens to have installed.
"""
import json
import os
import platform
import shutil
import subprocess
import time
import urllib.request
import zipfile
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
WORK = Path(os.environ.get("POLLUTRACE_WORK", REPO.parent / "work")).resolve()
TOOLS = WORK / "tools"
PROJECTS = WORK / "projects"
RESULTS = REPO / "results"
IS_WIN = platform.system() == "Windows"

JDKS = ["8", "11", "17"]
# Maven 3.6.3 still allows the plain-http repositories that many older IDoFT projects use;
# Maven >= 3.8.1 blocks them. 3.9 is used only as a fallback for JDK 17 projects.
MAVENS = {"3.6.3": "https://archive.apache.org/dist/maven/maven-3/3.6.3/binaries/apache-maven-3.6.3-bin.zip",
          "3.9.9": "https://archive.apache.org/dist/maven/maven-3/3.9.9/binaries/apache-maven-3.9.9-bin.zip"}


def _os_arch():
    s = platform.system()
    os_ = {"Windows": "windows", "Darwin": "mac", "Linux": "linux"}[s]
    m = platform.machine().lower()
    arch = "aarch64" if m in ("arm64", "aarch64") else "x64"
    return os_, arch


def _download(url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    print(f"  downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "pollutrace-setup"})
    with urllib.request.urlopen(req, timeout=600) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f)
    tmp.replace(dest)


def _unpack(archive, into):
    into.mkdir(parents=True, exist_ok=True)
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as z:
            z.extractall(into)
    else:
        with tarfile.open(archive) as t:
            t.extractall(into)
    # archives contain one top-level folder
    tops = [p for p in into.iterdir() if p.is_dir()]
    return tops[0]


def jdk_home(v):
    marker = TOOLS / f"jdk{v}.home"
    return Path(marker.read_text().strip()) if marker.exists() else None


def maven_home(v):
    marker = TOOLS / f"maven{v}.home"
    return Path(marker.read_text().strip()) if marker.exists() else None


def install_jdk(v):
    if jdk_home(v):
        return jdk_home(v)
    os_, arch = _os_arch()
    ext = "zip" if os_ == "windows" else "tar.gz"
    url = f"https://api.adoptium.net/v3/binary/latest/{v}/ga/{os_}/{arch}/jdk/hotspot/normal/eclipse"
    arc = TOOLS / "dl" / f"jdk{v}.{ext}"
    if not arc.exists():
        _download(url, arc)
    home = _unpack(arc, TOOLS / f"jdk{v}")
    if (home / "Contents" / "Home").exists():  # macOS layout
        home = home / "Contents" / "Home"
    (TOOLS / f"jdk{v}.home").write_text(str(home))
    return home


def install_maven(v):
    if maven_home(v):
        return maven_home(v)
    arc = TOOLS / "dl" / f"maven{v}.zip"
    if not arc.exists():
        _download(MAVENS[v], arc)
    home = _unpack(arc, TOOLS / f"maven{v}")
    if not IS_WIN:
        for f in (home / "bin").iterdir():
            f.chmod(0o755)
    (TOOLS / f"maven{v}.home").write_text(str(home))
    return home


def java_bin(v, tool="java"):
    return str(jdk_home(v) / "bin" / (tool + (".exe" if IS_WIN else "")))


def mvn_bin(mv):
    return str(maven_home(mv) / "bin" / ("mvn.cmd" if IS_WIN else "mvn"))


def toolchain_env(jdk):
    e = dict(os.environ)
    e["JAVA_HOME"] = str(jdk_home(jdk))
    e["PATH"] = str(jdk_home(jdk) / "bin") + os.pathsep + e.get("PATH", "")
    e["MAVEN_OPTS"] = "-Xmx1536m"
    e.pop("JAVA_TOOL_OPTIONS", None)
    e.pop("_JAVA_OPTIONS", None)
    return e


class Proc:
    def __init__(self, code, out, secs, timed_out=False):
        self.code, self.out, self.secs, self.timed_out = code, out, secs, timed_out

    @property
    def ok(self):
        return self.code == 0 and not self.timed_out


def run(cmd, cwd=None, env=None, timeout=1800, log=None):
    """Run a command, capture combined output, never raise on failure."""
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           timeout=timeout, shell=False)
        out = p.stdout.decode("utf-8", "replace")
        res = Proc(p.returncode, out, time.time() - t0)
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"").decode("utf-8", "replace")
        res = Proc(-1, out, time.time() - t0, timed_out=True)
    except FileNotFoundError as e:
        res = Proc(-2, str(e), time.time() - t0)
    if log:
        Path(log).parent.mkdir(parents=True, exist_ok=True)
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"\n$ {' '.join(map(str, cmd))}\n[exit {res.code}, {res.secs:.1f}s"
                    f"{', TIMEOUT' if res.timed_out else ''}]\n{res.out[-20000:]}\n")
    return res


def runner_dir():
    return TOOLS / "orderrunner"


def write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    tmp.replace(path)


def read_json(path, default=None):
    p = Path(path)
    if not p.exists():
        return default
    return json.loads(p.read_text(encoding="utf-8"))
