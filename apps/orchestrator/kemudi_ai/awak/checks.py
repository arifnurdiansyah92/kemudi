"""What the runner installs, gates and starts for a story: from the project's
runbook when it has one, else from the repo row's command fields.

Shared by the worker and the merge re-check, so both select the same gates
and run QA's services the same way. Compose services (kemudi-svc) are driven
by `Compose`: up, init, seed, health, and always down.
"""

import hashlib
import logging
import shlex
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

from .config_store import RepoConfig
from .runbook import ENV_REF_RE, SERVICE_URL_RE, App, OneShot, Runbook, Service, changed_exts

log = logging.getLogger(__name__)

# Per command, in seconds (the runner caps at 1800).
TIMEOUTS = {"install": 900, "checks": 900, "build": 600}
# More changed files than this: `{changed:...}` becomes `.` (argv stays small).
MAX_CHANGED_ARGS = 200
_FIELDS = {"install_cmd": "install", "check_cmd": "checks", "build_cmd": "build"}


class Unsupported(Exception):
    """The runbook asks for something this stage cannot run, or a command line
    is broken: a human must fix the settings (the story stops)."""


class ServiceFailed(Exception):
    """A compose service, an init/seed command or the QA login did not work.
    `infra`: retry later (kemudi-svc down, a start or health timeout); else a
    human must look (a failing init, missing vault value, the login form).
    `logs`: the redacted output tail for the event and the card."""

    def __init__(self, message: str, logs: str = "", infra: bool = True):
        super().__init__(message)
        self.logs = logs
        self.infra = infra


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
    return apps or None


def static_env(app: App) -> dict[str, str]:
    """The app's env without values that need a running service: install and
    gates run with no services up."""
    return {k: v for k, v in app.env.items() if not SERVICE_URL_RE.search(v)}


def _split(line: str, app: App) -> list[str]:
    try:
        return shlex.split(line)
    except ValueError as e:
        raise Unsupported(f"perintah app {app.name} di runbook tidak valid ({e}); perbaiki "
                          "runbook di Pengaturan proyek → Agen.") from e


def install_payloads(rc: RepoConfig, rb: Runbook | None) -> list[dict]:
    apps = _apps(rc, rb)
    if apps is None:
        return [_legacy(rc, "install")]
    # a run_in app's image build installs its dependencies
    return [_install_payload(a) for a in apps if not a.run_in]


def _install_payload(a: App) -> dict:
    return {"app": a.name, "subdir": a.dir, "env": static_env(a), "skipped": [],
            "commands": [_cmd(_split(line, a), TIMEOUTS["install"]) for line in a.install]}


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
                argv = _split(line, a)
                expanded = _expand(argv, a, changed, workdir)
                if expanded is None:
                    skipped.append(f"{shlex.join(argv)} (no changed files)")
                else:
                    cmds.append(_cmd(expanded, TIMEOUTS[field]))
        p = {"app": a.name, "subdir": a.dir, "env": static_env(a), "commands": cmds,
             "skipped": skipped}
        if a.run_in:
            svc, inner = a.run_in.split(":", 1)
            p["run_in"] = {"service": svc, "compose_service": inner}
        out.append(p)
    return out


Call = Callable[..., dict]


def _runner_payload(p: dict) -> dict:
    body = {"subdir": p["subdir"], "commands": p["commands"]}
    if p["env"]:
        body["env"] = p["env"]
    return body


def missing_dirs(payloads: list[dict], workdir: Path, repo: str) -> None:
    """Unsupported when a runbook app's folder is not in the checkout: the
    runbook names a folder the repo does not have. (The repo row's subdir is
    the runner's to refuse; a refusal stops the story too.)"""
    for p in payloads:
        if p["app"] and p["subdir"] and not (workdir / p["subdir"]).is_dir():
            raise Unsupported(f"app {p['app']} di runbook memakai folder `{p['subdir']}`, yang "
                              f"tidak ada di repo {repo} (branch default); perbaiki runbook di "
                              "Pengaturan proyek → Agen.")


def run_install(call: Call, path: str, payloads: list[dict], workdir: Path | None = None,
                repo: str = "") -> None:
    if workdir is not None:
        missing_dirs(payloads, workdir, repo)
    for p in payloads:
        call("install", path=path, **_runner_payload(p))


def needs_compose(payloads: list[dict]) -> bool:
    return any(p.get("run_in") and p["commands"] for p in payloads)


def run_gates(call: Call, path: str, payloads: list[dict],
              compose: "Compose | None" = None) -> list[dict]:
    """Gate results of every app in order, names prefixed with the app's name;
    stops after the first app with a failing gate. A command whose
    `{changed:...}` matched nothing counts as passed. A `run_in` app's
    commands run in its compose service (`compose`)."""
    results: list[dict] = []
    for p in payloads:
        prefix = f"{p['app']}: " if p["app"] else ""
        if p.get("run_in") and p["commands"]:
            if compose is None:
                raise Unsupported(f"app {p['app']} memakai run_in, tetapi kemudi-svc tidak "
                                  "tersedia untuk menjalankannya.")
            gates = compose.run_in_gates(path, p)
        else:
            gates = list(call("gates", path=path, **_runner_payload(p)).get("gates") or []) \
                if p["commands"] else []
        gates += [{"name": s, "ok": True, "output": ""} for s in p["skipped"]]
        results += [{**g, "name": prefix + str(g.get("name", ""))} for g in gates]
        if any(not g.get("ok") for g in gates):
            break
    return results


# --- browser QA from a runbook -----------------------------------------------------


def _one_shot(rb: Runbook, label: str, o: OneShot) -> dict:
    t = rb.target(o.service)
    if t is None:
        raise Unsupported(f"{label} di runbook memakai service {o.service!r}, yang bukan service "
                          "compose; perbaiki runbook di Pengaturan proyek → Agen.")
    try:
        argv = shlex.split(o.command)
    except ValueError as e:
        raise Unsupported(f"perintah {label} di runbook tidak valid ({e}).") from e
    return {"label": label, "service": t[0].name, "compose_service": t[1], "argv": argv,
            "command": o.command, "env": list(o.env), "timeout": o.timeout}


def qa_plan(rb: Runbook) -> dict:
    """The pieces of a runbook QA run: the process services the runner starts
    (the QA service and what its env refers to, in runbook order), the compose
    services kemudi-svc brings up first, init/seed, the login, the spec's
    vault names, warm-up paths and the app dirs."""
    qa = rb.qa_service()
    if qa is None or qa.kind != "process":
        raise Unsupported("service QA di runbook harus service process (dev server app).")
    services = []
    for s in rb.qa_needs():
        if s.kind != "process":
            continue
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
    one_shots = [_one_shot(rb, label, o) for label, o in rb.one_shots()]
    dirs = sorted({f"{a.repo}/{a.dir}" if a.dir else a.repo for a in rb.apps})
    assert rb.qa is not None
    login = rb.qa.login.model_dump() if rb.qa.login else None
    return {"services": services, "base_service": qa.name,
            "warm": list(rb.qa.routes), "app_dirs": dirs,
            "compose": [s.name for s in rb.qa_compose()],
            "init": [o for o in one_shots if o["label"] == "init"],
            "seed": next((o for o in one_shots if o["label"] == "seed"), None),
            "login": login, "qa_env": list(rb.qa.env)}


def qa_repos(rb: Runbook) -> list[str]:
    """The repos QA runs from: the process services' apps' repos and the
    compose services' repos, in order."""
    out: list[str] = []
    for s in [*rb.qa_needs(), *rb.qa_compose()]:
        app = rb.app(s.app) if s.kind == "process" else None
        repo = app.repo if app is not None else (s.repo if s.kind == "compose" else "")
        if repo and repo not in out:
            out.append(repo)
    return out


def qa_install_payloads(rb: Runbook, repo: str) -> list[dict]:
    """Install payloads of the apps of `repo` that back a QA service."""
    names = {s.app for s in rb.qa_needs() if s.kind == "process"}
    return [_install_payload(a) for a in rb.apps_of(repo) if a.name in names and not a.run_in]


def _required(rb: Runbook) -> set[str]:
    return {e.name for e in rb.env if e.required}


def vault_env(rb: Runbook, names: list[str], vault: dict[str, str], where: str) -> dict[str, str]:
    """The vault values of `names`; a required one without a value stops the
    run (a human fills it in), an optional one is left out."""
    missing = [n for n in names if n not in vault and n in _required(rb)]
    if missing:
        raise ServiceFailed(f"vault proyek belum punya nilai untuk {', '.join(missing)} "
                            f"({where}); isi di Pengaturan proyek → Agen → Env & secrets.",
                            infra=False)
    return {n: vault[n] for n in names if n in vault}


def login_payload(rb: Runbook, vault: dict[str, str]) -> dict | None:
    """qa.login with `{env.NAME}` resolved: the runner's `login` body."""
    lg = rb.qa.login if rb.qa else None
    if lg is None:
        return None
    missing = sorted({n for v in lg.fields.values() for n in ENV_REF_RE.findall(v)
                      if n not in vault})
    if missing:
        raise ServiceFailed(f"vault proyek belum punya nilai untuk {', '.join(missing)} "
                            "(qa.login); isi di Pengaturan proyek → Agen → Env & secrets.",
                            infra=False)
    fields = [{"selector": sel, "value": ENV_REF_RE.sub(lambda m: vault[m.group(1)], v)}
              for sel, v in lg.fields.items()]
    return {"path": lg.path, "fields": fields, "submit": lg.submit,
            "success_url": lg.success_url}


MAX_PROJECT = 63


def compose_projects(rb: Runbook | None, slug: str, tag: str) -> dict[str, str]:
    """Compose project name per compose service of the runbook: `<slug>-<tag>`
    (tag `us<ref>` or `setup`), plus `-<service>` when the runbook has more
    than one compose service; at most 63 characters (a hash keeps long slugs
    apart)."""
    names = [s.name for s in rb.services if s.kind == "compose"] if rb else []
    out = {}
    for n in names:
        full = f"{slug}-{tag}" + (f"-{n}" if len(names) > 1 else "")
        if len(full) > MAX_PROJECT:
            h = hashlib.sha256(full.encode()).hexdigest()[:8]
            full = full[:MAX_PROJECT - 9].rstrip("-") + "-" + h
        out[n] = full
    return out


class Compose:
    """A story's compose services through kemudi-svc.

    `svc(op, **body)` and `runner(op, **body)` raise on transport problems
    (the worker maps them to Infra/Unsupported/ServiceFailed). `path_of(repo)`
    is the runner/svc path of that repo's checkout in the story folder.
    Every `svc_up` is matched by a `svc_down`, also on failure."""

    def __init__(self, rb: Runbook, svc: Call, runner: Call, projects: dict[str, str],
                 path_of: Callable[[str], str], vault: dict[str, str], redact: list[str],
                 event: Callable[[str, dict], None] = lambda kind, detail: None):
        self.rb, self.svc, self.runner = rb, svc, runner
        self.projects, self.path_of = projects, path_of
        self.vault, self.redact, self.event = vault, redact, event

    def _service(self, name: str) -> Service:
        s = self.rb.service(name)
        if s is None or s.kind != "compose" or name not in self.projects:
            raise Unsupported(f"service {name!r} di runbook bukan service compose.")
        return s

    def up(self, s: Service, path: str, up: list[str] | None = None, wait: bool = True,
           expose: bool = True) -> dict:
        body: dict = {"path": path, "project": self.projects[s.name], "file": s.file,
                      "services": list(s.compose_services),
                      "env": vault_env(self.rb, s.env if isinstance(s.env, list) else [],
                                       self.vault, f"services.{s.name}"),
                      "redact": self.redact}
        if s.environment:
            body["environment"] = {c: dict(v) for c, v in s.environment.items()}
        if s.expose and expose:
            body["expose"] = s.expose
        if up is not None:
            body["up"] = up
        if not wait:
            body["wait"] = False
        res = self.svc("svc_up", **body)
        self.event("compose_up", {"service": s.name, "project": self.projects[s.name],
                                  "ok": bool(res.get("ok")), "stage": res.get("stage", ""),
                                  "built": res.get("built") or [],
                                  "logs_tail": str(res.get("logs_tail") or "")[-3000:]})
        return res

    def down(self, project: str) -> None:
        try:
            self.svc("svc_down", project=project)
        except Exception as e:  # noqa: BLE001 - the worker's start sweep catches leftovers
            log.warning("awak: svc_down %s failed: %s", project, e)
            self.event("compose_down_failed", {"project": project, "error": str(e)[:300]})

    def exec(self, project: str, compose_service: str, argv: list[str], env: dict[str, str],
             timeout: int) -> dict:
        return self.svc("svc_exec", project=project, service=compose_service, argv=argv,
                        env=env, timeout=timeout, redact=self.redact)

    def _start_failed(self, s: Service, res: dict) -> ServiceFailed:
        stage = res.get("stage") or "up"
        return ServiceFailed(f"service compose {s.name} gagal start ({stage}): "
                             f"{str(res.get('error') or '')[:300]}",
                             logs=str(res.get("logs_tail") or ""), infra=True)

    def _one_shot(self, o: dict) -> None:
        project = self.projects[o["service"]]
        env = vault_env(self.rb, o["env"], self.vault, o["label"])
        res = self.exec(project, o["compose_service"], o["argv"], env, o["timeout"])
        code = res.get("exit")
        self.event(o["label"], {"service": f"{o['service']}:{o['compose_service']}",
                                "command": o["command"], "exit": code})
        if code == 124:
            raise ServiceFailed(f"{o['label']} `{o['command']}` melewati batas waktu "
                                f"{o['timeout']} detik.", logs=str(res.get("output") or ""))
        if code != 0:
            raise ServiceFailed(f"{o['label']} `{o['command']}` di {o['service']}:"
                                f"{o['compose_service']} gagal (exit {code}).",
                                logs=str(res.get("output") or ""), infra=False)

    @contextmanager
    def for_qa(self, plan: dict) -> Iterator[dict[str, str]]:
        """Bring up QA's compose services, run init, then seed, wait for each
        exposed service's health through the runner; yields name -> URL (as
        the runner reaches it). Every started project goes down afterwards."""
        started: list[str] = []
        try:
            urls: dict[str, str] = {}
            for name in plan["compose"]:
                s = self._service(name)
                started.append(self.projects[name])  # a failed start leaves things too
                res = self.up(s, self.path_of(s.repo))
                if not res.get("ok"):
                    raise self._start_failed(s, res)
                if s.expose:
                    if not res.get("url"):
                        raise ServiceFailed(f"service compose {s.name}: {s.expose} tidak "
                                            "terpublikasi.", infra=False)
                    urls[name] = str(res["url"])
            for o in plan["init"]:
                self._one_shot(o)
            if plan.get("seed"):
                self._one_shot(plan["seed"])
            for name, url in urls.items():
                s = self._service(name)
                res = self.runner("health", url=url, path=s.health, timeout=s.ready_timeout)
                if not res.get("ok"):
                    logs = ""
                    try:
                        logs = str(self.svc("svc_logs", project=self.projects[name],
                                            service=s.expose_service(), tail=80,
                                            redact=self.redact).get("logs") or "")
                    except Exception as e:  # noqa: BLE001 - the health failure is the news
                        logs = f"(log tidak bisa diambil: {e})"
                    raise ServiceFailed(f"service compose {name} tidak sehat di {s.health} "
                                        f"setelah {s.ready_timeout} detik "
                                        f"({str(res.get('error') or '')[:200]}).", logs=logs)
            yield urls
        finally:
            for project in reversed(started):
                self.down(project)

    def run_in_gates(self, path: str, p: dict) -> list[dict]:
        """A run_in app's checks in its compose service: build the image from the
        story checkout, start only the other listed services (dependencies),
        run each command with `compose run --rm`, then down."""
        s = self._service(p["run_in"]["service"])
        inner = p["run_in"]["compose_service"]
        project = self.projects[s.name]
        deps = [c for c in s.compose_services if c != inner]
        try:
            # `up: []` builds only; the app service itself is never started here
            res = self.up(s, path, up=deps, expose=False)
            if not res.get("ok"):
                if res.get("stage") == "build":
                    # the story's own code does not build: a failed gate
                    return [{"name": f"build {s.name}:{inner}", "ok": False,
                             "output": str(res.get("logs_tail") or res.get("error") or "")}]
                raise self._start_failed(s, res)
            gates: list[dict] = []
            for i, c in enumerate(p["commands"]):
                r = self.exec(project, inner, c["argv"], p["env"], c["timeout"])
                if r.get("exit") == 124:
                    raise ServiceFailed(f"{c['name']} (di {s.name}:{inner}) melewati batas "
                                        f"waktu {c['timeout']} detik.",
                                        logs=str(r.get("output") or ""))
                ok = r.get("exit") == 0
                gates.append({"name": c["name"], "ok": ok, "output": str(r.get("output") or "")})
                if not ok and i == 0:
                    break  # like the runner: the first gate's errors repeat in later ones
            return gates
        finally:
            self.down(project)
