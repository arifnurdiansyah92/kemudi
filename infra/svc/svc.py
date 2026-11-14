"""kemudi-svc: the only client of the sandboxed Docker daemon (kemudi-dind).
Python stdlib only.

Starts a project's compose services for QA and `run_in` gates. It never runs
branch code itself: builds and containers run inside kemudi-dind, which it
reaches over a unix socket no other container mounts. The orchestrator calls
it over kemudi-svcnet (internal) with KEMUDI_SVC_KEY; every op is a JSON POST
and every reply is JSON.

`path` names one checkout under WORKSPACE (read-only here), as in
kemudi-runner: `<slug>/us-<ref>/<repo>` or `<slug>/setup/<repo>`.
"""

import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WORKSPACE = Path(os.environ.get("SVC_WORKSPACE", "/workspace"))
KEY = os.environ.get("KEMUDI_SVC_KEY", "")
PORT = int(os.environ.get("SVC_PORT", "8810"))
# <project slug>/<us-<ref> | setup>/<repo name> (the runner's PATH_RE)
PATH_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,99}/(us-\d+|setup)/"
                     r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")


def job_dir(body: dict) -> Path:
    """The checkout named by `path`, relative to WORKSPACE. A symlink anywhere
    on the way could point outside, so the resolved directory must stay
    inside."""
    rel = str(body.get("path", ""))
    if not PATH_RE.fullmatch(rel):
        raise ValueError(f"bad workspace path {rel!r}")
    d = WORKSPACE.joinpath(*rel.split("/"))
    if (d.is_symlink() or not d.is_dir()
            or not d.resolve().is_relative_to(WORKSPACE.resolve())):
        raise ValueError(f"no workspace at {rel}")
    return d


OPS: dict = {}


class Handler(BaseHTTPRequestHandler):
    def _reply(self, code: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        self._reply(200 if self.path == "/health" else 404, {"ok": self.path == "/health"})

    def do_POST(self):  # noqa: N802
        if not KEY or self.headers.get("Authorization") != f"Bearer {KEY}":
            return self._reply(401, {"error": "unauthorized"})
        op = OPS.get(self.path.strip("/"))
        if op is None:
            return self._reply(404, {"error": "unknown op"})
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("body must be a JSON object")
            return self._reply(200, op(body))
        except ValueError as e:
            return self._reply(400, {"error": str(e)})
        except Exception as e:  # noqa: BLE001
            return self._reply(200, {"infra_error": f"{type(e).__name__}: {e}"})

    def log_message(self, fmt, *args):
        print(f"svc: {self.command} {self.path} {fmt % args}", flush=True)


if __name__ == "__main__":
    # One job at a time: the orchestrator never calls in parallel.
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
