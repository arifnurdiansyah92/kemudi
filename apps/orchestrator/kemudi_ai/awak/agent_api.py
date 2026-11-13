"""Project settings -> Agent: `/projects/{slug}/agent/...`.

Reads need project membership, writes need project admin. Every write is a
`decisions` row without secret material. Responses carry public keys and
fingerprints only.
"""

import logging
import threading
from typing import Callable, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session, sessionmaker

from ..auth import TaigaUser
from ..config import Settings, get_settings
from ..deps import actor, admin, get_db, get_sessions, member
from ..store import AwakJob, AwakProject, record_decision
from . import config_store

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
    start_worker: Callable[[], None] = Depends(get_worker_starter),
):
    p = db.get(AwakProject, slug)
    if p is None:
        p = AwakProject(slug=slug, **config_store.DEFAULTS)
        db.add(p)
    new = body.model_dump()
    changed = {k: new[k] for k in config_store.SETTING_FIELDS if getattr(p, k) != new[k]}
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


