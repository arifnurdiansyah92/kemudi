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
                 {path, services, base_service, warm?, external?, login?, spec_env?}
                                             the same against the runbook's process
                                             services (see op_qa)
POST /health     {url, path?, timeout?}      wait until a compose service published on
                                             kemudi-dind answers 2xx/3xx at path
POST /screenshot {path, services, base_service, out, external?, login?}
                                             start the runbook's process services as
                                             `qa` does, save a PNG of base_service `/`
                                             to .qa/<out>, report RSS and log tails,
                                             stop them (the Setup Assistant's proof)
POST /reap       {}                          stop every process service left running and
                                             kill every process of the child uid
POST /clean_check {path}                     HEAD sha and `git status --ignored` entries
POST /deploy     {path, command}             the project's post-merge deploy command (sh -c)
                                             in the job workspace at the merged commit

`path` names one checkout under WORKSPACE: `<slug>/us-<ref>/<repo>` for a
story, `<slug>/setup/<repo>` for setup runs.

`commands` is [{name, argv, timeout}], run without a shell in `subdir` of the
job workspace; argv[0] must be in ALLOWED_PROGRAMS. Without `commands`, the
iteration 1 apps/web steps run.

The server runs as root with only the SETUID, SETGID and KILL capabilities
(compose: `cap_drop: [ALL]`, `cap_add: [SETUID, SETGID, KILL]`); it reads its
key from the environment at start. Every child (branch code: commands,
process services, Playwright, git for the clean check, the deploy command)
runs as CHILD_UID:CHILD_GID (10000, the owner of /workspace) with no
supplementary groups and a clean environment from `child_env`: no runner key,
no other KEMUDI_* variable. A child therefore cannot read the key from the
server's (or tini's) /proc/<pid>/environ. KILL lets the server stop a
child's process group.

The workspace belongs to the children, so the server never writes or reads
a file there itself (a symlink would make it do so as root): `.qa/` is made
and emptied, service logs are written and reports and logs are read by a
child (`read_as_child`). Without root (local tests) children keep the
server's uid and the same code paths run unchanged.

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
LOGIN_SCRIPT = os.environ.get("RUNNER_LOGIN_SCRIPT", "/opt/runner/login.cjs")
# Where compose services publish their ports (kemudi-dindnet); the only host
# `external` URLs and the health op may name.
DIND_HOST = os.environ.get("RUNNER_DIND_HOST", "kemudi-dind")
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


# The uid/gid children run as (the workspace owner; `hermes` in the image).
CHILD_UID = int(os.environ.get("RUNNER_CHILD_UID", "10000"))
CHILD_GID = int(os.environ.get("RUNNER_CHILD_GID", str(CHILD_UID)))


def dropping() -> bool:
    """Whether children switch to CHILD_UID (the server runs as root)."""
    return os.name == "posix" and os.geteuid() == 0


def child_kw() -> dict:
    """subprocess arguments that start a child as CHILD_UID:CHILD_GID."""
    if not dropping():
        return {}
    return {"user": CHILD_UID, "group": CHILD_GID, "extra_groups": []}


def _child_home() -> str:
    import pwd

    try:
        return pwd.getpwuid(CHILD_UID).pw_dir or "/tmp"
    except KeyError:
        return "/tmp"


# What a child keeps from the runner's own environment: the toolchain's
# locations and the locale, nothing else (no key, no gateway settings in its
# environment). As root, HOME is the child user's and USER/LOGNAME are dropped.
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
    if dropping():
        # the server's are root's
        env.pop("USER", None)
        env.pop("LOGNAME", None)
        env["HOME"] = _child_home()
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
                           env=child_env(env), **child_kw())
        return p.returncode, tail(p.stdout + p.stderr)
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"").decode() if isinstance(e.stdout, bytes) else (e.stdout or "")
        return 124, tail(out + f"\n[timed out after {timeout}s]")


def child_tmpdir(prefix: str) -> Path:
    """A private temp dir the child owns (the server only removes it). The
    child makes it: the server has no CHOWN capability."""
    if not dropping():
        return Path(tempfile.mkdtemp(prefix=prefix))
    p = subprocess.run(["mktemp", "-d", "-p", tempfile.gettempdir(), f"{prefix}XXXXXXXX"],
                       capture_output=True, text=True, timeout=30, cwd="/",
                       env=child_env(), **child_kw())
    if p.returncode != 0:
        raise RuntimeError(f"cannot create a temp dir: {p.stderr.strip()[:200]}")
    return Path(p.stdout.strip())


def remove_child_tmpdir(tmp: Path) -> None:
    """Remove a `child_tmpdir` (as the child: root lacks DAC_OVERRIDE here)."""
    if not dropping():
        shutil.rmtree(tmp, ignore_errors=True)
        return
    try:
        subprocess.run(["rm", "-rf", "--", str(tmp)], capture_output=True, timeout=120,
                       cwd="/", env=child_env(), **child_kw())
    except subprocess.TimeoutExpired:
        pass


def read_as_child(path: Path, limit: int = 8_000_000) -> str | None:
    """A file in a child-writable place, read with the child's rights (as
    root, a symlink there would read anything for it); None if unreadable."""
    if not dropping():
        try:
            with open(path, "rb") as f:
                return f.read(limit).decode(errors="replace")
        except OSError:
            return None
    try:
        p = subprocess.run(["head", "-c", str(limit), "--", str(path)], capture_output=True,
                           timeout=60, env=child_env(), **child_kw())
    except subprocess.TimeoutExpired:
        return None
    return p.stdout.decode(errors="replace") if p.returncode == 0 else None


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
    if dropping():
        run(["rm", "-rf", "--", ".qa"], d, 120)
        code, out = run(["mkdir", "-p", "--", ".qa/spec"], d, 60)
        if code != 0:
            return {"infra_error": "cannot create .qa/spec: " + out[-300:]}
        return {"ok": True}
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
    text = read_as_child(path)
    if text is None:
        return [], "Playwright wrote no report"
    data = json.loads(text)
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


def _spawn(argv: list[str], cwd: Path, env: dict, log: Path | None) -> subprocess.Popen:
    proc = _popen(argv, cwd, env, log)
    LIVE.add(proc)
    return proc


def _popen(argv: list[str], cwd: Path, env: dict, log: Path | None) -> subprocess.Popen:
    """A child in its own group (session), so stopping it stops its children.
    Output goes to `log` (None: discarded). As root, the child's own shell
    opens the log (then execs argv, keeping the pid), so a symlink in the
    workspace cannot make the server write somewhere as root."""
    kw = {"start_new_session": True} if os.name == "posix" else {
        "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    if log is not None and dropping():
        argv = ["sh", "-c", 'f=$1; shift; exec "$@" >"$f" 2>&1', "sh", str(log), *argv]
        return subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                **kw, **child_kw())
    if log is None:
        return subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
                                **kw, **child_kw())
    with open(log, "wb") as f:
        return subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=f,
                                stderr=subprocess.STDOUT, **kw, **child_kw())


# Every process service and dev server started, until stopped (`reap`).
LIVE: set[subprocess.Popen] = set()


def _stop(proc: subprocess.Popen) -> None:
    """SIGTERM to the process group, SIGKILL after 10 s."""
    LIVE.discard(proc)
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
    text = read_as_child(path)
    if text is None:
        return "(no log)"
    lines = text.splitlines()
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
        paths += (read_as_child(routes, 64_000) or "").splitlines()[:50]
    out: list[str] = []
    for p in (x.strip() for x in paths):
        if p.startswith("/") and not p.startswith("//") and not any(c.isspace() for c in p) \
                and p not in out:
            out.append(p)
    return out[:MAX_WARM]


def _start_services(services: list[dict], d: Path, deadline: float,
                    procs: list[subprocess.Popen],
                    external: dict[str, str] | None = None) -> dict[str, str] | str:
    """Start each service in order and wait for its health; returns name -> base
    URL, or an error text with the log tail. `external`: URLs of services
    already running elsewhere (compose services), for `{services.x.url}`."""
    logs = d / ".qa" / "logs"
    if dropping():
        code, out = run(["mkdir", "-p", "--", ".qa/logs"], d, 60)
        if code != 0:
            return "cannot create .qa/logs: " + out[-300:]
    else:
        logs.mkdir(parents=True, exist_ok=True)
    urls: dict[str, str] = dict(external or {})
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
        proc = _spawn(argv, s["cwd"], child_env(env), log_path)
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


def dind_url(raw) -> str:
    """`http://<DIND_HOST>:<port>`: a port kemudi-svc published on kemudi-dind."""
    url = str(raw or "")
    m = re.fullmatch(rf"http://{re.escape(DIND_HOST)}:(\d{{1,5}})", url)
    if not m or not 0 < int(m.group(1)) < 65536:
        raise ValueError(f"bad service url {url!r}; expected http://{DIND_HOST}:<port>")
    return url


def _external(body: dict, names: set[str]) -> dict[str, str]:
    raw = body.get("external") or {}
    if not isinstance(raw, dict):
        raise ValueError("external must be an object")
    out = {}
    for name, url in raw.items():
        if not (isinstance(name, str) and SERVICE_RE.fullmatch(name)) or name in names:
            raise ValueError(f"bad or duplicate external service name {name!r}")
        out[name] = dind_url(url)
    return out


# Set by the runner for the Playwright run; `spec_env` may not.
QA_FIXED_ENV = frozenset({"QA_SPEC_DIR", "QA_OUTPUT_DIR", "QA_REPORT", "QA_BASE_URL",
                          "QA_STATE", "QA_LOGIN", "QA_STATE_OUT", "NODE_PATH"})


def _spec_env(body: dict) -> dict[str, str]:
    """Values the spec reads (`process.env.X`): only Playwright gets them."""
    env = request_env(body.get("spec_env"))
    for k in env:
        if k.upper() in QA_FIXED_ENV:
            raise ValueError(f"spec_env name {k!r} is reserved")
    return env


def _url_path(raw, what: str, empty_ok: bool = False) -> str:
    p = str(raw or "")
    if empty_ok and not p:
        return p
    if (not p.startswith("/") or p.startswith("//") or len(p) > 500
            or any(c.isspace() or ord(c) < 32 for c in p)):
        raise ValueError(f"bad {what} {p!r}")
    return p


def _login_body(raw) -> dict | None:
    """`login`: {path, fields: [{selector, value}], submit, success_url?}."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("login must be an object")
    fields = raw.get("fields")
    if not (isinstance(fields, list) and 0 < len(fields) <= 10):
        raise ValueError("login.fields must be a list of 1-10 fields")

    def selector(x) -> str:
        if not (isinstance(x, str) and x.strip() and len(x) <= 300
                and not any(ord(c) < 32 for c in x)):
            raise ValueError(f"bad login selector {x!r}")
        return x

    out = []
    for f in fields:
        if not (isinstance(f, dict) and isinstance(f.get("value"), str)
                and len(f["value"]) <= 8192):
            raise ValueError("each login field needs a selector and a string value")
        out.append({"selector": selector(f.get("selector")), "value": f["value"]})
    return {"path": _url_path(raw.get("path"), "login.path"), "fields": out,
            "submit": selector(raw.get("submit")),
            "success_url": _url_path(raw.get("success_url"), "login.success_url", True)}


def _npm_root() -> str:
    return subprocess.run(["npm", "root", "-g"], capture_output=True, text=True,
                          env=child_env(), **child_kw()).stdout.strip()


LOGIN_TIMEOUT = 180


def _login(d: Path, base: str, login: dict, deadline: float, tmp: Path) -> str:
    """Sign in once through the app's form with Playwright (login.cjs) and save
    the browser state to `tmp/state.json`; returns an error text or "". The
    field values reach only that node process, through its environment."""
    left = int(deadline - time.monotonic())
    if left < 60:
        return "QA ran out of time before the login"
    env = {"QA_BASE_URL": base, "QA_LOGIN": json.dumps(login),
           "QA_STATE_OUT": str(tmp / "state.json"), "NODE_PATH": _npm_root()}
    code, out = run(["node", LOGIN_SCRIPT], d / ".qa", min(LOGIN_TIMEOUT, left - 30), env)
    if code != 0:
        return tail(out, 1500).strip() or f"login exited with {code}"
    return ""


def op_qa(body: dict) -> dict:
    """Run .qa/spec twice against the app. With `services` (a runbook): start
    them as processes in the story's checkouts (`external`: compose services
    already up, for their env), base URL = `base_service`; `login`: sign in
    once through the app's form first (the specs start logged in); `spec_env`:
    values only the spec process sees. Without: iteration 1's vite dev server
    for Kemudi with the QA token."""
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
        external = _external(body, {s["name"] for s in services})
        login = _login_body(body.get("login"))
        spec_env = _spec_env(body)
        procs: list[subprocess.Popen] = []
        login_tmp: Path | None = None
        try:
            urls = _start_services(services, d, deadline, procs, external)
            if isinstance(urls, str):
                return {"infra_error": urls}
            base = urls[base_name]
            _warm(base, _warm_paths(body, d), deadline)
            state = None
            if login is not None:
                login_tmp = child_tmpdir("qa-login-")
                err = _login(d, base, login, deadline, login_tmp)
                if err:
                    return {"login_error": err}
                state = login_tmp / "state.json"
            return _run_specs(d, spec_dir, base, state, spec_env, deadline)
        finally:
            for proc in reversed(procs):
                try:
                    _stop(proc)
                except Exception:  # noqa: BLE001 - stop the others too
                    pass
            if login_tmp is not None:
                remove_child_tmpdir(login_tmp)

    # The repo's web app directory; iteration 1 callers send none (apps/web).
    web = work_dir(body) if "subdir" in body else d / "apps" / "web"
    vite = _spawn(["pnpm", "exec", "vite", "--port", str(QA_PORT), "--strictPort", "--host",
                   "127.0.0.1"], web, child_env({"KEMUDI_DEV_GATEWAY": GATEWAY}),
                  None)
    # The server's own dir: children may read the state, not replace it.
    tmp = Path(tempfile.mkdtemp(prefix="qa-"))
    tmp.chmod(0o755)
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


SHOT_SCRIPT = os.environ.get("RUNNER_SHOT_SCRIPT", "/opt/runner/screenshot.cjs")
# `out`: a PNG path inside .qa/ (lowercase names, at most four folders deep).
SHOT_RE = re.compile(r"(?:[a-z0-9][a-z0-9-]{0,39}/){0,4}[a-z0-9][a-z0-9-]{0,39}\.png")
SHOT_TIMEOUT = 300
CGROUP_PEAK = Path("/sys/fs/cgroup/memory.peak")


def _group_rss_mb(pgid: int) -> float | None:
    """Resident memory of every process in the group (a service and its
    children), from /proc; None where there is no /proc."""
    root = Path("/proc")
    if not root.is_dir():
        return None
    total, found = 0, False
    for p in root.iterdir():
        if not p.name.isdigit():
            continue
        try:
            fields = (p / "stat").read_text().rsplit(")", 1)[1].split()
            if int(fields[2]) != pgid:  # state, ppid, pgrp
                continue
            for line in (p / "status").read_text().splitlines():
                if line.startswith("VmRSS:"):
                    total += int(line.split()[1])
                    found = True
        except (OSError, ValueError, IndexError):
            continue
    return round(total / 1024, 1) if found else None


def _peak_mb() -> float | None:
    """The runner container's peak memory (cgroup v2), if readable."""
    try:
        return round(int(CGROUP_PEAK.read_text().strip()) / 1024 / 1024, 1)
    except (OSError, ValueError):
        return None


def _process_report(services: list[dict], procs: list[subprocess.Popen], d: Path) -> list[dict]:
    """Per started service: RSS (while it runs) and its log tail."""
    out = []
    for s, proc in zip(services, procs):
        out.append({"name": s["name"],
                    "rss_mb": _group_rss_mb(proc.pid) if proc.poll() is None else None,
                    "log": _log_tail(d / ".qa" / "logs" / f"{s['name']}.log")})
    return out


def op_screenshot(body: dict) -> dict:
    """The Setup Assistant's proof of a runbook: start its process services
    the way `qa` does (`external`: compose services already up; `login`: sign
    in once), open `/` of `base_service` and save a PNG to `.qa/<out>`, then
    stop the services. Returns the PNG's path relative to the checkout, each
    service's RSS and log tail, and the runner's peak memory; or `infra_error`
    (a service did not start), `login_error`, `shot_error`."""
    d = job_dir(body)
    out = str(body.get("out") or "")
    if not SHOT_RE.fullmatch(out):
        raise ValueError(f"bad screenshot path {out!r}; expected e.g. setup/home.png")
    deadline = time.monotonic() + QA_DEADLINE
    services = _services(body, d)
    base_name = str(body.get("base_service") or "")
    if base_name not in {s["name"] for s in services}:
        raise ValueError(f"base_service {base_name!r} is not one of the services")
    external = _external(body, {s["name"] for s in services})
    login = _login_body(body.get("login"))
    procs: list[subprocess.Popen] = []
    login_tmp: Path | None = None
    try:
        urls = _start_services(services, d, deadline, procs, external)
        if isinstance(urls, str):
            return {"infra_error": urls, "processes": _process_report(services, procs, d),
                    "peak_mb": _peak_mb()}
        base = urls[base_name]
        state = None
        if login is not None:
            login_tmp = child_tmpdir("setup-login-")
            err = _login(d, base, login, deadline, login_tmp)
            if err:
                return {"login_error": err, "processes": _process_report(services, procs, d),
                        "peak_mb": _peak_mb()}
            state = login_tmp / "state.json"
        rel = f".qa/{out}"
        folder = str(Path(rel).parent.as_posix())
        if dropping():
            code, text = run(["mkdir", "-p", "--", folder], d, 60)
            if code != 0:
                return {"infra_error": f"cannot create {folder}: " + text[-300:]}
        else:
            (d / folder).mkdir(parents=True, exist_ok=True)
        env = {"QA_BASE_URL": base, "QA_SHOT_OUT": str(d / rel), "NODE_PATH": _npm_root()}
        if state is not None:
            env["QA_STATE"] = str(state)
        left = int(deadline - time.monotonic())
        code, text = run(["node", SHOT_SCRIPT], d / ".qa", max(30, min(SHOT_TIMEOUT, left)), env)
        report = _process_report(services, procs, d)
        if code != 0:
            return {"shot_error": tail(text, 1500).strip() or f"screenshot exited with {code}",
                    "processes": report, "peak_mb": _peak_mb()}
        return {"ok": True, "screenshot": rel, "processes": report, "peak_mb": _peak_mb()}
    finally:
        for proc in reversed(procs):
            try:
                _stop(proc)
            except Exception:  # noqa: BLE001 - stop the others too
                pass
        if login_tmp is not None:
            remove_child_tmpdir(login_tmp)


def _run_specs(d: Path, spec_dir: Path, base: str, state: Path | None, extra: dict,
               deadline: float) -> dict:
    tmp = child_tmpdir("qa-report-")  # Playwright writes the reports here
    try:
        npm_root = _npm_root()
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
        remove_child_tmpdir(tmp)


MAX_CLEAN_ENTRIES = 200


def _git_out(args: list[str], env: dict, timeout: int = 120) -> tuple[int, str]:
    try:
        p = subprocess.run(["git", *GIT_SAFE, *args], capture_output=True, timeout=timeout,
                           env=env, **child_kw())
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
    # git runs as the child in a dir it owns; nothing in .git is read as root.
    tmp = child_tmpdir("clean-")
    try:
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(tmp),
               "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
               "GIT_NO_REPLACE_OBJECTS": "1", "GIT_OPTIONAL_LOCKS": "0",
               "GIT_TERMINAL_PROMPT": "0",
               # borrow the workspace's objects (the server writes no file for it)
               "GIT_ALTERNATE_OBJECT_DIRECTORIES": str((gd / "objects").resolve())}
        code, out = _git_out(["init", "-q", str(tmp / "w")], env)
        if code != 0:
            return {"infra_error": "git init failed: " + out}
        git_dir = tmp / "w" / ".git"
        head_file = (read_as_child(gd / "HEAD", 4096) or "").strip()
        if head_file.startswith("ref: "):
            ref = head_file[5:]
            if not re.match(r"^refs/heads/[A-Za-z0-9._/-]+$", ref) or ".." in ref:
                return {"infra_error": f"unexpected HEAD {head_file[:100]!r}"}
            ref_path = gd / ref
            if ref_path.is_file():
                head = (read_as_child(ref_path, 4096) or "").strip()
            else:
                head = ""
                packed = gd / "packed-refs"
                for line in (read_as_child(packed) or "").splitlines():
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
        remove_child_tmpdir(tmp)
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


def op_health(body: dict) -> dict:
    """Wait until a compose service (published on kemudi-dind) answers 2xx/3xx
    at `path`: the orchestrator is not on kemudi-dindnet, the runner is."""
    url = dind_url(body.get("url"))
    path = _url_path(body.get("path") or "/", "health path")
    timeout = max(1, min(int(body.get("timeout") or 120), 600))
    t0 = time.monotonic()
    ok = _wait_http(url + path, timeout, ok=lambda st: 200 <= st < 400)
    out = {"ok": ok, "waited": int(time.monotonic() - t0)}
    if not ok:
        out["error"] = f"no 2xx/3xx answer at {path} within {timeout}s"
    return out


def op_reap(body: dict) -> dict:
    """Stop every process service or dev server a QA run left (the
    orchestrator calls this when its worker starts and no job runs). As root,
    also kill every process of the child uid: whatever branch code left behind."""
    stopped = 0
    for proc in list(LIVE):
        try:
            _stop(proc)
            stopped += 1
        except Exception:  # noqa: BLE001 - stop the others too
            LIVE.discard(proc)
    killed = False
    if dropping():
        try:
            # `kill -1` as the child signals every process of its uid (itself too)
            subprocess.run(["sh", "-c", "kill -KILL -1"], capture_output=True, timeout=30,
                           cwd="/", env=child_env(), **child_kw())
            killed = True
        except subprocess.TimeoutExpired:
            pass
    return {"ok": True, "stopped": stopped, "killed_child_uid": killed}


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
       "qa_reset": op_qa_reset, "qa": op_qa, "clean_check": op_clean_check,
       "health": op_health, "reap": op_reap, "screenshot": op_screenshot}


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
