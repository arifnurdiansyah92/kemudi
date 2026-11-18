"""Runs product agents in the background, a few at a time.

The API stores a run as `queued` and hands it here; a small thread pool runs
`agents.execute`. Nothing survives a restart: `recover()` ends the runs a
stopped process left behind as failed, so none stays "running" forever.
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings
from ..llm import HermesLLM
from ..store import ProductRun
from . import agents, data
from .web import HermesResearcher, Researcher

log = logging.getLogger(__name__)

RESTARTED = "server dimulai ulang saat riset berjalan; jalankan lagi"


def code_overview(settings: Settings):
    """The project's repos as intake reads them (awak/repo_context.py)."""
    def overview(db: Session, slug: str) -> str:
        from ..awak import repo_context

        ctx = repo_context.load(db, settings, slug)
        return ctx.overview() if ctx else ""
    return overview


class ProductService:
    def __init__(self, settings: Settings, sessions: sessionmaker[Session],
                 deps: agents.Deps | None = None, workers: int | None = None):
        self.settings, self.sessions = settings, sessions
        self.deps = deps or agents.Deps(
            settings=settings, sessions=sessions,
            llm=HermesLLM(settings, sessions),
            researcher=self._researcher(),
            source=lambda token: data.TaigaSource(settings.taiga_api_url, token),
            overview=code_overview(settings),
        )
        self.pool = ThreadPoolExecutor(max_workers=workers or settings.product_workers,
                                       thread_name_prefix="product")

    def _researcher(self) -> Researcher | None:
        if not self.settings.riset_url.strip():
            return None
        return HermesResearcher(self.settings, self.sessions)

    @property
    def web(self) -> bool:
        return self.deps.researcher is not None

    def start(self, run_id: int, token: str) -> None:
        """The token is the caller's Taiga token: held in memory for the run,
        never stored."""
        self.pool.submit(self._run, run_id, token)

    def _run(self, run_id: int, token: str) -> None:
        try:
            agents.execute(self.deps, run_id, token)
        except Exception:  # noqa: BLE001 - execute() already ends the run; belt and braces
            log.exception("product run %s crashed", run_id)


def recover(sessions: sessionmaker[Session]) -> int:
    """At start: runs a stopped process left queued or running end as failed."""
    with sessions() as db:
        rows = db.query(ProductRun).filter(ProductRun.status.in_(("queued", "running"))).all()
        for r in rows:
            r.status, r.error, r.stage = "failed", RESTARTED, ""
            r.finished_at = datetime.now(UTC)
        db.commit()
        return len(rows)
