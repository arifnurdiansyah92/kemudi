"""HTTP API for apps/web, served at /api/kemudi behind the gateway."""

import asyncio
import contextlib
import json
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
)
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session, sessionmaker

from .auth import TaigaUser, current_user
from . import audit, cr_check, retention
from .awak import agent_api, llm_proxy, marketplace_api, skills_api, usage_api
from .backtest import metrics, run_backtest
from .baseline import BaselineItem, draft_baseline
from .config import Settings, check_production, get_settings
from .deps import (
    _sessions,
    actor,
    admin,
    get_db,
    get_llm,
    get_sessions,
    is_kemudi_admin,
    member,
)
from .documents import extract_sections
from .llm import LLM, LLMError
from .pricing import RateCard
from .store import (
    BacktestResult,
    BacktestRun,
    BaselineVersion,
    Contract,
    CrCheck,
    ai_project,
    record_decision,
)

__all__ = ["app", "_sessions", "get_sessions", "get_llm", "get_db", "member", "admin", "actor"]


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    settings = get_settings()
    # KEMUDI_ENV=production: no start with an empty or placeholder secret.
    check_production(settings)
    # Respect a test override of the session factory, so a TestClient never
    # opens the real database file.
    override = _app.dependency_overrides.get(get_sessions)
    sessions = override() if override else _sessions(settings.ai_db_url)
    from .awak import config_store, marketplace, skills

    with sessions() as db:
        config_store.seed_from_env(db, settings)
        skills.seed_builtin(db)
        marketplace.seed_builtin_marketplaces(db)
        enabled = config_store.enabled_slugs(db)
    if settings.awak_project_slugs() or enabled:
        agent_api.start_worker_once(settings, sessions)
    # ai_calls retention: at start (before serving), then daily.
    retention.purge_safely(sessions, settings)
    purge = asyncio.create_task(retention.purge_loop(sessions, settings))
    try:
        yield
    finally:
        purge.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await purge


# The gateway and the Vite proxy strip the /api/kemudi prefix.
app = FastAPI(title="Kemudi AI", lifespan=_lifespan)
app.include_router(agent_api.router)
app.include_router(agent_api.intake_router)
app.include_router(skills_api.router)
app.include_router(marketplace_api.router)
# Internal only (kemudi-sandbox): the gateway does not route /llm/.
app.include_router(usage_api.router)
app.include_router(llm_proxy.router)
app.include_router(audit.router)
app.include_router(retention.router)


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


@app.get("/me")
def me(user: TaigaUser = Depends(current_user), settings: Settings = Depends(get_settings)):
    """Who is calling (the Taiga user id is what KEMUDI_ADMIN_USER_IDS
    lists), and whether they are a Kemudi instance admin (the skill library)."""
    return {"id": user.id, "username": user.username,
            "kemudi_admin": is_kemudi_admin(user, settings)}


@app.get("/skills")
def list_enabled_skills(_: TaigaUser = Depends(current_user), db: Session = Depends(get_db)):
    """Enabled skills for the role editor's picker (any signed-in user):
    slug, title, short description, source, licence, scan level, version;
    and each role template's default skills (those enabled now)."""
    from .awak import skills

    return {"skills": skills.picker(db),
            "template_defaults": {t: skills.template_defaults(db, t)
                                  for t in skills.ROLE_TEMPLATES}}


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
            "show_prices": bool(c.show_prices),
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
        with ai_project(slug):
            items = draft_baseline(llm, [Section.model_validate(s) for s in c.sections], c.lang)
    except LLMError as e:
        raise HTTPException(502, f"AI call failed: {e}") from e
    if not items:
        raise HTTPException(502, "the AI returned no usable baseline items; try again")
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


# --- CR check on one ticket ---------------------------------------------------
# docs/superpowers/specs/2026-11-11-contract-baseline-cr-design.md, goal 3.
# Members read, project admins run checks and record verdicts.


class ContractSettingsBody(BaseModel):
    show_prices: bool


@app.put("/projects/{slug}/contract/settings")
def set_contract_settings(slug: str, body: ContractSettingsBody, user: TaigaUser = Depends(admin),
                          db: Session = Depends(get_db)):
    c = _contract(db, slug)
    c.show_prices = body.show_prices
    db.commit()
    record_decision(db, actor(user), "contract_settings", slug, {"show_prices": body.show_prices})
    return {"show_prices": c.show_prices}


def _show_prices(db: Session, slug: str) -> bool:
    c = db.query(Contract).filter_by(project_slug=slug).one_or_none()
    return bool(c and c.show_prices)


class CrCheckBody(BaseModel):
    kind: cr_check.TicketKind
    ref: int = Field(gt=0)
    # Optional: check this text instead of reading the ticket from Taiga.
    subject: str | None = Field(None, max_length=500)
    text: str | None = Field(None, max_length=cr_check.MAX_TEXT)


@app.post("/projects/{slug}/cr-check")
def run_cr_check(
    slug: str,
    body: CrCheckBody,
    user: TaigaUser = Depends(admin),
    db: Session = Depends(get_db),
    llm: LLM = Depends(get_llm),
    settings: Settings = Depends(get_settings),
):
    c, b = cr_check.latest_baseline(db, slug)
    if body.text and body.text.strip():
        subject = (body.subject or "").strip()
        text = cr_check.ticket_text(subject, body.text)
    else:
        t = cr_check.fetch_ticket(settings, user, slug, body.kind, body.ref)
        subject = t["subject"]
        text = cr_check.ticket_text(t["subject"], t["description"])
    if not text.strip():
        raise HTTPException(422, "the ticket has no subject or description to check")
    try:
        with ai_project(slug):
            row = cr_check.run_check(db, llm, settings.ai_model, c, b, slug=slug, kind=body.kind,
                                     ref=body.ref, subject=subject, text=text,
                                     checked_by=actor(user))
    except LLMError as e:
        raise HTTPException(502, f"AI call failed: {e}") from e
    record_decision(db, actor(user), "cr_check", slug,
                    {"check": row.id, "ticket": f"{body.kind}#{body.ref}",
                     "label": row.label, "baseline": b.number})
    return cr_check.serialize(row, bool(c.show_prices))


@app.get("/projects/{slug}/cr-checks")
def list_cr_checks(slug: str, _: TaigaUser = Depends(member), db: Session = Depends(get_db)):
    rows = (db.query(CrCheck).filter_by(project_slug=slug)
            .order_by(CrCheck.checked_at.desc(), CrCheck.id.desc()).all())
    show = _show_prices(db, slug)
    return {"show_prices": show, "checks": [cr_check.serialize(r, show) for r in rows]}


@app.get("/projects/{slug}/cr-checks/export")
def export_cr_checks(slug: str, _: TaigaUser = Depends(member), db: Session = Depends(get_db)):
    rows = (db.query(CrCheck).filter_by(project_slug=slug)
            .order_by(CrCheck.checked_at.desc(), CrCheck.id.desc()).all())
    body = cr_check.to_csv(rows, _show_prices(db, slug))
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    return Response(
        content=cr_check.BOM + body,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{slug}-cr-checks-{stamp}.csv"'},
    )


@app.get("/projects/{slug}/cr-checks/{kind}/{ref}")
def ticket_cr_checks(slug: str, kind: cr_check.TicketKind, ref: int,
                     _: TaigaUser = Depends(member), db: Session = Depends(get_db)):
    """A ticket's checks, newest first, and whether a check can run at all."""
    c = db.query(Contract).filter_by(project_slug=slug).one_or_none()
    b = None
    if c is not None:
        approved = _approved(db, c)
        b = approved[0] if approved else None
    rows = (db.query(CrCheck).filter_by(project_slug=slug, ticket_kind=kind, ticket_ref=ref)
            .order_by(CrCheck.checked_at.desc(), CrCheck.id.desc()).all())
    show = bool(c and c.show_prices)
    return {
        "baseline": {"number": b.number} if b else None,
        "show_prices": show,
        "checks": [cr_check.serialize(r, show) for r in rows],
    }


class CrVerdictBody(BaseModel):
    verdict: Literal["agree", "disagree"]
    corrected_label: Literal["in_baseline", "cr_candidate", "needs_clarification"] | None = None
    note: str = Field("", max_length=2000)


@app.post("/projects/{slug}/cr-checks/{check_id}/verdict")
def cr_check_verdict(slug: str, check_id: int, body: CrVerdictBody,
                     user: TaigaUser = Depends(admin), db: Session = Depends(get_db)):
    r = db.get(CrCheck, check_id)
    if r is None or r.project_slug != slug:
        raise HTTPException(404, "no such check")
    if body.verdict == "disagree" and body.corrected_label == r.label:
        raise HTTPException(422, "the corrected label is the label the check gave")
    cr_check.decide(r, body.verdict, body.corrected_label, body.note.strip(), actor(user))
    db.commit()
    record_decision(db, actor(user), "cr_verdict", slug,
                    {"check": r.id, "ticket": f"{r.ticket_kind}#{r.ticket_ref}", "label": r.label, "verdict": r.verdict,
                     "corrected_label": r.corrected_label, "note": r.verdict_note})
    return cr_check.serialize(r, _show_prices(db, slug))


# --- Awak dev loop -------------------------------------------------------------
# docs/superpowers/specs/2026-11-13-awak-dev-loop-design.md


def get_taiga_bot(settings: Settings = Depends(get_settings)):
    from .awak.taiga import Taiga

    return Taiga(settings.taiga_api_url, settings.awak_username, settings.awak_password)


@app.post("/projects/{slug}/intake")
async def intake(
    slug: str,
    text: str = Form(""),
    lang: Literal["id", "en"] = Form("id"),
    file: UploadFile | None = File(None),
    user: TaigaUser = Depends(admin),
    llm: LLM = Depends(get_llm),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    from .awak import config_store
    from .awak.intake import create_stories, draft_stories
    from .awak.taiga import TaigaError
    from .documents import extract_text

    if slug not in settings.awak_project_slugs() and not config_store.is_enabled(db, slug):
        raise HTTPException(409, "Awak is not enabled for this project")
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
    try:
        created = create_stories(get_taiga_bot(settings), slug, drafts)
    except TaigaError as e:
        raise HTTPException(502, str(e)) from e
    record_decision(db, actor(user), "awak_intake", slug,
                    {"stories": [c["ref"] for c in created], "chars": len(body)})
    return {"stories": created}


@app.get("/projects/{slug}/awak/jobs")
def awak_jobs(slug: str, _: TaigaUser = Depends(member), db: Session = Depends(get_db)):
    from .store import AwakJob

    jobs = db.query(AwakJob).filter_by(project_slug=slug).order_by(AwakJob.id.desc()).all()
    return {"jobs": [
        {"story_ref": j.story_ref, "branch": j.branch, "state": j.state, "phase": j.phase,
         "attempts": j.attempts, "infra_errors": j.infra_errors, "last_sha": j.last_sha,
         "cost_idr": j.cost_idr, "started_at": j.started_at, "updated_at": j.updated_at}
        for j in jobs
    ]}
