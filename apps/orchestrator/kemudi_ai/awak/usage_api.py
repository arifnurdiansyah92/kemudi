"""Project settings -> Agent -> Usage and budget: `/projects/{slug}/agent/usage`.

Members read the usage (no secrets in it); admins set the limits and the
project's price override. Every change is a `decisions` row.
"""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from ..auth import TaigaUser
from ..config import Settings, get_settings
from ..deps import actor, admin, get_db
from ..store import AwakProject, record_decision
from . import config_store, llm_conn, usage

router = APIRouter(prefix="/projects/{slug}/agent")

# 10 billion tokens: far above any sane month, below any integer limit.
MAX_TOKENS = 10_000_000_000


class PriceIn(BaseModel):
    input: float = Field(ge=0, le=1_000_000_000)
    cached_input: float | None = Field(None, ge=0, le=1_000_000_000)
    output: float = Field(ge=0, le=1_000_000_000)
    currency: Literal["USD", "IDR"] = "USD"


class BudgetIn(BaseModel):
    # None or 0 = unlimited.
    monthly_tokens: int | None = Field(None, ge=0, le=MAX_TOKENS)
    story_cap: int | None = Field(None, ge=0, le=MAX_TOKENS)
    # None = the price table.
    price: PriceIn | None = None

    @model_validator(mode="after")
    def _zero_is_unset(self):
        self.monthly_tokens = self.monthly_tokens or None
        self.story_cap = self.story_cap or None
        return self


def _out(db: Session, settings: Settings, slug: str) -> dict:
    model = llm_conn.describe(db, settings, slug, None).model
    return usage.summary(db, settings, slug, model)


@router.get("/usage")
def get_usage(slug: str, _: TaigaUser = Depends(admin), db: Session = Depends(get_db),
              settings: Settings = Depends(get_settings)):
    return _out(db, settings, slug)


@router.put("/usage/budget")
def put_budget(slug: str, body: BudgetIn, user: TaigaUser = Depends(admin),
               db: Session = Depends(get_db), settings: Settings = Depends(get_settings)):
    p = db.get(AwakProject, slug)
    if p is None:
        p = AwakProject(slug=slug, **config_store.DEFAULTS)
        db.add(p)
    price = body.price
    new = {
        "token_budget_monthly": body.monthly_tokens,
        "token_cap_story": body.story_cap,
        "price_input_per_1m": price.input if price else None,
        "price_cached_input_per_1m": price.cached_input if price else None,
        "price_output_per_1m": price.output if price else None,
        "price_currency": price.currency if price else None,
    }
    changed = {k: v for k, v in new.items() if getattr(p, k) != v}
    for k, v in changed.items():
        setattr(p, k, v)
    if changed:
        p.updated_by, p.updated_at = actor(user), config_store.now()
    db.commit()
    if changed:
        record_decision(db, actor(user), "awak_budget", slug, {"changed": changed})
    return _out(db, settings, slug)
