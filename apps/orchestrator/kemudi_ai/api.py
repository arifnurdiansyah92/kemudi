"""HTTP API for apps/web, served at /api/kemudi behind the gateway."""

import json
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any, Literal

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    UploadFile,
)
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session, sessionmaker

from .auth import TaigaUser, current_user, project_access
from .backtest import metrics, run_backtest
from .baseline import BaselineItem, draft_baseline
from .config import Settings, get_settings
from .documents import extract_sections
from .llm import LLM, HermesLLM, LLMError
from .pricing import RateCard
from .store import (
    BacktestResult,
    BacktestRun,
    BaselineVersion,
    Contract,
    make_session,
    record_decision,
)

# The gateway and the Vite proxy strip the /api/kemudi prefix.
app = FastAPI(title="Kemudi AI")


@lru_cache
def _sessions(db_url: str) -> sessionmaker[Session]:
    return make_session(db_url)


def get_sessions(settings: Settings = Depends(get_settings)) -> sessionmaker[Session]:
    return _sessions(settings.ai_db_url)


def get_llm(
    settings: Settings = Depends(get_settings),
    sessions: sessionmaker[Session] = Depends(get_sessions),
) -> LLM:
    return HermesLLM(settings, sessions)


def get_db(sessions: sessionmaker[Session] = Depends(get_sessions)):
    with sessions() as s:
        yield s


def member(slug: str, user: TaigaUser = Depends(current_user), settings: Settings = Depends(get_settings)):
    project_access(slug, user, settings)
    return user


def admin(slug: str, user: TaigaUser = Depends(current_user), settings: Settings = Depends(get_settings)):
    if not project_access(slug, user, settings).is_admin:
        raise HTTPException(403, "project admins only")
    return user


def actor(user: TaigaUser) -> str:
    return f"{user.username} ({user.id})"


def _contract(db: Session, slug: str) -> Contract:
    c = db.query(Contract).filter_by(project_slug=slug).one_or_none()
    if c is None:
        raise HTTPException(404, "no contract for this project")
    return c


def _draft(db: Session, c: Contract) -> BaselineVersion | None:
    return db.query(BaselineVersion).filter_by(contract_id=c.id, status="draft").one_or_none()


def _approved(db: Session, c: Contract) -> list[BaselineVersion]:
    return (
        db.query(BaselineVersion)
        .filter_by(contract_id=c.id, status="approved")
        .order_by(BaselineVersion.number.desc())
        .all()
    )


def _version(v: BaselineVersion | None) -> dict | None:
    if v is None:
        return None
    return {
        "id": v.id,
        "number": v.number,
        "status": v.status,
        "items": v.items,
        "approved_by": v.approved_by,
        "approved_at": v.approved_at,
    }


def _run(run: BacktestRun) -> dict:
    return {
        "id": run.id,
        "dataset_name": run.dataset_name,
        "baseline_version_id": run.baseline_version_id,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "error": run.error,
    }


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/projects/{slug}/contract")
def get_contract(slug: str, _: TaigaUser = Depends(member), db: Session = Depends(get_db)):
    c = db.query(Contract).filter_by(project_slug=slug).one_or_none()
    if c is None:
        return {"contract": None, "baseline": None, "runs": []}
    approved = _approved(db, c)
    runs = db.query(BacktestRun).filter_by(contract_id=c.id).order_by(BacktestRun.id.desc()).all()
    return {
        "contract": {
            "filename": c.filename,
            "lang": c.lang,
            "rate_card": c.rate_card,
            "sections": c.sections,
            "created_at": c.created_at,
        },
        "baseline": {
            "draft": _version(_draft(db, c)),
            "approved": _version(approved[0] if approved else None),
            "history": [_version(v) for v in approved],
        },
        "runs": [_run(r) for r in runs],
    }


@app.post("/projects/{slug}/contract")
async def upload_contract(
    slug: str,
    file: UploadFile = File(...),
    lang: Literal["id", "en"] = Form("id"),
    rate_card: str = Form('{"per_day": {}}'),
    user: TaigaUser = Depends(admin),
    db: Session = Depends(get_db),
):
    try:
        rc = RateCard.model_validate_json(rate_card)
        sections = extract_sections(file.filename or "", await file.read())
    except (ValueError, ValidationError) as e:
        raise HTTPException(422, str(e)) from e
    c = db.query(Contract).filter_by(project_slug=slug).one_or_none()
    if c is None:
        c = Contract(project_slug=slug, filename=file.filename or "")
        db.add(c)
    c.filename, c.lang, c.rate_card = file.filename or "", lang, rc.model_dump()
    c.sections = [s.model_dump() for s in sections]
    db.commit()
    record_decision(db, actor(user), "upload_contract", slug, {"filename": c.filename, "sections": len(sections)})
    return {"sections": c.sections}


class RateCardBody(BaseModel):
    rate_card: RateCard


@app.put("/projects/{slug}/contract/rate-card")
def set_rate_card(slug: str, body: RateCardBody, user: TaigaUser = Depends(admin), db: Session = Depends(get_db)):
    c = _contract(db, slug)
    c.rate_card = body.rate_card.model_dump()
    db.commit()
    record_decision(db, actor(user), "set_rate_card", slug, c.rate_card)
    return {"rate_card": c.rate_card}


@app.post("/projects/{slug}/baseline/draft")
def generate_draft(
    slug: str,
    user: TaigaUser = Depends(admin),
    db: Session = Depends(get_db),
    llm: LLM = Depends(get_llm),
):
    from .documents import Section

    c = _contract(db, slug)
    try:
        items = draft_baseline(llm, [Section.model_validate(s) for s in c.sections], c.lang)
    except LLMError as e:
        raise HTTPException(502, f"AI call failed: {e}") from e
    draft = _draft(db, c) or BaselineVersion(contract_id=c.id)
    draft.items = [i.model_dump() for i in items]
    db.add(draft)
    db.commit()
    record_decision(db, actor(user), "generate_draft", slug, {"items": len(items)})
    return _version(draft)


class DraftBody(BaseModel):
    items: list[BaselineItem]


@app.put("/projects/{slug}/baseline/draft")
def save_draft(slug: str, body: DraftBody, user: TaigaUser = Depends(admin), db: Session = Depends(get_db)):
    c = _contract(db, slug)
    draft = _draft(db, c) or BaselineVersion(contract_id=c.id)
    draft.items = [i.model_dump() for i in body.items]
    db.add(draft)
    db.commit()
    record_decision(db, actor(user), "edit_draft", slug, {"items": len(body.items)})
    return _version(draft)


@app.post("/projects/{slug}/baseline/approve")
def approve(slug: str, user: TaigaUser = Depends(admin), db: Session = Depends(get_db)):
    c = _contract(db, slug)
    draft = _draft(db, c)
    if draft is None or not draft.items:
        raise HTTPException(409, "no draft to approve")
    approved = _approved(db, c)
    draft.status = "approved"
    draft.number = (approved[0].number if approved else 0) + 1
    draft.approved_by = actor(user)
    draft.approved_at = datetime.now(UTC)
    db.commit()
    record_decision(db, actor(user), "approve_baseline", slug, {"version": draft.number, "items": len(draft.items)})
    return _version(draft)


def _run_in_background(sessions: sessionmaker[Session], llm: LLM, run_id: int, dataset: dict) -> None:
    with sessions() as s:
        run = s.get(BacktestRun, run_id)
        c = s.get(Contract, run.contract_id)
        b = s.get(BaselineVersion, run.baseline_version_id)
        try:
            run_backtest(s, llm, c, b, dataset, run=run)
        except Exception as e:  # keep finished results; record why it stopped
            run.error = f"{type(e).__name__}: {e}"
            run.finished_at = datetime.now(UTC)
            s.commit()


@app.post("/projects/{slug}/backtests")
async def start_backtest(
    slug: str,
    background: BackgroundTasks,
    dataset: UploadFile = File(...),
    user: TaigaUser = Depends(admin),
    db: Session = Depends(get_db),
    sessions: sessionmaker[Session] = Depends(get_sessions),
    llm: LLM = Depends(get_llm),
):
    c = _contract(db, slug)
    approved = _approved(db, c)
    if not approved:
        raise HTTPException(409, "approve a baseline first")
    try:
        data = json.loads(await dataset.read())
        tickets = data["tickets"]
        assert isinstance(tickets, list)
    except (ValueError, KeyError, AssertionError) as e:
        raise HTTPException(422, "dataset must be JSON with a tickets list") from e
    if not c.rate_card.get("per_day") and data.get("rate_card"):
        c.rate_card = data["rate_card"]
    run = BacktestRun(contract_id=c.id, baseline_version_id=approved[0].id, dataset_name=dataset.filename or "dataset")
    db.add(run)
    db.commit()
    record_decision(db, actor(user), "start_backtest", slug, {"run": run.id, "tickets": len(tickets)})
    background.add_task(_run_in_background, sessions, llm, run.id, data)
    return {"run_id": run.id}


def _result(r: BacktestResult) -> dict[str, Any]:
    return {
        "id": r.id,
        "ticket_id": r.ticket_id,
        "source": r.source,
        "date": r.date,
        "text": r.text,
        "expected": r.expected,
        "predicted": r.predicted,
        "status": r.status,
        "verdict": r.verdict,
    }


def _get_run(db: Session, slug: str, run_id: int) -> BacktestRun:
    c = _contract(db, slug)
    run = db.get(BacktestRun, run_id)
    if run is None or run.contract_id != c.id:
        raise HTTPException(404, "no such run")
    return run


@app.get("/projects/{slug}/backtests/{run_id}")
def get_backtest(slug: str, run_id: int, _: TaigaUser = Depends(member), db: Session = Depends(get_db)):
    run = _get_run(db, slug, run_id)
    results = db.query(BacktestResult).filter_by(run_id=run.id).order_by(BacktestResult.id).all()
    return {"run": _run(run), "results": [_result(r) for r in results], "metrics": metrics(results).model_dump()}


class VerdictBody(BaseModel):
    verdict: Literal["right", "wrong"] | None


@app.put("/projects/{slug}/backtests/{run_id}/results/{result_id}/verdict")
def set_verdict(
    slug: str,
    run_id: int,
    result_id: int,
    body: VerdictBody,
    user: TaigaUser = Depends(admin),
    db: Session = Depends(get_db),
):
    run = _get_run(db, slug, run_id)
    r = db.get(BacktestResult, result_id)
    if r is None or r.run_id != run.id:
        raise HTTPException(404, "no such result")
    r.verdict = body.verdict
    db.commit()
    record_decision(db, actor(user), "verdict", f"{slug}#{run.id}/{r.ticket_id}", {"verdict": body.verdict})
    return _result(r)
