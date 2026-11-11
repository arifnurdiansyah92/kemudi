"""Callers authenticate with their Kemudi (Taiga) token; Taiga decides roles."""

import httpx
from fastapi import Depends, Header, HTTPException
from pydantic import BaseModel

from .config import Settings, get_settings


class TaigaUser(BaseModel):
    id: int
    username: str
    full_name: str = ""
    token: str


class ProjectAccess(BaseModel):
    slug: str
    is_admin: bool


_transport: httpx.BaseTransport | None = None  # tests swap in a MockTransport


def _client(settings: Settings, token: str) -> httpx.Client:
    return httpx.Client(
        base_url=settings.taiga_api_url.rstrip("/"),
        headers={"Authorization": f"Bearer {token}"},
        timeout=15,
        transport=_transport,
    )


def current_user(
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> TaigaUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "missing token")
    token = authorization.split(" ", 1)[1]
    with _client(settings, token) as c:
        r = c.get("/users/me")
    if r.status_code != 200:
        raise HTTPException(401, "invalid token")
    me = r.json()
    return TaigaUser(
        id=me["id"],
        username=me["username"],
        full_name=me.get("full_name_display") or me.get("full_name") or "",
        token=token,
    )


def project_access(slug: str, user: TaigaUser, settings: Settings) -> ProjectAccess:
    with _client(settings, user.token) as c:
        r = c.get("/projects/by_slug", params={"slug": slug})
    if r.status_code != 200:
        raise HTTPException(404, "project not found")
    return ProjectAccess(slug=slug, is_admin=bool(r.json().get("i_am_admin")))
