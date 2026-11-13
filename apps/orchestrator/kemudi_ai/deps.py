"""FastAPI dependencies shared by `api.py` and the routers it includes."""

from functools import lru_cache

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session, sessionmaker

from .auth import ProjectAccess, TaigaUser, current_user, project_access
from .config import Settings, get_settings
from .llm import LLM, HermesLLM
from .store import make_session


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


def access(slug: str, user: TaigaUser = Depends(current_user),
           settings: Settings = Depends(get_settings)) -> ProjectAccess:
    """Membership (404 otherwise) and whether the caller is a project admin."""
    return project_access(slug, user, settings)


def admin(slug: str, user: TaigaUser = Depends(current_user), settings: Settings = Depends(get_settings)):
    if not project_access(slug, user, settings).is_admin:
        raise HTTPException(403, "project admins only")
    return user


def actor(user: TaigaUser) -> str:
    return f"{user.username} ({user.id})"
