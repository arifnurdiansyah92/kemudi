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


def is_kemudi_admin(user: TaigaUser, settings: Settings) -> bool:
    """A Kemudi instance admin: manages the skill library. Matched by Taiga
    user id (KEMUDI_ADMIN_USER_IDS); the username list
    (KEMUDI_ADMIN_USERNAMES) is a fallback, weaker because a user can rename
    themselves."""
    if user.id in settings.admin_user_id_set():
        return True
    return user.username in settings.admin_username_set()


def kemudi_admin(user: TaigaUser = Depends(current_user),
                 settings: Settings = Depends(get_settings)) -> TaigaUser:
    if not is_kemudi_admin(user, settings):
        raise HTTPException(403, "Kemudi admins only")
    return user


def is_superadmin(user: TaigaUser, settings: Settings) -> bool:
    """Instance-wide oversight (the portfolio page): a Taiga superuser, or a
    Kemudi instance admin from KEMUDI_ADMIN_USER_IDS / USERNAMES."""
    return user.is_superuser or is_kemudi_admin(user, settings)


def superadmin(user: TaigaUser = Depends(current_user),
               settings: Settings = Depends(get_settings)) -> TaigaUser:
    if not is_superadmin(user, settings):
        raise HTTPException(403, "superadmins only")
    return user


def sees_money(acc: ProjectAccess, show_prices: bool) -> bool:
    """Rupiah values (rate card, baseline prices, backtest value, Awak cost)
    are for project admins. Members see them only once an admin turns on
    'show prices' for the project."""
    return acc.is_admin or show_prices


def actor(user: TaigaUser) -> str:
    return f"{user.username} ({user.id})"
