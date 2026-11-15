"""The superadmin portfolio ("helicopter view"): Kemudi's own signals for every
project in one call. The web app joins this with Taiga's project list and
sprint progress, keyed by project slug.

One GROUP BY query per table, never a loop of per-project queries.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from .auth import TaigaUser
from .awak.usage import WARN_AT, month_start
from .deps import get_db, superadmin
from .store import (
    AwakJob,
    AwakLlmUsage,
    AwakProject,
    BacktestRun,
    BaselineVersion,
    Contract,
    CrCheck,
    PortfolioPref,
    now as store_now,
)

router = APIRouter(tags=["portfolio"])

JOB_STATES = ("queued", "running", "passed", "failed", "stopped")
RECENT_DAYS = 7  # Awak failures older than this no longer colour the row


def _blank() -> dict[str, Any]:
    return {
        "contract": {"exists": False, "baseline_approved": 0, "has_draft": False,
                     "approved_at": None, "value_idr": None, "show_prices": False},
        "cr": {"total": 0, "in_baseline": 0, "cr_candidate": 0, "needs_clarification": 0,
               "unreviewed": 0, "unreviewed_cr": 0, "agreed_cr": 0, "agreed_cr_value_idr": 0,
               "last_checked_at": None},
        "backtest": {"runs": 0, "last_finished_at": None, "last_error": None},
        "awak": {"enabled": False, **{s: 0 for s in JOB_STATES}, "failed_recent": 0,
                 "cost_idr": 0.0, "last_error": "", "last_error_at": None,
                 "last_activity_at": None},
        "usage": {"tokens": 0, "cost_idr": 0.0, "budget_tokens": None, "used_ratio": None},
    }


def _item_value(items: list[Any] | None) -> int | None:
    prices = [i.get("price_idr") for i in (items or []) if isinstance(i, dict)]
    prices = [p for p in prices if isinstance(p, int | float) and p > 0]
    return int(sum(prices)) if prices else None


def collect(db: Session, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    naive_now = now.replace(tzinfo=None)
    since = month_start(naive_now)
    recent = naive_now - timedelta(days=RECENT_DAYS)
    out: dict[str, dict[str, Any]] = {}

    def row(slug: str) -> dict[str, Any]:
        return out.setdefault(slug, _blank())

    # Contract and its latest approved baseline (value = sum of item prices).
    contracts = db.query(Contract.id, Contract.project_slug, Contract.show_prices).all()
    by_contract = {cid: slug for cid, slug, _ in contracts}
    for _cid, slug, show in contracts:
        c = row(slug)["contract"]
        c["exists"], c["show_prices"] = True, bool(show)
    latest = (db.query(BaselineVersion.contract_id, func.max(BaselineVersion.number))
              .filter(BaselineVersion.status == "approved")
              .group_by(BaselineVersion.contract_id).all())
    latest_num = {cid: n for cid, n in latest}
    for v in db.query(BaselineVersion).filter(BaselineVersion.contract_id.in_(by_contract)).all():
        c = row(by_contract[v.contract_id])["contract"]
        if v.status == "draft":
            c["has_draft"] = True
        elif v.number == latest_num.get(v.contract_id):
            c["baseline_approved"] = v.number
            c["approved_at"] = v.approved_at
            c["value_idr"] = _item_value(v.items)

    # CR checks: the PM's corrected label wins over the AI's.
    eff = func.coalesce(CrCheck.corrected_label, CrCheck.label)
    unreviewed = CrCheck.verdict.is_(None)
    agreed_cr = (CrCheck.verdict.is_not(None)) & (eff == "cr_candidate")
    for (slug, total, inb, crc, clar, unrev, unrev_cr, agr, agr_val, last) in (
        db.query(
            CrCheck.project_slug,
            func.count(CrCheck.id),
            func.sum(case((eff == "in_baseline", 1), else_=0)),
            func.sum(case((eff == "cr_candidate", 1), else_=0)),
            func.sum(case((eff == "needs_clarification", 1), else_=0)),
            func.sum(case((unreviewed, 1), else_=0)),
            func.sum(case((unreviewed & (CrCheck.label == "cr_candidate"), 1), else_=0)),
            func.sum(case((agreed_cr, 1), else_=0)),
            func.sum(case((agreed_cr, CrCheck.price_idr), else_=0)),
            func.max(CrCheck.checked_at),
        ).group_by(CrCheck.project_slug).all()
    ):
        row(slug)["cr"].update(
            total=total, in_baseline=int(inb or 0), cr_candidate=int(crc or 0),
            needs_clarification=int(clar or 0), unreviewed=int(unrev or 0),
            unreviewed_cr=int(unrev_cr or 0), agreed_cr=int(agr or 0),
            agreed_cr_value_idr=int(agr_val or 0), last_checked_at=last)

    # Backtests: count and the latest run's outcome.
    last_run = (db.query(BacktestRun.contract_id, func.max(BacktestRun.id), func.count(BacktestRun.id))
                .group_by(BacktestRun.contract_id).all())
    run_ids = {rid: (cid, n) for cid, rid, n in last_run}
    for r in db.query(BacktestRun).filter(BacktestRun.id.in_(run_ids)).all():
        slug = by_contract.get(r.contract_id)
        if slug:
            row(slug)["backtest"].update(runs=run_ids[r.id][1], last_finished_at=r.finished_at,
                                         last_error=r.error)

    # Awak jobs by state, recent failures, and total job cost.
    for slug, state, n, cost, last in (
        db.query(AwakJob.project_slug, AwakJob.state, func.count(AwakJob.id),
                 func.coalesce(func.sum(AwakJob.cost_idr), 0), func.max(AwakJob.updated_at))
        .group_by(AwakJob.project_slug, AwakJob.state).all()
    ):
        a = row(slug)["awak"]
        if state in JOB_STATES:
            a[state] = n
        a["cost_idr"] += float(cost or 0)
        if last and (a["last_activity_at"] is None or last > a["last_activity_at"]):
            a["last_activity_at"] = last
    for slug, n in (db.query(AwakJob.project_slug, func.count(AwakJob.id))
                    .filter(AwakJob.state == "failed", AwakJob.updated_at >= recent)
                    .group_by(AwakJob.project_slug).all()):
        row(slug)["awak"]["failed_recent"] = n

    for p in db.query(AwakProject).all():
        r = row(p.slug)
        r["awak"].update(enabled=bool(p.enabled), last_error=p.last_error or "",
                         last_error_at=p.last_error_at)
        r["usage"]["budget_tokens"] = p.token_budget_monthly or None

    # This month's model usage against the monthly token budget.
    for slug, tokens, cost in (
        db.query(AwakLlmUsage.project_slug,
                 func.coalesce(func.sum(AwakLlmUsage.prompt_tokens
                                        + AwakLlmUsage.completion_tokens), 0),
                 func.coalesce(func.sum(AwakLlmUsage.cost_idr), 0))
        .filter(AwakLlmUsage.at >= since).group_by(AwakLlmUsage.project_slug).all()
    ):
        u = row(slug)["usage"]
        u["tokens"], u["cost_idr"] = int(tokens or 0), float(cost or 0)
    for r in out.values():
        u = r["usage"]
        if u["budget_tokens"]:
            u["used_ratio"] = u["tokens"] / u["budget_tokens"]

    return {"generated_at": now, "month_start": since, "warn_at": WARN_AT,
            "recent_days": RECENT_DAYS, "projects": out}


def _excluded(db: Session, user: TaigaUser) -> list[str]:
    p = db.get(PortfolioPref, user.id)
    return list(p.excluded) if p else []


@router.get("/portfolio")
def portfolio(user: TaigaUser = Depends(superadmin), db: Session = Depends(get_db)):
    """Every project's contract, scope-change, Awak and spend signals, and
    which projects this superadmin has left out of the view."""
    return {**collect(db), "excluded": _excluded(db, user)}


class ExcludedIn(BaseModel):
    excluded: list[str] = Field(default_factory=list, max_length=2000)


@router.put("/portfolio/excluded")
def put_excluded(body: ExcludedIn, user: TaigaUser = Depends(superadmin),
                 db: Session = Depends(get_db)):
    """Remember the projects left out of this superadmin's view (all others,
    including projects created later, are in)."""
    slugs = sorted({s.strip() for s in body.excluded if s.strip()})
    p = db.get(PortfolioPref, user.id)
    if p is None:
        p = PortfolioPref(user_id=user.id)
        db.add(p)
    p.excluded, p.updated_at = slugs, store_now()
    db.commit()
    return {"excluded": slugs}
