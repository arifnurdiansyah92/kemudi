"""What the runner installs, gates and starts for a story: from the project's
runbook when it has one, else from the repo row's command fields.

Shared by the worker and the merge re-check, so both select the same gates.
"""

import shlex
from pathlib import Path
from typing import Callable

from .config_store import RepoConfig
from .runbook import SERVICE_URL_RE, App, Runbook, changed_exts

# Per command, in seconds (the runner caps at 1800).
TIMEOUTS = {"install": 900, "checks": 900, "build": 600}
# More changed files than this: `{changed:...}` becomes `.` (argv stays small).
MAX_CHANGED_ARGS = 200
_FIELDS = {"install_cmd": "install", "check_cmd": "checks", "build_cmd": "build"}


class Unsupported(Exception):
    """The runbook asks for something this stage cannot run, or a command line
    is broken: a human must fix the settings (the story stops)."""


def command_lines(text: str) -> list[list[str]]:
    """Newline-separated command lines -> argv lists (no shell)."""
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(shlex.split(line))
    return out


def _cmd(argv: list[str], timeout: int) -> dict:
    return {"name": shlex.join(argv), "argv": argv, "timeout": timeout}


def _legacy(rc: RepoConfig, op: str) -> dict:
    """The repo row's subdir and commands (no runbook)."""
    fields = ("install_cmd",) if op == "install" else ("check_cmd", "build_cmd")
    cmds = []
    try:
        for f in fields:
            for argv in command_lines(getattr(rc, f)):
                cmds.append(_cmd(argv, TIMEOUTS[_FIELDS[f]]))
    except ValueError as e:
        raise Unsupported(f"perintah repo {rc.name} tidak valid ({e}); perbaiki di "
                          f"Pengaturan proyek → Agen.") from e
    return {"app": "", "subdir": rc.subdir, "commands": cmds, "env": {}, "skipped": []}


def _apps(rc: RepoConfig, rb: Runbook | None) -> list[App] | None:
    """The runbook's apps of this repo; None means: use the repo row."""
    if rb is None:
        return None
    apps = rb.apps_of(rc.name)
    if not apps:
        return None
    for a in apps:
        if a.run_in:
            raise Unsupported(f"app {a.name} di runbook memakai run_in (perintah di dalam "
                              "service compose); itu baru tersedia di tahap 1b.")
    return apps


def static_env(app: App) -> dict[str, str]:
    """The app's env without values that need a running service: install and
    gates run with no services up."""
    return {k: v for k, v in app.env.items() if not SERVICE_URL_RE.search(v)}


def _split(line: str, rc: RepoConfig, app: App) -> list[str]:
    try:
        return shlex.split(line)
    except ValueError as e:
        raise Unsupported(f"perintah app {app.name} di runbook tidak valid ({e}); perbaiki "
                          "runbook di Pengaturan proyek → Agen.") from e


def install_payloads(rc: RepoConfig, rb: Runbook | None) -> list[dict]:
    apps = _apps(rc, rb)
    if apps is None:
        return [_legacy(rc, "install")]
    return [{"app": a.name, "subdir": a.dir, "env": static_env(a), "skipped": [],
             "commands": [_cmd(_split(line, rc, a), TIMEOUTS["install"]) for line in a.install]}
            for a in apps]


def _inside(path: str, d: str) -> bool:
    return not d or path == d or path.startswith(d + "/")


def select_apps(apps: list[App], changed: list[str]) -> list[App]:
    """Apps whose dir holds a changed file. A change outside every app dir (the
    repo root), or none matching, selects them all."""
    if not changed or any(not any(_inside(f, a.dir) for a in apps) for f in changed):
        return list(apps)
    picked = [a for a in apps if any(_inside(f, a.dir) for f in changed)]
    return picked or list(apps)


def _expand(argv: list[str], app: App, changed: list[str], workdir: Path | None) -> list[str] | None:
    """`{changed:<exts>}` -> the story's changed files in the app dir (relative to
    it as `./<path>`, so a name starting with `-` is never read as an option;
    deleted ones left out); None when a placeholder expands to nothing. Above
    MAX_CHANGED_ARGS files the placeholder becomes `.` (the whole app dir)."""
    out: list[str] = []
    for a in argv:
        exts = changed_exts(a)
        if exts is None:
            out.append(a)
            continue
        files = []
        for f in changed:
            if not _inside(f, app.dir):
                continue
            if exts and not f.lower().endswith(tuple(exts)):
                continue
            if workdir is not None and not (workdir / f).is_file():
                continue  # deleted by the story
            files.append("./" + (f[len(app.dir) + 1:] if app.dir else f))
        if not files:
            return None
        out += sorted(files) if len(files) <= MAX_CHANGED_ARGS else ["."]
    return out


def gate_payloads(rc: RepoConfig, rb: Runbook | None, changed: list[str],
                  workdir: Path | None = None) -> list[dict]:
    apps = _apps(rc, rb)
    if apps is None:
        return [_legacy(rc, "gates")]
    out = []
    for a in select_apps(apps, changed):
        cmds, skipped = [], []
        for field in ("checks", "build"):
            for line in getattr(a, field):
                argv = _split(line, rc, a)
                expanded = _expand(argv, a, changed, workdir)
                if expanded is None:
                    skipped.append(f"{shlex.join(argv)} (no changed files)")
                else:
                    cmds.append(_cmd(expanded, TIMEOUTS[field]))
        out.append({"app": a.name, "subdir": a.dir, "env": static_env(a), "commands": cmds,
                    "skipped": skipped})
    return out


Call = Callable[..., dict]


def _runner_payload(p: dict) -> dict:
    body = {"subdir": p["subdir"], "commands": p["commands"]}
    if p["env"]:
        body["env"] = p["env"]
    return body


def run_install(call: Call, path: str, payloads: list[dict]) -> None:
    for p in payloads:
        call("install", path=path, **_runner_payload(p))


def run_gates(call: Call, path: str, payloads: list[dict]) -> list[dict]:
    """Gate results of every app in order, names prefixed with the app's name;
    stops after the first app with a failing gate. A command whose
    `{changed:...}` matched nothing counts as passed."""
    results: list[dict] = []
    for p in payloads:
        prefix = f"{p['app']}: " if p["app"] else ""
        gates = list(call("gates", path=path, **_runner_payload(p)).get("gates") or []) \
            if p["commands"] else []
        gates += [{"name": s, "ok": True, "output": ""} for s in p["skipped"]]
        results += [{**g, "name": prefix + str(g.get("name", ""))} for g in gates]
        if any(not g.get("ok") for g in gates):
            break
    return results


# --- browser QA from a runbook -----------------------------------------------------


def qa_plan(rb: Runbook) -> dict:
    """The runner's `qa` payload pieces for the runbook's QA service: the
    process services it needs (itself and the services its env refers to, in
    runbook order), the base service, warm-up paths and the app dirs."""
    qa = rb.qa_service()
    if qa is None:
        raise Unsupported("runbook tidak punya bagian qa dengan service yang ada.")
    services = []
    for s in rb.qa_needs():
        if s.kind != "process":
            raise Unsupported(f"service {s.name} di runbook bertipe compose; QA dengan service "
                              "compose baru tersedia di tahap 1b.")
        app = rb.app(s.app)
        try:
            argv = shlex.split(s.command)
        except ValueError as e:
            raise Unsupported(f"perintah service {s.name} tidak valid ({e}).") from e
        env = dict(app.env if app else {})
        if isinstance(s.env, dict):
            env.update(s.env)
        services.append({"name": s.name, "repo": app.repo if app else "",
                         "subdir": app.dir if app else "", "argv": argv, "env": env,
                         "health": s.health, "ready_timeout": s.ready_timeout})
    dirs = sorted({f"{a.repo}/{a.dir}" if a.dir else a.repo for a in rb.apps})
    return {"services": services, "base_service": qa.name,
            "warm": list(rb.qa.routes if rb.qa else []), "app_dirs": dirs}
