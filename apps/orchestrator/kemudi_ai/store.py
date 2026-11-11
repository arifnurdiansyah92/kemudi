"""Contract data, backtests and the append-only audit tables.

`ai_calls` and `decisions` are written only through `record_ai_call` and
`record_decision`; nothing in the service updates or deletes them.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, ForeignKey, String, Text, create_engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    sessionmaker,
)

__all__ = [
    "Base",
    "Contract",
    "BaselineVersion",
    "BacktestRun",
    "BacktestResult",
    "AiCall",
    "Decision",
    "make_session",
    "init_db",
    "record_ai_call",
    "record_decision",
]


def now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


class Contract(Base):
    __tablename__ = "contracts"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_slug: Mapped[str] = mapped_column(String(200), unique=True)
    filename: Mapped[str] = mapped_column(String(300))
    sections: Mapped[list[Any]] = mapped_column(default=list)
    lang: Mapped[str] = mapped_column(String(5), default="id")
    rate_card: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(default=now)


class BaselineVersion(Base):
    __tablename__ = "baseline_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("contracts.id"))
    # 0 for the working draft; approved versions are 1, 2, ...
    number: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String(10), default="draft")
    items: Mapped[list[Any]] = mapped_column(default=list)
    approved_by: Mapped[str | None] = mapped_column(String(200), default=None)
    approved_at: Mapped[datetime | None] = mapped_column(default=None)


class BacktestRun(Base):
    __tablename__ = "backtest_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    contract_id: Mapped[int] = mapped_column(ForeignKey("contracts.id"))
    baseline_version_id: Mapped[int] = mapped_column(
        ForeignKey("baseline_versions.id")
    )
    dataset_name: Mapped[str] = mapped_column(String(300))
    started_at: Mapped[datetime] = mapped_column(default=now)
    finished_at: Mapped[datetime | None] = mapped_column(default=None)
    error: Mapped[str | None] = mapped_column(Text, default=None)


class BacktestResult(Base):
    __tablename__ = "backtest_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("backtest_runs.id"))
    ticket_id: Mapped[str] = mapped_column(String(50))
    source: Mapped[str] = mapped_column(String(20), default="")
    date: Mapped[str] = mapped_column(String(20), default="")
    text: Mapped[str] = mapped_column(Text)
    expected: Mapped[dict[str, Any]] = mapped_column(default=dict)
    predicted: Mapped[dict[str, Any] | None] = mapped_column(JSON, default=None)
    status: Mapped[str] = mapped_column(String(10), default="ok")
    verdict: Mapped[str | None] = mapped_column(String(10), default=None)


class AiCall(Base):
    __tablename__ = "ai_calls"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(default=now)
    purpose: Mapped[str] = mapped_column(String(50))
    model: Mapped[str] = mapped_column(String(100))
    prompt: Mapped[str] = mapped_column(Text)
    response: Mapped[str] = mapped_column(Text, default="")
    prompt_tokens: Mapped[int] = mapped_column(default=0)
    completion_tokens: Mapped[int] = mapped_column(default=0)
    latency_ms: Mapped[int] = mapped_column(default=0)
    cost_idr: Mapped[float] = mapped_column(default=0.0)
    ok: Mapped[bool] = mapped_column(default=True)


class Decision(Base):
    __tablename__ = "decisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(default=now)
    actor: Mapped[str] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(50))
    subject: Mapped[str] = mapped_column(String(200))
    detail: Mapped[dict[str, Any]] = mapped_column(default=dict)


def make_session(db_url: str) -> sessionmaker[Session]:
    if db_url.startswith("sqlite:///") and not db_url.startswith("sqlite:///:"):
        Path(db_url.removeprefix("sqlite:///")).parent.mkdir(
            parents=True, exist_ok=True
        )
    engine = create_engine(
        db_url,
        connect_args={"check_same_thread": False}
        if db_url.startswith("sqlite")
        else {},
    )
    init_db(engine)
    return sessionmaker(engine, expire_on_commit=False)


def init_db(engine) -> None:
    Base.metadata.create_all(engine)


def record_ai_call(session: Session, **fields: Any) -> AiCall:
    row = AiCall(**fields)
    session.add(row)
    session.commit()
    return row


def record_decision(
    session: Session, actor: str, action: str, subject: str, detail: dict
) -> Decision:
    row = Decision(actor=actor, action=action, subject=subject, detail=detail)
    session.add(row)
    session.commit()
    return row
