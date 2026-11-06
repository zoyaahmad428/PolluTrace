"""State-diff agent (gap G2): what shared state does the polluter actually leave behind?

Two fresh JVMs run OrderRunner's `state` mode on the same class list:
    clean     -- no test, only class initialisation
    polluted  -- the polluter test, then the snapshot
Every static field (except compile-time constants) of the listed classes, every system
property, the default locale and time zone are compared. The class list comes from the
victim's and the polluter's sources (resolved imports, same-package types) and from the
application classes in the failure trace. The diff is given to the repair agent as concrete
evidence ("Registry.NAMES: size 0 -> size 1"), instead of letting it guess.
"""
import json
import random
import re
import time

from .. import env
from .. import static_state as ss
from ..project import _open_flags

AGENT = "statediff"
NOISE = re.compile(r"^System\.property:(sun\.java\.command|sun\.boot|java\.class\.path|jdk\.debug|"
                   r"user\.dir|sun\.jnu|java\.io\.tmpdir|line\.separator)")
SKIP_PREFIX = ("java.", "javax.", "sun.", "jdk.", "org.junit.", "junit.", "org.hamcrest.", "org.mockito.",
               "org.apache.maven.", "OrderRunner")
MAX_CHANGES = 25


def classes_for(proj, victim, polluter, trace):
    srcs = []
    for t in (victim, polluter):
        p = proj.test_source(t) if t else None
        srcs.append(p.read_text(encoding="utf-8", errors="replace") if p else "")
    out = []
    for s in srcs:
        out += ss.candidate_classes(ss.analyse(s))
    out += [t.split("#")[0] for t in (victim, polluter) if t]
    for fq in re.findall(r"\bat\s+((?:[\w$]+\.)+[\w$]+)\.[\w$<>]+\(", trace or ""):
        out.append(fq.split("$")[0])
    seen, res = set(), []
    for c in out:
        if c and c not in seen and not c.startswith(SKIP_PREFIX):
            seen.add(c)
            res.append(c)
    return res[:200]


def run_state(proj, classes, tests, timeout=600):
    """Snapshot via OrderRunner `state` in one fresh JVM. Returns dict(state, missing, results, secs)."""
    if hasattr(proj, "run_state"):  # test doubles
        return proj.run_state(classes, tests)
    m = proj.mod()
    stamp = f"{int(time.time() * 1000)}_{random.randint(0, 9999)}"
    tmp = env.WORK / "tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    cf, out = tmp / f"classes_{stamp}.txt", tmp / f"state_{stamp}.json"
    cf.write_text("\n".join(classes), encoding="utf-8")
    cmd = [env.java_bin(m["jdk"]), "-Xmx1g"] + _open_flags(m["jdk"]) + \
          ["-cp", m["pathing_jar"], "OrderRunner", "state", str(out), str(cf)] + list(tests)
    r = env.run(cmd, cwd=proj.mdir, env=env.toolchain_env(m["jdk"]), timeout=timeout)
    data = {"state": {}, "missing": [], "results": [], "secs": round(r.secs, 2), "ok": False}
    if out.exists():
        try:
            data.update(json.loads(out.read_text(encoding="utf-8")))
            data["ok"] = True
        except Exception as e:
            data["error"] = str(e)
        out.unlink()
    else:
        data["error"] = r.out[-1500:]
    cf.unlink(missing_ok=True)
    return data


def diff(clean, polluted):
    changes = []
    for k in sorted(set(clean) | set(polluted)):
        a, b = clean.get(k), polluted.get(k)
        if a != b and not NOISE.match(k):
            changes.append({"key": k, "before": a, "after": b})
    # application state first, then system-wide state
    changes.sort(key=lambda c: (c["key"].startswith(("System.property:", "Locale.", "TimeZone.")), c["key"]))
    return changes


def compute(proj, victim, polluter, trace, traj):
    classes = classes_for(proj, victim, polluter, trace)
    traj.step(AGENT, "plan", polluter=polluter, n_classes=len(classes), classes=classes[:15])
    t0 = time.time()
    clean = run_state(proj, classes, [])
    polluted = run_state(proj, classes, [polluter])
    traj.usage["test_runs"] += 2
    traj.usage["test_executions"] += 1
    traj.usage["test_secs"] += clean.get("secs", 0) + polluted.get("secs", 0)
    if not (clean.get("ok") and polluted.get("ok")):
        res = {"ok": False, "error": (clean.get("error") or polluted.get("error") or "")[:500], "changes": []}
        traj.step(AGENT, "error", **res)
        return res
    ch = diff(clean["state"], polluted["state"])
    res = {"ok": True, "polluter": polluter, "n_classes": len(classes) - len(polluted.get("missing", [])),
           "n_fields": len(polluted["state"]), "n_changed": len(ch), "changes": ch[:MAX_CHANGES],
           "secs": round(time.time() - t0, 1)}
    traj.step(AGENT, "observation", what="state diff", n_changed=len(ch), changes=ch[:10])
    return res


def render(res):
    """Text for the repair prompt."""
    if not res or not res.get("ok"):
        return "(state diff unavailable)"
    if not res["changes"]:
        return (f"No difference in {res['n_fields']} static fields of {res['n_classes']} classes and in system "
                f"properties. The shared state is probably outside the JVM heap (files, database, network) "
                f"or in a class not referenced by either test.")
    lines = [f"- {c['key']}: {c['before']}  ->  {c['after']}" for c in res["changes"]]
    more = res["n_changed"] - len(res["changes"])
    return "\n".join(lines) + (f"\n- ... and {more} more" if more > 0 else "")
