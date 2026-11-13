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
from typing import Callable, Iterator, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.orm import Session, sessionmaker

from ..auth import TaigaUser
from ..config import Settings, get_settings
from ..deps import actor, admin, get_db, get_sessions, member
from ..store import AwakJob, AwakKey, AwakProject, AwakRepo, record_decision
from . import config_store, crypto, gitops, secrets, ssh
from .crypto import SecretKeyMissing
from .detect import FIELDS as COMMAND_FIELDS
from .detect import detect_commands
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


def _settings_out(db: Session, slug: str) -> dict:
    p = db.get(AwakProject, slug)
    cfg = config_store.load(db, slug)
    key = config_store.key_row(db, p.ssh_key_id) if p else None
    return {
        **{k: getattr(cfg, k) for k in config_store.SETTING_FIELDS},
        "ssh_public_key": key.public_key if key else None,
        "ssh_fingerprint": key.fingerprint if key else None,
        "preflight": (p.preflight if p else {}) or {},
        # Jobs run on the local executor until remote execution ships.
        "remote_execution": False,
        "updated_by": p.updated_by if p else None,
        "updated_at": p.updated_at if p else None,
    }


@router.get("/settings")
def get_agent_settings(slug: str, _: TaigaUser = Depends(member), db: Session = Depends(get_db)):
    return _settings_out(db, slug)


@router.put("/settings")
def put_agent_settings(
    slug: str,
    body: AgentSettings,
    user: TaigaUser = Depends(admin),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    start_worker: Callable[[], None] = Depends(get_worker_starter),
):
    p = db.get(AwakProject, slug)
    if p is None:
        p = AwakProject(slug=slug, **config_store.DEFAULTS)
        db.add(p)
    new = body.model_dump()
    changed = {k: new[k] for k in config_store.SETTING_FIELDS if getattr(p, k) != new[k]}
    if p.ssh_host and ({"ssh_host", "ssh_port"} & set(changed)):
        # A new machine: never trust the old machine's host key for it.
        ssh.forget_host(settings, slug, p.ssh_host)
    for k, v in changed.items():
        setattr(p, k, v)
    if changed:
        p.updated_by, p.updated_at = actor(user), config_store.now()
    db.commit()
    if changed:
        # The deploy command is admin text that may hold a token: log that it
        # changed, not what it is.
        detail = {k: ("(changed)" if k == "deploy_command" else v) for k, v in changed.items()}
        record_decision(db, actor(user), "awak_settings", slug, {"changed": detail})
    if p.enabled:
        start_worker()
    return _settings_out(db, slug)


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
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,99}$")
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
                db: Session = Depends(get_db)):
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
    if _name_taken(db, slug, body.name, repo_id):
        raise HTTPException(409, f"a repo named {body.name!r} already exists")
    old_host = ssh.url_host(r.url)
    new = body.model_dump()
    changed = sorted(k for k, v in new.items() if getattr(r, k) != v)
    for k in changed:
        setattr(r, k, new[k])
    if "url" in changed and old_host and old_host != ssh.url_host(r.url):
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
           "host_key": None, "detected": {}, "error": None}
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
        prefix = f"{r.subdir}/" if r.subdir else ""

        def tree(path: str) -> str | None:
            try:
                return gitops._git("show", f"refs/heads/{branch}:{prefix}{path}", git_dir=bare,
                                   timeout=30)
            except gitops.GitError:
                return None

        res["detected"] = detect_commands(tree)
    res["ok"] = res["clone"] and res["push"] and res["default_branch_found"]
    return res


@router.post("/repos/{repo_id}/check")
def check_repo_access(slug: str, repo_id: int, user: TaigaUser = Depends(admin),
                      db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
                      run: CommandRunner = Depends(get_command_runner)):
    r = _get_repo(db, slug, repo_id)
    key = config_store.key_row(db, r.key_id)
    if not ssh.is_local_url(r.url) and key is None:
        raise HTTPException(409, "generate a deploy key and add it to the git host first")
    try:
        res = check_repo(settings, slug, r, key, run)
    except SecretKeyMissing as e:
        raise _no_secret_key(e) from e
    filled = [f for f in COMMAND_FIELDS if not getattr(r, f) and res["detected"].get(f)]
    for f in filled:
        setattr(r, f, res["detected"][f])
    r.last_check = {**res, "checked_at": config_store.now().isoformat()}
    db.commit()
    record_decision(db, actor(user), "awak_repo_check", slug,
                    {"repo": r.name, "ok": res["ok"], "filled": filled})
    return res


