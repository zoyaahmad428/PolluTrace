"""The PolluTrace web console.

    python web/server.py                  # then open http://127.0.0.1:8000
    python web/server.py --port 8080 --open

Serves the dashboard and a small JSON API over the files the experiments wrote. Standard
library only. It listens on the loopback address unless you pass --host, because it can
start test runs on this machine.
"""
import argparse
import json
import mimetypes
import re
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO))

import webapi  # noqa: E402
import webrunner  # noqa: E402

STATIC = HERE / "static"
SAFE = re.compile(r"^[A-Za-z0-9_.-]+$")  # path segments we will join onto a directory
_api_lock = threading.Lock()


def safe(*parts):
    return all(p and SAFE.fullmatch(str(p)) and ".." not in str(p) for p in parts)


class Handler(BaseHTTPRequestHandler):
    server_version = "PolluTrace"
    protocol_version = "HTTP/1.1"

    # ------------------------------------------------------------- responses
    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def json(self, obj, code=200):
        self._send(code, json.dumps(obj, default=str))

    def fail(self, code, message):
        self.json({"error": message}, code)

    def log_message(self, fmt, *args):  # one tidy line per request
        if "/api/" in str(args[0]):
            sys.stderr.write(f"  {args[0]}\n")

    # ------------------------------------------------------------- routing
    def do_GET(self):
        url = urlparse(self.path)
        path, query = url.path, parse_qs(url.query)
        try:
            if path.startswith("/api/"):
                return self.api_get(path[5:].strip("/").split("/"), query)
            return self.static(path)
        except BrokenPipeError:
            pass
        except Exception as e:  # never take the server down over one request
            self.fail(500, f"{type(e).__name__}: {e}")

    do_HEAD = do_GET

    def do_POST(self):
        url = urlparse(self.path)
        if not url.path.startswith("/api/"):
            return self.fail(404, "Not found")
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            return self.fail(400, "Body must be JSON.")
        try:
            return self.api_post(url.path[5:].strip("/").split("/"), body)
        except Exception as e:
            self.fail(500, f"{type(e).__name__}: {e}")

    # ------------------------------------------------------------- static
    def static(self, path):
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        target = (STATIC / rel).resolve()
        if not str(target).startswith(str(STATIC.resolve())) or not target.is_file():
            return self.fail(404, "Not found")
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "image/svg+xml"):
            ctype += "; charset=utf-8"
        self._send(200, target.read_bytes(), ctype)

    # ------------------------------------------------------------- API (GET)
    def api_get(self, seg, query):
        head = seg[0] if seg else ""
        after = int((query.get("after") or ["0"])[0] or 0)

        if head == "health":
            return self.json(webapi.health())
        if head == "overview":
            with _api_lock:  # eval/stats.py rewrites csv files it finds retryable rows in
                return self.json(webapi.overview())
        if head == "victims":
            if len(seg) == 1:
                return self.json(webapi.victims())
            detail = webapi.victim_detail(seg[1])
            return self.json(detail) if detail else self.fail(404, f"No victim {seg[1]}.")
        if head == "gaps":
            return self.json(webapi.gaps())
        if head == "efficiency":
            return self.json(webapi.efficiency())
        if head == "trajectories":
            return self.json(webapi.trajectory_index())
        if head in ("trajectory", "dossier", "patch"):
            if len(seg) != 5 or not safe(*seg[1:]):
                return self.fail(400, "Expected /api/%s/<experiment>/<system>/<run>/<victim>." % head)
            exp, system, run, vid = seg[1:]
            if head == "trajectory":
                t = webapi.trajectory(exp, system, run, vid, after=after)
                return self.json(t) if t else self.fail(404, "No trajectory for that run.")
            if head == "dossier":
                d = webapi.dossier(exp, system, run, vid)
                return self.json(d) if d else self.fail(404, "No dossier for that run.")
            p = webapi.patch_text(exp, system, run, vid, int((query.get("i") or ["0"])[0]))
            return self.json(p) if p else self.fail(404, "That run produced no patch.")
        if head == "runs":
            if len(seg) == 1:
                return self.json({"runs": webrunner.listing(), "systems": webrunner.systems(),
                                  "health": webapi.health()})
            r = webrunner.get(seg[1], after=after)
            return self.json(r) if r else self.fail(404, "No such run.")
        return self.fail(404, "Not found")

    # ------------------------------------------------------------- API (POST)
    def api_post(self, seg, body):
        if seg[:1] != ["runs"]:
            return self.fail(404, "Not found")
        if len(seg) >= 3 and seg[2] == "stop":
            r = webrunner.stop(seg[1])
            return self.json(r) if r else self.fail(404, "No such run.")
        try:
            rec = webrunner.start(
                str(body.get("victim_id", "")).strip(),
                str(body.get("system", "PolluTrace")).strip(),
                int(body.get("n_final", 20)), int(body.get("final_secs", 300)))
        except ValueError as e:
            return self.fail(400, str(e))
        return self.json(rec, 201)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to reach it from another machine")
    ap.add_argument("--open", action="store_true", help="open the console in a browser")
    a = ap.parse_args()

    httpd = ThreadingHTTPServer((a.host, a.port), Handler)
    url = f"http://{'127.0.0.1' if a.host == '0.0.0.0' else a.host}:{a.port}"
    h = webapi.health()
    print(f"PolluTrace console on {url}")
    print(f"  results: {'found' if h['results_present'] else 'none yet — the dashboard will be empty'}")
    print(f"  runs:    {'ready' if h['can_run'] else h['blockers'][0]}")
    print("  stop with Ctrl+C")
    if a.open:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        webrunner.shutdown()
        httpd.server_close()


if __name__ == "__main__":
    main()
