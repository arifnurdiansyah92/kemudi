"""kemudi-runner: a tiny HTTP service that runs a fixed set of commands in an
Awak job workspace. Python stdlib only.

POST /install    {path, subdir?, commands?, env?}  pnpm install (frozen, no scripts), or
                                             the commands
POST /commit     {path, message}             commit anything the agent left
POST /gates      {path, subdir?, commands?, env?}  tsc, eslint, vitest, vite build, or the
                                             commands
POST /qa_reset   {path}                      empty .qa/ for a fresh spec
POST /qa         {path, token, user, project, subdir?}  run .qa/spec twice against a dev
                                             server started in subdir (default apps/web)
                 {path, services, base_service, warm?}  the same against the runbook's
                                             process services (see op_qa)
POST /clean_check {path}                     HEAD sha and `git status --ignored` entries
POST /deploy     {path, command}             the project's post-merge deploy command (sh -c)
                                             in the job workspace at the merged commit

`path` names one checkout under WORKSPACE: `<slug>/us-<ref>/<repo>` for a
story, `<slug>/setup/<repo>` for setup runs.

`commands` is [{name, argv, timeout}], run without a shell in `subdir` of the
job workspace; argv[0] must be in ALLOWED_PROGRAMS. Without `commands`, the
iteration 1 apps/web steps run.

Children (branch code) get a clean environment from `child_env`: never the
runner's key or any other KEMUDI_* variable.

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
import socket
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WORKSPACE = Path(os.environ.get("RUNNER_WORKSPACE", "/workspace"))
KEY = os.environ.get("KEMUDI_RUNNER_KEY", "")
GATEWAY = os.environ.get("KEMUDI_DEV_GATEWAY", "http://kemudi-gateway")
CONFIG = "/opt/runner/playwright.config.cjs"
QA_PORT = 5199
# <project slug>/<us-<ref> | setup>/<repo name>
PATH_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,99}/(us-\d+|setup)/"
                     r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
GIT_SAFE = ["-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false",
            "-c", "safe.directory=*"]


ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
# The backend writes absolute media URLs for the host (http://localhost:9100).
# Forward that address to the gateway so images load in QA like in a browser.
HOST_PORT = int(os.environ.get("KEMUDI_HOST_PORT", "9100"))


def tail(text: str, n: int = 6000) -> str:
    return ANSI.sub("", text)[-n:]


# What a child keeps from the runner's own environment: the toolchain's
# locations and the locale, nothing else (no key, no gateway settings).
KEEP_ENV = {"PATH", "HOME", "LANG", "LANGUAGE", "LC_ALL", "LC_CTYPE", "TZ", "TERM", "USER",
            "LOGNAME", "SHELL", "TMPDIR", "PLAYWRIGHT_BROWSERS_PATH", "PNPM_HOME", "NODE_PATH",
            "NODE_EXTRA_CA_CERTS", "SSL_CERT_FILE", "SSL_CERT_DIR", "COREPACK_HOME",
            # Windows (local tests)
            "SYSTEMROOT", "COMSPEC", "PATHEXT", "TEMP", "TMP", "APPDATA", "LOCALAPPDATA",
            "USERPROFILE", "PROGRAMDATA", "WINDIR"}
KEEP_ENV_PREFIXES = ("NPM_CONFIG_", "XDG_")


def child_env(extra: dict | None = None) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if (k.upper() in KEEP_ENV or k.upper().startswith(KEEP_ENV_PREFIXES))
           and not k.upper().startswith("KEMUDI_")}
    env.update({"CI": "1", "FORCE_COLOR": "0", "NO_COLOR": "1",
                "npm_config_store_dir": "/pnpm-store"})
    env.update(extra or {})
    return env


# Env names a request may not set (same lists as the orchestrator's runbook.py).
BLOCKED_ENV_PREFIXES = ("KEMUDI_", "DOCKER_", "COMPOSE_", "GIT_")
BLOCKED_ENV_NAMES = frozenset({"PATH", "LD_PRELOAD", "LD_LIBRARY_PATH", "NODE_OPTIONS",
                               "PYTHONPATH", "HOME"})
ENV_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,99}")


def request_env(raw) -> dict[str, str]:
    """A request's `env`: string -> string, names not reserved."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("env must be an object")
    for k, v in raw.items():
        if not (isinstance(k, str) and ENV_NAME_RE.fullmatch(k) and isinstance(v, str)):
            raise ValueError(f"bad env entry {k!r}")
        if k.upper() in BLOCKED_ENV_NAMES or k.upper().startswith(BLOCKED_ENV_PREFIXES):
            raise ValueError(f"env name {k!r} is reserved")
    return dict(raw)


def run(cmd: list[str], cwd: Path, timeout: int, env: dict | None = None) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
                           env=child_env(env))
        return p.returncode, tail(p.stdout + p.stderr)
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        return 124, tail(out + f"\n[timed out after {timeout}s]")


def job_dir(body: dict) -> Path:
    """The checkout named by `path` (`<slug>/us-<ref>/<repo>` or
    `<slug>/setup/<repo>`), relative to WORKSPACE. A symlink anywhere on the
    way could point outside, so the resolved directory must stay inside."""
    rel = str(body.get("path", ""))
    if not PATH_RE.fullmatch(rel):
        raise ValueError(f"bad workspace path {rel!r}")
    d = WORKSPACE.joinpath(*rel.split("/"))
    if (d.is_symlink() or not d.is_dir()
            or not d.resolve().is_relative_to(WORKSPACE.resolve())):
        raise ValueError(f"no workspace at {rel}")
    return d


# --- operations -------------------------------------------------------------

# Programs a repo's configured commands may start (argv[0], a bare name looked
# up on PATH). No shell is involved, so `;`, `&&` or `$(...)` are plain text.
ALLOWED_PROGRAMS = frozenset({"pnpm", "npm", "npx", "yarn", "node", "python", "uv", "pytest",
                              "make", "go", "cargo"})
MAX_TIMEOUT = 1800


def work_dir(body: dict, d: Path | None = None) -> Path:
    """The job dir (or `d`), or `subdir` inside it: relative, no `..`, must exist."""
    d = job_dir(body) if d is None else d
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
    env = request_env(body.get("env"))
    if cmds is None:
        web = job_dir(body) / "apps" / "web"
        code, out = run(["pnpm", "install", "--frozen-lockfile", "--ignore-scripts",
                         "--store-dir", "/pnpm-store", "--reporter", "append-only"], web, 900)
        if code != 0:
            return {"ok": False, "infra_error": "pnpm install failed: " + out[-800:]}
        return {"ok": True}
    cwd = work_dir(body)
    for name, argv, timeout in cmds:
        code, out = run(argv, cwd, timeout, env)
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
    env = request_env(body.get("env"))
    if cmds is None:
        cwd, cmds = job_dir(body) / "apps" / "web", GATES
    else:
        cwd = work_dir(body)
    results = []
    for i, (name, cmd, timeout) in enumerate(cmds):
        code, out = run(cmd, cwd, timeout, env)
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


def _wait_http(url: str, seconds: float, ok=lambda status: status < 500,
               alive=lambda: True) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and alive():
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                if ok(r.status):
                    return True
        except urllib.error.HTTPError as e:
            if ok(e.code):
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


# The whole `qa` op stays under the orchestrator's 1800 s client timeout.
QA_DEADLINE = 1700
SERVICE_PORT = 5200
SERVICE_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
SERVICE_URL_RE = re.compile(r"\{services\.([a-z0-9-]+)\.url\}")
MAX_WARM = 10
WARM_TIMEOUT = 180
LOG_TAIL_LINES = 60


def _spawn(argv: list[str], cwd: Path, env: dict, log) -> subprocess.Popen:
    """A process in its own group (session), so stopping it stops its children."""
    kw = {"start_new_session": True} if os.name == "posix" else {
        "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=log,
                            stderr=subprocess.STDOUT, **kw)


def _stop(proc: subprocess.Popen) -> None:
    """SIGTERM to the process group, SIGKILL after 10 s."""
    if os.name != "posix":
        if proc.poll() is None:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True)
        proc.wait(timeout=10)
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)  # children may outlive the leader
    except ProcessLookupError:
        pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def _free_port(start: int, taken: set[int]) -> int:
    for port in range(start, start + 200):
        if port in taken:
            continue
        with socket.socket() as sock:
            try:
                sock.bind(("0.0.0.0", port))
            except OSError:
                continue
        return port
    raise RuntimeError("no free port for a QA service")


def _log_tail(path: Path, n: int = LOG_TAIL_LINES) -> str:
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError:
        return "(no log)"
    return ANSI.sub("", "\n".join(lines[-n:]))


def _services(body: dict, d: Path) -> list[dict]:
    """Validated process services: cwd in the story folder (the story's repo or
    a sibling checkout), argv allowlisted, env names not reserved."""
    raw = body.get("services")
    if not isinstance(raw, list) or not raw:
        raise ValueError("services must be a non-empty list")
    out, names = [], set()
    for s in raw:
        if not isinstance(s, dict):
            raise ValueError("each service must be an object")
        name = str(s.get("name") or "")
        if not SERVICE_RE.fullmatch(name) or name in names:
            raise ValueError(f"bad or duplicate service name {name!r}")
        names.add(name)
        argv = s.get("argv")
        if not (isinstance(argv, list) and argv and all(isinstance(a, str) for a in argv)):
            raise ValueError(f"service {name}: argv must be a non-empty list of strings")
        if argv[0] not in ALLOWED_PROGRAMS:
            raise ValueError(f"service {name}: program {argv[0]!r} is not allowed")
        repo = str(s.get("repo") or d.name)
        root = d if repo == d.name else job_dir({"path": f"{d.parent.parent.name}/"
                                                         f"{d.parent.name}/{repo}"})
        health = str(s.get("health") or "/")
        if not health.startswith("/") or any(c.isspace() for c in health):
            raise ValueError(f"service {name}: bad health path {health!r}")
        out.append({"name": name, "cwd": work_dir(s, root), "argv": argv,
                    "env": request_env(s.get("env")), "health": health,
                    "ready_timeout": max(1, min(int(s.get("ready_timeout") or 120), 600))})
    return out


def _warm_paths(body: dict, d: Path) -> list[str]:
    paths = [str(p) for p in body.get("warm") or []]
    routes = d / ".qa" / "routes.txt"
    if routes.is_file() and not routes.is_symlink():
        paths += routes.read_text(errors="replace").splitlines()[:50]
    out: list[str] = []
    for p in (x.strip() for x in paths):
        if p.startswith("/") and not p.startswith("//") and not any(c.isspace() for c in p) \
                and p not in out:
            out.append(p)
    return out[:MAX_WARM]


def _start_services(services: list[dict], d: Path, deadline: float,
                    procs: list[subprocess.Popen]) -> dict[str, str] | str:
    """Start each service in order and wait for its health; returns name -> base
    URL, or an error text with the log tail."""
    logs = d / ".qa" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    urls: dict[str, str] = {}
    taken: set[int] = set()
    for s in services:
        port = _free_port(SERVICE_PORT, taken)
        taken.add(port)
        env = {}
        for k, v in s["env"].items():
            for ref in SERVICE_URL_RE.findall(v):
                if ref not in urls:
                    return f"service {s['name']}: {k} refers to service {ref!r}, not started"
            env[k] = SERVICE_URL_RE.sub(lambda m: urls[m.group(1)], v)
        env.update({"PORT": str(port), "NEXT_TELEMETRY_DISABLED": "1",
                    "NODE_OPTIONS": "--max-old-space-size=2048"})
        argv = [a.replace("{port}", str(port)) for a in s["argv"]]
        log_path = logs / f"{s['name']}.log"
        with open(log_path, "wb") as log:
            proc = _spawn(argv, s["cwd"], child_env(env), log)
        procs.append(proc)
        base = f"http://localhost:{port}"
        wait = min(s["ready_timeout"], max(0.0, deadline - time.monotonic()))
        if not _wait_http(base + s["health"], wait, ok=lambda st: 200 <= st < 400,
                          alive=lambda: proc.poll() is None):
            why = (f"exited with {proc.returncode}" if proc.poll() is not None
                   else f"not healthy at {s['health']} after {int(wait)}s")
            return (f"service {s['name']} did not start ({why}). Last lines of "
                    f".qa/logs/{s['name']}.log:\n{_log_tail(log_path)}")
        urls[s["name"]] = base
    return urls


def _warm(base: str, paths: list[str], deadline: float) -> None:
    """Load each path once: dev servers compile a page on its first request."""
    for p in paths:
        left = deadline - time.monotonic()
        if left < 60:
            return
        try:
            with urllib.request.urlopen(base + p, timeout=min(WARM_TIMEOUT, left - 30)) as r:
                r.read(1)
        except Exception:  # noqa: BLE001 - a 404 or a slow page is the spec's business
            pass


def op_qa(body: dict) -> dict:
    """Run .qa/spec twice against the app. With `services` (a runbook): start
    them as processes in the story's checkouts, base URL = `base_service`, no
    login. Without: iteration 1's vite dev server for Kemudi with the QA token."""
    d = job_dir(body)
    spec_dir = d / ".qa" / "spec"
    if not any(spec_dir.glob("*.spec.ts")):
        return {"spec_error": "no spec file in .qa/spec"}
    deadline = time.monotonic() + QA_DEADLINE
    if "services" in body:
        services = _services(body, d)
        base_name = str(body.get("base_service") or "")
        if base_name not in {s["name"] for s in services}:
            raise ValueError(f"base_service {base_name!r} is not one of the services")
        procs: list[subprocess.Popen] = []
        try:
            urls = _start_services(services, d, deadline, procs)
            if isinstance(urls, str):
                return {"infra_error": urls}
            base = urls[base_name]
            _warm(base, _warm_paths(body, d), deadline)
            return _run_specs(d, spec_dir, base, None, {}, deadline)
        finally:
            for proc in reversed(procs):
                try:
                    _stop(proc)
                except Exception:  # noqa: BLE001 - stop the others too
                    pass

    # The repo's web app directory; iteration 1 callers send none (apps/web).
    web = work_dir(body) if "subdir" in body else d / "apps" / "web"
    vite = _spawn(["pnpm", "exec", "vite", "--port", str(QA_PORT), "--strictPort", "--host",
                   "127.0.0.1"], web, child_env({"KEMUDI_DEV_GATEWAY": GATEWAY}),
                  subprocess.DEVNULL)
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
        return _run_specs(d, spec_dir, base, tmp / "state.json",
                          {"KEMUDI_QA_TOKEN": body["token"],
                           "KEMUDI_QA_PROJECT": str(body.get("project", ""))}, deadline)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        _stop(vite)


def _run_specs(d: Path, spec_dir: Path, base: str, state: Path | None, extra: dict,
               deadline: float) -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="qa-report-"))
    try:
        npm_root = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True,
                                  env=child_env()).stdout.strip()
        runs = []
        for k in (1, 2):
            out_dir = d / ".qa" / "results" / f"run{k}"
            report = tmp / f"report{k}.json"
            left = int(deadline - time.monotonic())
            if left < 30:
                return {"infra_error": "QA ran out of time before the spec runs"}
            env = {"QA_SPEC_DIR": str(spec_dir), "QA_OUTPUT_DIR": str(out_dir),
                   "QA_REPORT": str(report), "QA_BASE_URL": base, "NODE_PATH": npm_root,
                   **extra}
            if state is not None:
                env["QA_STATE"] = str(state)
            # The global @playwright/test, run from .qa/ so the spec, the config
            # and the runner all load the same copy (not the app's playwright).
            code, out = run(
                ["node", f"{npm_root}/@playwright/test/cli.js", "test", "--config", CONFIG],
                d / ".qa", min(900, left), env=env)
            if code == 124:
                return {"infra_error": "QA run timed out"}
            tests, load_error = _parse_report(report)
            if not tests:
                return {"spec_error": (load_error or out)[-2000:]}
            runs.append({"exit": code, "tests": tests})
        return {"ok": True, "runs": runs}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


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
