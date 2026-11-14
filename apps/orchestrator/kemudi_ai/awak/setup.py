"""The Setup Assistant ("Configure automatically"): the setup agent proposes a
runbook, the runner and kemudi-svc prove it, a human approves it.

A run (`awak_setup_runs`) moves through

    queued -> reading -> proving -> ready -> approved
    reading -> needs_input -> proving        (the vault lacks a value)
    proving -> reading                       (a fix round)
    queued, reading, proving -> failed;  any active state or ready -> cancelled (API)

- `queued`: every repo is synced and checked out at its default branch to
  `<workspace>/<slug>/setup/<repo>/`; `detect_apps` gives a draft.
- `reading`: one setup-agent turn writes `<workspace>/<slug>/setup/runbook.json`;
  it is validated (and scanned for secret values). Problems go back to the
  agent, at most MAX_RETRIES more turns, then `failed`. A valid runbook goes to
  `needs_input` when the vault lacks a value it needs, else to `proving`.
- `needs_input`: holds nothing; the API writes the values and moves on.
- `proving`: fresh checkouts, install every app, run its checks once (a red
  check is reported, never blocking), bring up the compose services (init,
  health, seed: the worker's `Compose.for_qa`), start the process services
  and take one screenshot of `qa.service` `/` (runner `screenshot`), memory
  and logs, then everything comes down. A failed install, start, health or a
  check that could not run at all goes back to the agent with the redacted
  logs (state `reading`, `round` + 1), at most MAX_ROUNDS rounds, then `failed`.
- `ready` -> `approved` (API; saved as the project's runbook) or `cancelled`.

The worker calls `SetupRunner.step` once per tick (after requested merges,
before stories): one state change per call, persisted, so a restart resumes
where it was. Every stored text (step output, error, the agent's feedback)
is redacted with the project's vault values and the usual secrets first.
State changes are conditional (`UPDATE ... WHERE state = <expected>`), so a
cancel from the API is never overwritten by a step that was still running.
"""

import json
import logging
from contextlib import nullcontext
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import update
from sqlalchemy.orm import Session

from ..config import Settings
from ..store import AwakEnvVar, AwakSetupRun
from . import checks, config_store, detect, runbook, secrets
from .agent import AgentError
from .gitops import GitError
from .prompts import RoleScope, render
from .runbook import ENV_REF_RE, Runbook
from .runner import RunnerError, RunnerRejected
from .svc import SvcError, SvcRejected

log = logging.getLogger(__name__)

ACTIVE = ("queued", "reading", "proving", "needs_input")
# States the worker steps (needs_input waits for a human).
STEPPED = ("queued", "reading", "proving")
MAX_ROUNDS = 3        # proposal + proof rounds
MAX_RETRIES = 2       # more agent turns after an invalid runbook, per round
MAX_INFRA = 3         # transport failures (runner, svc, git, model) before `failed`
OUTPUT_MAX = 4000     # stored tail of a step's output
FEEDBACK_MAX = 12000
RUNBOOK_FILE = "runbook.json"
MAX_RUNBOOK_BYTES = 256_000
MAX_READ_BYTES = 200_000
SHOT_OUT = "setup/home.png"
PURPOSE = "awak.setup"

# Words that make an env name a secret whatever the runbook says.
_SECRET_WORDS = ("KEY", "SECRET", "PASSWORD", "PASSWD", "PASS", "PWD", "TOKEN", "CREDENTIAL",
                 "PRIVATE", "SALT", "DSN", "DATABASE_URL", "AUTH")
# Suffixes of names that are clearly not secrets (an email, a URL, a port...).
_PLAIN_SUFFIXES = ("EMAIL", "USER", "USERNAME", "URL", "HOST", "PORT", "NAME", "ENV", "MODE",
                   "LEVEL", "DEBUG", "REGION", "LOCALE", "LANG", "TZ")


class SetupInfra(Exception):
    """The runner, kemudi-svc, git or the model could not be reached: the step
    is tried again (MAX_INFRA times), no round is used."""


class SetupBlocked(Exception):
    """Nothing the agent can fix (kemudi-svc not configured, no vault key, no
    repos): the run fails with this message."""


class _ProofFailed(Exception):
    def __init__(self, message: str, logs: str = ""):
        super().__init__(message)
        self.logs = logs


class _Cancelled(Exception):
    pass


def now() -> datetime:
    return datetime.now(UTC)


def setup_root(settings: Settings, slug: str) -> Path:
    return Path(settings.workspace_dir) / slug / "setup"


def contained(settings: Settings, slug: str) -> Path | None:
    """The setup folder, if neither it nor its project folder is a symlink and it
    resolves inside the workspace: the agent can write /workspace, so a folder
    swapped for a link must not make the orchestrator read elsewhere."""
    root = setup_root(settings, slug)
    ws = Path(settings.workspace_dir)
    try:
        if root.is_symlink() or root.parent.is_symlink() or not root.is_dir():
            return None
        if not root.resolve().is_relative_to(ws.resolve()):
            return None
    except OSError:
        return None
    return root


# --- queries used by the API ------------------------------------------------------


def active(db: Session, slug: str) -> AwakSetupRun | None:
    return (db.query(AwakSetupRun)
            .filter(AwakSetupRun.project_slug == slug, AwakSetupRun.state.in_(ACTIVE))
            .order_by(AwakSetupRun.id.desc()).first())


def latest(db: Session, slug: str) -> AwakSetupRun | None:
    return (db.query(AwakSetupRun).filter_by(project_slug=slug)
            .order_by(AwakSetupRun.id.desc()).first())


def start(db: Session, slug: str, by: str) -> AwakSetupRun:
    run = AwakSetupRun(project_slug=slug, state="queued", round=1, created_by=by,
                       proposal={}, steps=[], missing_env=[], resources={})
    db.add(run)
    db.commit()
    return run


def proposed(run: AwakSetupRun) -> Runbook | None:
    spec = (run.proposal or {}).get("runbook")
    if not spec:
        return None
    try:
        return Runbook.model_validate(spec)
    except ValueError:
        return None


def transition(db: Session, run_id: int, expect: tuple[str, ...] | str, **fields) -> bool:
    """Set fields only while the run is still in one of `expect` (a cancel or
    approval in between wins). Returns whether it applied."""
    expect = (expect,) if isinstance(expect, str) else expect
    fields["updated_at"] = now()
    res = db.execute(update(AwakSetupRun)
                     .where(AwakSetupRun.id == run_id, AwakSetupRun.state.in_(expect))
                     .values(**fields))
    db.commit()
    return res.rowcount == 1


def services_down(run: AwakSetupRun, svc) -> list[str]:
    """Bring the run's compose projects (`<slug>-setup...`) down (cancel).
    Failures are logged: the worker's start sweep catches leftovers."""
    projects = sorted(set(checks.compose_projects(
        proposed(run), run.project_slug, "setup").values()))
    if svc is None:
        return []
    for project in projects:
        try:
            svc.call("svc_down", project=project)
        except SvcError as e:
            log.warning("awak: svc_down %s on cancel failed: %s", project, e)
    return projects


def out(run: AwakSetupRun, is_admin: bool) -> dict:
    """The run as the UI polls it. Members see the runbook's env values masked."""
    p = run.proposal or {}
    spec = p.get("runbook")
    return {
        "id": run.id,
        "project_slug": run.project_slug,
        "state": run.state,
        "active": run.state in ACTIVE,
        "round": run.round,
        "max_rounds": MAX_ROUNDS,
        "proposal": {
            "runbook": spec if is_admin else runbook.masked(spec),
            "draft": p.get("draft") or {},
            "env_help": p.get("env_help") or {},
            "report": p.get("report") or "",
            "feedback": p.get("feedback") or "",
        },
        "steps": run.steps or [],
        "missing_env": run.missing_env or [],
        "screenshot": bool(run.screenshot),
        "resources": run.resources or {},
        "error": run.error or "",
        "cost_idr": run.cost_idr or 0.0,
        "created_by": run.created_by,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
    }


# --- env -------------------------------------------------------------------------


def plain_name(name: str) -> bool:
    """Clearly not a secret: no secret word, and a plain suffix (EMAIL, URL...)."""
    if any(w in name for w in _SECRET_WORDS):
        return False
    return name.split("_")[-1] in _PLAIN_SUFFIXES


def login_refs(rb: Runbook) -> list[str]:
    lg = rb.qa.login if rb.qa else None
    if lg is None:
        return []
    return [n for v in lg.fields.values() for n in ENV_REF_RE.findall(v)]


def referenced(rb: Runbook) -> list[str]:
    """Every vault name the runbook uses (compose services, init/seed, qa.env,
    qa.login) plus its required names, in order, once each."""
    names: list[str] = []
    for s in rb.services:
        if s.kind == "compose" and isinstance(s.env, list):
            names += s.env
    for _, o in rb.one_shots():
        names += o.env
    if rb.qa is not None:
        names += rb.qa.env
    names += login_refs(rb)
    names += [e.name for e in rb.env if e.required]
    return list(dict.fromkeys(names))


def missing_env(rb: Runbook, have: set[str], env_help: dict[str, str]) -> list[dict]:
    """The names the proof needs that the vault lacks. A name the runbook
    declares optional is left out (the proof runs without it), unless the
    login types it."""
    declared = {e.name: e for e in rb.env}
    login = set(login_refs(rb))
    out_: list[dict] = []
    for n in referenced(rb):
        if n in have:
            continue
        d = declared.get(n)
        if d is not None and not d.required and n not in login:
            continue
        out_.append({"name": n,
                     "description": (env_help.get(n) or (d.description if d else ""))[:500],
                     "secret": bool(d and d.secret) or not plain_name(n)})
    return out_


def vault_names(db: Session, slug: str) -> set[str]:
    return {r.name for r in db.query(AwakEnvVar).filter_by(project_slug=slug)}


# --- the task --------------------------------------------------------------------


def setup_task(root: Path, slug: str, repos: list[tuple[str, str]], draft: dict,
               have: list[str], feedback: str = "", previous: dict | None = None) -> str:
    """What the setup agent is asked for. `repos`: (name, default branch)."""
    schema = json.dumps(Runbook.model_json_schema(), separators=(",", ":"))
    parts = [
        f"Workspace: {root}",
        f"Project: {slug}",
        "",
        f"Write the project's runbook to {root / RUNBOOK_FILE} (one JSON object; an optional "
        "top-level \"env_help\" object maps env names to what a human should enter).",
        "",
        "Repositories, checked out at their default branch (read them, change nothing; `repo` "
        "in the runbook is the folder name):",
        *[f"- {name}: {root / name} (branch {branch})" for name, branch in repos],
        "",
        "A quick scan of their files found this (a starting point; check it against the files):",
        json.dumps(draft, indent=1)[:12000],
        "",
        "Env names that already have a value in the project's vault (values are never shown): "
        + (", ".join(sorted(have)) or "none"),
        "",
        "Programs native commands may start (argv[0]): "
        + ", ".join(sorted(runbook.ALLOWED_PROGRAMS)),
        "",
        "The runbook JSON schema:",
        schema,
    ]
    if previous:
        parts += ["", "Your previous runbook:", json.dumps(previous, indent=1)[:20000]]
    if feedback:
        parts += ["", "Fix the runbook for these problems (from validation or from running it "
                      "in the sandbox; logs are redacted):", feedback.strip()[:FEEDBACK_MAX]]
    return "\n".join(parts)


# --- the state machine ------------------------------------------------------------


class SetupRunner:
    """Steps setup runs for a Worker (its sessions, agent, runner, svc and
    redaction)."""

    def __init__(self, worker):
        self.w = worker
        self.s: Settings = worker.s

    # ---------------------------------------------------------------- entry
    def next_run(self) -> int | None:
        """The active run waiting longest for its next step."""
        with self.w.sessions() as db:
            run = (db.query(AwakSetupRun).filter(AwakSetupRun.state.in_(STEPPED))
                   .order_by(AwakSetupRun.updated_at, AwakSetupRun.id).first())
            return run.id if run else None

    def step_next(self) -> bool:
        run_id = self.next_run()
        if run_id is None:
            return False
        self.step(run_id)
        return True

    def step(self, run_id: int) -> None:
        """Advance the run by one state; never raises."""
        run = self._get(run_id)
        if run is None or run.state not in STEPPED:
            return
        slug, state = run.project_slug, run.state
        try:
            if state == "queued":
                self._read_repos(run)
            elif state == "reading":
                self._propose(run)
            else:
                self._prove(run)
        except _Cancelled:
            return
        except SetupBlocked as e:
            self._set(run_id, state, state="failed", error=self._redact(slug, str(e)))
        except (SetupInfra, AgentError, GitError, RunnerError, SvcError) as e:
            self._infra(run_id, state, slug, e)
        except Exception as e:  # noqa: BLE001 - the worker must go on
            log.exception("awak: setup run %s failed in %s", run_id, state)
            self._infra(run_id, state, slug, e)
        else:
            self._infra_ok(run_id)

    def recover(self) -> None:
        """Worker start: a proof cut off by a crash starts over (its compose
        project is kept by the sweep and reused); the agent turn of a `reading`
        run simply runs again."""
        with self.w.sessions() as db:
            ids = [r.id for r in db.query(AwakSetupRun).filter_by(state="proving")]
            for run_id in ids:
                transition(db, run_id, "proving", steps=[], screenshot="", resources={},
                           error="")

    def keep_projects(self, db: Session) -> set[str]:
        """Compose projects of active runs (the sweep keeps them)."""
        keep: set[str] = set()
        for run in db.query(AwakSetupRun).filter(AwakSetupRun.state.in_(ACTIVE)):
            keep |= set(checks.compose_projects(proposed(run), run.project_slug,
                                                "setup").values())
        return keep

    # --------------------------------------------------------------- states
    def _read_repos(self, run: AwakSetupRun) -> None:
        slug = run.project_slug
        cfg, keys = self._config(slug)
        if not cfg.repos:
            raise SetupBlocked("the project has no repositories; add one in Project settings "
                               "→ Agent first.")
        draft = {}
        for rc in cfg.repos:
            d = self._checkout(cfg, rc, keys, sync=True)
            draft[rc.name] = detect.detect_apps(_tree(d), _list_dir(d))
        self._set(run.id, "queued", state="reading", proposal={"draft": draft, "turns": 0},
                  error="")

    def _propose(self, run: AwakSetupRun) -> None:
        slug = run.project_slug
        cfg, _ = self._config(slug)
        setup_root(self.s, slug).mkdir(parents=True, exist_ok=True)
        root = contained(self.s, slug)
        if root is None:
            raise SetupBlocked(f"{setup_root(self.s, slug)} is not a plain folder inside the "
                               "workspace.")
        target = root / RUNBOOK_FILE
        if target.is_symlink() or target.exists():
            target.unlink()
        p = dict(run.proposal or {})
        with self.w.sessions() as db:
            have = vault_names(db, slug)
        task = setup_task(root, slug, [(r.name, r.default_branch) for r in cfg.repos],
                          p.get("draft") or {}, sorted(have), p.get("feedback") or "",
                          p.get("previous"))
        system = render("setup", "", RoleScope(repos=[r.name for r in cfg.repos]))
        report, cost = self.w.agent.run(PURPOSE, self.s.awak_model, system, task, slug=slug)
        self._add_cost(run.id, cost)
        p["report"] = self._redact(slug, report)[-2000:]
        rb, env_help, problems, raw = self._read_runbook(target, {r.name for r in cfg.repos},
                                                         slug)
        if problems:
            turns = int(p.get("turns") or 0) + 1
            text = self._redact(slug, "\n".join(f"- {x}" for x in problems))
            if turns > MAX_RETRIES:
                self._set(run.id, "reading", state="failed", proposal=p,
                          error=f"The proposed runbook was still invalid after {turns} turns:\n"
                                + text[:OUTPUT_MAX])
                return
            p.update(turns=turns, feedback="The runbook is not valid:\n" + text)
            if isinstance(raw, dict):
                p["previous"] = json.loads(self._redact(slug, json.dumps(raw)))
            self._set(run.id, "reading", proposal=p, error="")
            return
        assert rb is not None
        spec = rb.model_dump(mode="json", exclude_unset=True)
        p.update(runbook=spec, env_help=env_help, feedback="", turns=0)
        p.pop("previous", None)
        with self.w.sessions() as db:
            missing = missing_env(rb, vault_names(db, slug), env_help)
        self._set(run.id, "reading", state="needs_input" if missing else "proving",
                  proposal=p, missing_env=missing, steps=[], screenshot="", resources={},
                  error="")

    def _prove(self, run: AwakSetupRun) -> None:
        slug = run.project_slug
        rb = proposed(run)
        if rb is None:
            raise SetupBlocked("the run has no valid runbook to prove.")
        with self.w.sessions() as db:
            missing = missing_env(rb, vault_names(db, slug),
                                  (run.proposal or {}).get("env_help") or {})
        if missing:
            self._set(run.id, "proving", state="needs_input", missing_env=missing)
            return
        steps: list[dict] = []
        resources: dict = {}
        shot = ""
        try:
            shot = self._proof(run, rb, steps, resources)
        except (_ProofFailed, checks.Unsupported, checks.ServiceFailed) as e:
            logs = getattr(e, "logs", "") or ""
            self._failed_round(run, steps, resources, str(e), logs)
            return
        self._set(run.id, "proving", state="ready", steps=self._clean_steps(slug, steps),
                  screenshot=shot, resources=resources, missing_env=[], error="")

    # ---------------------------------------------------------------- proof
    def _proof(self, run: AwakSetupRun, rb: Runbook, steps: list[dict],
               resources: dict) -> str:
        """Install, checks, services, screenshot; returns the screenshot path
        (relative to the setup folder) or "". Raises on a failure the agent
        can fix; everything started comes down."""
        slug = run.project_slug
        cfg, keys = self._config(slug)
        root = setup_root(self.s, slug)
        redact = self.w.redact_values_for(slug)
        dirs = {rc.name: self._checkout(cfg, rc, keys, sync=False) for rc in cfg.repos
                if rb.apps_of(rc.name) or any(s.kind == "compose" and s.repo == rc.name
                                              for s in rb.services)}

        def add(name: str, ok: bool, output: str = "", **extra) -> None:
            steps.append({"name": name, "ok": ok, "output": output, **extra})

        # install
        for rc in cfg.repos:
            if not rb.apps_of(rc.name):
                continue
            payloads = checks.install_payloads(rc, rb)
            checks.missing_dirs(payloads, dirs[rc.name], rc.name)
            for p in payloads:
                self._alive(run.id)
                res = self._run("install", path=self.w._path(dirs[rc.name]),
                                **checks._runner_payload(p))
                ok = bool(res.get("ok")) and not res.get("infra_error")
                text = str(res.get("infra_error") or res.get("output") or "")
                add(f"install {p['app']}", ok, text)
                if not ok:
                    raise _ProofFailed(f"install of app {p['app']} failed", text)

        values = self._vault(slug) if (rb.services or rb.qa) else {}
        compose = None
        if any(s.kind == "compose" for s in rb.services):
            if self.w.svc is None:
                raise SetupBlocked("the runbook has compose services, but kemudi-svc is not "
                                   "configured (KEMUDI_SVC_KEY).")
            compose = checks.Compose(
                rb, self._svc, self._run, checks.compose_projects(rb, slug, "setup"),
                lambda repo: self.w._path(root / repo), values, redact,
                lambda kind, detail: _compose_step(add, kind, detail))

        # checks: once each, red is reported; "could not run" fails the round
        for rc in cfg.repos:
            if not rb.apps_of(rc.name):
                continue
            for p in checks.gate_payloads(rc, rb, [], dirs[rc.name]):
                self._alive(run.id)
                self._checks(p, self.w._path(dirs[rc.name]), compose, add)

        # services and the screenshot
        return self._services(run, rb, compose, values, root, add, resources)

    def _checks(self, p: dict, path: str, compose, add) -> None:
        name = f"checks {p['app']}" if p["app"] else "checks"
        if p.get("run_in") and p["commands"]:
            try:
                gates = compose.run_in_gates(path, p) if compose else None
            except checks.ServiceFailed as e:
                add(name, False, f"{e}\n{e.logs}")
                raise _ProofFailed(f"the checks of app {p['app']} could not run: {e}",
                                   e.logs) from e
            if gates is None:
                raise _ProofFailed(f"app {p['app']} uses run_in, but no compose service runs it")
        elif p["commands"]:
            res = self._run("gates", path=path, **checks._runner_payload(p))
            if res.get("infra_error"):
                text = str(res["infra_error"])
                add(name, False, text)
                raise _ProofFailed(f"the checks of app {p['app']} could not run "
                                   "(a missing tool or a timeout)", text)
            gates = list(res.get("gates") or [])
        else:
            gates = []
        gates += [{"name": s, "ok": True, "output": ""} for s in p["skipped"]]
        red = [g for g in gates if not g.get("ok")]
        summary = "\n".join(f"{'ok ' if g.get('ok') else 'RED'} {g.get('name', '')}"
                            for g in gates)
        detail = "\n\n".join(f"$ {g.get('name', '')}\n{str(g.get('output') or '')[-1500:]}"
                             for g in red)
        add(name, not red, (summary + ("\n\n" + detail if detail else "")).strip(),
            red=bool(red), gates=[{"name": g.get("name", ""), "ok": bool(g.get("ok"))}
                                  for g in gates])

    def _services(self, run: AwakSetupRun, rb: Runbook, compose, values: dict, root: Path,
                  add, resources: dict) -> str:
        if not rb.services:
            return ""
        if rb.browser_qa_ready():
            plan = checks.qa_plan(rb)
            login = checks.login_payload(rb, values)
        else:
            shots = [checks._one_shot(rb, label, o) for label, o in rb.one_shots()]
            plan = {"services": [], "base_service": "",
                    "compose": [s.name for s in rb.services if s.kind == "compose"],
                    "init": [o for o in shots if o["label"] == "init"],
                    "seed": next((o for o in shots if o["label"] == "seed"), None)}
            login = None
            add("screenshot", True, "the runbook has no qa section with a process service: "
                                    "no dev server started, no screenshot")
        self._alive(run.id)
        shot = ""
        ctx = compose.for_qa(plan) if (compose and plan["compose"]) else nullcontext({})
        try:
            with ctx as urls:
                for name in urls:
                    add(f"health {name}", True, f"{rb.service(name).health} answered")
                if plan["services"]:
                    base = next(s for s in plan["services"] if s["name"] == plan["base_service"])
                    repo = base["repo"]
                    body = {"path": self.w._path(root / repo), "services": plan["services"],
                            "base_service": plan["base_service"], "out": SHOT_OUT}
                    if urls:
                        body["external"] = urls
                    if login:
                        body["login"] = login
                    res = self._run("screenshot", **body)
                    procs = res.get("processes") or []
                    for i, p in enumerate(procs):
                        # a start failure is the last service started
                        down = bool(res.get("infra_error")) and i == len(procs) - 1
                        add(f"service {p.get('name', '')}", not down, str(p.get("log") or ""))
                    resources["processes"] = [{"name": p.get("name", ""),
                                               "rss_mb": p.get("rss_mb")} for p in procs]
                    if res.get("peak_mb") is not None:
                        resources["runner_peak_mb"] = res["peak_mb"]
                    if res.get("infra_error"):
                        raise _ProofFailed("a process service did not start",
                                           str(res["infra_error"]))
                    if res.get("login_error"):
                        add("login", False, str(res["login_error"]))
                        raise _ProofFailed("the QA login (qa.login) failed",
                                           str(res["login_error"]))
                    if login:
                        add("login", True, "")
                    if res.get("shot_error"):
                        add("screenshot", False, str(res["shot_error"]))
                        raise _ProofFailed(f"{plan['base_service']} `/` did not load",
                                           str(res["shot_error"]))
                    shot = f"{repo}/{res.get('screenshot') or ''}".rstrip("/")
                    add("screenshot", True, f"{plan['base_service']} /")
                if compose:
                    self._compose_resources(compose, plan, add, resources)
        except checks.ServiceFailed as e:
            add("services", False, f"{e}\n{e.logs}".strip())
            raise
        total = sum(float(x.get("mem_mb") or 0) for x in resources.get("compose", []))
        total += sum(float(x.get("rss_mb") or 0) for x in resources.get("processes", []))
        resources["total_mb"] = round(total, 1)
        return shot

    def _compose_resources(self, compose, plan: dict, add, resources: dict) -> None:
        """svc_stats and a log tail of each compose project, before it comes down."""
        rows = []
        for name in plan["compose"]:
            project = compose.projects[name]
            try:
                stats = self._svc("svc_stats", project=project).get("stats") or []
            except (SetupInfra, checks.Unsupported) as e:
                stats = []
                log.warning("awak: setup svc_stats %s: %s", project, e)
            for s in stats:
                rows.append({"service": name, "container": s.get("service") or s.get("name"),
                             "mem_mb": round(float(s.get("mem_bytes") or 0) / 1024 / 1024, 1),
                             "cpu_pct": s.get("cpu_pct")})
            try:
                logs = str(self._svc("svc_logs", project=project, tail=60,
                                     redact=compose.redact).get("logs") or "")
            except (SetupInfra, checks.Unsupported) as e:
                logs = f"(no logs: {e})"
            add(f"logs {name}", True, logs)
        resources["compose"] = rows

    # ------------------------------------------------------------- outcome
    def _failed_round(self, run: AwakSetupRun, steps: list[dict], resources: dict,
                      message: str, logs: str) -> None:
        slug = run.project_slug
        text = self._redact(slug, f"{message}\n\n{logs}".strip())
        clean = self._clean_steps(slug, steps)
        if run.round >= MAX_ROUNDS:
            self._set(run.id, "proving", state="failed", steps=clean, resources=resources,
                      screenshot="", error=f"Round {run.round}/{MAX_ROUNDS}: " + text[-OUTPUT_MAX:])
            return
        failed = "\n\n".join(f"$ {s['name']}\n{s['output'][-1500:]}" for s in clean
                             if not s["ok"] and not s.get("red"))
        p = dict(run.proposal or {})
        p.update(turns=0, previous=p.get("runbook"),
                 feedback=(f"Running the runbook in the sandbox failed: {text[-4000:]}"
                           + (f"\n\nFailed steps:\n{failed}" if failed else ""))[:FEEDBACK_MAX])
        self._set(run.id, "proving", state="reading", round=run.round + 1, proposal=p,
                  steps=clean, resources=resources, screenshot="", error=text[-OUTPUT_MAX:])

    def _infra(self, run_id: int, state: str, slug: str, e: Exception) -> None:
        run = self._get(run_id)
        if run is None:
            return
        p = dict(run.proposal or {})
        n = int(p.get("infra_errors") or 0) + 1
        p["infra_errors"] = n
        text = self._redact(slug, f"{type(e).__name__}: {e}")[-OUTPUT_MAX:]
        if n >= MAX_INFRA:
            self._set(run_id, state, state="failed", proposal=p,
                      error=f"Environment problem, {n} times in a row: {text}")
            return
        self._set(run_id, state, proposal=p, error=f"Environment problem (retrying): {text}")
        self.w.sleep(10 * n)

    def _infra_ok(self, run_id: int) -> None:
        """A step went through: the next environment problem counts from one."""
        with self.w.sessions() as db:
            run = db.get(AwakSetupRun, run_id)
            if run is not None and (run.proposal or {}).get("infra_errors"):
                run.proposal = {**run.proposal, "infra_errors": 0}
                db.commit()

    # ------------------------------------------------------------- helpers
    def _config(self, slug: str):
        with self.w.sessions() as db:
            cfg = config_store.load(db, slug)
            keys = {rc.id: config_store.key_row(db, rc.key_id) for rc in cfg.repos}
        return cfg, keys

    def _checkout(self, cfg, rc, keys, sync: bool) -> Path:
        repo = self.w._repo_of(cfg, rc, keys.get(rc.id))
        if sync:
            repo.sync_default()
        return repo.checkout_setup()

    def _read_runbook(self, path: Path, repos: set[str], slug: str
                      ) -> tuple[Runbook | None, dict[str, str], list[str], object]:
        """(runbook, env_help, problems, the raw JSON)."""
        if path.is_symlink() or not path.is_file():
            return None, {}, [f"{path} was not written; write the runbook there"], None
        if path.stat().st_size > MAX_RUNBOOK_BYTES:
            return None, {}, [f"{path} is larger than {MAX_RUNBOOK_BYTES} bytes"], None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeDecodeError) as e:
            return None, {}, [f"{path} is not valid JSON: {e}"], None
        if not isinstance(raw, dict):
            return None, {}, ["the runbook must be one JSON object"], raw
        data = dict(raw)
        help_raw = data.pop("env_help", None) or {}
        env_help = {}
        problems: list[str] = []
        if not isinstance(help_raw, dict):
            problems.append("env_help must be an object of env name -> description")
        else:
            env_help = {str(k): str(v)[:500] for k, v in help_raw.items()
                        if isinstance(k, str) and runbook.ENV_NAME_RE.fullmatch(k)}
        hits = secrets.find(json.dumps(raw), self.w.scan_values_for(slug))
        if hits:
            problems.append("the runbook contains a secret value or a key-like string ("
                            + ", ".join(hits) + "); never write values, declare the name in "
                            "`env` and list it where it is needed")
        rb, errs = runbook.validate(data, repos)
        problems += errs
        if problems:
            return None, env_help, problems, raw
        return rb, {k: self._redact(slug, v) for k, v in env_help.items()}, [], raw

    def _vault(self, slug: str) -> dict[str, str]:
        try:
            return self.w._vault(slug)
        except checks.Unsupported as e:
            raise SetupBlocked(str(e)) from e

    def _run(self, op: str, **payload) -> dict:
        try:
            return self.w.runner.call(op, **payload)
        except RunnerRejected as e:
            raise checks.Unsupported(f"the runner refused {op}: {e}") from e
        except RunnerError as e:
            raise SetupInfra(f"runner {op}: {e}") from e

    def _svc(self, op: str, **payload) -> dict:
        if self.w.svc is None:
            raise SetupBlocked("kemudi-svc is not configured (KEMUDI_SVC_KEY).")
        try:
            res = self.w.svc.call(op, **payload)
        except SvcRejected as e:
            raise checks.Unsupported(f"kemudi-svc refused {op}: {e}") from e
        except SvcError as e:
            raise SetupInfra(f"kemudi-svc {op}: {e}") from e
        if res.get("infra_error"):
            raise SetupInfra(f"kemudi-svc {op}: {res['infra_error']}")
        return res

    def _alive(self, run_id: int) -> None:
        run = self._get(run_id)
        if run is None or run.state != "proving":
            raise _Cancelled()

    def _redact(self, slug: str, text: str) -> str:
        return secrets.redact(text or "", self.w.redact_values_for(slug))

    def _clean_steps(self, slug: str, steps: list[dict]) -> list[dict]:
        values = self.w.redact_values_for(slug)
        return [{**s, "name": secrets.redact(str(s["name"]), values)[:200],
                 "output": secrets.redact(str(s.get("output") or ""), values)[-OUTPUT_MAX:]}
                for s in steps]

    def _get(self, run_id: int) -> AwakSetupRun | None:
        with self.w.sessions() as db:
            return db.get(AwakSetupRun, run_id)

    def _set(self, run_id: int, expect: str, **fields) -> bool:
        with self.w.sessions() as db:
            return transition(db, run_id, expect, **fields)

    def _add_cost(self, run_id: int, cost: float) -> None:
        with self.w.sessions() as db:
            run = db.get(AwakSetupRun, run_id)
            if run is not None:
                run.cost_idr = (run.cost_idr or 0.0) + float(cost or 0.0)
                db.commit()


def _compose_step(add, kind: str, detail: dict) -> None:
    """Compose's events as steps (svc_up of a service, init, seed)."""
    if kind == "compose_up":
        what = f"start {detail.get('service', '')}"
        if detail.get("stage") and not detail.get("ok"):
            what += f" ({detail['stage']})"
        add(what, bool(detail.get("ok")), str(detail.get("logs_tail") or ""),
            built=list(detail.get("built") or []))
    elif kind in ("init", "seed"):
        add(f"{kind} {detail.get('command', '')}", detail.get("exit") == 0,
            f"in {detail.get('service', '')}, exit {detail.get('exit')}")


def _inside(d: Path, rel: str) -> Path | None:
    p = d.joinpath(*[x for x in rel.split("/") if x])
    try:
        if not p.resolve().is_relative_to(d.resolve()):
            return None
    except OSError:
        return None
    return p


def _tree(d: Path):
    def read(rel: str) -> str | None:
        p = _inside(d, rel)
        if p is None or not p.is_file() or p.stat().st_size > MAX_READ_BYTES:
            return None
        try:
            return p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
    return read


def _list_dir(d: Path):
    def ls(rel: str) -> list[str]:
        p = _inside(d, rel) if rel else d
        if p is None or not p.is_dir():
            return []
        return sorted(x.name for x in p.iterdir() if x.is_dir() and not x.is_symlink())
    return ls

