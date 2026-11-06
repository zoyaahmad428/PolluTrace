"""Localizer agent (gap G1): find the polluter of a victim inside a failing test order.

Input: a failing order (prefix tests ... victim) and the failure trace. No ground truth.
1. Rank every prefix test by shared static state with the victim (pollutrace.static_state),
   then, optionally, let the LLM re-rank the top suspects using the trace and the code.
2. Confirm suspects by execution, most suspicious first: run [suspect, victim] for the top
   suspects one by one, then the rest in groups of 8 with bisection on a failing group.
   A suspect is confirmed only when the victim fails right after it in a fresh JVM.

Strategies compared in E4-G1 (all execution-confirmed, same budget):
    ranked      static score (+ LLM re-rank when cfg.llm_rank)       -- PolluTrace
    one_by_one  each prefix test singly, in failing-order order       -- iDFlakies-style
    bisect      delta debugging over the whole prefix                 -- iFixFlakies minimizer
    random      prefix tests singly, in random order                  -- control
"""
import json
import random
import re

from .. import static_state as ss

AGENT = "localizer"
SINGLES = 5      # top suspects tried one by one before group testing
GROUP = 8

RANK_PROMPT = """A JUnit test fails only when some other test runs before it in the same JVM (an order-dependent flaky test). Your job is to say which earlier tests most likely leave behind shared state (static fields, singletons, system properties, files, caches) that breaks it.

Victim test `{victim}`:
```java
{victim_src}
```

Failure:
```
{trace}
```

Candidate tests that ran before it, with the static members each shares with the victim:
{cands}

Reply with a JSON list of the candidate names, most likely polluter first, at most {k} names, and nothing else."""


class Budget:
    def __init__(self, max_runs):
        self.max_runs, self.used = max_runs, 0

    def ok(self):
        return self.used < self.max_runs


def _fails(traj, proj, prefix, victim, budget, purpose):
    budget.used += 1
    r = traj.run_order(proj, list(prefix) + [victim], AGENT, purpose)
    return proj.status(r, victim) == "FAIL", r


def rank(proj, victim, prefix, trace, traj, llm_rank=True, k_llm=15):
    """Static ranking of the prefix tests, optionally re-ranked by the LLM."""
    src_cache = {}

    def src(test):
        cls = test.split("#")[0].split("$")[0]
        if cls not in src_cache:
            p = proj.test_source(test)
            src_cache[cls] = p.read_text(encoding="utf-8", errors="replace") if p else ""
        return src_cache[cls]

    vcls, vm = victim.split("#")
    vsrc = src(victim)
    vbody = ss.method_source(vsrc, vm) or ""
    vinfo = ss.analyse(vsrc)
    # the victim's own method and its setup/teardown carry the state it reads
    vfocus = ss.analyse(vbody + "\n" + "\n".join(ss.lifecycle_methods(vsrc)))
    vinfo = {**vinfo, "members": vinfo["members"] | vfocus["members"]}
    tnames = ss.trace_types(trace)
    scored = []
    info_cache = {}
    for i, t in enumerate(prefix):
        cls, m = t.split("#")
        csrc = src(t)
        if cls not in info_cache:
            info_cache[cls] = ss.analyse(csrc)
        body = ss.method_source(csrc, m)
        lc = "\n".join(ss.lifecycle_methods(csrc))
        score, shared = ss.shared_state_score(vinfo, info_cache[cls], tnames, same_class=(cls == vcls),
                                              cand_method_src=(body or "") + "\n" + lc if body else None)
        scored.append({"test": t, "score": score, "shared": shared, "pos": i})
    # ties: tests closer to the victim first (pollution is often recent)
    scored.sort(key=lambda x: (-x["score"], -x["pos"]))
    traj.step(AGENT, "observation", what="static ranking", top=[(x["test"], x["score"], x["shared"][:4])
                                                                  for x in scored[:10]])
    ranked = [x["test"] for x in scored]
    if llm_rank and len(ranked) > 1:
        top = scored[:k_llm]
        cands = "\n".join(f"- {x['test']}: {', '.join(x['shared'][:6]) or '(no shared static members found)'}"
                          for x in top)
        msg = RANK_PROMPT.format(victim=victim, victim_src=(vbody or vsrc)[:6000], trace=(trace or "")[:2500],
                                 cands=cands, k=min(10, len(top)))
        try:
            resp = traj.llm([{"role": "user", "content": msg}], AGENT, "rank suspects", max_tokens=2000)
            names = parse_name_list(resp["text"], {x["test"] for x in top})
            if names:
                ranked = names + [t for t in ranked if t not in names]
                traj.step(AGENT, "decision", what="LLM re-rank", order=names)
        except Exception as e:  # the static ranking still stands
            traj.step(AGENT, "error", what="LLM re-rank failed", error=str(e)[:300])
    return ranked, scored


def parse_name_list(text, allowed):
    m = re.search(r"\[.*?\]", text or "", re.S)
    names = []
    if m:
        try:
            names = [str(x).strip() for x in json.loads(m.group(0))]
        except Exception:
            names = re.findall(r'"([^"]+)"', m.group(0))
    if not names:
        names = re.findall(r"[\w.$]+#\w+", text or "")
    out = []
    for n in names:
        n = n.replace("()", "")
        if n not in allowed:  # accept pkg.Cls.method as well
            i = n.rfind(".")
            n = n[:i] + "#" + n[i + 1:] if i > 0 else n
        if n in allowed and n not in out:
            out.append(n)
    return out


def _bisect(traj, proj, group, victim, budget, purpose):
    """Delta debugging on a failing group: returns one test that fails the victim alone, or None."""
    while len(group) > 1 and budget.ok():
        half = group[:len(group) // 2]
        f, _ = _fails(traj, proj, half, victim, budget, purpose)
        if f:
            group = half
            continue
        rest = group[len(group) // 2:]
        if not budget.ok():
            return None
        f, _ = _fails(traj, proj, rest, victim, budget, purpose)
        if f:
            group = rest
            continue
        return None  # pollution needs tests from both halves together
    if len(group) == 1:
        f, _ = _fails(traj, proj, group, victim, budget, purpose + " (confirm)")
        return group[0] if f else None
    return None


def confirm(traj, proj, victim, ordered, budget, singles=SINGLES, group=GROUP):
    for t in ordered[:singles]:
        if not budget.ok():
            return None
        f, _ = _fails(traj, proj, [t], victim, budget, "confirm suspect")
        if f:
            return t
    rest = ordered[singles:]
    for i in range(0, len(rest), group):
        if not budget.ok():
            return None
        g = rest[i:i + group]
        f, _ = _fails(traj, proj, g, victim, budget, "group test")
        if f:
            p = _bisect(traj, proj, g, victim, budget, "bisect group")
            if p:
                return p
    return None


def localize(proj, victim, failing_order, trace, traj, cfg, strategy=None, seed=0):
    """Returns dict(polluter, strategy, runs, ranked (first 10), rank_of_found)."""
    strategy = strategy or cfg.localizer
    prefix = [t for t in failing_order if t != victim]
    budget = Budget(cfg.max_local_runs)
    traj.step(AGENT, "plan", strategy=strategy, prefix_len=len(prefix), budget=cfg.max_local_runs)
    ranked = prefix
    if strategy == "ranked":
        ranked, _ = rank(proj, victim, prefix, trace, traj, llm_rank=cfg.llm_rank)
        p = confirm(traj, proj, victim, ranked, budget)
    elif strategy == "one_by_one":
        p = confirm(traj, proj, victim, prefix, budget, singles=len(prefix))
    elif strategy == "random":
        ranked = prefix[:]
        random.Random(seed).shuffle(ranked)
        p = confirm(traj, proj, victim, ranked, budget, singles=len(ranked))
    elif strategy == "bisect":
        p = _bisect(traj, proj, prefix, victim, budget, "delta debugging")
    else:
        raise ValueError(strategy)
    res = {"polluter": p, "strategy": strategy, "runs": budget.used, "ranked": ranked[:10],
           "rank_of_found": (ranked.index(p) + 1) if p in ranked else None, "budget_hit": p is None and not budget.ok()}
    traj.step(AGENT, "decision", what="polluter", **res)
    return res
