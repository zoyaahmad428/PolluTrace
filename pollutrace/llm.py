"""Provider-agnostic LLM client (OpenAI-compatible chat/completions endpoint).

Defaults to Google Gemini through its OpenAI-compatible endpoint. Any other compatible
provider (OpenAI, Groq, a local Ollama server) works by setting:

  POLLUTRACE_LLM_BASE_URL   e.g. https://api.openai.com/v1  or  http://localhost:11434/v1
  POLLUTRACE_LLM_MODEL      e.g. gpt-4o-mini, qwen2.5-coder:7b
  POLLUTRACE_LLM_API_KEY    (or GEMINI_API_KEY, or a key file at <work>/secrets/llm_key.txt)
"""
import json
import os
import re
import time
import urllib.error
import urllib.request

from . import env

BASE = os.environ.get("POLLUTRACE_LLM_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai")
MODEL = os.environ.get("POLLUTRACE_LLM_MODEL", "")  # empty: discover the newest available "flash" model


def _key():
    for k in ("POLLUTRACE_LLM_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY"):
        if os.environ.get(k):
            return os.environ[k].strip()
    f = env.WORK / "secrets" / "llm_key.txt"
    if f.exists():
        return f.read_text(encoding="utf-8").strip()
    return ""


def _discover():
    """Ask the provider which models exist and pick the newest general-purpose 'flash' model.
    Hard-coded model names go stale (gemini-2.5-flash was retired for new keys)."""
    req = urllib.request.Request(BASE.rstrip("/") + "/models",
                                 headers={"Authorization": "Bearer " + _key(), "User-Agent": "pollutrace"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.loads(r.read().decode("utf-8"))
    ids = [m["id"].split("/")[-1] for m in data.get("data", [])]
    bad = ("lite", "image", "tts", "audio", "live", "embedding", "preview", "exp", "thinking", "8b")
    cands = [i for i in ids if "flash" in i and not any(b in i for b in bad)]
    if not cands:
        cands = [i for i in ids if "flash" in i] or ids

    def ver(i):
        return tuple(int(x) for x in re.findall(r"\d+", i)[:3])
    return max(cands, key=ver)


def model():
    global MODEL
    if not MODEL:
        MODEL = _discover()
    return MODEL


def info():
    return {"base_url": BASE, "model": model()}


def chat(messages, temperature=0.0, max_tokens=16000, retries=6):
    """Returns dict(text, prompt_tokens, completion_tokens, total_tokens, secs)."""
    body = json.dumps({"model": model(), "messages": messages, "temperature": temperature,
                       "max_tokens": max_tokens}).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": "pollutrace"}
    key = _key()
    if key:
        headers["Authorization"] = "Bearer " + key
    url = BASE.rstrip("/") + "/chat/completions"
    t0 = time.time()
    delay = 10
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                data = json.loads(r.read().decode("utf-8"))
            u = data.get("usage") or {}
            return {"text": data["choices"][0]["message"].get("content") or "",
                    "prompt_tokens": u.get("prompt_tokens", 0),
                    "completion_tokens": u.get("completion_tokens", 0),
                    "total_tokens": u.get("total_tokens", 0),
                    "secs": round(time.time() - t0, 1), "attempts": attempt + 1}
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:500]}"
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(delay)
                delay = min(delay * 2, 120)
                continue
            break
        except Exception as e:  # network hiccup
            last = str(e)
            time.sleep(delay)
            delay = min(delay * 2, 120)
    raise RuntimeError(f"LLM call failed: {last}")
