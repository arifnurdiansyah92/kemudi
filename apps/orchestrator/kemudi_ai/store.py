"""Contract data, backtests and the append-only audit tables.

`ai_calls` and `decisions` are written only through `record_ai_call` and
`record_decision`; nothing in the service updates or deletes them.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, ForeignKey, String, Text, UniqueConstraint, create_engine, inspect, text
from sqlalchemy.pool import StaticPool
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
    "AwakJob",
    "AwakEvent",
    "AwakKey",
    "AwakProject",
    "AwakRepo",
    "AwakRole",
    "AwakRunbook",
    "AwakEnvVar",
    "AwakWorkerLease",
    "AwakLlmAlias",
    "record_event",
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
    # Awak runs: which level the model connection came from (agent|project|
    # server); '' for other calls. Never the key.
    llm_source: Mapped[str] = mapped_column(String(10), default="")


class Decision(Base):
    __tablename__ = "decisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(default=now)
    actor: Mapped[str] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(50))
    subject: Mapped[str] = mapped_column(String(200))
    detail: Mapped[dict[str, Any]] = mapped_column(default=dict)


class AwakJob(Base):
    """One story's run through the Awak loop. Mutable: phase and counters."""

    __tablename__ = "awak_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_slug: Mapped[str] = mapped_column(String(200))
    story_id: Mapped[int] = mapped_column()
    story_ref: Mapped[int] = mapped_column()
    branch: Mapped[str] = mapped_column(String(100))
    # queued, running, passed, failed (gave up), stopped (human took over)
    state: Mapped[str] = mapped_column(String(20), default="queued")
    phase: Mapped[str] = mapped_column(String(20), default="")
    attempts: Mapped[int] = mapped_column(default=0)
    infra_errors: Mapped[int] = mapped_column(default=0)
    feedback: Mapped[str] = mapped_column(Text, default="")
    last_sha: Mapped[str] = mapped_column(String(64), default="")
    cost_idr: Mapped[float] = mapped_column(default=0.0)
    started_at: Mapped[datetime] = mapped_column(default=now)
    updated_at: Mapped[datetime] = mapped_column(default=now)
    # Iteration 2: pinned at pick, kept for rework.
    repo_id: Mapped[int | None] = mapped_column(default=None)
    role_id: Mapped[int | None] = mapped_column(default=None)
    # The repo as the last attempt ran it; a merge refuses if it changed since.
    repo_url: Mapped[str] = mapped_column(String(500), default="")
    repo_branch: Mapped[str] = mapped_column(String(100), default="")
    prompt_version: Mapped[str] = mapped_column(String(80), default="")
    merge_mode: Mapped[str] = mapped_column(String(10), default="")  # snapshot at pick
    # '' | requested | merging | merged | failed
    merge_state: Mapped[str] = mapped_column(String(12), default="")
    merged_sha: Mapped[str] = mapped_column(String(64), default="")
    merge_error: Mapped[str] = mapped_column(Text, default="")


class AwakKey(Base):
    """A Kemudi-generated SSH key pair. The private half is a Fernet token."""

    __tablename__ = "awak_keys"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_kind: Mapped[str] = mapped_column(String(10))  # repo | machine
    owner_id: Mapped[int] = mapped_column()
    public_key: Mapped[str] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String(100))
    private_key_enc: Mapped[str] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(default=now)


class AwakProject(Base):
    """Per-project Awak settings (Project settings -> Agent)."""

    __tablename__ = "awak_projects"
    slug: Mapped[str] = mapped_column(String(200), primary_key=True)
    enabled: Mapped[bool] = mapped_column(default=False)
    merge_mode: Mapped[str] = mapped_column(String(10), default="approve")
    # off | gates | browser: what runs after the commit is collected. Added to
    # an old table without a default: NULL marks a row the one-time fix-up
    # (`_set_qa_modes`) has not reached yet.
    qa_mode: Mapped[str] = mapped_column(String(10), default="gates",
                                         info={"migrate_default": False})
    deploy_command: Mapped[str] = mapped_column(Text, default="")
    executor: Mapped[str] = mapped_column(String(10), default="local")
    ssh_host: Mapped[str] = mapped_column(String(255), default="")
    ssh_port: Mapped[int] = mapped_column(default=22)
    ssh_user: Mapped[str] = mapped_column(String(64), default="")
    ssh_key_id: Mapped[int | None] = mapped_column(ForeignKey("awak_keys.id"), default=None)
    preflight: Mapped[dict[str, Any]] = mapped_column(default=dict)
    # BYOK, project level ("all agents"). The key is a Fernet token; set means
    # base_url and model are both non-empty.
    llm_base_url: Mapped[str] = mapped_column(String(500), default="")
    llm_model: Mapped[str] = mapped_column(String(100), default="")
    llm_api_key_enc: Mapped[str] = mapped_column(Text, default="")
    llm_key_last4: Mapped[str] = mapped_column(String(4), default="")
    # The worker's last failure for this project (e.g. the bot cannot open it);
    # cleared on the next pass that reaches the board.
    last_error: Mapped[str] = mapped_column(Text, default="")
    last_error_at: Mapped[datetime | None] = mapped_column(default=None)
    updated_by: Mapped[str] = mapped_column(String(200), default="")
    updated_at: Mapped[datetime] = mapped_column(default=now)


class AwakRepo(Base):
    __tablename__ = "awak_repos"
    __table_args__ = (UniqueConstraint("project_slug", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_slug: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(10), default="web")  # web|api|mobile|other
    url: Mapped[str] = mapped_column(String(500))
    default_branch: Mapped[str] = mapped_column(String(100), default="main")
    subdir: Mapped[str] = mapped_column(String(200), default="")
    # Newline-separated command lines.
    install_cmd: Mapped[str] = mapped_column(Text, default="")
    check_cmd: Mapped[str] = mapped_column(Text, default="")
    build_cmd: Mapped[str] = mapped_column(Text, default="")
    run_cmd: Mapped[str] = mapped_column(Text, default="")
    key_id: Mapped[int | None] = mapped_column(ForeignKey("awak_keys.id"), default=None)
    last_check: Mapped[dict[str, Any]] = mapped_column(default=dict)
    position: Mapped[int] = mapped_column(default=0)
    updated_by: Mapped[str] = mapped_column(String(200), default="")
    updated_at: Mapped[datetime] = mapped_column(default=now)


class AwakRole(Base):
    __tablename__ = "awak_roles"
    id: Mapped[int] = mapped_column(primary_key=True)
    project_slug: Mapped[str] = mapped_column(String(200))
    template: Mapped[str] = mapped_column(String(20))  # frontend|backend|qa
    name: Mapped[str] = mapped_column(String(100))
    area: Mapped[str] = mapped_column(String(20))  # web|backend|qa
    model: Mapped[str] = mapped_column(String(100))
    repo_ids: Mapped[list[Any]] = mapped_column(default=list)
    allowed_paths: Mapped[list[Any]] = mapped_column(default=list)
    denied_paths: Mapped[list[Any]] = mapped_column(default=list)
    prompt_overlay: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(default=True)
    version: Mapped[int] = mapped_column(default=1)
    # BYOK, agent level; same shape as AwakProject's.
    llm_base_url: Mapped[str] = mapped_column(String(500), default="")
    llm_model: Mapped[str] = mapped_column(String(100), default="")
    llm_api_key_enc: Mapped[str] = mapped_column(Text, default="")
    llm_key_last4: Mapped[str] = mapped_column(String(4), default="")
    updated_by: Mapped[str] = mapped_column(String(200), default="")
    updated_at: Mapped[datetime] = mapped_column(default=now)


class AwakRunbook(Base):
    """A project's runbook (kemudi_ai/awak/runbook.py), as an admin approved it."""

    __tablename__ = "awak_runbooks"
    project_slug: Mapped[str] = mapped_column(String(200), primary_key=True)
    spec: Mapped[dict[str, Any]] = mapped_column(default=dict)
    version: Mapped[int] = mapped_column(default=0)
    approved_by: Mapped[str] = mapped_column(String(200), default="")
    approved_at: Mapped[datetime | None] = mapped_column(default=None)
    updated_by: Mapped[str] = mapped_column(String(200), default="")
    updated_at: Mapped[datetime] = mapped_column(default=now)


class AwakEnvVar(Base):
    """A project's env value (kemudi_ai/awak/vault.py). The value is a Fernet
    token under a key derived for the vault, secret or not; a secret's value
    is never returned by the API."""

    __tablename__ = "awak_env_vars"
    __table_args__ = (UniqueConstraint("project_slug", "name"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    project_slug: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(64))
    value_enc: Mapped[str] = mapped_column(Text)
    secret: Mapped[bool] = mapped_column(default=True)
    updated_by: Mapped[str] = mapped_column(String(200), default="")
    updated_at: Mapped[datetime] = mapped_column(default=now)


class AwakLlmAlias(Base):
    """A per-run model name Awak sends to the orchestrator's model proxy. It
    maps to a project/role, not to a key; rows are deleted when the run ends.
    Naive UTC times."""

    __tablename__ = "awak_llm_aliases"
    alias: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_slug: Mapped[str] = mapped_column(String(200))
    role_id: Mapped[int | None] = mapped_column(default=None)
    # The model for the server-default level (the role's model, or QA's).
    fallback_model: Mapped[str] = mapped_column(String(100), default="")
    purpose: Mapped[str] = mapped_column(String(50), default="")
    expires_at: Mapped[datetime] = mapped_column()
    # What the proxy saw upstream during the run: a run whose every model call
    # failed is the provider's fault, not the story's (an infra error).
    upstream_ok: Mapped[int] = mapped_column(default=0)
    upstream_errors: Mapped[int] = mapped_column(default=0)
    upstream_error: Mapped[str] = mapped_column(Text, default="")


class AwakWorkerLease(Base):
    """One row: the Awak worker allowed to run. Claimed with a conditional
    UPDATE (or the first INSERT); naive UTC times."""

    __tablename__ = "awak_worker_lease"
    id: Mapped[int] = mapped_column(primary_key=True)  # always 1
    holder: Mapped[str] = mapped_column(String(200))
    expires_at: Mapped[datetime] = mapped_column()


class AwakEvent(Base):
    """Append-only log of job steps."""

    __tablename__ = "awak_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(default=now)
    job_id: Mapped[int] = mapped_column(ForeignKey("awak_jobs.id"))
    kind: Mapped[str] = mapped_column(String(30))
    detail: Mapped[dict[str, Any]] = mapped_column(default=dict)


def record_event(session: Session, job_id: int, kind: str, detail: dict) -> AwakEvent:
    row = AwakEvent(job_id=job_id, kind=kind, detail=detail)
    session.add(row)
    session.commit()
    return row


def make_session(db_url: str) -> sessionmaker[Session]:
    if db_url.startswith("sqlite:///") and not db_url.startswith("sqlite:///:"):
        Path(db_url.removeprefix("sqlite:///")).parent.mkdir(
            parents=True, exist_ok=True
        )
    kwargs: dict[str, Any] = {}
    if db_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    if ":memory:" in db_url:
        kwargs["poolclass"] = StaticPool  # one shared in-memory database
    engine = create_engine(db_url, **kwargs)
    init_db(engine)
    return sessionmaker(engine, expire_on_commit=False)


def init_db(engine, host_git: str | None = None) -> None:
    """`host_git`: the local Kemudi repo (settings.host_git), for one-time
    data fix-ups; read from the settings when not given."""
    Base.metadata.create_all(engine)
    _migrate(engine)
    _set_qa_modes(engine, host_git)


def _set_qa_modes(engine, host_git: str | None) -> None:
    """For projects from before `awak_projects.qa_mode` (NULL there): those
    with the Kemudi repo keep browser QA (iteration 1-2 behaviour); the others
    get `gates`, and `auto` merge, which needs browser QA, becomes `approve`.
    Driven by the NULLs, in one transaction, so a crash in between is
    finished on the next start and a fixed-up row is never touched again."""
    with Session(engine) as db:
        rows = db.query(AwakProject).filter(AwakProject.qa_mode.is_(None)).all()
        if not rows:
            return
        if host_git is None:
            from .config import get_settings

            host_git = get_settings().host_git
        kemudi = {r.project_slug for r in db.query(AwakRepo).filter_by(url=host_git)}
        for p in rows:
            p.qa_mode = "browser" if p.slug in kemudi else "gates"
            if p.merge_mode == "auto" and p.qa_mode != "browser":
                p.merge_mode = "approve"
                db.add(Decision(actor="migration", action="awak_settings", subject=p.slug,
                                detail={"changed": {"merge_mode": "approve"},
                                        "reason": "auto merge needs QA mode browser"}))
        db.commit()


# Tables that existed before a column was added to them. `create_all` never
# alters an existing table, so missing columns are added here.
_MIGRATED_TABLES = ("awak_jobs", "awak_projects", "awak_roles", "ai_calls",
                    "awak_llm_aliases")


def _sql_literal(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


def _migrate(engine) -> dict[str, set[str]]:
    """Adds missing columns; returns {table: names of the columns added}."""
    added: dict[str, set[str]] = {}
    for name in _MIGRATED_TABLES:
        table = Base.metadata.tables[name]
        existing = {c["name"] for c in inspect(engine).get_columns(name)}
        missing = [c for c in table.columns if c.name not in existing]
        if not missing:
            continue
        added[name] = {c.name for c in missing}
        with engine.begin() as conn:
            for col in missing:
                ddl = f"ALTER TABLE {name} ADD COLUMN {col.name} {col.type.compile(dialect=engine.dialect)}"
                default = col.default.arg if col.default is not None else None
                if col.info.get("migrate_default") is False:
                    default = None  # left NULL for a data fix-up to fill in
                if default is not None and not callable(default):
                    ddl += f" DEFAULT {_sql_literal(default)}"
                    if not col.nullable:
                        ddl += " NOT NULL"
                conn.execute(text(ddl))
    return added


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
