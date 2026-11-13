"""kemudi-runner: a tiny HTTP service that runs a fixed set of commands in an
Awak job workspace. Python stdlib only.

POST /install    {job, subdir?, commands?}  pnpm install (frozen, no scripts), or the commands
POST /commit     {job, message}             commit anything the agent left
POST /gates      {job, subdir?, commands?}  tsc, eslint, vitest, vite build, or the commands
POST /qa_reset   {job}                      empty .qa/ for a fresh spec
POST /qa         {job, token, user, project, subdir?}  run .qa/spec twice against a dev
                                            server started in subdir (default apps/web)
POST /clean_check {job}                     HEAD sha and `git status --ignored` entries
POST /deploy     {job, command}             the project's post-merge deploy command (sh -c)
                                            in the job workspace at the merged commit

`commands` is [{name, argv, timeout}], run without a shell in `subdir` of the
job workspace; argv[0] must be in ALLOWED_PROGRAMS. Without `commands`, the
iteration 1 apps/web steps run.

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


ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
# The backend writes absolute media URLs for the host (http://localhost:9100).
# Forward that address to the gateway so images load in QA like in a browser.
HOST_PORT = int(os.environ.get("KEMUDI_HOST_PORT", "9100"))


def tail(text: str, n: int = 6000) -> str:
    return ANSI.sub("", text)[-n:]


def run(cmd: list[str], cwd: Path, timeout: int, env: dict | None = None) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                           env={**os.environ, "CI": "1", "FORCE_COLOR": "0", "NO_COLOR": "1",
                                **(env or {})})
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

# Programs a repo's configured commands may start (argv[0], a bare name looked
# up on PATH). No shell is involved, so `;`, `&&` or `$(...)` are plain text.
ALLOWED_PROGRAMS = {"pnpm", "npm", "npx", "yarn", "node", "python", "uv", "pytest", "make",
                    "go", "cargo"}
MAX_TIMEOUT = 1800


def work_dir(body: dict) -> Path:
    """The job dir, or `subdir` inside it: relative, no `..`, must exist."""
    d = job_dir(body)
    sub = str(body.get("subdir") or "")
    if not sub:
        return d
    parts = sub.replace("\\", "/").split("/")
    if (sub.startswith(("/", "\\")) or ":" in sub or ".." in parts
            or any(p in ("", ".") for p in parts[:-1])):
        raise ValueError(f"bad subdir {sub!r}")
    target = d.joinpath(*[p for p in parts if p])
    if not target.resolve().is_relative_to(d.resolve()) or not target.is_dir():
        raise ValueError(f"no directory {sub!r} in the workspace")
    return target


def commands(body: dict, default_timeout: int) -> list[tuple[str, list[str], int]] | None:
    """Validated `commands`, or None when the caller sent none (iteration 1 mode)."""
    raw = body.get("commands")
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ValueError("commands must be a list")
    out = []
    for c in raw:
        argv = c.get("argv") if isinstance(c, dict) else None
        if not (isinstance(argv, list) and argv and all(isinstance(a, str) for a in argv)):
            raise ValueError("each command needs argv: a non-empty list of strings")
        if argv[0] not in ALLOWED_PROGRAMS:
            raise ValueError(f"program {argv[0]!r} is not allowed; use one of "
                             f"{sorted(ALLOWED_PROGRAMS)}")
        timeout = min(int(c.get("timeout") or default_timeout), MAX_TIMEOUT)
        out.append((str(c.get("name") or " ".join(argv))[:200], argv, timeout))
    return out


def op_install(body: dict) -> dict:
    cmds = commands(body, 900)
    if cmds is None:
        web = job_dir(body) / "apps" / "web"
        code, out = run(["pnpm", "install", "--frozen-lockfile", "--ignore-scripts",
                         "--store-dir", "/pnpm-store", "--reporter", "append-only"], web, 900)
        if code != 0:
            return {"ok": False, "infra_error": "pnpm install failed: " + out[-800:]}
        return {"ok": True}
    cwd = work_dir(body)
    for name, argv, timeout in cmds:
        code, out = run(argv, cwd, timeout)
        if code != 0:
            return {"ok": False, "infra_error": f"{name} failed: " + out[-800:]}
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
    cmds = commands(body, 900)
    if cmds is None:
        cwd, cmds = job_dir(body) / "apps" / "web", GATES
    else:
        cwd = work_dir(body)
    results = []
    for i, (name, cmd, timeout) in enumerate(cmds):
        code, out = run(cmd, cwd, timeout)
        if code == 124:
            return {"infra_error": f"{name} timed out"}
        results.append({"name": name, "ok": code == 0, "output": out})
        if code != 0 and i == 0:
            break  # the first gate is the type check; later ones only repeat its errors
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
    # The repo's web app directory; iteration 1 callers send none (apps/web).
    web = work_dir(body) if "subdir" in body else d / "apps" / "web"
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


MAX_CLEAN_ENTRIES = 200


def _git_out(args: list[str], env: dict, timeout: int = 120) -> tuple[int, str]:
    try:
        p = subprocess.run(["git", *GIT_SAFE, *args], capture_output=True, timeout=timeout,
                           env=env)
    except subprocess.TimeoutExpired:
        return 124, f"git {args[0] if args else ''} timed out"
    if p.returncode != 0:
        return p.returncode, tail(p.stderr.decode(errors="replace"), 500)
    return 0, p.stdout.decode(errors="replace")


def op_clean_check(body: dict) -> dict:
    """HEAD and every path `git status` reports, ignored files included, so the
    orchestrator can tell whether the checks ran on exactly the commit.

    The workspace's .git belongs to the agent: its config (filters, worktree),
    index (assume-unchanged, skip-worktree) and replace refs could all hide a
    change. So status runs from a throwaway git dir that only borrows the
    workspace's objects, with an index rebuilt from HEAD's tree."""
    d = job_dir(body)
    gd = d / ".git"
    if gd.is_symlink() or not gd.is_dir():
        return {"ok": True, "head": "", "entries": [{"status": "!?", "path": ".git"}],
                "truncated": False}
    tmp = Path(tempfile.mkdtemp(prefix="clean-"))
    try:
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp),
               "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
               "GIT_NO_REPLACE_OBJECTS": "1", "GIT_OPTIONAL_LOCKS": "0",
               "GIT_TERMINAL_PROMPT": "0"}
        code, out = _git_out(["init", "-q", str(tmp / "w")], env)
        if code != 0:
            return {"infra_error": "git init failed: " + out}
        git_dir = tmp / "w" / ".git"
        (git_dir / "objects" / "info" / "alternates").write_bytes(
            ((gd / "objects").resolve().as_posix() + "\n").encode())
        head_file = (gd / "HEAD").read_text().strip()
        if head_file.startswith("ref: "):
            ref = head_file[5:]
            if not re.match(r"^refs/heads/[A-Za-z0-9._/-]+$", ref) or ".." in ref:
                return {"infra_error": f"unexpected HEAD {head_file[:100]!r}"}
            ref_path = gd / ref
            if ref_path.is_file():
                head = ref_path.read_text().strip()
            else:
                head = ""
                packed = gd / "packed-refs"
                for line in packed.read_text().splitlines() if packed.is_file() else []:
                    if line.endswith(" " + ref):
                        head = line.split(" ", 1)[0]
        else:
            head = head_file
        if not re.match(r"^[0-9a-f]{40}([0-9a-f]{24})?$", head):
            return {"infra_error": f"cannot read HEAD ({head[:100]!r})"}
        base = ["--git-dir", str(git_dir), "--work-tree", str(d)]
        env["GIT_INDEX_FILE"] = str(tmp / "index")
        code, out = _git_out([*base, "update-ref", "HEAD", head], env)
        if code != 0:
            return {"infra_error": "git update-ref failed: " + out}
        code, out = _git_out([*base, "read-tree", f"{head}^{{tree}}"], env)
        if code != 0:
            return {"infra_error": "git read-tree failed: " + out}
        code, out = _git_out([*base, "status", "--porcelain=v1", "-z", "--ignored=matching",
                              "--untracked-files=normal"], env, 300)
        if code != 0:
            return {"infra_error": "git status failed: " + out}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    entries = []
    parts = out.split("\0")
    i = 0
    while i < len(parts):
        item = parts[i]
        i += 1
        if len(item) < 4:
            continue
        status, path = item[:2], item[3:]
        if "R" in status or "C" in status:
            i += 1  # -z puts a rename's source path in the next field
        entries.append({"status": status, "path": path})
    return {"ok": True, "head": head, "entries": entries[:MAX_CLEAN_ENTRIES],
            "truncated": len(entries) > MAX_CLEAN_ENTRIES}


DEPLOY_TIMEOUT = 900


def op_deploy(body: dict) -> dict:
    """Run the admin's deploy command in the workspace. It runs here, in the
    runner's sandbox (no Docker socket, no secrets, egress network only), so it
    can only reach what the network allows; the output goes back redacted by
    the orchestrator."""
    d = job_dir(body)
    command = str(body.get("command") or "").strip()
    if not command:
        raise ValueError("no deploy command")
    if len(command) > 2000:
        raise ValueError("deploy command too long")
    code, out = run(["sh", "-c", command], d, DEPLOY_TIMEOUT)
    return {"ok": code == 0, "exit": code, "output": out[-4000:]}


OPS = {"install": op_install, "commit": op_commit, "gates": op_gates, "deploy": op_deploy,
       "qa_reset": op_qa_reset, "qa": op_qa, "clean_check": op_clean_check}


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


def forward_host_port() -> None:
    """127.0.0.1:HOST_PORT -> the gateway, as plain TCP."""
    import socket
    import threading
    from urllib.parse import urlparse

    target = urlparse(GATEWAY)
    dest = (target.hostname or "kemudi-gateway", target.port or 80)

    def pipe(a: socket.socket, b: socket.socket) -> None:
        try:
            while data := a.recv(65536):
                b.sendall(data)
        except OSError:
            pass
        finally:
            for s in (a, b):
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

    def serve() -> None:
        srv = socket.socket()
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", HOST_PORT))
        srv.listen(64)
        while True:
            client, _ = srv.accept()
            try:
                upstream = socket.create_connection(dest, timeout=10)
            except OSError:
                client.close()
                continue
            for a, b in ((client, upstream), (upstream, client)):
                threading.Thread(target=pipe, args=(a, b), daemon=True).start()

    threading.Thread(target=serve, name="host-port-forward", daemon=True).start()


if __name__ == "__main__":
    forward_host_port()
    # One job at a time: the orchestrator never calls in parallel.
    ThreadingHTTPServer(("0.0.0.0", 8800), Handler).serve_forever()
