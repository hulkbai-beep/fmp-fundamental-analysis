#!/usr/bin/env python3
"""
Local web UI for the fmp-fundamental-analysis skill.

Runs the same analysis as scripts/analyze.py (analyze.run(): the same fa-2.0 document and the
same report) and shows it in the browser. Standard library only.

Usage:
  python ui/server.py              # then open http://127.0.0.1:8765
  python ui/server.py --port 9000

Settings come from the environment exactly as for the scripts. On Windows, values saved with
`setx` are also read from the user environment, so a terminal opened before `setx` still works.
"""
from __future__ import annotations

import argparse
import io
import json
import math
import os
import sys
import threading
import traceback
import urllib.parse
from contextlib import redirect_stderr
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

ENV_NAMES = ("FMP_API_KEY", "FMP_MAX_PER_MIN", "FMP_CACHE_DIR")


def load_user_env():
    """Fill missing FMP_* variables from the Windows user/machine environment (setx)."""
    if os.name != "nt":
        return
    import winreg
    roots = ((winreg.HKEY_CURRENT_USER, r"Environment"),
             (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"))
    for name in ENV_NAMES:
        if os.environ.get(name):
            continue
        for root, path in roots:
            try:
                with winreg.OpenKey(root, path) as k:
                    os.environ[name] = str(winreg.QueryValueEx(k, name)[0])
                    break
            except OSError:
                continue


load_user_env()

import analyze as A  # noqa: E402
from fmp_client import FMPError, InvalidKey  # noqa: E402
from symbols import normalize_symbol  # noqa: E402

_lock = threading.Lock()  # FMPClient rate limiting and cache are per-process; run one analysis at a time


def run_analysis(q):
    """(HTTP status, payload) for /api/analyze: {"result": the fa-2.0 document, "report": the markdown report,
    "log": what the run wrote to stderr}, or {"error": ...}."""
    try:
        sym = normalize_symbol(q.get("symbol"))  # BRK.B -> BRK-B; refuses foreign listings
    except ValueError as e:
        return 400, {"error": f"Enter a valid ticker, e.g. AAPL or BRK.B ({e})."}
    argv = [sym]
    peers = (q.get("peers") or "").strip()
    if peers:
        argv.append(f"--peers={peers}")  # attached, so a value starting with "-" is not read as an option
    for key, flag in (("discount", "--discount"), ("growth", "--growth"), ("terminal", "--terminal")):
        v = (q.get(key) or "").strip()
        if v:
            try:
                x = float(v) / 100
            except ValueError:
                x = math.nan
            if not math.isfinite(x):
                return 400, {"error": f"{key} must be a number (percent)."}
            argv.append(f"{flag}={x}")  # attached: str(-0.005 / 100) is "-5e-05"
    if q.get("fcf_base") in ("latest", "avg3"):
        argv.append(f"--fcf-base={q['fcf_base']}")
    if q.get("macro") == "1":
        argv.append("--macro")
    if q.get("refresh") == "1":
        argv.append("--refresh")
    log = io.StringIO()
    with _lock, redirect_stderr(log):  # sys.stderr is process-wide: swap it only under the lock
        try:
            args = A.parse_args(argv)
        except SystemExit:  # argparse refused an option and printed why; answer instead of dropping the connection
            lines = log.getvalue().strip().splitlines()
            return 400, {"error": lines[-1] if lines else "Invalid options."}
        try:
            doc, report = A.run(args)
        except InvalidKey as e:
            return 401, {"error": f"API key problem: {e}", "log": log.getvalue()}
        except SystemExit as e:
            return 404, {"error": str(e), "log": log.getvalue()}
        except FMPError as e:
            return 502, {"error": f"FMP error: {e}", "log": log.getvalue()}
    return 200, {"result": doc, "report": report, "log": log.getvalue()}


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        if url.path in ("/", "/index.html"):
            self._send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif url.path == "/i18n.js":
            self._send(200, (HERE / "i18n.js").read_bytes(), "text/javascript; charset=utf-8")
        elif url.path == "/api/analyze":
            q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
            try:
                code, payload = run_analysis(q)
            except Exception as e:  # keep the server alive and show the error in the page
                traceback.print_exc()
                code, payload = 500, {"error": f"{type(e).__name__}: {e}"}
            self._send(code, json.dumps(payload, default=str), "application/json")
        else:
            self._send(404, "Not found", "text/plain")

    def log_message(self, fmt, *args):
        sys.stderr.write("[ui] " + fmt % args + "\n")


def main():
    ap = argparse.ArgumentParser(description="Local UI for fmp-fundamental-analysis")
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    if not os.environ.get("FMP_API_KEY"):
        print("Warning: FMP_API_KEY is not set; analyses will fail. See SKILL.md > Setup.", file=sys.stderr)
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    print(f"FMP fundamentals UI running at http://127.0.0.1:{a.port}  (Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
