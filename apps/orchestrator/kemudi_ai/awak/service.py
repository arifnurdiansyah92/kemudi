"""Wire the real clients together and run the worker in a daemon thread."""

import logging
import threading

from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings
from .agent import HermesAgent
from .runner import HttpRunner
from .svc import SvcClient
from .taiga import Taiga
from .worker import Worker

log = logging.getLogger(__name__)


def build_worker(settings: Settings, sessions: sessionmaker[Session]) -> Worker:
    return Worker(
        settings,
        sessions,
        taiga=Taiga(settings.taiga_api_url, settings.awak_username, settings.awak_password),
        qa_taiga=Taiga(settings.taiga_api_url, settings.qa_username, settings.qa_password),
        agent=HermesAgent(settings, sessions),
        runner=HttpRunner(settings.runner_url, settings.runner_key),
        repo=None,  # built per job from the repo row (worker.repo_for)
        svc=SvcClient(settings.svc_url, settings.svc_key) if settings.svc_key else None,
    )


def start_worker(settings: Settings, sessions: sessionmaker[Session]) -> threading.Thread:
    worker = build_worker(settings, sessions)  # fails fast on a non-local Taiga
    t = threading.Thread(target=worker.run_forever, name="awak-worker", daemon=True)
    t.start()
    log.warning("Awak worker started (seed: %s)", settings.awak_project_slugs())
    return t
