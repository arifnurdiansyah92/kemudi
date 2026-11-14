"""kemudi-svc: the only client of the sandboxed Docker daemon (kemudi-dind).
Python stdlib only.

Starts a project's compose services for QA and `run_in` gates. It never runs
branch code itself: builds and containers run inside kemudi-dind, which it
reaches over a unix socket no other container mounts. The orchestrator calls
it over kemudi-svcnet (internal) with KEMUDI_SVC_KEY; every op is a JSON POST
and every reply is JSON.

`path` names one checkout under WORKSPACE (read-only here), as in
kemudi-runner: `<slug>/us-<ref>/<repo>` or `<slug>/setup/<repo>`. `project`
is the compose project name (`<slug>-us<ref>`, `<slug>-setup`). `redact` is
an optional list of values replaced by `[redacted]` in returned output (svc_up
and svc_exec add their own `env` values).

POST /svc_up    {path, project, services, file?, expose?, env?, up?, wait?, redact?}
    file: compose file relative to the checkout (default docker-compose.yml).
    services: the services wanted; their depends_on closure comes along.
    expose: "<service>:<port>", published on a random port of kemudi-dind.
    env: vault values, the only variables compose interpolates with.
    up: services to start (default all of the closure; with their deps).
    wait: `up --wait` for health (default true).
    -> {ok: true, project, services, built, url?, logs_tail}
    -> {ok: false, stage: "build"|"up", error, logs_tail}
POST /svc_exec  {project, service, argv, env?, timeout?, redact?}
    `compose run --rm --no-deps -T` in the service's image (timeout <= 1500 s)
    -> {ok, exit, output}
POST /svc_logs  {project, service?, tail?, redact?}       -> {ok, logs}
POST /svc_stats {project}
    -> {ok, stats: [{name, service, cpu_pct, mem_bytes, mem_limit_bytes, mem_pct, pids}]}
POST /svc_down  {project}                                 -> {ok, output}
POST /svc_sweep {keep: [project]}
    downs every labelled project not in keep, removes their images, prunes
    dangling images and the build cache over 10 GB -> {ok, removed, images_removed}

svc_up, step by step (sanitize.py has the rules):
1. the compose file is checked for keys that read other files, then
   `docker compose config --no-interpolate --format json` reads it as uid
   10000 (which cannot read /run/svc), env cleared, `--env-file /dev/null`;
2. `sanitize.reduce`: selected services + depends_on closure, allowlist,
   build paths inside the checkout;
3. the reduced file is interpolated by compose with only the vault env file
   (`/run/svc/<project>/vault.env`, deleted right after);
4. `sanitize.rewrite` -> `/run/svc/<project>/compose.json` (0600), kept until
   svc_down;
5. `compose build` (900 s), `compose up -d --wait` (300 s), `compose port`.

Every docker call runs with a cleared environment (PATH, HOME, DOCKER_HOST),
in its own process group, killed on its deadline.
"""

import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sanitize  # noqa: E402
from sanitize import Refused, redact  # noqa: E402,F401

WORKSPACE = Path(os.environ.get("SVC_WORKSPACE", "/workspace"))
RUN_DIR = Path(os.environ.get("SVC_RUN_DIR", "/run/svc"))
KEY = os.environ.get("KEMUDI_SVC_KEY", "")
PORT = int(os.environ.get("SVC_PORT", "8810"))
DOCKER = os.environ.get("SVC_DOCKER", "docker")
DOCKER_HOST = os.environ.get("DOCKER_HOST", "unix:///run/dind/docker.sock")
# Where the runner reaches published ports (kemudi-dindnet).
DIND_HOST = os.environ.get("SVC_DIND_HOST", "kemudi-dind")
CHILD_UID = int(os.environ.get("SVC_CHILD_UID", "10000"))

BUILD_TIMEOUT = 900
UP_TIMEOUT = 300
CONFIG_TIMEOUT = 60
EXEC_MAX_TIMEOUT = 1500
LOG_TAIL_LINES = 200
TAIL_CHARS = 8000
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
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


# --- running docker ------------------------------------------------------------

def tail(text: str, n: int = TAIL_CHARS) -> str:
    return ANSI.sub("", text)[-n:]


def dropping() -> bool:
    """Whether the compose file's first read switches to CHILD_UID (as root)."""
    return os.name == "posix" and os.geteuid() == 0


def base_env(daemon: bool) -> dict[str, str]:
    """The cleared environment of every docker call: nothing of svc's own (no
    key), so compose interpolates only with the env file it is given."""
    if os.name == "nt":  # local tests only
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith("KEMUDI_")}
    else:
        env = {"PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
               "HOME": os.environ.get("HOME") or "/root"}
    if daemon:
        env["DOCKER_HOST"] = DOCKER_HOST
    else:
        env.pop("DOCKER_HOST", None)
    return env


def docker(args: list[str], timeout: float, *, env: dict | None = None, as_child: bool = False,
           daemon: bool = True) -> tuple[int, str, str]:
    """Run `docker <args>`; (exit code, stdout, stderr). The whole process
    group dies on the deadline (exit 124)."""
    full_env = {**base_env(daemon), **(env or {})}
    kw: dict = {}
    if os.name == "posix":
        kw["start_new_session"] = True
        kw["cwd"] = "/"
        if as_child and dropping():
            kw.update(user=CHILD_UID, group=CHILD_UID, extra_groups=[])
            full_env["HOME"] = "/tmp"
    p = subprocess.Popen([DOCKER, *args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, env=full_env, **kw)
    try:
        out, err = p.communicate(timeout=timeout)
        code = p.returncode
    except subprocess.TimeoutExpired:
        try:
            if os.name == "posix":
                os.killpg(p.pid, signal.SIGKILL)
            else:
                p.kill()
        except OSError:
            pass
        out, err = p.communicate()
        err += f"\n[timed out after {int(timeout)}s]".encode()
        code = 124
    return code, out.decode(errors="replace"), err.decode(errors="replace")


def project_dir(project: str) -> Path:
    return RUN_DIR / project


def compose_json(project: str) -> Path:
    return project_dir(project) / "compose.json"


def write_private(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def compose_base(project: str, with_file: bool = True) -> list[str]:
    args = ["compose", "-p", project, "--env-file", os.devnull]
    if with_file:
        args += ["-f", str(compose_json(project))]
    return args


def started_project(body: dict) -> tuple[str, dict]:
    """The request's project and its compose.json (svc_up wrote it)."""
    project = sanitize.project_name(body.get("project"))
    try:
        doc = json.loads(compose_json(project).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise Refused(f"project {project!r} is not up (no svc_up)") from None
    return project, doc


def redact_values(body: dict) -> list[str]:
    raw = body.get("redact") or []
    if not (isinstance(raw, list) and all(isinstance(v, str) for v in raw)):
        raise Refused("redact must be a list of strings")
    return raw


def compose_logs(project: str, service: str | None, lines: int) -> str:
    args = [*compose_base(project), "logs", "--no-color", "--tail", str(lines)]
    if service:
        args.append(service)
    _, out, err = docker(args, 120)
    return out + err


# --- operations -------------------------------------------------------------

def op_svc_up(body: dict) -> dict:
    d = job_dir(body)
    project = sanitize.project_name(body.get("project"))
    file = sanitize.compose_file(d, body.get("file"))
    selected = sanitize.service_names(body.get("services"))
    expose = sanitize.parse_expose(body.get("expose"))
    env = sanitize.request_env(body.get("env"))
    up_only = sanitize.service_names(body["up"], "up") if body.get("up") is not None else None
    wait = body.get("wait", True) is not False
    hide = redact_values(body) + list(env.values())

    # 1. read as compose sees it, without interpolation, as an unprivileged uid
    try:
        with open(file, "rb") as f:
            text = f.read(2_000_000).decode(errors="replace")
    except OSError as e:
        raise Refused(f"cannot read the compose file: {e.strerror}") from None
    sanitize.precheck_text(text)
    code, out, err = docker(
        ["compose", "-p", project, "-f", str(file), "--project-directory", str(file.parent),
         "--env-file", os.devnull, "config", "--no-interpolate", "--format", "json"],
        CONFIG_TIMEOUT, as_child=True, daemon=False)
    if code != 0:
        raise Refused(f"docker compose config failed: {tail(redact(err or out, hide), 2000)}")
    try:
        doc = json.loads(out)
    except ValueError:
        raise Refused("docker compose config gave no JSON") from None

    # 2. reduce and check
    reduced = sanitize.reduce(doc, selected, d)
    keep = list(reduced["services"])
    if expose and expose[0] not in keep:
        raise Refused(f"expose: no service {expose[0]!r} among {keep}")
    for s in up_only or []:
        if s not in keep:
            raise Refused(f"up: no service {s!r} among {keep}")

    # 3. interpolate with the vault values only
    pd = project_dir(project)
    pd.mkdir(mode=0o700, exist_ok=True)
    reduced_path, env_path = pd / "reduced.json", pd / "vault.env"
    write_private(reduced_path, json.dumps(reduced))
    write_private(env_path, sanitize.env_file_text(env))
    try:
        code, out, err = docker(
            ["compose", "-p", project, "-f", str(reduced_path), "--project-directory",
             str(file.parent), "--env-file", str(env_path), "config", "--format", "json"],
            CONFIG_TIMEOUT, daemon=False)
    finally:
        for p in (env_path, reduced_path):
            p.unlink(missing_ok=True)
    if code != 0:
        raise Refused(f"docker compose config failed: {tail(redact(err or out, hide), 2000)}")

    # 4. rewrite
    final = sanitize.rewrite(json.loads(out), project, expose)
    write_private(compose_json(project), json.dumps(final, indent=1))
    built = [n for n, s in final["services"].items() if "build" in s]
    base = compose_base(project)

    # 5. build, start
    if built:
        code, out, err = docker([*base, "build", *built], BUILD_TIMEOUT)
        if code != 0:
            return {"ok": False, "stage": "build", "error": f"build failed (exit {code})",
                    "logs_tail": tail(redact(out + err, hide))}
    up = [*base, "up", "-d", "--no-build", "--pull", "missing", "--remove-orphans"]
    if wait:
        up += ["--wait", "--wait-timeout", str(UP_TIMEOUT)]
    code, out, err = docker([*up, *(up_only or keep)], UP_TIMEOUT + 300)
    if code != 0:
        return {"ok": False, "stage": "up", "error": tail(redact(err or out, hide), 2000),
                "logs_tail": tail(redact(compose_logs(project, None, LOG_TAIL_LINES), hide))}
    url = None
    if expose:
        code, out, err = docker([*base, "port", expose[0], str(expose[1])], 60)
        port = out.strip().rsplit(":", 1)[-1]
        if code != 0 or not port.isdigit():
            return {"ok": False, "stage": "up",
                    "error": f"{expose[0]}:{expose[1]} is not published: "
                             f"{tail(redact(err or out, hide), 500)}",
                    "logs_tail": tail(redact(compose_logs(project, None, LOG_TAIL_LINES), hide))}
        url = f"http://{DIND_HOST}:{port}"
    return {"ok": True, "project": project, "services": keep, "built": built, "url": url,
            "logs_tail": tail(redact(compose_logs(project, None, 50), hide))}


def op_svc_exec(body: dict) -> dict:
    project, doc = started_project(body)
    service = str(body.get("service") or "")
    if service not in (doc.get("services") or {}):
        raise Refused(f"no service {service!r} in project {project!r}")
    argv = body.get("argv")
    if not (isinstance(argv, list) and argv and all(isinstance(a, str) for a in argv)):
        raise Refused("argv must be a non-empty list of strings")
    env = sanitize.request_env(body.get("env"))
    timeout = min(int(body.get("timeout") or 600), EXEC_MAX_TIMEOUT)
    if timeout <= 0:
        raise Refused("timeout must be positive")
    hide = redact_values(body) + list(env.values())
    name = f"{project}-run-{secrets.token_hex(4)}"
    args = [*compose_base(project), "run", "--rm", "--no-deps", "-T", "--name", name]
    for k in env:  # the value comes from the docker CLI's environment, not argv
        args += ["-e", k]
    code, out, err = docker([*args, service, *argv], timeout, env=env)
    if code == 124:
        docker(["rm", "-f", name], 60)
    return {"ok": code == 0, "exit": code, "output": tail(redact(out + err, hide))}


def op_svc_logs(body: dict) -> dict:
    project, doc = started_project(body)
    service = body.get("service") or None
    if service is not None and service not in (doc.get("services") or {}):
        raise Refused(f"no service {service!r} in project {project!r}")
    lines = max(1, min(int(body.get("tail") or LOG_TAIL_LINES), 2000))
    logs = compose_logs(project, service, lines)
    return {"ok": True, "logs": tail(redact(logs, redact_values(body)), 64_000)}


_SIZE = re.compile(r"([\d.]+)\s*([KMGT]?i?B)", re.I)
_SIZE_UNITS = {"b": 1, "kb": 1000, "mb": 1000 ** 2, "gb": 1000 ** 3, "tb": 1000 ** 4,
               "kib": 1024, "mib": 1024 ** 2, "gib": 1024 ** 3, "tib": 1024 ** 4}


def parse_size(text: str) -> int | None:
    m = _SIZE.search(text or "")
    if not m:
        return None
    return int(float(m.group(1)) * _SIZE_UNITS.get(m.group(2).lower(), 1))


def parse_pct(text: str) -> float | None:
    try:
        return float(str(text).strip().rstrip("%"))
    except ValueError:
        return None


def op_svc_stats(body: dict) -> dict:
    project = sanitize.project_name(body.get("project"))
    code, out, err = docker(["ps", "--filter", f"label={sanitize.LABEL}={project}", "--format",
                             '{{.Names}}\t{{.Label "com.docker.compose.service"}}'], 60)
    if code != 0:
        raise RuntimeError(tail(err, 500))
    names = dict(line.split("\t", 1) for line in out.splitlines() if "\t" in line)
    if not names:
        return {"ok": True, "stats": []}
    code, out, err = docker(["stats", "--no-stream", "--format", "{{json .}}", *names], 60)
    if code != 0:
        raise RuntimeError(tail(err, 500))
    stats = []
    for line in out.splitlines():
        try:
            s = json.loads(line)
        except ValueError:
            continue
        used, _, limit = str(s.get("MemUsage") or "").partition("/")
        stats.append({"name": s.get("Name"), "service": names.get(s.get("Name"), ""),
                      "cpu_pct": parse_pct(s.get("CPUPerc", "")),
                      "mem_bytes": parse_size(used), "mem_limit_bytes": parse_size(limit),
                      "mem_pct": parse_pct(s.get("MemPerc", "")),
                      "pids": int(s["PIDs"]) if str(s.get("PIDs", "")).isdigit() else None})
    return {"ok": True, "stats": stats}


def down(project: str) -> tuple[bool, str]:
    """`compose down -v` (with svc's file when it still has it), then any
    volume or network of the project compose left behind, then its files."""
    has_file = compose_json(project).is_file()
    code, out, err = docker([*compose_base(project, has_file), "down", "-v", "--remove-orphans",
                             "-t", "10"], 300)
    for kind in ("volume", "network"):
        for label in (f"com.docker.compose.project={project}", f"{sanitize.LABEL}={project}"):
            _, ids, _ = docker([kind, "ls", "-q", "--filter", f"label={label}"], 60)
            if ids.split():
                docker([kind, "rm", *([] if kind == "network" else ["-f"]), *ids.split()], 120)
    shutil.rmtree(project_dir(project), ignore_errors=True)
    return code == 0, tail(out + err, 4000)


def op_svc_down(body: dict) -> dict:
    ok, output = down(sanitize.project_name(body.get("project")))
    return {"ok": ok, "output": output}


def labelled_projects() -> set[str]:
    found: set[str] = set()
    for args in (["ps", "-a"], ["volume", "ls"]):
        code, out, _ = docker([*args, "--filter", f"label={sanitize.LABEL}", "--format",
                               '{{.Label "' + sanitize.LABEL + '"}}'], 60)
        if code != 0:
            raise RuntimeError(f"docker {args[0]} failed")
        found |= {p for p in out.split() if sanitize.PROJECT_RE.fullmatch(p)}
    if RUN_DIR.is_dir():
        found |= {p.name for p in RUN_DIR.iterdir()
                  if p.is_dir() and sanitize.PROJECT_RE.fullmatch(p.name)}
    return found


def op_svc_sweep(body: dict) -> dict:
    raw = body.get("keep") or []
    if not (isinstance(raw, list) and all(isinstance(p, str) for p in raw)):
        raise Refused("keep must be a list of project names")
    keep = {sanitize.project_name(p) for p in raw}
    removed = sorted(labelled_projects() - keep)
    for project in removed:
        down(project)
    images_removed = 0
    _, ids, _ = docker(["image", "ls", "-q", "--filter", f"label={sanitize.LABEL}"], 60)
    ids = list(dict.fromkeys(ids.split()))
    if ids:
        _, out, _ = docker(["image", "inspect", "--format",
                            '{{.Id}} {{index .Config.Labels "' + sanitize.LABEL + '"}}', *ids], 60)
        for line in out.splitlines():
            image_id, _, project = line.partition(" ")
            if project.strip() not in keep:
                # in use by a container: docker refuses, and the image stays
                code, _, _ = docker(["image", "rm", image_id], 120)
                images_removed += code == 0
    docker(["image", "prune", "-f"], 300)
    docker(["builder", "prune", "-f", "--keep-storage", "10GB"], 600)
    return {"ok": True, "removed": removed, "images_removed": images_removed}


OPS: dict = {"svc_up": op_svc_up, "svc_exec": op_svc_exec, "svc_logs": op_svc_logs,
             "svc_stats": op_svc_stats, "svc_down": op_svc_down, "svc_sweep": op_svc_sweep}


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
