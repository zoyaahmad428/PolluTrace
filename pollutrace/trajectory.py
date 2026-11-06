"""Trajectory log: every reasoning step, tool call, observation and LLM call of one agent run.

Written as JSON Lines to logs/trajectories/<experiment>/<system>/run<k>/<victim id>.jsonl and
summarised in the per-victim dossier. LLM calls go through Trajectory.llm() so that tokens,
latency and the per-victim call budget are counted in one place.
"""
import json
import time

from . import env, llm


class BudgetExceeded(RuntimeError):
    pass


class Trajectory:
    def __init__(self, path=None, max_llm_calls=None, temperature=0.0):
        self.path = path
        self.steps = []
        self.t0 = time.time()
        self.max_llm_calls = max_llm_calls
        self.temperature = temperature
        self.usage = {"llm_calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "llm_secs": 0.0,
                      "test_runs": 0, "test_executions": 0, "test_secs": 0.0, "compiles": 0}
        if path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")

    def step(self, agent, kind, **data):
        """kind: plan | thought | tool_call | observation | state | decision | error"""
        rec = {"i": len(self.steps), "t": round(time.time() - self.t0, 2), "agent": agent, "kind": kind}
        rec.update(data)
        self.steps.append(rec)
        if self.path:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, default=str) + "\n")
        return rec

    # ---------------------------------------------------------------- tools
    def run_order(self, proj, order, agent, purpose):
        """Run a test order through the project and log it as a tool call."""
        r = proj.run_order(order)
        self.usage["test_runs"] += 1
        self.usage["test_executions"] += len(order)
        self.usage["test_secs"] += r["secs"]
        self.step(agent, "tool_call", tool="run_order", purpose=purpose, n_tests=len(order),
                  order=order if len(order) <= 12 else order[:5] + ["..."] + order[-5:],
                  statuses={t: v["status"] for t, v in r["results"].items() if v["status"] != "PASS"},
                  secs=r["secs"], timeout=r.get("timeout", False))
        return r

    def compile(self, proj, agent):
        r = proj.recompile()
        self.usage["compiles"] += 1
        self.step(agent, "tool_call", tool="compile", ok=r.ok, secs=round(r.secs, 1),
                  errors=compile_errors(r.out) if not r.ok else "")
        return r

    def llm(self, messages, agent, purpose, max_tokens=16000):
        if self.max_llm_calls is not None and self.usage["llm_calls"] >= self.max_llm_calls:
            raise BudgetExceeded(f"LLM call budget of {self.max_llm_calls} used")
        self.usage["llm_calls"] += 1
        resp = llm.chat(messages, temperature=self.temperature, max_tokens=max_tokens)
        self.usage["prompt_tokens"] += resp["prompt_tokens"]
        self.usage["completion_tokens"] += resp["completion_tokens"]
        self.usage["llm_secs"] += resp["secs"]
        self.step(agent, "llm_call", purpose=purpose, model=resp.get("model"), prompt_tokens=resp["prompt_tokens"],
                  completion_tokens=resp["completion_tokens"], secs=resp["secs"],
                  prompt_chars=sum(len(m["content"]) for m in messages), reply=resp["text"][:4000])
        return resp

    def summary(self):
        u = dict(self.usage)
        u["wall_secs"] = round(time.time() - self.t0, 1)
        u["llm_secs"] = round(u["llm_secs"], 1)
        u["test_secs"] = round(u["test_secs"], 1)
        u["steps"] = len(self.steps)
        return u


def compile_errors(out, n=12):
    lines = [l for l in out.splitlines() if "[ERROR]" in l and ".java" in l]
    return "\n".join(lines[:n]) or "\n".join(l for l in out.splitlines() if "[ERROR]" in l)[:1500]


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, default=str) + "\n")


LOGS = env.REPO / "logs"
