"""The audit trail (`audit_events`): who changed what, append-only.

Written for merges and deploys, merge/QA mode and other Agent settings, model
connections (with the insecure-http acknowledgement), env vault values, SSH
keys and machines, repos, roles, skills and marketplaces, contracts. Most
events mirror a decision (`store.record_decision` calls `mirror_decision`);
the worker records merges and deploys with `record_audit`.

A detail never holds a secret value: known secret keys are replaced by
`(redacted)` before a row is written, whoever the caller.
"""

import csv
import io
import re
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from .auth import TaigaUser
from .deps import admin, get_db, kemudi_admin
from .store import AuditEvent, Decision

# Decision actions about one project (the subject is the project slug).
PROJECT_ACTIONS = frozenset({
    "awak_settings",            # merge mode, QA mode, deploy command, executor/machine
    "awak_llm",                 # model connection; insecure_http flags plain http
    "awak_env",                 # vault value set/delete (never the value)
    "awak_repo",
    "awak_repo_delete",
    "awak_repo_key",            # SSH deploy key generated/replaced
    "awak_machine_key",         # SSH machine key generated/replaced
    "awak_machine_forget_host",
    "awak_merge_requested",
    "awak_role",                # includes the skills assigned to an agent
    "awak_runbook",
    "awak_bot_access",
    "awak_budget",              # token budget, story cap, price override
    "upload_contract",
    "approve_baseline",
    "delete_contract",
})
# Decision actions about the instance (the skill library): the subject is the
# skill or marketplace, kept in the detail; project_slug is ''.
INSTANCE_ACTIONS = {"awak_skill": "skill", "awak_skill_marketplace": "marketplace"}

SECRET_KEYS = frozenset({
    "value", "values", "api_key", "password", "token", "secret_value", "private_key",
    "private_key_enc", "value_enc", "llm_api_key_enc", "authorization", "deploy_command",
})
REDACTED = "(redacted)"
_MAX_STR = 2000
_ACTOR = re.compile(r"^(?P<name>.*) \((?P<id>\d+)\)$")


def scrub(detail: Any) -> Any:
    """A copy without secret values (by key, at any depth); long strings cut."""
    if isinstance(detail, dict):
        out = {}
        for k, v in detail.items():
            if str(k).lower() in SECRET_KEYS and v not in (None, "", "(changed)"):
                out[k] = REDACTED
            else:
                out[k] = scrub(v)
        return out
    if isinstance(detail, (list, tuple)):
        return [scrub(v) for v in detail]
    if isinstance(detail, str) and len(detail) > _MAX_STR:
        return detail[:_MAX_STR] + "..."
    return detail


def record_audit(db: Session, *, actor_id: int | None, actor_username: str, project: str,
                 action: str, detail: dict | None = None) -> AuditEvent:
    row = AuditEvent(actor_id=actor_id, actor_username=actor_username[:200],
                     project_slug=project, action=action[:50], detail=scrub(detail or {}))
    db.add(row)
    db.commit()
    return row


def audit_user(db: Session, user: TaigaUser, project: str, action: str,
               detail: dict | None = None) -> AuditEvent:
    return record_audit(db, actor_id=user.id, actor_username=user.username, project=project,
                        action=action, detail=detail)


def parse_actor(actor: str) -> tuple[int | None, str]:
    """`deps.actor` writes "username (id)"; anything else is a system actor."""
    m = _ACTOR.match(actor or "")
    if m:
        return int(m["id"]), m["name"]
    return None, actor or ""


def mirror_decision(db: Session, d: Decision) -> AuditEvent | None:
    if d.action in PROJECT_ACTIONS:
        project, detail = d.subject, dict(d.detail or {})
    elif d.action in INSTANCE_ACTIONS:
        project, detail = "", {INSTANCE_ACTIONS[d.action]: d.subject, **(d.detail or {})}
    else:
        return None
    actor_id, username = parse_actor(d.actor)
    return record_audit(db, actor_id=actor_id, actor_username=username, project=project,
                        action=d.action, detail=detail)


# --- read API -------------------------------------------------------------------

router = APIRouter()

CSV_COLUMNS = ("id", "ts", "actor_id", "actor_username", "project", "action", "detail")


def _out(e: AuditEvent) -> dict:
    return {"id": e.id, "ts": e.ts.isoformat() if e.ts else None, "actor_id": e.actor_id,
            "actor_username": e.actor_username, "project": e.project_slug,
            "action": e.action, "detail": e.detail}


def _cell(value: Any) -> str:
    """No spreadsheet formulas from user-controlled text (CSV injection)."""
    import json

    text = value if isinstance(value, str) else (
        "" if value is None else json.dumps(value, ensure_ascii=False, default=str)
        if isinstance(value, (dict, list)) else str(value))
    if text[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + text
    return text


def _answer(rows: list[AuditEvent], fmt: str, filename: str):
    events = [_out(e) for e in rows]
    if fmt != "csv":
        return {"events": events}
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_COLUMNS)
    for e in events:
        w.writerow([_cell(e[c]) for c in CSV_COLUMNS])
    return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _query(db: Session, project: str, action: str | None, limit: int) -> list[AuditEvent]:
    q = db.query(AuditEvent).filter(AuditEvent.project_slug == project)
    if action:
        q = q.filter(AuditEvent.action == action)
    return q.order_by(AuditEvent.id.desc()).limit(limit).all()


@router.get("/projects/{slug}/audit")
def project_audit(slug: str, format: Literal["json", "csv"] = "json",
                  action: str | None = None, limit: int = Query(1000, ge=1, le=10000),
                  _: TaigaUser = Depends(admin), db: Session = Depends(get_db)):
    """The project's audit events, newest first (project admins)."""
    return _answer(_query(db, slug, action, limit), format, f"kemudi-audit-{slug}.csv")


@router.get("/audit")
def instance_audit(format: Literal["json", "csv"] = "json", action: str | None = None,
                   limit: int = Query(1000, ge=1, le=10000),
                   _: TaigaUser = Depends(kemudi_admin), db: Session = Depends(get_db)):
    """Instance-level events (the skill library), newest first (Kemudi admins)."""
    return _answer(_query(db, "", action, limit), format, "kemudi-audit-instance.csv")
