"""A project's runbook: how to install, check, run and QA its apps.

One JSON document per project (`awak_runbooks`), saved by an admin and used
only from the DB copy. Stage 1a runs `process` services; `compose` services,
`run_in` and `seed` are accepted by the schema and refused at run time
("stage 1b").
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
    # "<service>:<compose service>": run the commands in that image (stage 1b).
    run_in: str = ""

    @field_validator("dir")
    @classmethod
    def _dir(cls, v: str) -> str:
        return v.strip().rstrip("/")  # a leading '/' is reported by _problems


class Service(_Strict):
    name: str
    kind: Literal["process", "compose"]
    # process: a long-running command of an app, `{port}` allocated by the runner
    app: str = ""
    command: str = ""
    # compose (stage 1b)
    repo: str = ""
    file: str = ""
    compose_services: list[str] = Field(default_factory=list)
    expose: str = ""
    health: str = "/"
    ready_timeout: int = Field(120, ge=1, le=600)
    # vault names (compose), or name -> value for a process service
    env: list[str] | dict[str, str] = Field(default_factory=dict)


class EnvVar(_Strict):
    name: str
    secret: bool = False
    required: bool = False
    description: str = Field("", max_length=500)


class Seed(_Strict):
    service: str
    command: str


class Qa(_Strict):
    service: str
    env: list[str] = Field(default_factory=list)
    # paths to load once before the spec runs (dev servers compile on first hit)
    routes: list[str] = Field(default_factory=list, max_length=10)


class Runbook(_Strict):
    apps: list[App] = Field(default_factory=list, max_length=20)
    services: list[Service] = Field(default_factory=list, max_length=20)
    env: list[EnvVar] = Field(default_factory=list, max_length=100)
    seed: Seed | None = None
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

    def browser_qa_ready(self) -> bool:
        """Whether stage 1a can run browser QA from this runbook: the QA service
        and what it needs are all process services."""
        needs = self.qa_needs()
        return bool(needs) and all(s.kind == "process" for s in needs)


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

    def refs(where: str, values: dict[str, str], allowed: list[str]) -> None:
        for k, v in values.items():
            p = env_name_problem(k)
            if p:
                out.append(f"{where}: {p}")
            for ref in SERVICE_URL_RE.findall(v):
                if ref not in allowed:
                    out.append(f"{where}: {k} refers to {{services.{ref}.url}}, which is not "
                               + ("an earlier service" if ref in services else "a service"))

    for a in rb.apps:
        w = f"apps.{a.name}"
        if a.repo not in repo_names:
            out.append(f"{w}: repo {a.repo!r} is not one of the project's repos "
                       f"({', '.join(sorted(repo_names)) or 'none'})")
        p = rel_path_problem(a.dir, "dir")
        if p:
            out.append(f"{w}: {p}")
        native = not a.run_in  # run_in commands run in the project's own image
        if a.run_in and (":" not in a.run_in or a.run_in.split(":", 1)[0] not in services):
            out.append(f"{w}: run_in must be '<compose service>:<service in its file>'")
        for field, lines in (("install", a.install), ("checks", a.checks), ("build", a.build)):
            for line in lines:
                p = command_problem(line, allow_changed=field != "install", check_program=native)
                if p:
                    out.append(f"{w}.{field}: {p}")
        refs(w + ".env", a.env, services)

    for i, s in enumerate(rb.services):
        w = f"services.{s.name}"
        earlier = services[:i]
        if (not s.health.startswith("/") or s.health.startswith("//")
                or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in s.health)):
            out.append(f"{w}: health must be a path starting with '/' (no spaces or "
                       "control characters)")
        if s.kind == "process":
            app = rb.app(s.app)
            if app is None:
                out.append(f"{w}: app {s.app!r} is not an app of the runbook")
            if not s.command:
                out.append(f"{w}: a process service needs a command")
            else:
                p = command_problem(s.command, allow_port=True)
                if p:
                    out.append(f"{w}.command: {p}")
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
            for name in s.env if isinstance(s.env, list) else []:
                p = env_name_problem(name)
                if p:
                    out.append(f"{w}.env: {p}")
            if isinstance(s.env, dict) and s.env:
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

    if rb.seed is not None:
        s = rb.service(rb.seed.service)
        if s is None or s.kind != "compose":
            out.append(f"seed: service {rb.seed.service!r} must be a compose service")
    if rb.qa is not None:
        if rb.service(rb.qa.service) is None:
            out.append(f"qa: service {rb.qa.service!r} is not a service of the runbook")
        for n in rb.qa.env:
            p = env_name_problem(n)
            if p:
                out.append(f"qa.env: {p}")
        for r in rb.qa.routes:
            if not r.startswith("/") or any(c.isspace() for c in r):
                out.append(f"qa.routes: {r!r} must be a path starting with '/'")
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
    """The stored runbook with app and process-service env values hidden."""
    if not spec:
        return spec
    out = {**spec}
    out["apps"] = [{**a, "env": {k: MASK for k in a["env"]}}
                   if isinstance(a, dict) and isinstance(a.get("env"), dict) else a
                   for a in spec.get("apps") or []]
    out["services"] = [{**s, "env": {k: MASK for k in s["env"]}}
                       if isinstance(s, dict) and isinstance(s.get("env"), dict) else s
                       for s in spec.get("services") or []]
    return out


# Shorter values ("1", "dev") would redact ordinary words.
MIN_SECRET_LEN = 6


def env_values(rb: Runbook | None) -> list[str]:
    """Env values of the runbook's apps and process services, to keep out of
    comments; values that only refer to a service URL are left out."""
    if rb is None:
        return []
    values = [v for a in rb.apps for v in a.env.values()]
    values += [v for s in rb.services if isinstance(s.env, dict) for v in s.env.values()]
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
