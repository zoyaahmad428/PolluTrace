"""Repair agent: proposes a patch to the victim's or the polluter's test class.

The prompt holds everything the other agents found: the failure trace, the victim class, the
polluter test (if localized) with its setup/teardown, the state diff (G2), and the validator's
feedback on earlier attempts. Allowed fixes follow the IDoFT fix categories: reset the shared
state in the victim's setup, clean it up in the polluter's teardown, or make the victim
set up the state it needs. The reply names the file it changes and gives that whole file.
"""
import re

from .. import static_state as ss
from .statediff import render

AGENT = "repair"
SYSTEM = "You are an expert Java developer who fixes order-dependent flaky tests without weakening them."
PROMPT = """The JUnit test `{victim}` passes when run alone but fails when some tests run before it in the same JVM.

Failure in the failing order:
```
{trace}
```
{polluter_part}{diff_part}
Victim test class `{vfile}`:
```java
{vsrc}
```
{psrc_part}{history_part}
Fix the order dependency so the victim passes no matter which tests run before it. Typical fixes: reset or restore the shared state in the victim class (e.g. a @Before/setUp method), clean it up in the polluter class (e.g. an @After/tearDown method), or make the victim set the state it relies on. Do NOT delete, skip, ignore or weaken any assertion, do not catch assertion errors, and do not change what either test checks. Only change one test class.

Reply in exactly this format:
FILE: {choices}
```java
<the complete updated file>
```
REASON: <one sentence>"""


def _history(history):
    if not history:
        return ""
    parts = ["\nEarlier attempts that were rejected (do not repeat them):"]
    for h in history[-3:]:
        parts.append(f"Attempt {h['attempt']} changed {h.get('target', '?')}: {h.get('reason', '')}\n"
                     f"Rejected: {h['feedback'][:1800]}")
        if h.get("diff"):
            parts.append(f"Its change was:\n```diff\n{h['diff'][:2000]}\n```")
    return "\n".join(parts) + "\n"


def build_prompt(proj, victim, trace, polluters, diffs, history, failing_order=None):
    vpath = proj.test_source(victim)
    vsrc = vpath.read_text(encoding="utf-8", errors="replace") if vpath else ""
    targets = {"victim": vpath}
    pol = polluters[0] if polluters else None
    polluter_part = psrc_part = ""
    if pol:
        ppath = proj.test_source(pol)
        polluter_part = (f"\nThe polluter, confirmed by running it right before the victim, is `{pol}`."
                         + (f" Other tests that also break the victim: {', '.join(polluters[1:])}." if polluters[1:] else "")
                         + "\n")
        if ppath and ppath != vpath:
            psrc = ppath.read_text(encoding="utf-8", errors="replace")
            body = ss.method_source(psrc, pol.split("#")[1]) or ""
            life = "\n\n".join(ss.lifecycle_methods(psrc))
            psrc_part = (f"\nPolluter test class `{ppath.name}` (full file, you may change it instead of the victim):\n"
                         f"```java\n{psrc[:30000]}\n```\n" if len(psrc) < 30000 else
                         f"\nPolluter method and its setup/teardown:\n```java\n{body}\n\n{life}\n```\n")
            targets["polluter"] = ppath
    elif failing_order:
        prefix = [t for t in failing_order if t != victim]
        polluter_part = ("\nThe polluter is unknown. Tests that ran before the victim in the failing order:\n"
                         + "\n".join(f"- {t}" for t in prefix[-40:]) + "\n")
    diff_part = ""
    if diffs:
        diff_part = "".join(f"\nShared state changed by `{p}` (static fields and system properties, clean JVM vs after it):\n"
                            f"{render(d)}\n" for p, d in diffs.items())
    msg = PROMPT.format(victim=victim, trace=(trace or "")[:3500], polluter_part=polluter_part, diff_part=diff_part,
                        vfile=vpath.name if vpath else "?", vsrc=vsrc[:50000], psrc_part=psrc_part,
                        history_part=_history(history), choices=" | ".join(targets))
    return msg, targets


def parse(text, targets):
    m = re.search(r"FILE:\s*`?(\w+)`?", text or "")
    choice = m.group(1).lower() if m else "victim"
    if choice not in targets:
        choice = "victim"
    blocks = re.findall(r"```(?:java)?\s*\n(.*?)```", text or "", flags=re.S)
    code = max(blocks, key=len) if blocks else None
    reason = re.search(r"REASON:\s*(.+)", text or "")
    return {"target": choice, "path": targets.get(choice), "code": code,
            "reason": reason.group(1).strip()[:300] if reason else ""}


def propose(proj, victim, trace, polluters, diffs, history, traj, failing_order=None):
    msg, targets = build_prompt(proj, victim, trace, polluters, diffs, history, failing_order)
    if not targets.get("victim"):
        return None
    traj.step(AGENT, "plan", polluters=polluters, with_diff=bool(diffs), attempt=len(history) + 1,
              targets=list(targets))
    resp = traj.llm([{"role": "system", "content": SYSTEM}, {"role": "user", "content": msg}], AGENT,
                    f"repair attempt {len(history) + 1}")
    prop = parse(resp["text"], targets)
    traj.step(AGENT, "decision", target=prop["target"], reason=prop["reason"], has_code=bool(prop["code"]))
    return prop
