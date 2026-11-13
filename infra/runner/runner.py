"""kemudi-runner: a tiny HTTP service that runs a fixed set of commands in an
Awak job workspace. Python stdlib only.

POST /install    {job}                      pnpm install (frozen, no scripts)
POST /commit     {job, message}             commit anything the agent left
POST /gates      {job}                      tsc, eslint, vitest, vite build
POST /qa_reset   {job}                      empty .qa/ for a fresh spec
POST /qa         {job, token, user, project} run .qa/spec twice against a dev server

Every reply is JSON. `infra_error` is set when the step could not run at all
(as opposed to the code failing a check).
"""

import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WORKSPACE = Path(os.environ.get("RUNNER_WORKSPACE", "/workspace"))
KEY = os.environ.get("KEMUDI_RUNNER_KEY", "")
GATEWAY = os.environ.get("KEMUDI_DEV_GATEWAY", "http://kemudi-gateway")
CONFIG = "/opt/runner/playwright.config.cjs"
QA_PORT = 5199
JOB_RE = re.compile(r"^awak-us-\d+$")
GIT_SAFE = ["-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
            "-c", "safe.directory=*"]


def tail(text: str, n: int = 6000) -> str:
    return text[-n:]


def run(cmd: list[str], cwd: Path, timeout: int, env: dict | None = None) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                           env={**os.environ, "CI": "1", **(env or {})})
        return p.returncode, tail(p.stdout + p.stderr)
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        return 124, tail(out + f"\n[timed out after {timeout}s]")


def job_dir(body: dict) -> Path:
    job = str(body.get("job", ""))
    if not JOB_RE.match(job):
        raise ValueError(f"bad job name {job!r}")
    d = WORKSPACE / job
    if not d.is_dir():
        raise ValueError(f"no workspace for {job}")
    return d


# --- operations -------------------------------------------------------------

def op_install(body: dict) -> dict:
    web = job_dir(body) / "apps" / "web"
    code, out = run(["pnpm", "install", "--frozen-lockfile", "--ignore-scripts",
                     "--store-dir", "/pnpm-store", "--reporter", "append-only"], web, 900)
    if code != 0:
        return {"ok": False, "infra_error": "pnpm install failed: " + out[-800:]}
    return {"ok": True}


def op_commit(body: dict) -> dict:
    d = job_dir(body)
    run(["git", *GIT_SAFE, "add", "-A"], d, 60)
    code, _ = run(["git", *GIT_SAFE, "diff", "--cached", "--quiet"], d, 60)
    if code == 0:
        return {"ok": True, "committed": False}
    code, out = run(["git", *GIT_SAFE, "commit", "-q", "-m",
                     str(body.get("message") or "awak: uncommitted changes")], d, 60)
    return {"ok": code == 0, "committed": code == 0, "output": out}


GATES = [
    ("tsc -b", ["pnpm", "exec", "tsc", "-b"], 600),
    ("eslint", ["pnpm", "exec", "eslint", "."], 600),
    ("vitest", ["pnpm", "exec", "vitest", "run", "--browser.headless"], 900),
    ("vite build", ["pnpm", "exec", "vite", "build"], 600),
]


def op_gates(body: dict) -> dict:
    web = job_dir(body) / "apps" / "web"
    results = []
    for name, cmd, timeout in GATES:
        code, out = run(cmd, web, timeout)
        if code == 124:
            return {"infra_error": f"{name} timed out"}
        results.append({"name": name, "ok": code == 0, "output": out})
        if code != 0 and name == "tsc -b":
            break  # later gates only repeat the type errors
    return {"ok": all(r["ok"] for r in results), "gates": results}


def op_qa_reset(body: dict) -> dict:
    d = job_dir(body)
    qa = d / ".qa"
    shutil.rmtree(qa, ignore_errors=True)
    (qa / "spec").mkdir(parents=True)
    return {"ok": True}


def _wait_http(url: str, seconds: int) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                if r.status < 500:
                    return True
        except Exception:  # noqa: BLE001 - keep polling until the deadline
            pass
        time.sleep(1)
    return False


def _parse_report(path: Path) -> tuple[list[dict], str]:
    """Tests from Playwright's JSON report, and any load/compile error."""
    if not path.exists():
        return [], "Playwright wrote no report"
    data = json.loads(path.read_text())
    errors = [e.get("message", "") for e in data.get("errors") or []]
    tests: list[dict] = []

    def walk(suite: dict) -> None:
        for spec in suite.get("specs") or []:
            for t in spec.get("tests") or []:
                res = (t.get("results") or [{}])[-1]
                shots = [a["path"] for a in res.get("attachments") or []
                         if a.get("contentType") == "image/png" and a.get("path")]
                err = res.get("error") or {}
                tests.append({"title": spec.get("title", ""), "status": res.get("status", ""),
                              "error": (err.get("message") or "")[:1500],
                              "screenshots": shots})
        for child in suite.get("suites") or []:
            walk(child)

    for s in data.get("suites") or []:
        walk(s)
    return tests, "\n".join(errors)


def op_qa(body: dict) -> dict:
    d = job_dir(body)
    spec_dir = d / ".qa" / "spec"
    if not any(spec_dir.glob("*.spec.ts")):
        return {"spec_error": "no spec file in .qa/spec"}
    web = d / "apps" / "web"
    vite = subprocess.Popen(
        ["pnpm", "exec", "vite", "--port", str(QA_PORT), "--strictPort", "--host", "127.0.0.1"],
        cwd=web, env={**os.environ, "KEMUDI_DEV_GATEWAY": GATEWAY},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    tmp = Path(tempfile.mkdtemp(prefix="qa-"))
    base = f"http://127.0.0.1:{QA_PORT}"
    try:
        if not _wait_http(base + "/", 120):
            return {"infra_error": "dev server did not start"}
        session = {"token": body["token"], "refresh": "", "user": body.get("user") or {}}
        (tmp / "state.json").write_text(json.dumps({"cookies": [], "origins": [{
            "origin": base,
            "localStorage": [{"name": "kemudi.auth", "value": json.dumps(session)},
                             {"name": "kemudi.lang", "value": "en"}],
        }]}))
        npm_root = subprocess.run(["npm", "root", "-g"], capture_output=True,
                                  text=True).stdout.strip()
        runs = []
        for k in (1, 2):
            out_dir = d / ".qa" / "results" / f"run{k}"
            report = tmp / f"report{k}.json"
            # The global @playwright/test, run from .qa/ so the spec, the config
            # and the runner all load the same copy (not apps/web's playwright).
            code, out = run(
                ["node", f"{npm_root}/@playwright/test/cli.js", "test", "--config", CONFIG],
                d / ".qa", 900,
                env={"QA_SPEC_DIR": str(spec_dir), "QA_OUTPUT_DIR": str(out_dir),
                     "QA_REPORT": str(report), "QA_BASE_URL": base,
                     "QA_STATE": str(tmp / "state.json"), "NODE_PATH": npm_root,
                     "KEMUDI_QA_TOKEN": body["token"],
                     "KEMUDI_QA_PROJECT": str(body.get("project", ""))})
            if code == 124:
                return {"infra_error": "QA run timed out"}
            tests, load_error = _parse_report(report)
            if not tests:
                return {"spec_error": (load_error or out)[-2000:]}
            runs.append({"exit": code, "tests": tests})
        return {"ok": True, "runs": runs}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            os.killpg(vite.pid, signal.SIGTERM)
            vite.wait(timeout=10)
        except Exception:  # noqa: BLE001
            os.killpg(vite.pid, signal.SIGKILL)


OPS = {"install": op_install, "commit": op_commit, "gates": op_gates,
       "qa_reset": op_qa_reset, "qa": op_qa}


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
            return self._reply(200, op(body))
        except ValueError as e:
            return self._reply(400, {"error": str(e)})
        except Exception as e:  # noqa: BLE001
            return self._reply(200, {"infra_error": f"{type(e).__name__}: {e}"})

    def log_message(self, fmt, *args):
        print(f"runner: {self.command} {self.path} {fmt % args}", flush=True)


if __name__ == "__main__":
    # One job at a time: the orchestrator never calls in parallel.
    ThreadingHTTPServer(("0.0.0.0", 8800), Handler).serve_forever()
