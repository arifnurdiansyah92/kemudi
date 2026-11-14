"""Awak usage: tokens and cost per model call, per run, per project; budgets.

The /llm/v1 proxy records one `awak_llm_usage` row per answered model call,
from the usage the provider reported (prompt, cached prompt and completion
tokens). The cost comes from a price table per model, per 1M tokens, in USD
or IDR: the project's override, else KEMUDI_LLM_PRICES merged over the
built-in defaults, else the legacy flat KEMUDI_TOKEN_PRICE_IDR_PER_1K. A
model with no price has an unknown cost (NULL), never a silent 0.

Budgets (Project settings -> Agent -> Usage and budget): a monthly token
budget per project (calendar month, UTC) and an optional cap per story run.
Unset (NULL or 0) means unlimited. Over a limit the proxy refuses the call,
the worker blocks the story with `needs-human` and a comment, and the Setup
Assistant run fails with the reason.
"""

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..config import Settings
from ..store import AwakJob, AwakLlmAlias, AwakLlmUsage, AwakProject

log = logging.getLogger(__name__)

CURRENCIES = ("USD", "IDR")
WARN_AT = 0.8  # the settings page warns from 80% of the monthly budget


@dataclass(frozen=True)
class Price:
    """Per 1M tokens. `cached_input`: prompt tokens served from the
    provider's cache (None: billed as input)."""

    input: float
    output: float
    cached_input: float | None = None
    currency: str = "USD"

    def out(self) -> dict:
        return {"input": self.input, "cached_input": self.cached_input,
                "output": self.output, "currency": self.currency}


# USD per 1M tokens. deepseek-chat / -reasoner: DeepSeek's list price (V3.2,
# api-docs.deepseek.com, cache miss / cache hit / output). The flash and v4
# entries are estimates: resellers (sumopod, OpenRouter) price differently,
# so check your provider's page and override with KEMUDI_LLM_PRICES or the
# project's price in Project settings -> Agent.
_DEEPSEEK_V32 = Price(input=0.28, cached_input=0.028, output=0.42)
_DEEPSEEK_FLASH = Price(input=0.14, cached_input=0.028, output=0.28)
DEFAULT_PRICES: dict[str, Price] = {
    "deepseek-chat": _DEEPSEEK_V32,
    "deepseek-reasoner": _DEEPSEEK_V32,
    "deepseek-v3.2": _DEEPSEEK_V32,
    "deepseek-flash": _DEEPSEEK_FLASH,
    "deepseek-v4-flash": _DEEPSEEK_FLASH,
    "deepseek-v4-pro": Price(input=1.74, cached_input=0.145, output=3.48),
}


def _price_from(raw) -> Price | None:
    if not isinstance(raw, dict):
        return None
    try:
        inp, outp = float(raw["input"]), float(raw["output"])
        cached = raw.get("cached_input")
        cached = None if cached is None else float(cached)
    except (KeyError, TypeError, ValueError):
        return None
    currency = str(raw.get("currency") or "USD").upper()
    if currency not in CURRENCIES or min(inp, outp, cached or 0.0) < 0:
        return None
    return Price(input=inp, output=outp, cached_input=cached, currency=currency)


def price_table(settings: Settings) -> dict[str, Price]:
    """The built-in table with KEMUDI_LLM_PRICES over it (bad entries are
    logged and skipped)."""
    table = dict(DEFAULT_PRICES)
    if not settings.llm_prices.strip():
        return table
    try:
        extra = json.loads(settings.llm_prices)
    except ValueError:
        log.warning("KEMUDI_LLM_PRICES is not JSON; using the built-in prices")
        return table
    if not isinstance(extra, dict):
        log.warning("KEMUDI_LLM_PRICES is not a JSON object; using the built-in prices")
        return table
    for model, raw in extra.items():
        p = _price_from(raw)
        if p is None:
            log.warning("KEMUDI_LLM_PRICES: the price of %r is not valid; skipped", model)
            continue
        table[_norm(model)] = p
    return table


def _norm(model: str) -> str:
    return (model or "").strip().lower()


def lookup(table: dict[str, Price], model: str) -> Price | None:
    """Exact (case-insensitive), then without a provider prefix
    (`deepseek/deepseek-chat` -> `deepseek-chat`)."""
    m = _norm(model)
    if m in table:
        return table[m]
    tail = m.rsplit("/", 1)[-1]
    return table.get(tail)


def project_price(p: AwakProject | None) -> Price | None:
    if p is None or p.price_input_per_1m is None or p.price_output_per_1m is None:
        return None
    return Price(input=p.price_input_per_1m, output=p.price_output_per_1m,
                 cached_input=p.price_cached_input_per_1m,
                 currency=p.price_currency or "USD")


def price_for(db: Session, settings: Settings, slug: str,
              model: str) -> tuple[Price | None, str]:
    """(price, source): project | table | flat, or (None, '') when unknown."""
    own = project_price(db.get(AwakProject, slug)) if slug else None
    if own is not None:
        return own, "project"
    p = lookup(price_table(settings), model)
    if p is not None:
        return p, "table"
    if settings.token_price_idr_per_1k > 0:
        flat = settings.token_price_idr_per_1k * 1000
        return Price(input=flat, output=flat, currency="IDR"), "flat"
    return None, ""


def cost_idr(settings: Settings, price: Price | None, prompt: int, cached: int,
             completion: int) -> float | None:
    if price is None:
        return None
    cached = max(0, min(cached, prompt))
    cached_rate = price.input if price.cached_input is None else price.cached_input
    amount = ((prompt - cached) * price.input + cached * cached_rate
              + completion * price.output) / 1_000_000
    return amount * settings.usd_idr_rate if price.currency == "USD" else amount


def parse_usage(usage) -> tuple[int, int, int] | None:
    """(prompt, cached prompt, completion) from an OpenAI-shaped `usage`, or
    None when the answer carried none."""
    if not isinstance(usage, dict):
        return None
    if usage.get("prompt_tokens") is None and usage.get("completion_tokens") is None:
        return None
    try:
        prompt = int(usage.get("prompt_tokens") or 0)
        completion = int(usage.get("completion_tokens") or 0)
        details = usage.get("prompt_tokens_details") or {}
        cached = int((details.get("cached_tokens") if isinstance(details, dict) else 0)
                     or usage.get("prompt_cache_hit_tokens") or 0)
    except (TypeError, ValueError):
        return None
    return max(prompt, 0), max(cached, 0), max(completion, 0)


def _naive_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _naive(t: datetime) -> datetime:
    return t.astimezone(UTC).replace(tzinfo=None) if t.tzinfo else t


def month_start(at: datetime | None = None) -> datetime:
    at = _naive(at) if at is not None else _naive_now()
    return at.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


@dataclass(frozen=True)
class CallMeta:
    """Who a proxied call belongs to (copied from the alias row)."""

    alias: str
    project_slug: str
    purpose: str = ""
    job_id: int | None = None
    setup_run_id: int | None = None

    @classmethod
    def of(cls, row: AwakLlmAlias) -> "CallMeta":
        return cls(alias=row.alias, project_slug=row.project_slug, purpose=row.purpose or "",
                   job_id=row.job_id, setup_run_id=row.setup_run_id)


def record_call(db: Session, settings: Settings, meta: CallMeta, model: str, source: str,
                usage) -> AwakLlmUsage:
    """One answered model call. Usage missing from the answer is recorded as
    such (tokens and cost unknown)."""
    parsed = parse_usage(usage)
    prompt, cached, completion = parsed or (0, 0, 0)
    price, price_src = price_for(db, settings, meta.project_slug, model)
    row = AwakLlmUsage(
        at=_naive_now(), project_slug=meta.project_slug, alias=meta.alias,
        purpose=meta.purpose, job_id=meta.job_id, setup_run_id=meta.setup_run_id,
        model=(model or "")[:100], llm_source=source, prompt_tokens=prompt,
        cached_tokens=cached, completion_tokens=completion, usage_reported=parsed is not None,
        cost_idr=(cost_idr(settings, price, prompt, cached, completion)
                  if parsed is not None else None),
        price_source=price_src)
    db.add(row)
    db.commit()
    return row


@dataclass(frozen=True)
class RunCost:
    calls: int
    prompt_tokens: int
    completion_tokens: int
    cost_idr: float  # the known part
    unknown: int  # calls whose cost is unknown


def run_cost(db: Session, alias: str) -> RunCost:
    rows = db.query(AwakLlmUsage).filter_by(alias=alias).all()
    return RunCost(
        calls=len(rows),
        prompt_tokens=sum(r.prompt_tokens for r in rows),
        completion_tokens=sum(r.completion_tokens for r in rows),
        cost_idr=sum(r.cost_idr or 0.0 for r in rows),
        unknown=sum(1 for r in rows if r.cost_idr is None))


# --- budgets -------------------------------------------------------------------


def _tokens():
    return func.coalesce(func.sum(AwakLlmUsage.prompt_tokens + AwakLlmUsage.completion_tokens),
                         0)


def month_tokens(db: Session, slug: str, at: datetime | None = None) -> int:
    return int(db.query(_tokens()).filter(AwakLlmUsage.project_slug == slug,
                                          AwakLlmUsage.at >= month_start(at)).scalar() or 0)


def job_tokens(db: Session, job: AwakJob) -> int:
    """Tokens of the story's current run (since its last reset)."""
    q = db.query(_tokens()).filter(AwakLlmUsage.job_id == job.id)
    if job.started_at is not None:
        q = q.filter(AwakLlmUsage.at >= _naive(job.started_at))
    return int(q.scalar() or 0)


def limits(p: AwakProject | None) -> tuple[int, int]:
    """(monthly budget, story cap); 0 = unlimited."""
    if p is None:
        return 0, 0
    return max(p.token_budget_monthly or 0, 0), max(p.token_cap_story or 0, 0)


def _fmt(n: int) -> str:
    return f"{n:,}".replace(",", ".")


class BudgetExceeded(Exception):
    """A project's monthly token budget or a story's token cap is used up.
    `cost_idr`: what the run that hit it cost (when raised after one)."""

    def __init__(self, kind: str, used: int, limit: int, cost_idr: float = 0.0):
        self.kind, self.used, self.limit, self.cost_idr = kind, used, limit, cost_idr
        what = ("the project's monthly token budget" if kind == "monthly"
                else "this story's token cap")
        super().__init__(
            f"Stopped: {what} is used up ({_fmt(used)} of {_fmt(limit)} tokens). "
            "An admin can raise it in Project settings -> Agent -> Usage and budget.")

    def comment(self) -> str:
        """For the story's card (Awak's comments are Indonesian)."""
        what = ("Anggaran token bulanan proyek" if self.kind == "monthly"
                else "Batas token per story")
        return (f"{what} sudah habis ({_fmt(self.used)} dari {_fmt(self.limit)} token), "
                "jadi Awak berhenti sebelum memanggil model lagi. Admin proyek dapat "
                "menaikkannya di Project settings → Agent → Penggunaan dan anggaran, lalu "
                "membuka blokir story ini.")


def check(db: Session, slug: str, job_id: int | None = None) -> None:
    """Raises BudgetExceeded when the project's month or the job's run is at
    or over its limit."""
    budget, cap = limits(db.get(AwakProject, slug))
    if budget:
        used = month_tokens(db, slug)
        if used >= budget:
            raise BudgetExceeded("monthly", used, budget)
    if cap and job_id is not None:
        job = db.get(AwakJob, job_id)
        if job is not None:
            used = job_tokens(db, job)
            if used >= cap:
                raise BudgetExceeded("story", used, cap)


def problem(db: Session, slug: str, job_id: int | None = None) -> BudgetExceeded | None:
    try:
        check(db, slug, job_id)
    except BudgetExceeded as e:
        return e
    return None


# --- the settings page ---------------------------------------------------------


def summary(db: Session, settings: Settings, slug: str, model: str,
            stories: int = 10) -> dict:
    """Usage this month, recent stories and the limits, for the Agent page.
    `model`: the project's effective model (the price shown)."""
    start = month_start()
    rows = (db.query(AwakLlmUsage)
            .filter(AwakLlmUsage.project_slug == slug, AwakLlmUsage.at >= start).all())
    p = db.get(AwakProject, slug)
    budget, cap = limits(p)
    total = sum(r.prompt_tokens + r.completion_tokens for r in rows)
    setup_rows = [r for r in rows if r.setup_run_id is not None]
    price, price_src = price_for(db, settings, slug, model)

    jobs = (db.query(AwakJob).filter_by(project_slug=slug)
            .order_by(AwakJob.id.desc()).limit(stories).all())
    recent = []
    for j in jobs:
        jr = db.query(AwakLlmUsage).filter(AwakLlmUsage.job_id == j.id)
        if j.started_at is not None:
            jr = jr.filter(AwakLlmUsage.at >= _naive(j.started_at))
        jr = jr.all()
        recent.append({
            "job_id": j.id, "story_ref": j.story_ref, "state": j.state,
            "calls": len(jr),
            "prompt_tokens": sum(r.prompt_tokens for r in jr),
            "completion_tokens": sum(r.completion_tokens for r in jr),
            "tokens": sum(r.prompt_tokens + r.completion_tokens for r in jr),
            "cost_idr": sum(r.cost_idr or 0.0 for r in jr),
            "cost_unknown": any(r.cost_idr is None for r in jr),
            "updated_at": j.updated_at,
        })
    return {
        "month_start": start,
        "calls": len(rows),
        "prompt_tokens": sum(r.prompt_tokens for r in rows),
        "cached_tokens": sum(r.cached_tokens for r in rows),
        "completion_tokens": sum(r.completion_tokens for r in rows),
        "tokens": total,
        "cost_idr": sum(r.cost_idr or 0.0 for r in rows),
        # Calls whose cost is unknown (no price for the model) and calls whose
        # answer reported no usage at all.
        "unknown_cost_calls": sum(1 for r in rows if r.cost_idr is None and r.usage_reported),
        "unreported_calls": sum(1 for r in rows if not r.usage_reported),
        "setup_tokens": sum(r.prompt_tokens + r.completion_tokens for r in setup_rows),
        "setup_cost_idr": sum(r.cost_idr or 0.0 for r in setup_rows),
        "budget": {
            "monthly_tokens": budget or None,
            "story_cap": cap or None,
            "used_ratio": (total / budget) if budget else None,
            "warning": bool(budget and total >= WARN_AT * budget),
            "exceeded": bool(budget and total >= budget),
            "recommended_monthly_tokens": settings.token_budget_recommended,
        },
        "price": {
            "model": model,
            "source": price_src or None,
            **(price.out() if price else {"input": None, "cached_input": None,
                                          "output": None, "currency": None}),
        },
        "price_override": project_price(p).out() if project_price(p) else None,
        "usd_idr_rate": settings.usd_idr_rate,
        "stories": recent,
    }
