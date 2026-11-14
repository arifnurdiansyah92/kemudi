"""A project's runbook: how to install, check, run and QA its apps.

One JSON document per project (`awak_runbooks`), saved by an admin and used
only from the DB copy.

- `process` services run in kemudi-runner (an app's dev server); `compose`
  services are started by kemudi-svc in the sandboxed Docker daemon from the
  repo's compose file (only the listed services and their dependencies).
- `run_in: "<compose service>:<service in its file>"` runs an app's checks
  in that service's image (built from the story checkout).
- `init` (one-shot commands after the compose services are up) and `seed`
  run the same way before QA.
- `{services.<name>.url}` in an app's or process service's env is the base
  URL of that service; `{env.NAME}` (a vault value) is only allowed in
  `qa.login.fields`. Compose services, init/seed and `qa.env` name vault
  values; their values never appear in the runbook.
"""

import re
import shlex
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy.orm import Session

from ..store import AwakRunbook

# Programs a command may start (argv[0], a bare name looked up on PATH). The
# runner keeps its own copy (infra/runner/runner.py); a test checks they match.
ALLOWED_PROGRAMS = frozenset({"pnpm", "npm", "npx", "yarn", "node", "python", "uv", "pytest",
                              "make", "go", "cargo"})
# Env names a runbook may not set: they would steer the runner, git, docker or
# the toolchain itself. Same copy in the runner.
BLOCKED_ENV_PREFIXES = ("KEMUDI_", "DOCKER_", "COMPOSE_", "GIT_")
BLOCKED_ENV_NAMES = frozenset({"PATH", "LD_PRELOAD", "LD_LIBRARY_PATH", "NODE_OPTIONS",
                               "PYTHONPATH", "HOME"})

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
ENV_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]{0,99}$")
SERVICE_URL_RE = re.compile(r"\{services\.([^.{}]*)\.url\}")
ENV_REF_RE = re.compile(r"\{env\.([^{}]*)\}")
COMPOSE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
EXPOSE_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]{0,99}):(\d{1,5})$")
# Env names the runner sets for the Playwright run itself (qa.env may not).
QA_RESERVED_ENV = frozenset({"QA_SPEC_DIR", "QA_OUTPUT_DIR", "QA_REPORT", "QA_BASE_URL",
                             "QA_STATE", "QA_LOGIN", "QA_STATE_OUT", "NODE_PATH"})
# `{changed:.ts,.tsx}`: the story's changed files in the app dir, as a whole
# argv element; an empty extension list means every changed file.
CHANGED_RE = re.compile(r"^\{changed:((?:\.[A-Za-z0-9]{1,10}(?:,\.[A-Za-z0-9]{1,10})*)?)\}$")
PORT_TOKEN = "{port}"
MAX_COMMANDS = 20


def env_name_problem(name: str) -> str | None:
    if not ENV_NAME_RE.fullmatch(name):
        return f"env name {name!r} must match [A-Z_][A-Z0-9_]*"
    if name in BLOCKED_ENV_NAMES or name.startswith(BLOCKED_ENV_PREFIXES):
        return f"env name {name!r} is reserved"
    return None


def changed_exts(arg: str) -> list[str] | None:
    """The extensions of a `{changed:...}` argv element, or None if it is not one."""
    m = CHANGED_RE.fullmatch(arg)
    if m is None:
        return None
    return [e.lower() for e in m.group(1).split(",") if e]


def rel_path_problem(value: str, what: str) -> str | None:
    """A path inside a repo: relative, `/`-separated, no `..`."""
    if not value:
        return None
    if value.startswith(("/", "\\")) or "\\" in value or ":" in value:
        return f"{what} {value!r} must be a relative path with '/'"
    if any(p in ("", ".", "..") for p in value.split("/")):
        return f"{what} {value!r} must not contain '..', '.' or empty parts"
    return None


def command_problem(line: str, allow_changed: bool = False, allow_port: bool = False,
                    check_program: bool = True) -> str | None:
    try:
        argv = shlex.split(line)
    except ValueError as e:
        return f"cannot parse {line!r}: {e}"
    if not argv:
        return "empty command"
    if check_program and argv[0] not in ALLOWED_PROGRAMS:
        return (f"{argv[0]!r} is not an allowed program; use one of "
                f"{', '.join(sorted(ALLOWED_PROGRAMS))} (no shell)")
    for a in argv:
        if "{changed" in a:
            if not allow_changed:
                return f"{{changed:...}} is only allowed in checks and build ({line!r})"
            if changed_exts(a) is None:
                return (f"{a!r} must be a whole argument like {{changed:.ts,.tsx}} "
                        "(extensions start with '.', comma-separated, or none)")
        if PORT_TOKEN in a and not allow_port:
            return f"{{port}} is only allowed in a process service command ({line!r})"
    return None


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class App(_Strict):
    name: str
    repo: str
    dir: str = ""
    install: list[str] = Field(default_factory=list, max_length=MAX_COMMANDS)
    checks: list[str] = Field(default_factory=list, max_length=MAX_COMMANDS)
    build: list[str] = Field(default_factory=list, max_length=MAX_COMMANDS)
    env: dict[str, str] = Field(default_factory=dict)
    # "<service>:<compose service>": checks and build run in that compose
    # service's image (built from the story checkout), in its working_dir.
    run_in: str = ""
    # Ignored files the install or build writes (globs, relative to `dir`),
    # e.g. a generated CSS bundle; the clean check accepts them.
    generated: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("dir")
    @classmethod
    def _dir(cls, v: str) -> str:
        return v.strip().rstrip("/")  # a leading '/' is reported by _problems

    @field_validator("generated")
    @classmethod
    def _generated(cls, v: list[str]) -> list[str]:
        # "out/" and "out" mean the same; a leading '/' is reported by _problems
        return [g.strip().rstrip("/") or g for g in v]


class Service(_Strict):
    name: str
    kind: Literal["process", "compose"]
    # process: a long-running command of an app, `{port}` allocated by the runner
    app: str = ""
    command: str = ""
    # compose: the repo's compose file, the services wanted (their depends_on
    # come along) and the one port the runner reaches ("<service>:<port>")
    repo: str = ""
    file: str = ""
    compose_services: list[str] = Field(default_factory=list, max_length=20)
    expose: str = ""
    health: str = "/"
    ready_timeout: int = Field(120, ge=1, le=600)
    # vault names (compose), or name -> value for a process service
    env: list[str] | dict[str, str] = Field(default_factory=dict)
    # compose: literal values that replace a compose service's environment
    # entries (a production compose run for QA: DATABASE_URL, FLASK_ENV...).
    # Not for secrets: those are vault names in `env`, interpolated by compose.
    environment: dict[str, dict[str, str]] = Field(default_factory=dict)

    def expose_service(self) -> str:
        return self.expose.split(":", 1)[0] if self.expose else ""


class EnvVar(_Strict):
    name: str
    secret: bool = False
    required: bool = False
    description: str = Field("", max_length=500)


class OneShot(_Strict):
    """A command run once in a compose service's image (`init`, `seed`).
    `service`: "<compose service of the runbook>" (its exposed service) or
    "<compose service of the runbook>:<service in its file>"."""

    service: str
    command: str
    env: list[str] = Field(default_factory=list, max_length=20)  # vault names
    timeout: int = Field(600, ge=1, le=1500)


Seed = OneShot  # older name


class Login(_Strict):
    """A form login the runner performs once before the spec runs (the specs
    start logged in). Field values may use `{env.NAME}` (vault values)."""

    path: str
    fields: dict[str, str] = Field(min_length=1, max_length=10)  # CSS selector -> value
    submit: str
    # Path prefix the browser reaches after a good login; default: any page
    # other than the login path.
    success_url: str = ""


class Qa(_Strict):
    service: str
    env: list[str] = Field(default_factory=list, max_length=20)  # vault names for the spec
    # paths to load once before the spec runs (dev servers compile on first hit)
    routes: list[str] = Field(default_factory=list, max_length=10)
    login: Login | None = None


class Runbook(_Strict):
    apps: list[App] = Field(default_factory=list, max_length=20)
    services: list[Service] = Field(default_factory=list, max_length=20)
    env: list[EnvVar] = Field(default_factory=list, max_length=100)
    init: list[OneShot] = Field(default_factory=list, max_length=10)
    seed: OneShot | None = None
    qa: Qa | None = None

    def app(self, name: str) -> App | None:
        return next((a for a in self.apps if a.name == name), None)

    def service(self, name: str) -> Service | None:
        return next((s for s in self.services if s.name == name), None)

    def apps_of(self, repo: str) -> list[App]:
        return [a for a in self.apps if a.repo == repo]

    def qa_service(self) -> Service | None:
        return self.service(self.qa.service) if self.qa else None

    def qa_needs(self) -> list["Service"]:
        """The QA service and every service its env (and its app's env) refers
        to, transitively, in runbook order. Unknown names are left out."""
        needed: set[str] = set()

        def need(name: str) -> None:
            s = self.service(name)
            if s is None or name in needed:
                return
            needed.add(name)
            app = self.app(s.app) if s.kind == "process" else None
            values = [*(app.env.values() if app else []),
                      *(s.env.values() if isinstance(s.env, dict) else [])]
            for v in values:
                for ref in SERVICE_URL_RE.findall(v):
                    need(ref)

        if self.qa is not None:
            need(self.qa.service)
        return [s for s in self.services if s.name in needed]

    def target(self, ref: str) -> tuple["Service", str] | None:
        """`"<service>"` or `"<service>:<compose service>"` (init, seed, run_in)
        -> the runbook's compose service and the service in its file; None
        when it names no compose service (or one without a default)."""
        name, _, inner = ref.partition(":")
        s = self.service(name)
        if s is None or s.kind != "compose":
            return None
        inner = inner or s.expose_service()
        return (s, inner) if inner else None

    def one_shots(self) -> list[tuple[str, OneShot]]:
        """`init` then `seed`, labelled."""
        return [*(("init", i) for i in self.init), *([("seed", self.seed)] if self.seed else [])]

    def qa_compose(self) -> list["Service"]:
        """The compose services QA brings up, in runbook order: those the QA
        service needs, and those `init`/`seed` run in."""
        names = {s.name for s in self.qa_needs() if s.kind == "compose"}
        for _, o in self.one_shots():
            t = self.target(o.service)
            if t is not None:
                names.add(t[0].name)
        return [s for s in self.services if s.name in names]

    def browser_qa_ready(self) -> bool:
        """Whether browser QA can run from this runbook: its QA service is a
        process service (the base URL is the runner's localhost); what it needs
        may be process or compose services."""
        qa = self.qa_service()
        return qa is not None and qa.kind == "process"


def _path_problem(value: str) -> bool:
    """Not a URL path: must start with one '/', no spaces or control characters."""
    return (not value.startswith("/") or value.startswith("//")
            or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value))


def _problems(rb: Runbook, repo_names: set[str]) -> list[str]:
    out: list[str] = []

    def unique(kind: str, names: list[str]) -> None:
        for n in names:
            if not NAME_RE.fullmatch(n):
                out.append(f"{kind} name {n!r} must match [a-z0-9-] (max 40)")
        dup = sorted({n for n in names if names.count(n) > 1})
        if dup:
            out.append(f"duplicate {kind} names: {', '.join(dup)}")

    unique("app", [a.name for a in rb.apps])
    unique("service", [s.name for s in rb.services])
    services = [s.name for s in rb.services]
    declared = {e.name for e in rb.env}

    def no_env_refs(where: str, text: str) -> None:
        if ENV_REF_RE.search(text):
            out.append(f"{where}: {{env.NAME}} is only allowed in qa.login.fields; "
                       "compose services, init, seed and qa list vault names in `env`")

    def vault_names(where: str, names: list[str]) -> None:
        for n in names:
            p = env_name_problem(n)
            if p:
                out.append(f"{where}: {p}")
            elif n not in declared:
                out.append(f"{where}: {n} is not declared in the runbook's env list")
        dup = sorted({n for n in names if names.count(n) > 1})
        if dup:
            out.append(f"{where}: duplicate names: {', '.join(dup)}")

    def refs(where: str, values: dict[str, str], allowed: list[str]) -> None:
        for k, v in values.items():
            p = env_name_problem(k)
            if p:
                out.append(f"{where}: {p}")
            no_env_refs(f"{where}.{k}", v)
            for ref in SERVICE_URL_RE.findall(v):
                if ref not in allowed:
                    out.append(f"{where}: {k} refers to {{services.{ref}.url}}, which is not "
                               + ("an earlier service" if ref in services else "a service"))
                    continue
                s = rb.service(ref)
                if s is not None and s.kind == "compose" and not s.expose:
                    out.append(f"{where}: {k} refers to {{services.{ref}.url}}, but compose "
                               f"service {ref} has no expose (so no URL)")

    def target(where: str, ref: str) -> "tuple[Service, str] | None":
        name = ref.partition(":")[0]
        s = rb.service(name)
        if s is None or s.kind != "compose":
            out.append(f"{where}: {name!r} is not a compose service of the runbook "
                       "(use '<compose service>:<service in its file>')")
            return None
        t = rb.target(ref)
        if t is None:
            out.append(f"{where}: name the service in {name}'s file "
                       f"('{name}:<service>'); {name} has no expose to default to")
            return None
        if t[1] not in s.compose_services:
            out.append(f"{where}: {t[1]!r} is not one of {name}'s compose_services "
                       f"({', '.join(s.compose_services) or 'none'})")
            return None
        return t

    for a in rb.apps:
        w = f"apps.{a.name}"
        if a.repo not in repo_names:
            out.append(f"{w}: repo {a.repo!r} is not one of the project's repos "
                       f"({', '.join(sorted(repo_names)) or 'none'})")
        p = rel_path_problem(a.dir, "dir")
        if p:
            out.append(f"{w}: {p}")
        for g in a.generated:
            parts = g.split("/")
            if (not g or g.startswith("/") or "\\" in g or ".." in parts
                    or any(not set(x) - {"*", "?"} for x in parts) or any(c.isspace() for c in g)):
                out.append(f"{w}.generated: {g!r} must be a relative path or glob inside the "
                           "app dir, naming at least one fixed part per segment")
        native = not a.run_in  # run_in commands run in the project's own image
        if a.run_in:
            if ":" not in a.run_in:
                out.append(f"{w}: run_in must be '<compose service>:<service in its file>'")
            else:
                t = target(f"{w}.run_in", a.run_in)
                if t is not None and t[0].repo != a.repo:
                    out.append(f"{w}: run_in service {t[0].name} builds from repo "
                               f"{t[0].repo}, not the app's repo {a.repo}")
            if a.install:
                out.append(f"{w}: an app with run_in has no install (the image build "
                           "installs its dependencies)")
        for field, lines in (("install", a.install), ("checks", a.checks), ("build", a.build)):
            for line in lines:
                p = command_problem(line, allow_changed=field != "install", check_program=native)
                if p:
                    out.append(f"{w}.{field}: {p}")
                no_env_refs(f"{w}.{field}", line)
        refs(w + ".env", a.env, services)

    for i, s in enumerate(rb.services):
        w = f"services.{s.name}"
        earlier = services[:i]
        if _path_problem(s.health):
            out.append(f"{w}: health must be a path starting with '/' (no spaces or "
                       "control characters)")
        if s.kind == "process":
            app = rb.app(s.app)
            if app is None:
                out.append(f"{w}: app {s.app!r} is not an app of the runbook")
            elif app.run_in:
                out.append(f"{w}: app {app.name} runs in a compose image (run_in); a process "
                           "service needs an app the runner can start")
            if not s.command:
                out.append(f"{w}: a process service needs a command")
            else:
                p = command_problem(s.command, allow_port=True)
                if p:
                    out.append(f"{w}.command: {p}")
                no_env_refs(f"{w}.command", s.command)
            for field in ("repo", "file", "compose_services", "expose", "environment"):
                if getattr(s, field):
                    out.append(f"{w}: {field} is only for a compose service")
            if isinstance(s.env, list) and s.env:
                out.append(f"{w}.env: a process service takes env as name -> value")
            elif isinstance(s.env, dict):
                refs(w + ".env", s.env, earlier)
            if app is not None:
                # The app's env reaches the process too: same ordering rule.
                for k, v in app.env.items():
                    for ref in SERVICE_URL_RE.findall(v):
                        if ref in services and ref not in earlier:
                            out.append(f"{w}: app {app.name} env {k} refers to service "
                                       f"{ref!r}, which must come before {s.name!r}")
        else:
            if s.repo not in repo_names:
                out.append(f"{w}: repo {s.repo!r} is not one of the project's repos")
            if not s.file:
                out.append(f"{w}: a compose service needs a file")
            p = rel_path_problem(s.file, "file")
            if p:
                out.append(f"{w}: {p}")
            for field in ("app", "command"):
                if getattr(s, field):
                    out.append(f"{w}: {field} is only for a process service")
            if not s.compose_services:
                out.append(f"{w}: list the services to start in compose_services")
            for c in s.compose_services:
                if not COMPOSE_NAME_RE.fullmatch(c):
                    out.append(f"{w}.compose_services: {c!r} is not a compose service name")
            dup = sorted({c for c in s.compose_services if s.compose_services.count(c) > 1})
            if dup:
                out.append(f"{w}.compose_services: duplicate names: {', '.join(dup)}")
            if s.expose:
                m = EXPOSE_RE.fullmatch(s.expose)
                if not m or not 0 < int(m.group(2)) < 65536:
                    out.append(f"{w}: expose must be '<service>:<port>', e.g. 'backend:5000'")
                elif m.group(1) not in s.compose_services:
                    out.append(f"{w}: expose names {m.group(1)!r}, which is not in "
                               "compose_services")
            for c, over in s.environment.items():
                if c not in s.compose_services:
                    out.append(f"{w}.environment: {c!r} is not in compose_services")
                if len(over) > 50:
                    out.append(f"{w}.environment.{c}: at most 50 entries")
                for k, v in over.items():
                    p = env_name_problem(k)
                    if p:
                        out.append(f"{w}.environment.{c}: {p}")
                    if len(v) > 2000 or any(chr(o) in v for o in (0, 10, 13)):
                        out.append(f"{w}.environment.{c}.{k}: one line, at most 2000 characters")
            if isinstance(s.env, list):
                vault_names(f"{w}.env", s.env)
            elif s.env:
                out.append(f"{w}.env: a compose service lists env names (values live in "
                           "the vault)")

    names = [e.name for e in rb.env]
    for n in names:
        p = env_name_problem(n)
        if p:
            out.append(f"env: {p}")
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        out.append(f"env: duplicate names: {', '.join(dup)}")

    for k, (label, o) in enumerate(rb.one_shots()):
        w = "seed" if label == "seed" else f"init[{k}]"
        target(f"{w}: service", o.service)
        p = command_problem(o.command, check_program=False)
        if p:
            out.append(f"{w}.command: {p}")
        no_env_refs(f"{w}.command", o.command)
        vault_names(f"{w}.env", o.env)

    if rb.qa is not None:
        qs = rb.service(rb.qa.service)
        if qs is None:
            out.append(f"qa: service {rb.qa.service!r} is not a service of the runbook")
        elif qs.kind != "process":
            out.append(f"qa: service {rb.qa.service!r} must be a process service (the app's "
                       "dev server; QA's base URL is the runner's localhost)")
        vault_names("qa.env", rb.qa.env)
        for n in rb.qa.env:
            if n in QA_RESERVED_ENV:
                out.append(f"qa.env: {n} is set by the runner itself")
        for r in rb.qa.routes:
            if not r.startswith("/") or any(c.isspace() for c in r):
                out.append(f"qa.routes: {r!r} must be a path starting with '/'")
        lg = rb.qa.login
        if lg is not None:
            if _path_problem(lg.path):
                out.append("qa.login.path must be a path starting with '/'")
            if lg.success_url and _path_problem(lg.success_url):
                out.append("qa.login.success_url must be a path starting with '/'")
            for sel in [*lg.fields, lg.submit]:
                if not sel.strip() or len(sel) > 300 or any(ord(c) < 32 for c in sel):
                    out.append(f"qa.login: {sel!r} must be a CSS selector (1-300 characters)")
            for sel, value in lg.fields.items():
                if len(value) > 500:
                    out.append(f"qa.login.fields[{sel!r}]: the value is too long")
                vault_names(f"qa.login.fields[{sel!r}]", ENV_REF_RE.findall(value))
    return out


def validate(data: object, repo_names: set[str]) -> tuple[Runbook | None, list[str]]:
    """The runbook, or every problem found as readable lines."""
    try:
        rb = Runbook.model_validate(data)
    except ValidationError as e:
        lines = []
        for err in e.errors():
            loc = ".".join(str(p) for p in err["loc"])
            lines.append(f"{loc}: {err['msg']}" if loc else err["msg"])
        return None, lines
    problems = _problems(rb, repo_names)
    return (None, problems) if problems else (rb, [])


def repo_refs(rb: Runbook | None, repo: str) -> list[str]:
    """The runbook's apps and compose services that name `repo`."""
    if rb is None:
        return []
    return ([f"apps.{a.name}" for a in rb.apps if a.repo == repo]
            + [f"services.{s.name}" for s in rb.services if s.kind == "compose" and s.repo == repo])


MASK = "***"


def masked(spec: dict | None) -> dict | None:
    """The stored runbook with app and process-service env values, and the
    literal values of compose services' `environment`, hidden."""
    if not spec:
        return spec
    out = {**spec}
    out["apps"] = [{**a, "env": {k: MASK for k in a["env"]}}
                   if isinstance(a, dict) and isinstance(a.get("env"), dict) else a
                   for a in spec.get("apps") or []]

    def service(s):
        if not isinstance(s, dict):
            return s
        s = {**s}
        if isinstance(s.get("env"), dict):
            s["env"] = {k: MASK for k in s["env"]}
        if isinstance(s.get("environment"), dict):
            s["environment"] = {c: {k: MASK for k in over} if isinstance(over, dict) else MASK
                                for c, over in s["environment"].items()}
        return s

    out["services"] = [service(s) for s in spec.get("services") or []]
    qa = spec.get("qa")
    login = qa.get("login") if isinstance(qa, dict) else None
    if isinstance(login, dict) and isinstance(login.get("fields"), dict):
        # `{env.NAME}` names a vault value; anything else is literal text
        fields = {k: v if isinstance(v, str) and ENV_REF_RE.fullmatch(v) else MASK
                  for k, v in login["fields"].items()}
        out["qa"] = {**qa, "login": {**login, "fields": fields}}
    return out


# Shorter values ("1", "dev") would redact ordinary words.
MIN_SECRET_LEN = 6


def env_values(rb: Runbook | None) -> list[str]:
    """Env values of the runbook's apps and process services (and literal
    qa.login field text), to keep out of comments; values that only refer to
    a service URL are left out."""
    if rb is None:
        return []
    values = [v for a in rb.apps for v in a.env.values()]
    values += [v for s in rb.services if isinstance(s.env, dict) for v in s.env.values()]
    if rb.qa is not None and rb.qa.login is not None:
        values += [ENV_REF_RE.sub("", v) for v in rb.qa.login.fields.values()]
    return sorted({v for v in values
                   if len(v) >= MIN_SECRET_LEN and not SERVICE_URL_RE.fullmatch(v)},
                  key=len, reverse=True)


# --- storage ------------------------------------------------------------------


def now() -> datetime:
    return datetime.now(UTC)


def load(db: Session, slug: str) -> Runbook | None:
    """The approved runbook, parsed (it was validated when saved)."""
    row = db.get(AwakRunbook, slug)
    if row is None or not row.spec:
        return None
    try:
        return Runbook.model_validate(row.spec)
    except ValidationError:
        return None


def all_env_values(db: Session) -> list[str]:
    """`env_values` of every project's runbook."""
    out: set[str] = set()
    for row in db.query(AwakRunbook):
        try:
            out.update(env_values(Runbook.model_validate(row.spec or {})))
        except ValidationError:
            continue
    return sorted(out, key=len, reverse=True)


def state(db: Session, slug: str) -> dict:
    row = db.get(AwakRunbook, slug)
    if row is None:
        return {"runbook": None, "version": 0, "approved_by": "", "approved_at": None}
    return {"runbook": row.spec or None, "version": row.version,
            "approved_by": row.approved_by, "approved_at": row.approved_at}


def save(db: Session, slug: str, rb: Runbook, by: str) -> AwakRunbook:
    row = db.get(AwakRunbook, slug)
    if row is None:
        row = AwakRunbook(project_slug=slug, version=0)
        db.add(row)
    t = now()
    # What the admin wrote, defaults included when written; unset fields are
    # left out (readers fill in the defaults).
    row.spec = rb.model_dump(mode="json", exclude_unset=True)
    row.version = (row.version or 0) + 1
    row.approved_by, row.approved_at = by, t
    row.updated_by, row.updated_at = by, t
    db.commit()
    return row
