"""Skill marketplaces: `/skill-marketplaces/...` (Kemudi admins only).

docs/superpowers/plans/2026-11-14-awak-skills-pr3-marketplace.md, Task 2.
Register a GitHub repo, refresh its listing (fetched by kemudi-runner),
list plugins -> skills, install one skill (pinned to the fetched commit,
disabled until an admin enables it). Every write is a `decisions` row.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..auth import TaigaUser
from ..config import Settings, get_settings
from ..deps import actor, get_db, kemudi_admin
from ..store import AwakSkillMarketplace, record_decision
from . import marketplace, skills
from .fetched import FetchError
from .runner import Runner
from .skills_api import _detail, _problems, _record, _version_detail, get_fetch_runner

router = APIRouter(prefix="/skill-marketplaces")


def _row(m: AwakSkillMarketplace) -> dict:
    plugins, skill_count = marketplace.counts(m.listing or {})
    return {"id": m.id, "name": m.name or f"{m.owner}/{m.repo}",
            "repo": f"{m.owner}/{m.repo}", "ref": m.ref, "builtin": m.builtin,
            "url": f"https://github.com/{m.owner}/{m.repo}",
            "last_sha": m.last_sha, "last_fetched_at": m.last_fetched_at, "error": m.error,
            "description": (m.listing or {}).get("description", ""),
            "plugin_count": plugins, "skill_count": skill_count,
            "created_by": m.created_by, "created_at": m.created_at}


def _get(db: Session, mid: int) -> AwakSkillMarketplace:
    m = db.get(AwakSkillMarketplace, mid)
    if m is None:
        raise HTTPException(404, "no such marketplace")
    return m


def _decide(db: Session, user: TaigaUser, m: AwakSkillMarketplace, op: str, **detail) -> None:
    record_decision(db, actor(user), "awak_skill_marketplace", f"{m.owner}/{m.repo}",
                    {"op": op, "id": m.id, **detail})


@router.get("")
def list_marketplaces(_: TaigaUser = Depends(kemudi_admin), db: Session = Depends(get_db)):
    rows = (db.query(AwakSkillMarketplace)
            .order_by(AwakSkillMarketplace.builtin.desc(), AwakSkillMarketplace.id).all())
    return {"marketplaces": [_row(m) for m in rows]}


class MarketplaceIn(BaseModel):
    repo: str = Field("", max_length=300)


@router.post("", status_code=201)
def add_marketplace(body: MarketplaceIn, user: TaigaUser = Depends(kemudi_admin),
                    db: Session = Depends(get_db)):
    """`{repo: "owner/repo[@ref]" | "https://github.com/owner/repo"}`; GitHub
    only. Registered, not fetched: refresh it next."""
    try:
        owner, repo, ref = marketplace.parse_repo(body.repo)
    except marketplace.MarketplaceError as e:
        raise _problems(422, str(e), [str(e)], code="bad_repo") from e
    if marketplace.find_marketplace(db, owner, repo, ref) is not None:
        raise _problems(409, f"{owner}/{repo} is already registered", [], code="exists")
    m = AwakSkillMarketplace(name=f"{owner}/{repo}", owner=owner, repo=repo, ref=ref,
                             builtin=False, created_by=actor(user))
    db.add(m)
    db.commit()
    _decide(db, user, m, "add", ref=ref)
    return _row(m)


@router.delete("/{mid}")
def delete_marketplace(mid: int, user: TaigaUser = Depends(kemudi_admin),
                       db: Session = Depends(get_db)):
    """Installed skills stay (they keep their origin for update checks)."""
    m = _get(db, mid)
    if m.builtin:
        raise _problems(409, "built-in marketplaces cannot be removed", [], code="builtin")
    _decide(db, user, m, "delete")
    db.delete(m)
    db.commit()
    return {"deleted": mid}


@router.post("/{mid}/refresh")
def refresh_marketplace(mid: int, user: TaigaUser = Depends(kemudi_admin),
                        settings: Settings = Depends(get_settings),
                        runner: Runner = Depends(get_fetch_runner),
                        db: Session = Depends(get_db)):
    """Fetch the repo (and its github plugin sources) through the runner and
    cache the listing at the fetched sha. A failure is kept on the row (502)."""
    m = _get(db, mid)
    try:
        marketplace.refresh(db, runner, settings, m)
    except (FetchError, marketplace.MarketplaceError) as e:
        _decide(db, user, m, "refresh_failed", error=str(e)[:300])
        raise _problems(502 if isinstance(e, FetchError) else 422,
                        "the marketplace could not be read", [str(e)], code="fetch_failed",
                        marketplace=jsonable_encoder(_row(m))) from e
    _decide(db, user, m, "refresh", sha=m.last_sha)
    return _row(m)


@router.get("/{mid}/plugins")
def marketplace_plugins(mid: int, _: TaigaUser = Depends(kemudi_admin),
                        db: Session = Depends(get_db)):
    """The cached listing: plugins -> skills, each skill with `installed`
    ({slug, source, version, enabled, same_origin, sha}) when the library has it."""
    m = _get(db, mid)
    listing = m.listing or {}
    plugins = []
    for p in listing.get("plugins") or []:
        p = {k: v for k, v in p.items() if not k.startswith("_")}
        p["skills"] = [{**s, "installed": marketplace.installed_info(db, m, p, s)}
                       for s in p.get("skills") or []]
        plugins.append(p)
    return {"marketplace": _row(m), "refreshed": bool(m.last_sha),
            "owner": listing.get("owner", ""), "kind": listing.get("kind", ""),
            "plugins": plugins}


class InstallIn(BaseModel):
    plugin: str = Field(..., min_length=1, max_length=200)
    skill: str = Field(..., min_length=1, max_length=64)


@router.post("/{mid}/install")
def install_skill(mid: int, body: InstallIn, user: TaigaUser = Depends(kemudi_admin),
                  settings: Settings = Depends(get_settings),
                  runner: Runner = Depends(get_fetch_runner), db: Session = Depends(get_db)):
    """Install one skill from the cached listing at its pinned sha: a new
    `marketplace` skill, disabled until an admin enables it. 409 when a
    skill with that name exists."""
    m = _get(db, mid)
    try:
        sk, v = marketplace.install(db, runner, settings, m, body.plugin, body.skill,
                                    actor(user))
    except marketplace.SkillClash as e:
        raise _problems(409, f"a {e.skill.source} skill named {e.skill.slug} is already in "
                        "the library", [], code="exists", slug=e.skill.slug,
                        source=e.skill.source) from e
    except marketplace.MarketplaceError as e:
        raise _problems(422, str(e), [str(e)], code="bad_request") from e
    except skills.SkillError as e:
        _record(db, user, body.skill, "install_refused", marketplace=f"{m.owner}/{m.repo}",
                plugin=body.plugin, problems=e.problems[:20])
        raise _problems(422, "the skill is not valid", e.problems) from e
    except FetchError as e:
        raise _problems(502, "the skill could not be fetched", [str(e)],
                        code="fetch_failed") from e
    except IntegrityError as e:
        db.rollback()
        raise _problems(409, f"{body.skill} was installed at the same time by another "
                        "request", [], code="conflict") from e
    _record(db, user, sk.slug, "install", marketplace=f"{m.owner}/{m.repo}",
            plugin=body.plugin, path=(sk.origin or {}).get("path", ""),
            upstream_sha=(sk.origin or {}).get("sha", ""), **_version_detail(v))
    return _detail(db, sk)
