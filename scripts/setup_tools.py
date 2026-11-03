"""Download portable JDK 8/11/17 and Maven 3.6.3/3.9.9, then compile OrderRunner.

    python scripts/setup_tools.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pollutrace import env  # noqa: E402


def main():
    env.TOOLS.mkdir(parents=True, exist_ok=True)
    for v in env.JDKS:
        print(f"JDK {v}: {env.install_jdk(v)}")
    for v in env.MAVENS:
        print(f"Maven {v}: {env.install_maven(v)}")
    out = env.runner_dir()
    out.mkdir(parents=True, exist_ok=True)
    src = env.REPO / "java" / "OrderRunner.java"
    r = env.run([env.java_bin("8", "javac"), "-encoding", "UTF-8", "-d", str(out), str(src)], timeout=300)
    print("OrderRunner compiled" if r.ok else "OrderRunner compile FAILED:\n" + r.out)
    for v in env.JDKS:
        r = env.run([env.java_bin(v), "-version"], timeout=60)
        print(f"  jdk{v}: {r.out.strip().splitlines()[0] if r.out else r.code}")


if __name__ == "__main__":
    main()
