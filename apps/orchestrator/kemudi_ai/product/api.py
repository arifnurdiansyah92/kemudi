"""/projects/{slug}/product: start a product agent, list and read its runs.

Any project member starts and reads runs (like Intake: a run only reads what
the member can read, with their own Taiga token). A run's creator or a
project admin deletes it.
"""

from datetime import UTC, datetime
from functools import lru_cache
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, sessionmaker

from ..auth import ProjectAccess, TaigaUser, current_user
from ..config import Settings, get_settings
from ..deps import access, actor, get_db, get_sessions, member
from ..store import ProductRun, record_decision
from . import KINDS, NEEDS_WEB, agents
from .service import ProductService

router = APIRouter(prefix="/projects/{slug}/product")

ACTIVE = ("queued", "running")


@lru_cache
def _service(db_url: str) -> ProductService:
    settings = get_settings()
    from ..deps import _sessions

    return ProductService(settings, _sessions(db_url))


def get_service(settings: Settings = Depends(get_settings),
                _: sessionmaker[Session] = Depends(get_sessions)) -> ProductService:
    return _service(settings.ai_db_url)


class Options(BaseModel):
    days: Literal[7, 14, 30, 90] | None = None
    based_on: int | None = Field(None, ge=1)


class RunIn(BaseModel):
    kind: Literal["competitor", "features", "report", "custom"]
    brief: str = Field("", max_length=4000)
    lang: Literal["id", "en"] = "id"
    options: Options = Field(default_factory=Options)


def _iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=UTC)).isoformat()


def summary_out(r: ProductRun) -> dict:
    return {"id": r.id, "kind": r.kind, "title": r.title, "brief": r.brief, "lang": r.lang,
            "status": r.status, "stage": r.stage, "error": r.error, "web": bool(r.web),
            "created_by": r.created_by, "created_at": _iso(r.created_at),
            "started_at": _iso(r.started_at), "finished_at": _iso(r.finished_at),
            "options": {k: v for k, v in (r.options or {}).items() if v is not None}}


def run_out(r: ProductRun) -> dict:
    return {**summary_out(r), "report": r.report or "",
            "suggestions": list(r.suggestions or []), "sources": list(r.sources or [])}


def _get(db: Session, slug: str, run_id: int) -> ProductRun:
    row = db.get(ProductRun, run_id)
    if row is None or row.project_slug != slug:
        raise HTTPException(404, "no such run")
    return row


@router.get("/agents")
def get_agents(slug: str, _: TaigaUser = Depends(member),
               service: ProductService = Depends(get_service)):
    return {"web": service.web,
            "agents": [{"kind": k, "needs_web": NEEDS_WEB[k]} for k in KINDS]}


@router.post("/runs", status_code=202)
def start_run(slug: str, body: RunIn, user: TaigaUser = Depends(member),
              db: Session = Depends(get_db), settings: Settings = Depends(get_settings),
              service: ProductService = Depends(get_service)):
    brief = body.brief.strip()
    if body.kind == "custom" and len(brief) < 10:
        raise HTTPException(400, "Tulis arahan riset (minimal 10 karakter).")
    active = (db.query(ProductRun)
              .filter(ProductRun.project_slug == slug, ProductRun.status.in_(ACTIVE)).count())
    if active >= settings.product_max_active:
        raise HTTPException(409, f"Masih ada {active} riset yang berjalan di proyek ini. "
                                 "Tunggu sampai selesai, lalu coba lagi.")
    options = {}
    if body.kind == "report":
        options["days"] = body.options.days or 30
    if body.kind == "features" and body.options.based_on:
        base = db.get(ProductRun, body.options.based_on)
        if (base is None or base.project_slug != slug or base.kind != "competitor"
                or base.status != "done"):
            raise HTTPException(400, "Riset kompetitor yang dipilih tidak ada atau belum "
                                     "selesai.")
        options["based_on"] = base.id
    now = datetime.now(UTC)
    row = ProductRun(project_slug=slug, kind=body.kind, brief=brief, lang=body.lang,
                     options=options, status="queued", created_by=user.username,
                     created_by_id=user.id, created_at=now,
                     title=agents.title_for(body.kind, body.lang, brief, now))
    db.add(row)
    db.commit()
    record_decision(db, actor(user), "product_run", slug,
                    {"id": row.id, "kind": row.kind, "chars": len(brief),
                     "web": service.web and NEEDS_WEB[row.kind]})
    service.start(row.id, user.token)
    db.refresh(row)
    return run_out(row)


@router.get("/runs")
def list_runs(slug: str, limit: int = 30, _: TaigaUser = Depends(member),
              db: Session = Depends(get_db)):
    rows = (db.query(ProductRun).filter_by(project_slug=slug)
            .order_by(ProductRun.id.desc()).limit(max(1, min(limit, 100))).all())
    return {"runs": [summary_out(r) for r in rows]}


@router.get("/runs/{run_id}")
def get_run(slug: str, run_id: int, _: TaigaUser = Depends(member),
            db: Session = Depends(get_db)):
    return run_out(_get(db, slug, run_id))


@router.delete("/runs/{run_id}", status_code=204)
def delete_run(slug: str, run_id: int, acc: ProjectAccess = Depends(access),
               user: TaigaUser = Depends(current_user), db: Session = Depends(get_db)):
    row = _get(db, slug, run_id)
    if not (acc.is_admin or row.created_by_id == user.id):
        raise HTTPException(403, "Hanya admin proyek atau pembuat riset yang bisa menghapus.")
    if row.status == "running":
        raise HTTPException(409, "Riset sedang berjalan; tunggu sampai selesai.")
    db.delete(row)
    db.commit()
    record_decision(db, actor(user), "product_run_delete", slug, {"id": run_id})
    return Response(status_code=204)
