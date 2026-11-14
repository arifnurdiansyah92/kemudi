"""Project settings -> Agent: `/projects/{slug}/agent/...`.

Reads need project membership, writes need project admin. Every write is a
`decisions` row without secret material. Responses carry public keys and
fingerprints only.
"""

import logging
import shlex
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Callable, Iterator, Literal

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.orm import Session, sessionmaker

from ..auth import ProjectAccess, TaigaUser
from ..config import Settings, get_settings
from ..deps import access, actor, admin, get_db, get_llm, get_sessions, member
from ..llm import LLM
from ..store import AwakJob, AwakKey, AwakProject, AwakRepo, AwakRole, record_decision
from . import config_store, crypto, detect, gitops, llm_conn, prompts, secrets, ssh
from .bot_access import BotAccess, BotAccessError
from .crypto import SecretKeyMissing
from .detect import FIELDS as COMMAND_FIELDS
from .detect import detect_apps, detect_commands
from .ssh import CommandRunner

log = logging.getLogger(__name__)

router = APIRouter(prefix="/projects/{slug}/agent")


# --- worker start ------------------------------------------------------------

_worker_lock = threading.Lock()
_worker_started = False


def start_worker_once(settings: Settings, sessions: sessionmaker[Session]) -> None:
    """Start the Awak worker thread unless it already runs in this process."""
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        from .service import start_worker

        try:
            start_worker(settings, sessions)
        except Exception:  # noqa: BLE001 - a bad Awak config must not break the API
            log.exception("could not start the Awak worker")
            return
        _worker_started = True


def get_worker_starter(
    settings: Settings = Depends(get_settings),
    sessions: sessionmaker[Session] = Depends(get_sessions),
) -> Callable[[], None]:
    return lambda: start_worker_once(settings, sessions)


# --- settings ----------------------------------------------------------------


class AgentSettings(BaseModel):
    enabled: bool
    merge_mode: Literal["manual", "approve", "auto"]
    deploy_command: str = Field("", max_length=2000)
    executor: Literal["local", "ssh"]
    ssh_host: str = Field("", max_length=255, pattern=r"^[A-Za-z0-9.\-:\[\]]*$")
    ssh_port: int = Field(22, ge=1, le=65535)
    ssh_user: str = Field("", max_length=64, pattern=r"^[a-z_][a-z0-9_\-]*$|^$")

    @model_validator(mode="after")
    def _ssh_target(self):
        if self.executor == "ssh" and not (self.ssh_host and self.ssh_user):
            raise ValueError("executor ssh needs ssh_host and ssh_user")
        if self.ssh_host.startswith("-"):
            raise ValueError("invalid ssh_host")
        return self


def get_bot_access(settings: Settings = Depends(get_settings)) -> BotAccess:
    """Overridden in tests."""
    return BotAccess(settings)


def _settings_out(db: Session, slug: str, is_admin: bool, bot_access: dict) -> dict:
    p = db.get(AwakProject, slug)
    cfg = config_store.load(db, slug)
    key = config_store.key_row(db, p.ssh_key_id) if p else None
    return {
        # Whether the Awak bot user can open the project (Taiga 404s otherwise).
        "bot_access": bot_access,
        # The worker's last failure for this project, cleared on its next good pass.
        "last_error": (p.last_error or None) if p else None,
        "last_error_at": p.last_error_at if p else None,
        **{k: getattr(cfg, k) for k in config_store.SETTING_FIELDS},
        # The deploy command may hold a token: admins only; members see whether
        # one is set.
        "deploy_command": cfg.deploy_command if is_admin else None,
        "deploy_command_set": bool(cfg.deploy_command.strip()),
        "ssh_public_key": key.public_key if key else None,
        "ssh_fingerprint": key.fingerprint if key else None,
        "preflight": (p.preflight if p else {}) or {},
        # Jobs run on the local executor until remote execution ships.
        "remote_execution": False,
        "updated_by": p.updated_by if p else None,
        "updated_at": p.updated_at if p else None,
    }


@router.get("/settings")
def get_agent_settings(slug: str, acc: ProjectAccess = Depends(access),
                       db: Session = Depends(get_db),
                       bot: BotAccess = Depends(get_bot_access)):
    return _settings_out(db, slug, acc.is_admin, bot.check(slug))


def _grant_bot(db: Session, bot: BotAccess, user: TaigaUser, slug: str) -> dict:
    """Add the bot as a member with the admin's token; a decision when added."""
    res = bot.grant(slug, user.token)
    if res["added"]:
        record_decision(db, actor(user), "awak_bot_access", slug,
                        {"username": bot.username, "role": res["role"]})
    return res


@router.post("/bot-access")
def give_bot_access(slug: str, user: TaigaUser = Depends(admin), db: Session = Depends(get_db),
                    bot: BotAccess = Depends(get_bot_access)):
    """Make the Awak bot user a member of the Taiga project (caller's token)."""
    try:
        res = _grant_bot(db, bot, user, slug)
    except BotAccessError as e:
        raise HTTPException(e.status, str(e)) from e
    return {**res, "bot_access": bot.check(slug, fresh=True)}


@router.put("/settings")
def put_agent_settings(
    slug: str,
    body: AgentSettings,
    user: TaigaUser = Depends(admin),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    start_worker: Callable[[], None] = Depends(get_worker_starter),
    bot: BotAccess = Depends(get_bot_access),
):
    p = db.get(AwakProject, slug)
    if p is None:
        p = AwakProject(slug=slug, **config_store.DEFAULTS)
        db.add(p)
    new = body.model_dump()
    changed = {k: new[k] for k in config_store.SETTING_FIELDS if getattr(p, k) != new[k]}
    if (p.ssh_host and ({"ssh_host", "ssh_port"} & set(changed))
            and p.ssh_host not in _hosts_in_use(db, slug, machine=False)):
        # A new machine: never trust the old machine's host key for it (unless
        # a repo still uses that host: known_hosts is one file per project).
        ssh.forget_host(settings, slug, p.ssh_host)
    for k, v in changed.items():
        setattr(p, k, v)
    if {"executor", "ssh_host", "ssh_port", "ssh_user"} & set(changed):
        p.preflight = {}  # a check of the old machine says nothing about the new one
    if changed:
        p.updated_by, p.updated_at = actor(user), config_store.now()
    db.commit()
    if changed:
        # The deploy command is admin text that may hold a token: log that it
        # changed, not what it is.
        detail = {k: ("(changed)" if k == "deploy_command" else v) for k, v in changed.items()}
        record_decision(db, actor(user), "awak_settings", slug, {"changed": detail})
    grant_error = None
    if p.enabled:
        # Without membership Taiga 404s the project for the bot and nothing is
        # picked up; a failure here does not undo the save, it is reported.
        try:
            _grant_bot(db, bot, user, slug)
        except BotAccessError as e:
            grant_error = str(e)
        start_worker()
    status = bot.check(slug, fresh=True)
    if grant_error and not status["ok"]:
        status = {**status, "error": grant_error}
    return _settings_out(db, slug, True, status)


def _hosts_in_use(db: Session, slug: str, skip_repo: int | None = None,
                  machine: bool = True) -> set[str]:
    """SSH hosts the project's repos (and machine) use. They share one
    known_hosts, so a host is forgotten only when nothing else uses it."""
    hosts = {ssh.url_host(r.url) for r in db.query(AwakRepo).filter_by(project_slug=slug)
             if r.id != skip_repo}
    p = db.get(AwakProject, slug)
    if machine and p is not None and p.ssh_host:
        hosts.add(p.ssh_host)
    hosts.discard("")
    return hosts


# --- jobs --------------------------------------------------------------------


def _job_out(j: AwakJob) -> dict:
    return {
        "id": j.id, "story_id": j.story_id, "story_ref": j.story_ref, "branch": j.branch,
        "state": j.state, "phase": j.phase, "attempts": j.attempts, "cost_idr": j.cost_idr,
        "repo_id": j.repo_id, "role_id": j.role_id, "prompt_version": j.prompt_version,
        "merge_state": j.merge_state, "merged_sha": j.merged_sha,
        "started_at": j.started_at, "updated_at": j.updated_at,
    }


@router.get("/jobs")
def get_agent_jobs(slug: str, _: TaigaUser = Depends(member), db: Session = Depends(get_db)):
    jobs = (db.query(AwakJob).filter_by(project_slug=slug)
            .order_by(AwakJob.id.desc()).limit(50).all())
    return {"jobs": [_job_out(j) for j in jobs]}


# --- repos -------------------------------------------------------------------

# Mirrors infra/runner/runner.py ALLOWED_PROGRAMS (the runner enforces it).
ALLOWED_PROGRAMS = {"pnpm", "npm", "npx", "yarn", "node", "python", "uv", "pytest", "make",
                    "go", "cargo"}
ACCESS_CHECK_REF = "refs/heads/awak/kemudi-access-check"


def get_command_runner() -> CommandRunner:
    return ssh.subprocess_runner


def _no_secret_key(e: SecretKeyMissing) -> HTTPException:
    return HTTPException(503, str(e) or crypto.MISSING_MESSAGE)


class RepoIn(BaseModel):
    # The checkout folder name in the workspace (the runner validates the same shape).
    name: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
    role: Literal["web", "api", "mobile", "other"]
    url: str = Field(max_length=500)
    default_branch: str = Field("main", pattern=r"^[A-Za-z0-9._/-]{1,100}$")
    subdir: str = Field("", max_length=200)
    install_cmd: str = Field("", max_length=2000)
    check_cmd: str = Field("", max_length=2000)
    build_cmd: str = Field("", max_length=2000)
    run_cmd: str = Field("", max_length=2000)

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        v = v.strip()
        if any(c.isspace() for c in v) or v.startswith("-"):
            raise ValueError("invalid git URL")
        if not (ssh.is_local_url(v) or ssh.is_ssh_url(v)):
            raise ValueError("use an SSH URL (git@host:owner/repo.git or ssh://...) so a "
                             "deploy key can be used; HTTPS URLs are not supported")
        return v

    @field_validator("default_branch")
    @classmethod
    def _branch(cls, v: str) -> str:
        if v.startswith(("-", "/")) or v.endswith(("/", ".lock")) or ".." in v:
            raise ValueError("invalid branch name")
        return v

    @field_validator("subdir")
    @classmethod
    def _subdir(cls, v: str) -> str:
        v = v.strip()
        if v.startswith(("/", "\\")) or ":" in v:
            raise ValueError("subdir must be a relative path inside the repo")
        v = v.replace("\\", "/").strip("/")
        if v and any(p in ("", ".", "..") for p in v.split("/")):
            raise ValueError("subdir must be a relative path inside the repo, without '..'")
        return v

    @field_validator("install_cmd", "check_cmd", "build_cmd", "run_cmd")
    @classmethod
    def _commands(cls, v: str) -> str:
        for line in v.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                argv = shlex.split(line)
            except ValueError as e:
                raise ValueError(f"cannot parse {line!r}: {e}") from e
            if argv[0] not in ALLOWED_PROGRAMS:
                raise ValueError(f"{argv[0]!r} is not an allowed program; use one of "
                                 f"{', '.join(sorted(ALLOWED_PROGRAMS))} (no shell)")
        return v.strip()


def _repo_out(db: Session, r: AwakRepo) -> dict:
    key = config_store.key_row(db, r.key_id)
    return {
        **{f: getattr(r, f) for f in RepoIn.model_fields},
        "id": r.id,
        "has_key": key is not None,
        "public_key": key.public_key if key else None,
        "fingerprint": key.fingerprint if key else None,
        "local": ssh.is_local_url(r.url),
        "last_check": r.last_check or {},
    }


def _allowed_local(settings: Settings, url: str) -> None:
    """A local path may only be the Kemudi repo itself (settings.host_git):
    anything else would let an admin read or push any path the orchestrator
    can reach."""
    if ssh.is_local_url(url) and (url.startswith("file://") or url != settings.host_git):
        raise HTTPException(400, "a local path is only allowed for Kemudi's own repo "
                                 f"({settings.host_git}); use an SSH URL")


def _get_repo(db: Session, slug: str, repo_id: int) -> AwakRepo:
    r = db.get(AwakRepo, repo_id)
    if r is None or r.project_slug != slug:
        raise HTTPException(404, "no such repo")
    return r


def _name_taken(db: Session, slug: str, name: str, repo_id: int | None = None) -> bool:
    q = db.query(AwakRepo).filter_by(project_slug=slug, name=name)
    return any(r.id != repo_id for r in q)


@router.get("/repos")
def list_repos(slug: str, _: TaigaUser = Depends(member), db: Session = Depends(get_db)):
    rows = (db.query(AwakRepo).filter_by(project_slug=slug)
            .order_by(AwakRepo.position, AwakRepo.id).all())
    return {"repos": [_repo_out(db, r) for r in rows]}


@router.post("/repos")
def create_repo(slug: str, body: RepoIn, user: TaigaUser = Depends(admin),
                db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    _allowed_local(settings, body.url)
    if _name_taken(db, slug, body.name):
        raise HTTPException(409, f"a repo named {body.name!r} already exists")
    last = (db.query(AwakRepo).filter_by(project_slug=slug)
            .order_by(AwakRepo.position.desc()).first())
    r = AwakRepo(project_slug=slug, position=(last.position + 1) if last else 0,
                 updated_by=actor(user), **body.model_dump())
    db.add(r)
    db.commit()
    record_decision(db, actor(user), "awak_repo", slug,
                    {"op": "create", "repo": r.name, "url": r.url, "role": r.role})
    return _repo_out(db, r)


@router.put("/repos/{repo_id}")
def update_repo(slug: str, repo_id: int, body: RepoIn, user: TaigaUser = Depends(admin),
                db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    r = _get_repo(db, slug, repo_id)
    _allowed_local(settings, body.url)
    if _name_taken(db, slug, body.name, repo_id):
        raise HTTPException(409, f"a repo named {body.name!r} already exists")
    old_host = ssh.url_host(r.url)
    new = body.model_dump()
    changed = sorted(k for k, v in new.items() if getattr(r, k) != v)
    for k in changed:
        setattr(r, k, new[k])
    if ("url" in changed and old_host and old_host != ssh.url_host(r.url)
            and old_host not in _hosts_in_use(db, slug, skip_repo=r.id)):
        ssh.forget_host(settings, slug, old_host)
    if changed:
        r.updated_by, r.updated_at = actor(user), config_store.now()
        if "url" in changed or "default_branch" in changed:
            r.last_check = {}
    db.commit()
    if changed:
        record_decision(db, actor(user), "awak_repo", slug,
                        {"op": "update", "repo": r.name, "changed": changed})
    return _repo_out(db, r)


@router.delete("/repos/{repo_id}", status_code=204)
def delete_repo(slug: str, repo_id: int, user: TaigaUser = Depends(admin),
                db: Session = Depends(get_db)):
    r = _get_repo(db, slug, repo_id)
    if db.query(AwakJob).filter_by(repo_id=r.id, state="running").count():
        raise HTTPException(409, "a running job uses this repo; stop it first")
    key = config_store.key_row(db, r.key_id)
    name = r.name
    db.delete(r)
    if key is not None:
        db.delete(key)
    db.commit()
    record_decision(db, actor(user), "awak_repo_delete", slug, {"repo": name})
    return Response(status_code=204)


@router.post("/repos/{repo_id}/key")
def generate_repo_key(slug: str, repo_id: int, user: TaigaUser = Depends(admin),
                      db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    r = _get_repo(db, slug, repo_id)
    if ssh.is_local_url(r.url):
        raise HTTPException(409, "a local repo needs no deploy key")
    try:
        private, public, fp = crypto.generate_keypair(f"kemudi-{slug}-{r.name}")
        token = crypto.encrypt(settings, private)
    except SecretKeyMissing as e:
        raise _no_secret_key(e) from e
    del private
    old = config_store.key_row(db, r.key_id)
    key = AwakKey(owner_kind="repo", owner_id=r.id, public_key=public, fingerprint=fp,
                  private_key_enc=token, created_by=actor(user))
    db.add(key)
    db.flush()
    r.key_id = key.id
    if old is not None:
        db.delete(old)
    r.updated_by, r.updated_at = actor(user), config_store.now()
    db.commit()
    record_decision(db, actor(user), "awak_repo_key", slug,
                    {"repo": r.name, "fingerprint": fp, "replaced": old is not None})
    return {"public_key": public, "fingerprint": fp}


def bare_path(settings: Settings, r: AwakRepo) -> str:
    """Same rule as worker.repo_for: the seeded Kemudi repo keeps its bare repo."""
    if r.url == settings.host_git:
        return settings.bare_repo
    return str(Path(settings.repos_dir) / f"{r.id}.git")


@contextmanager
def _remote(settings: Settings, slug: str, key: AwakKey | None,
            local: bool) -> Iterator[tuple[dict[str, str], list[str]]]:
    """(git env extras, strings to scrub from error output)."""
    if local:
        yield {}, []
        return
    known_hosts = ssh.known_hosts_path(settings, slug)
    known_hosts.parent.mkdir(parents=True, exist_ok=True)
    with ssh.key_file(settings, key) as key_path:
        yield ssh.git_ssh_env(key_path, known_hosts), [str(key_path)]


def _clean(text: str, scrub: list[str]) -> str:
    for s in scrub:
        text = text.replace(s, "<key>")
    return secrets.redact(text.strip(), secrets.known_values())[:500]


def check_repo(settings: Settings, slug: str, r: AwakRepo, key: AwakKey | None,
               run: CommandRunner) -> dict:
    """Can Kemudi clone and push? Nothing is created on the remote."""
    res = {"ok": False, "clone": False, "push": False, "default_branch_found": False,
           "host_key": None, "detected": {}, "apps": [], "compose_files": [], "error": None}
    local = ssh.is_local_url(r.url)
    bare = bare_path(settings, r)
    branch = r.default_branch
    fetched = False
    with _remote(settings, slug, key, local) as (extra, scrub):
        env = gitops.git_env(extra)
        code, out = run(["git", "ls-remote", "--heads", r.url], env, 60)
        if code != 0:
            res["error"] = _clean(out, scrub) or f"git ls-remote exited {code}"
        else:
            res["clone"] = True
            heads = {}
            for line in out.splitlines():
                if "\t" in line:
                    sha, ref = line.split("\t", 1)
                    heads[ref.strip()] = sha.strip()
            sha = heads.get(f"refs/heads/{branch}")
            if not sha:
                res["error"] = f"branch {branch!r} not found on the remote"
            else:
                res["default_branch_found"] = True
                gitops.Repo(bare, r.url, settings.workspace_dir, 0).ensure_bare()
                code, out = run(["git", "--git-dir", bare, "fetch", "--no-tags", r.url,
                                 f"+refs/heads/{branch}:refs/heads/{branch}"], env, 300)
                fetched = code == 0
                if not fetched:
                    res["error"] = _clean(out, scrub) or "fetch failed"
                else:
                    code, out = run(["git", "--git-dir", bare, "push", "--dry-run", r.url,
                                     f"{sha}:{ACCESS_CHECK_REF}"], env, 60)
                    res["push"] = code == 0
                    if code != 0:
                        res["error"] = _clean(out, scrub) or "no write access"
    if not local:
        res["host_key"] = ssh.host_key_fingerprint(ssh.known_hosts_path(settings, slug),
                                                   ssh.url_host(r.url))
    if fetched:
        def tree(path: str) -> str | None:
            try:
                return gitops._git("show", f"refs/heads/{branch}:{path}", git_dir=bare,
                                   timeout=30)
            except gitops.GitError:
                return None

        found = detect_apps(tree, lambda path: gitops.list_dirs(bare, branch, path))
        res["apps"], res["compose_files"] = found["apps"], found["compose_files"]
        if r.subdir:
            # The admin chose the app's folder: detect there only.
            res["detected"] = detect_commands(lambda p: tree(f"{r.subdir}/{p}"))
        else:
            # The root app, else the first subfolder app (with its `subdir`).
            res["detected"] = detect.suggestion(found)
    res["ok"] = res["clone"] and res["push"] and res["default_branch_found"]
    return res


@router.post("/repos/{repo_id}/check")
def check_repo_access(slug: str, repo_id: int, user: TaigaUser = Depends(admin),
                      db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
                      run: CommandRunner = Depends(get_command_runner)):
    r = _get_repo(db, slug, repo_id)
    _allowed_local(settings, r.url)
    key = config_store.key_row(db, r.key_id)
    if not ssh.is_local_url(r.url) and key is None:
        raise HTTPException(409, "generate a deploy key and add it to the git host first")
    try:
        res = check_repo(settings, slug, r, key, run)
    except SecretKeyMissing as e:
        raise _no_secret_key(e) from e
    detected = res["detected"]
    if detected.get("subdir") and any(getattr(r, f) for f in COMMAND_FIELDS):
        # Commands from another folder would mix with the ones typed for the root.
        filled = []
    else:
        filled = [f for f in (*COMMAND_FIELDS, "subdir") if not getattr(r, f) and detected.get(f)]
    for f in filled:
        setattr(r, f, res["detected"][f])
    r.last_check = {**res, "checked_at": config_store.now().isoformat()}
    db.commit()
    record_decision(db, actor(user), "awak_repo_check", slug,
                    {"repo": r.name, "ok": res["ok"], "filled": filled})
    return res


# --- execution machine -------------------------------------------------------


def get_runner_health(settings: Settings = Depends(get_settings)) -> Callable[[], bool]:
    def ok() -> bool:
        import httpx

        try:
            r = httpx.get(f"{settings.runner_url.rstrip('/')}/health", timeout=5)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    return ok


def _project_row(db: Session, slug: str) -> AwakProject:
    p = db.get(AwakProject, slug)
    if p is None:
        p = AwakProject(slug=slug, **config_store.DEFAULTS)
        db.add(p)
        db.flush()
    return p


@router.post("/machine/key")
def generate_machine_key(slug: str, user: TaigaUser = Depends(admin),
                         db: Session = Depends(get_db),
                         settings: Settings = Depends(get_settings)):
    """The key Kemudi logs in to the SSH machine with (preflight and deploy)."""
    try:
        private, public, fp = crypto.generate_keypair(f"kemudi-{slug}-machine")
        token = crypto.encrypt(settings, private)
    except SecretKeyMissing as e:
        raise _no_secret_key(e) from e
    del private
    p = _project_row(db, slug)
    old = config_store.key_row(db, p.ssh_key_id)
    key = AwakKey(owner_kind="machine", owner_id=0, public_key=public, fingerprint=fp,
                  private_key_enc=token, created_by=actor(user))
    db.add(key)
    db.flush()
    p.ssh_key_id = key.id
    db.flush()
    if old is not None:
        db.delete(old)
    p.updated_by, p.updated_at = actor(user), config_store.now()
    db.commit()
    record_decision(db, actor(user), "awak_machine_key", slug,
                    {"fingerprint": fp, "replaced": old is not None})
    return {"public_key": public, "fingerprint": fp}


@router.post("/machine/check")
def check_machine(slug: str, user: TaigaUser = Depends(admin), db: Session = Depends(get_db),
                  settings: Settings = Depends(get_settings),
                  run: CommandRunner = Depends(get_command_runner),
                  runner_ok: Callable[[], bool] = Depends(get_runner_health)):
    from . import machine

    cfg = config_store.load(db, slug)
    p = _project_row(db, slug)
    if cfg.executor == "ssh":
        key = config_store.key_row(db, p.ssh_key_id)
        if key is None:
            raise HTTPException(409, "generate the machine key and add it to the machine's "
                                     "authorized_keys first")
        try:
            res = machine.check_ssh(settings, cfg, key, run)
        except SecretKeyMissing as e:
            raise _no_secret_key(e) from e
    else:
        res = machine.check_local(settings, runner_ok)
    out = {**res.to_dict(), "executor": cfg.executor,
           # Jobs run on the local executor until remote execution ships.
           "remote_execution": False}
    p.preflight = out
    db.commit()
    record_decision(db, actor(user), "awak_machine_check", slug,
                    {"executor": cfg.executor, "ok": res.ok, "slots": res.slots,
                     "error": bool(res.error)})
    return out


@router.delete("/machine/host-key", status_code=204)
def forget_machine_host_key(slug: str, user: TaigaUser = Depends(admin),
                            db: Session = Depends(get_db),
                            settings: Settings = Depends(get_settings)):
    cfg = config_store.load(db, slug)
    if cfg.ssh_host:
        ssh.forget_host(settings, slug, cfg.ssh_host)
        p = db.get(AwakProject, slug)
        if p is not None and p.preflight:
            p.preflight = {**p.preflight, "host_key": None}
            db.commit()
    record_decision(db, actor(user), "awak_machine_forget_host", slug, {"host": cfg.ssh_host})
    return Response(status_code=204)


# --- roles -------------------------------------------------------------------

# Fields whose change makes a different prompt (or model) -> version += 1.
PROMPT_FIELDS = ("template", "prompt_overlay", "model", "repo_ids", "allowed_paths",
                 "denied_paths")


def _clean_paths(paths: list[str]) -> list[str]:
    out = []
    for p in paths:
        p = p.strip().replace("\\", "/")
        if not p:
            continue
        parts = p.strip("/").split("/")
        if p.startswith("/") or ":" in p or any(x in ("..", ".") for x in parts) or len(p) > 200:
            raise ValueError(f"{p!r}: use a relative path inside the repo, without '..'")
        out.append(p)
    if len(out) > 50:
        raise ValueError("at most 50 paths")
    return out


class RoleIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    template: Literal["frontend", "backend", "fullstack", "qa"]
    # `both`: stories touching web and backend (and single-area ones when no
    # role covers that area alone).
    area: Literal["web", "backend", "both", "qa"]
    # Empty: use the model of the connection the role resolves to.
    model: str = Field("", pattern=r"^[A-Za-z0-9._:/-]{0,100}$")
    repo_ids: list[int] = Field(default_factory=list, max_length=20)
    allowed_paths: list[str] = Field(default_factory=list)
    denied_paths: list[str] = Field(default_factory=list)
    prompt_overlay: str = ""
    enabled: bool = True

    @field_validator("allowed_paths", "denied_paths")
    @classmethod
    def _paths(cls, v: list[str]) -> list[str]:
        return _clean_paths(v)

    @field_validator("prompt_overlay")
    @classmethod
    def _overlay(cls, v: str) -> str:
        prompts.check_overlay(v, secrets.known_values())
        return v


def _role_out(db: Session, r: AwakRole, settings: Settings) -> dict:
    cfg = config_store.load(db, r.project_slug)
    role = cfg.role(r.id)
    return {
        **{f: getattr(r, f) for f in RoleIn.model_fields},
        "id": r.id,
        "version": r.version,
        "prompt_version": prompts.prompt_version(role, cfg.repos),
        # The resolved model connection (agent > project > server), no key.
        **llm_conn.describe(db, settings, r.project_slug, r.id).public(),
        "updated_by": r.updated_by,
        "updated_at": r.updated_at,
    }


def _get_role(db: Session, slug: str, role_id: int) -> AwakRole:
    r = db.get(AwakRole, role_id)
    if r is None or r.project_slug != slug:
        raise HTTPException(404, "no such role")
    return r


def _check_repo_ids(db: Session, slug: str, repo_ids: list[int]) -> list[int]:
    ids = list(dict.fromkeys(repo_ids))
    known = {r.id for r in db.query(AwakRepo).filter_by(project_slug=slug)}
    unknown = [i for i in ids if i not in known]
    if unknown:
        raise HTTPException(422, f"repos {unknown} do not belong to this project")
    return ids


@router.get("/roles")
def list_roles(slug: str, _: TaigaUser = Depends(member), db: Session = Depends(get_db),
               settings: Settings = Depends(get_settings)):
    rows = db.query(AwakRole).filter_by(project_slug=slug).order_by(AwakRole.id).all()
    return {"roles": [_role_out(db, r, settings) for r in rows],
            "models": settings.model_choices()}


@router.post("/roles")
def create_role(slug: str, body: RoleIn, user: TaigaUser = Depends(admin),
                db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    data = body.model_dump()
    data["repo_ids"] = _check_repo_ids(db, slug, body.repo_ids)
    r = AwakRole(project_slug=slug, version=1, updated_by=actor(user), **data)
    db.add(r)
    db.commit()
    out = _role_out(db, r, settings)
    record_decision(db, actor(user), "awak_role", slug,
                    {"op": "create", "role": r.name, "role_id": r.id, "old_overlay": None,
                     "new_overlay": r.prompt_overlay, "version": out["prompt_version"]})
    return out


@router.put("/roles/{role_id}")
def update_role(slug: str, role_id: int, body: RoleIn, user: TaigaUser = Depends(admin),
                db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    r = _get_role(db, slug, role_id)
    new = body.model_dump()
    new["repo_ids"] = _check_repo_ids(db, slug, body.repo_ids)
    changed = sorted(k for k, v in new.items() if getattr(r, k) != v)
    if not changed:
        return _role_out(db, r, settings)
    old_overlay = r.prompt_overlay
    old_version = _role_out(db, r, settings)["prompt_version"]
    for k in changed:
        setattr(r, k, new[k])
    if set(changed) & set(PROMPT_FIELDS):
        r.version += 1
    r.updated_by, r.updated_at = actor(user), config_store.now()
    db.commit()
    out = _role_out(db, r, settings)
    record_decision(db, actor(user), "awak_role", slug,
                    {"op": "update", "role": r.name, "role_id": r.id, "changed": changed,
                     "old_overlay": old_overlay, "new_overlay": r.prompt_overlay,
                     "old_version": old_version, "version": out["prompt_version"]})
    return out


@router.get("/roles/{role_id}/prompt")
def get_role_prompt(slug: str, role_id: int, _: TaigaUser = Depends(member),
                    db: Session = Depends(get_db)):
    _get_role(db, slug, role_id)
    cfg = config_store.load(db, slug)
    role = cfg.role(role_id)
    scope = prompts.scope_for(role, cfg.repos)
    return {
        "fixed": prompts.KEMUDI_RULES,
        "role": prompts.ROLE_TEMPLATES[role.template],
        "scope": scope.__dict__,
        "overlay": role.prompt_overlay,
        "reminder": prompts.REMINDER,
        "rendered": prompts.render_role(role, cfg.repos),
        "version": prompts.prompt_version(role, cfg.repos),
    }


# --- model connection (BYOK) -------------------------------------------------
# docs/superpowers/specs/2026-11-14-awak-byok-design.md. A level is a whole
# connection or nothing; the key is write-only (key_set + key_last4).


class LlmIn(BaseModel):
    base_url: str = Field("", max_length=500)
    model: str = Field("", max_length=100)
    # Empty keeps the stored key.
    api_key: str = Field("", max_length=1000)
    # Removes the level (the agent then uses the project default, the project
    # the server default).
    clear: bool = False

    @field_validator("api_key")
    @classmethod
    def _key(cls, v: str) -> str:
        v = v.strip()
        if any(c.isspace() for c in v):
            raise ValueError("the API key cannot contain spaces")
        return v

    @model_validator(mode="after")
    def _level(self):
        if self.clear:
            return self
        self.base_url = llm_conn.validate_base_url(self.base_url)
        self.model = self.model.strip()
        if not self.model or any(c.isspace() for c in self.model):
            raise ValueError("enter the provider's model name, e.g. gpt-4o-mini")
        return self


def get_llm_transport() -> httpx.BaseTransport | None:
    """Overridden in tests with an httpx.MockTransport."""
    return None


def _llm_out(db: Session, settings: Settings, slug: str, row, role_id: int | None) -> dict:
    return {
        **llm_conn.level_out(row),
        "effective": llm_conn.describe(db, settings, slug, role_id).public(),
        "server_default": {"model": settings.awak_model,
                           "host": llm_conn.server_default(settings, "").host},
        "updated_by": getattr(row, "updated_by", None),
        "updated_at": getattr(row, "updated_at", None),
    }


def _put_level(db: Session, settings: Settings, user: TaigaUser, slug: str, row,
               body: LlmIn, role_id: int | None) -> None:
    if body.clear:
        llm_conn.clear_level(row)
        detail = {"op": "clear"}
    else:
        try:
            key_changed = llm_conn.set_level(settings, row, body.base_url, body.model,
                                             body.api_key)
        except SecretKeyMissing as e:
            db.rollback()
            raise _no_secret_key(e) from e
        detail = {"op": "set", "base_url": body.base_url, "model": body.model,
                  "key_changed": key_changed}
    row.updated_by, row.updated_at = actor(user), config_store.now()
    db.commit()
    record_decision(db, actor(user), "awak_llm", slug,
                    {"level": "agent" if role_id else "project", "role_id": role_id, **detail})


def _test(db: Session, settings: Settings, slug: str, row, role_id: int | None,
          body: LlmIn | None, transport) -> dict:
    """Test unsaved values when a body is sent, else the resolved connection.
    A stored key is reused only for the base URL it was saved with."""
    try:
        if body is not None and not body.clear:
            key = body.api_key
            if not key and row is not None and row.llm_base_url == body.base_url:
                key = llm_conn.stored_key(settings, row)
            conn = llm_conn.Connection(body.base_url, key, body.model,
                                       "agent" if role_id else "project")
        else:
            conn = llm_conn.resolve(db, settings, slug, role_id)
    except SecretKeyMissing as e:
        raise _no_secret_key(e) from e
    return llm_conn.check_connection(conn, transport)


@router.get("/llm")
def get_project_llm(slug: str, _: TaigaUser = Depends(member), db: Session = Depends(get_db),
                    settings: Settings = Depends(get_settings)):
    return _llm_out(db, settings, slug, db.get(AwakProject, slug), None)


@router.put("/llm")
def put_project_llm(slug: str, body: LlmIn, user: TaigaUser = Depends(admin),
                    db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    p = _project_row(db, slug)
    _put_level(db, settings, user, slug, p, body, None)
    return _llm_out(db, settings, slug, p, None)


@router.post("/llm/test")
def test_project_llm(slug: str, body: LlmIn | None = None, _: TaigaUser = Depends(admin),
                     db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
                     transport=Depends(get_llm_transport)):
    return _test(db, settings, slug, db.get(AwakProject, slug), None, body, transport)


class ModelsIn(BaseModel):
    role_id: int | None = None
    # Unsaved values; without base_url the saved connection that applies is used.
    base_url: str = Field("", max_length=500)
    api_key: str = Field("", max_length=1000)

    @field_validator("api_key")
    @classmethod
    def _key(cls, v: str) -> str:
        v = v.strip()
        if any(c.isspace() for c in v):
            raise ValueError("the API key cannot contain spaces")
        return v

    @field_validator("base_url")
    @classmethod
    def _url(cls, v: str) -> str:
        return llm_conn.validate_base_url(v) if v.strip() else ""


@router.post("/llm/models")
def list_llm_models(slug: str, body: ModelsIn | None = None, _: TaigaUser = Depends(admin),
                    db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
                    transport=Depends(get_llm_transport)):
    """Model ids the provider offers, for the connection that would apply:
    unsaved base URL/key when given (a stored key only for its own base URL),
    else the role level, else the project level, else the server default."""
    body = body or ModelsIn()
    role = _get_role(db, slug, body.role_id) if body.role_id else None
    row = role if role is not None else db.get(AwakProject, slug)
    try:
        if body.base_url:
            key = body.api_key
            if not key and row is not None and row.llm_base_url == body.base_url \
                    and row.llm_api_key_enc:
                key = llm_conn.stored_key(settings, row)
            conn = llm_conn.Connection(body.base_url, key, "",
                                       "agent" if role is not None else "project")
        else:
            conn = llm_conn.resolve(db, settings, slug, body.role_id)
    except SecretKeyMissing as e:
        raise _no_secret_key(e) from e
    return llm_conn.list_models(conn, transport)


@router.get("/roles/{role_id}/llm")
def get_role_llm(slug: str, role_id: int, _: TaigaUser = Depends(member),
                 db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    return _llm_out(db, settings, slug, _get_role(db, slug, role_id), role_id)


@router.put("/roles/{role_id}/llm")
def put_role_llm(slug: str, role_id: int, body: LlmIn, user: TaigaUser = Depends(admin),
                 db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    r = _get_role(db, slug, role_id)
    _put_level(db, settings, user, slug, r, body, role_id)
    return _llm_out(db, settings, slug, r, role_id)


@router.post("/roles/{role_id}/llm/test")
def test_role_llm(slug: str, role_id: int, body: LlmIn | None = None,
                  _: TaigaUser = Depends(admin), db: Session = Depends(get_db),
                  settings: Settings = Depends(get_settings),
                  transport=Depends(get_llm_transport)):
    r = _get_role(db, slug, role_id)
    return _test(db, settings, slug, r, role_id, body, transport)


# --- story merge (approve mode) ----------------------------------------------


def get_bot_taiga(settings: Settings = Depends(get_settings)):
    """The Awak bot's Taiga client (local stack only: Taiga() asserts it)."""
    from .taiga import Taiga

    return Taiga(settings.taiga_api_url, settings.awak_username, settings.awak_password)


def _story_job(db: Session, slug: str, story_id: int) -> AwakJob | None:
    return db.query(AwakJob).filter_by(project_slug=slug, story_id=story_id).one_or_none()


def _merge_blocker(db: Session, slug: str, job: AwakJob | None) -> str | None:
    """Why Merge cannot be requested now (the card's tag is checked separately)."""
    from .merge import effective_mode

    if job is None:
        return "Awak has no job for this story"
    if not config_store.is_enabled(db, slug):
        return "Awak is turned off for this project"
    if effective_mode(job.merge_mode, config_store.load(db, slug).merge_mode) != "approve":
        return "the merge mode for this story is not approve"
    if job.state != "passed":
        return "the story has not passed QA"
    if job.merge_state not in ("", "failed"):
        return f"a merge is already {job.merge_state}"
    return None


@router.get("/stories/{story_id}")
def get_story_agent(slug: str, story_id: int, _: TaigaUser = Depends(member),
                    db: Session = Depends(get_db)):
    from .merge import effective_mode

    job = _story_job(db, slug, story_id)
    current = config_store.load(db, slug).merge_mode
    return {
        "job": _job_out(job) if job else None,
        "merge_mode": effective_mode(job.merge_mode, current) if job else current,
        # The card's awaiting-merge tag is not checked here (no Taiga call while
        # polling); the UI has the tags and POST merge checks them.
        "can_merge": _merge_blocker(db, slug, job) is None,
        "merge_state": job.merge_state if job else "",
        "merge_error": job.merge_error if job else "",
    }


@router.post("/stories/{story_id}/merge", status_code=202)
def request_merge(slug: str, story_id: int, user: TaigaUser = Depends(admin),
                  db: Session = Depends(get_db), taiga=Depends(get_bot_taiga),
                  start_worker: Callable[[], None] = Depends(get_worker_starter)):
    from .merge import DONE_TAG
    from .taiga import TaigaError, tag_names

    job = _story_job(db, slug, story_id)
    why = _merge_blocker(db, slug, job)
    if why:
        raise HTTPException(409, why)
    try:
        story = taiga.story(story_id)
    except TaigaError as e:
        raise HTTPException(502, f"could not read the story: {e}") from e
    if DONE_TAG not in tag_names(story):
        raise HTTPException(409, f"the story does not carry {DONE_TAG}")
    # Conditional update: a second click (or a racing request) changes nothing.
    n = (db.query(AwakJob)
         .filter(AwakJob.id == job.id, AwakJob.merge_state.in_(("", "failed")))
         .update({"merge_state": "requested", "merge_error": ""}, synchronize_session=False))
    db.commit()
    if n != 1:
        raise HTTPException(409, "a merge is already requested")
    record_decision(db, actor(user), "awak_merge_requested", slug,
                    {"story_ref": job.story_ref, "branch": job.branch, "last_sha": job.last_sha})
    start_worker()
    return {"merge_state": "requested"}


# --- intake (draft, then create) ---------------------------------------------
# Under /projects/{slug}/intake: any member may draft; Taiga's own add_us
# permission decides create, because stories are created with the caller's
# token. Works whether or not the agent is enabled.

intake_router = APIRouter(prefix="/projects/{slug}/intake")


def get_taiga_for_user(user: TaigaUser = Depends(member),
                       settings: Settings = Depends(get_settings)):
    """The caller's own Taiga client (local stack only: with_token asserts it)."""
    from .taiga import Taiga

    return Taiga.with_token(settings.taiga_api_url, user.token)


def _enabled_areas(db: Session, slug: str) -> set[str]:
    from .intake import AREAS, BOTH

    return {r.area for r in config_store.load(db, slug).roles
            if r.enabled and r.area in (*AREAS, BOTH)}


class IntakeDraft(BaseModel):
    subject: str = Field(min_length=3, max_length=200)
    description: str = Field("", max_length=5000)
    criteria: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(
        default_factory=list, max_length=10)
    area: Literal["web", "backend", "both"]
    hold: bool = False  # the PM keeps it in New even if it qualifies


class IntakeCreate(BaseModel):
    drafts: list[IntakeDraft] = Field(min_length=1, max_length=30)


@intake_router.post("/draft")
async def intake_draft(
    slug: str,
    text: str = Form(""),
    lang: Literal["id", "en"] = Form("id"),
    file: UploadFile | None = File(None),
    _: TaigaUser = Depends(member),
    llm: LLM = Depends(get_llm),
    db: Session = Depends(get_db),
):
    """Drafts only: nothing is created in Taiga."""
    from ..documents import extract_text
    from ..llm import LLMError
    from .intake import draft_stories

    body = text.strip()
    if file is not None:
        try:
            body += "\n\n" + extract_text(file.filename or "", await file.read())
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
    if not body.strip():
        raise HTTPException(400, "send text or a file")
    try:
        drafts = draft_stories(llm, body, lang)
    except LLMError as e:
        raise HTTPException(502, f"the model did not return stories: {e}") from e
    areas = _enabled_areas(db, slug)
    out = []
    for d in drafts:
        ready, reason = d.auto_ready(areas)
        out.append({"subject": d.subject, "description": d.description,
                    "criteria": d.criteria, "area": d.area, "ready": ready, "reason": reason})
    return {"drafts": out}


@intake_router.post("/create")
def intake_create(slug: str, body: IntakeCreate, user: TaigaUser = Depends(member),
                  db: Session = Depends(get_db), taiga=Depends(get_taiga_for_user)):
    from .intake import StoryDraft, create_stories
    from .taiga import TaigaError

    drafts = [StoryDraft(subject=d.subject, description=d.description, criteria=d.criteria,
                         area=d.area) for d in body.drafts]
    hold = {i for i, d in enumerate(body.drafts) if d.hold}
    try:
        created = create_stories(taiga, slug, drafts, _enabled_areas(db, slug), hold)
    except TaigaError as e:
        if "HTTP 403" in str(e):
            raise HTTPException(403, "Taiga does not let you add stories to this project") from e
        if "HTTP 401" in str(e):
            raise HTTPException(401, "your Taiga session expired; sign in again") from e
        raise HTTPException(502, secrets.redact(str(e), secrets.known_values())) from e
    chars = sum(len(d.subject) + len(d.description) + sum(map(len, d.criteria))
                for d in body.drafts)
    record_decision(db, actor(user), "awak_intake", slug,
                    {"stories": [c["ref"] for c in created], "chars": chars,
                     "held": sorted(hold)})
    return {"stories": created}
