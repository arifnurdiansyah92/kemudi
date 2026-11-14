"""How long contract-derived data lives.

- `purge_ai_calls`: ai_calls older than KEMUDI_AI_LOG_RETENTION_DAYS are
  deleted; with KEMUDI_AI_LOG_PROMPTS off, prompt/response texts left by an
  earlier configuration are reduced to their SHA-256. Runs at start and daily
  (`purge_loop`, started by the API's lifespan).
- `DELETE /projects/{slug}/contract`: a project admin deletes the contract,
  its baselines, backtests, CR checks and the AI calls made for the project.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session, sessionmaker

from .auth import TaigaUser
from .config import Settings
from .deps import actor, admin, get_db
from .store import (
    AiCall,
    BacktestResult,
    BacktestRun,
    BaselineVersion,
    Contract,
    CrCheck,
    record_decision,
    sha256_text,
)

log = logging.getLogger(__name__)

PURGE_INTERVAL_S = 24 * 3600


def purge_ai_calls(db: Session, retention_days: int, log_prompts: bool,
                   now: datetime | None = None) -> dict[str, int]:
    """{deleted, scrubbed}. retention_days <= 0 keeps every row."""
    deleted = scrubbed = 0
    if retention_days > 0:
        cutoff = (now or datetime.now(UTC)) - timedelta(days=retention_days)
        # SQLite stores naive UTC; compare like with like.
        cutoff = cutoff.replace(tzinfo=None)
        deleted = (db.query(AiCall).filter(AiCall.at < cutoff)
                   .delete(synchronize_session=False))
    if not log_prompts:
        rows = (db.query(AiCall)
                .filter(or_(AiCall.prompt != "", AiCall.response != "")).all())
        for r in rows:
            r.prompt_sha256 = r.prompt_sha256 or sha256_text(r.prompt)
            r.response_sha256 = r.response_sha256 or sha256_text(r.response)
            r.prompt, r.response = "", ""
            scrubbed += 1
    db.commit()
    if deleted or scrubbed:
        log.info("ai_calls retention: %d deleted, %d prompt texts removed", deleted, scrubbed)
    return {"deleted": deleted, "scrubbed": scrubbed}


def purge_once(sessions: sessionmaker[Session], settings: Settings) -> dict[str, int]:
    with sessions() as db:
        return purge_ai_calls(db, settings.ai_log_retention_days, settings.ai_log_prompts)


def purge_safely(sessions: sessionmaker[Session], settings: Settings) -> None:
    """A failed pass is logged, never fatal."""
    try:
        purge_once(sessions, settings)
    except Exception:  # noqa: BLE001 - retention must not stop the service
        log.exception("ai_calls retention pass failed")


async def purge_loop(sessions: sessionmaker[Session], settings: Settings,
                     interval_s: float = PURGE_INTERVAL_S) -> None:
    """Every `interval_s` (the start-up pass runs before the app serves)."""
    while True:
        await asyncio.sleep(interval_s)
        await asyncio.to_thread(purge_safely, sessions, settings)


# --- contract deletion -----------------------------------------------------------

router = APIRouter()


def delete_contract_data(db: Session, slug: str) -> dict[str, int]:
    """Deletes the project's contract and everything derived from it; the
    decisions and audit trail stay (they hold no contract text)."""
    c = db.query(Contract).filter_by(project_slug=slug).one_or_none()
    counts = {"contracts": 0, "baseline_versions": 0, "backtest_runs": 0,
              "backtest_results": 0, "cr_checks": 0, "ai_calls": 0}
    # CR checks hold ticket text and AI reasoning against this contract; the
    # PM verdicts on them stay in the decisions and audit trail.
    counts["cr_checks"] = (db.query(CrCheck).filter_by(project_slug=slug)
                           .delete(synchronize_session=False))
    if c is not None:
        run_ids = [r.id for r in db.query(BacktestRun.id).filter_by(contract_id=c.id)]
        if run_ids:
            counts["backtest_results"] = (db.query(BacktestResult)
                                          .filter(BacktestResult.run_id.in_(run_ids))
                                          .delete(synchronize_session=False))
        counts["backtest_runs"] = (db.query(BacktestRun).filter_by(contract_id=c.id)
                                   .delete(synchronize_session=False))
        counts["baseline_versions"] = (db.query(BaselineVersion).filter_by(contract_id=c.id)
                                       .delete(synchronize_session=False))
        db.delete(c)
        counts["contracts"] = 1
    # The contract's AI calls (baseline drafts, classification); Awak's own
    # runs are not contract data.
    counts["ai_calls"] = (db.query(AiCall)
                          .filter(AiCall.project_slug == slug,
                                  ~AiCall.purpose.startswith("awak"))
                          .delete(synchronize_session=False))
    db.commit()
    return counts


@router.delete("/projects/{slug}/contract")
def delete_contract(slug: str, user: TaigaUser = Depends(admin), db: Session = Depends(get_db)):
    """Project admins: delete the contract, its baselines, backtests, CR checks
    and AI calls."""
    if db.query(Contract).filter_by(project_slug=slug).one_or_none() is None:
        raise HTTPException(404, "no contract for this project")
    counts = delete_contract_data(db, slug)
    record_decision(db, actor(user), "delete_contract", slug, {"deleted": counts})
    return {"deleted": counts}
