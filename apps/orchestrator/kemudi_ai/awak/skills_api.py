"""The skill library: `/skills/...` (Kemudi admins; the picker list stays in api.py).

docs/superpowers/plans/2026-11-14-awak-skills-pr2-library.md, Task 1. List,
detail, one file by exact key, upload (zip / .skill / SKILL.md, read in
memory), authored skills and their new versions, enable / disable, delete,
and a dry-run validate for the editor. Every write is a `decisions` row
(action `awak_skill`) without file contents.
"""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile as StarletteUpload

from ..auth import TaigaUser, current_user
from ..config import Settings, get_settings
from ..deps import actor, get_db, is_kemudi_admin, kemudi_admin
from ..store import AwakSkill, AwakSkillVersion, record_decision
from . import marketplace, skills
from .fetched import FetchError
from .runner import HttpRunner, Runner

router = APIRouter(prefix="/skills")

LICENSE_FILES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "NOTICE", "NOTICE.md", "NOTICE.txt",
                 "COPYING")
MAX_EXTRA_FILES = skills.MAX_FILES - 1


# --- shapes ---------------------------------------------------------------------

def _problems(status: int, message: str, problems: list[str], **extra) -> HTTPException:
    return HTTPException(status, {"message": message, "problems": problems, **extra})


def _current(db: Session, sk: AwakSkill) -> AwakSkillVersion | None:
    return (db.query(AwakSkillVersion)
            .filter_by(slug=sk.slug, version=sk.current_version).one_or_none())


def _scan_level(v: AwakSkillVersion | None) -> str:
    return (v.scan or {}).get("worst", "") if v is not None else ""


def _item(db: Session, sk: AwakSkill, used: dict[str, list[dict]]) -> dict:
    v = _current(db, sk)
    pending = db.query(AwakSkillVersion).filter_by(slug=sk.slug, status="pending").count()
    return {"slug": sk.slug, "title": sk.title or sk.slug,
            "description": skills._short(sk.description), "source": sk.source,
            "license": sk.license, "enabled": sk.enabled,
            "version": v.version if v is not None else None, "scan_level": _scan_level(v),
            "used_by": used.get(sk.slug, []), "pending_versions": pending,
            "updated_at": sk.updated_at}


def _detail(db: Session, sk: AwakSkill) -> dict:
    out = _item(db, sk, skills.used_by(db))
    out["description"] = sk.description
    out.update(origin=sk.origin or {}, created_by=sk.created_by, created_at=sk.created_at)
    versions = (db.query(AwakSkillVersion).filter_by(slug=sk.slug)
                .order_by(AwakSkillVersion.version.desc()).all())
    if sk.source == "marketplace":
        out["pending"] = marketplace.pending_detail(db, sk)
        o = sk.origin or {}
        if o.get("repo") and o.get("sha"):
            out["origin_url"] = (f"https://github.com/{o['repo']}/tree/{o['sha']}/"
                                 f"{o.get('path', '')}").rstrip("/")
    else:
        out["pending"] = []
    out["versions"] = [{"version": v.version, "sha256": v.sha256, "size": v.size,
                        "files": len(v.files or {}), "status": v.status,
                        "scan_level": _scan_level(v), "created_by": v.created_by,
                        "created_at": v.created_at} for v in versions]
    v = _current(db, sk)
    if v is None:
        out["current"] = None
        return out
    files = skills.decode_files(v.files or {})
    text = {p: d.decode("utf-8") for p, d in files.items() if skills._is_text(d)}
    out["current"] = {
        "version": v.version, "sha256": v.sha256,
        "files": [{"path": p, "size": len(files[p]), "binary": p not in text}
                  for p in sorted(files)],
        "findings": (v.scan or {}).get("findings", []),
        "warnings": (v.scan or {}).get("warnings", []),
        "skill_md": text.get(skills.SKILL_FILE, ""),
        "license_files": [{"path": p, "text": text[p]} for p in sorted(text)
                          if p in LICENSE_FILES],
    }
    return out


def get_fetch_runner(settings: Settings = Depends(get_settings)) -> Runner:
    """kemudi-runner, for `fetch_repo` (marketplace fetches)."""
    return HttpRunner(settings.runner_url, settings.runner_key)


def _get(db: Session, slug: str) -> AwakSkill:
    sk = db.get(AwakSkill, slug)
    if sk is None:
        raise HTTPException(404, "no such skill")
    return sk


def _record(db: Session, user: TaigaUser, slug: str, op: str, **detail) -> None:
    record_decision(db, actor(user), "awak_skill", slug, {"op": op, **detail})


def _version_detail(v: AwakSkillVersion) -> dict:
    """What a decision row says about a version: never file contents."""
    return {"version": v.version, "sha": v.sha256, "size": v.size,
            "files": len(v.files or {}), "worst": _scan_level(v),
            "findings": len((v.scan or {}).get("findings", []))}


def _check(slug: str, files: dict[str, bytes]) -> skills.Checked:
    try:
        return skills.check(slug, files)
    except skills.SkillError as e:
        raise _problems(422, "the skill is not valid", e.problems) from e


def _conflict(db: Session, slug: str) -> HTTPException:
    """Another write to the same skill landed first (unique slug / version)."""
    db.rollback()
    return _problems(409, f"{slug} was changed at the same time by another request; "
                     "try again", [], code="conflict", slug=slug)


def _findings_rise(db: Session, sk: AwakSkill, cur: AwakSkillVersion | None,
                   worst: str) -> dict | None:
    """What a new version of `sk` would bring to the roles that run it: set
    when the skill is enabled, listed by a role, and the new version's worst
    scan level is above the current one's."""
    if not sk.enabled:
        return None
    before = _scan_level(cur)
    if skills.severity_rank(worst) <= skills.severity_rank(before):
        return None
    used = skills.used_by(db).get(sk.slug, [])
    if not used:
        return None
    return {"from": before, "to": worst, "used_by": used}


def _add_version(db: Session, sk: AwakSkill, files: dict[str, bytes], c: skills.Checked,
                 user: TaigaUser, accept_findings: bool = False
                 ) -> tuple[AwakSkillVersion | None, bool, dict | None]:
    """A new current version of `sk` (None when the tree equals the current
    one). A new version of an enabled skill goes live at once for the roles
    that list it, so one whose scan is worse than the current version's is
    refused (409 `findings_rise`) unless `accept_findings`. A high finding
    disables the skill (enabling refuses it anyway). Returns (version,
    disabled now, the accepted rise or None)."""
    cur = _current(db, sk)
    if cur is not None and cur.sha256 == c.sha:
        return None, False, None
    rise = _findings_rise(db, sk, cur, c.worst)
    if rise is not None and not accept_findings:
        n = len(rise["used_by"])
        raise _problems(
            409, f"this version's scan ({rise['to']}) is worse than the current version's "
            f"({rise['from'] or 'clean'}) and {n} role{'s' if n != 1 else ''} will get it on "
            "the next run; send accept_findings=true to use it anyway",
            [f"{f['path']}:{f['line']} {f['rule']}" for f in c.findings],
            code="findings_rise", slug=sk.slug, worst=rise["to"], previous=rise["from"],
            findings=c.findings, used_by=rise["used_by"])
    slug = sk.slug  # readable after a failed flush
    try:
        v = skills.store_version(db, slug, files, c, actor(user))
        sk.current_version = v.version
        sk.description = c.meta.description
        # The new version's metadata wins: no licence there clears it.
        sk.license = c.meta.license
        sk.updated_at = datetime.now(UTC)
        disabled = sk.enabled and c.worst == "high"
        if disabled:
            sk.enabled = False
        db.commit()
    except IntegrityError as e:
        raise _conflict(db, slug) from e
    return v, disabled, rise


def _rise_detail(rise: dict | None) -> dict:
    """What a version decision row says about an accepted findings rise."""
    if rise is None:
        return {}
    return {"accepted_findings": {"from": rise["from"], "to": rise["to"],
                                  "used_by": [f"{u['project']}/{u['role']}"
                                              for u in rise["used_by"]]}}


def _new_skill(db: Session, slug: str, files: dict[str, bytes], c: skills.Checked,
               user: TaigaUser, origin: dict) -> AwakSkillVersion:
    """A new `local` skill, disabled until an admin enables it."""
    try:
        sk = AwakSkill(slug=slug, source="local", title=slug, description=c.meta.description,
                       license=c.meta.license, enabled=False, current_version=1,
                       origin=origin, created_by=actor(user))
        db.add(sk)
        v = skills.store_version(db, slug, files, c, actor(user))
        sk.current_version = v.version
        db.commit()
    except IntegrityError as e:
        raise _conflict(db, slug) from e
    return v


# --- reads ---------------------------------------------------------------------------

@router.get("/library")
def library(_: TaigaUser = Depends(kemudi_admin), db: Session = Depends(get_db)):
    """Every skill, enabled or not, with where it is used."""
    used = skills.used_by(db)
    rows = db.query(AwakSkill).order_by(AwakSkill.slug).all()
    return {"skills": [_item(db, sk, used) for sk in rows],
            "limits": {"max_bytes": skills.MAX_TOTAL_BYTES, "max_files": skills.MAX_FILES,
                       "max_upload_bytes": skills.MAX_UPLOAD_BYTES,
                       "description_max": skills.DESCRIPTION_MAX,
                       "description_agent_max": skills.DESCRIPTION_AGENT_MAX}}


class AuthoredIn(BaseModel):
    slug: str = Field("", max_length=64)
    description: str = Field("", max_length=4000)
    body: str = Field("", max_length=skills.MAX_TOTAL_BYTES)
    license: str = Field("", max_length=100)
    files: dict[str, str] | None = Field(None, max_length=MAX_EXTRA_FILES)


@router.post("/validate")
def validate_draft(body: AuthoredIn, _: TaigaUser = Depends(kemudi_admin)):
    """Dry run for the editor: problems, warnings, scan findings and the
    SKILL.md as stored and as the agent gets it. Stores nothing."""
    out: dict = {"ok": False, "problems": [], "warnings": [], "findings": [], "worst": "",
                 "skill_md": "", "agent_skill_md": "", "size": 0}
    try:
        files = skills.authored_files(body.slug, body.description, body.body, body.files,
                                      body.license)
    except skills.SkillError as e:
        out["problems"] = e.problems
        return out
    raw = files[skills.SKILL_FILE]
    out["skill_md"] = raw.decode("utf-8")
    out["size"] = sum(len(d) for d in files.values())
    try:
        out["agent_skill_md"] = skills.agent_skill_md(raw).decode("utf-8")
    except skills.SkillError:
        pass
    out["findings"] = skills.scan(files)
    out["worst"] = skills.worst(out["findings"])
    try:
        meta = skills.validate(body.slug, files)
    except skills.SkillError as e:
        out["problems"] = e.problems
        return out
    out.update(ok=True, warnings=list(meta.warnings))
    return out


@router.get("/{slug}")
def skill_detail(slug: str, user: TaigaUser = Depends(current_user),
                 settings: Settings = Depends(get_settings), db: Session = Depends(get_db)):
    """Admins: the full detail. Members: the picker summary of an enabled skill."""
    if not is_kemudi_admin(user, settings):
        for s in skills.picker(db):
            if s["slug"] == slug:
                return s
        raise HTTPException(404, "no such skill")
    return _detail(db, _get(db, slug))


@router.get("/{slug}/versions/{version}/files/{path:path}")
def skill_file(slug: str, version: int, path: str, _: TaigaUser = Depends(kemudi_admin),
               db: Session = Depends(get_db)):
    """One stored file by its exact key: text as {path, text}; binaries as
    {path, size, binary: true} (no download)."""
    v = db.query(AwakSkillVersion).filter_by(slug=slug, version=version).one_or_none()
    if v is None or path not in (v.files or {}):
        raise HTTPException(404, "no such file")
    data = skills.decode_files({path: v.files[path]})[path]
    if skills._is_text(data):
        return {"path": path, "size": len(data), "text": data.decode("utf-8")}
    return {"path": path, "size": len(data), "binary": True}


# --- writes ----------------------------------------------------------------------------

# The whole multipart request: the archive cap plus room for the part headers
# and boundaries. The gateway allows 5 MB on this path (infra/gateway/kemudi.conf).
MAX_UPLOAD_BODY = skills.MAX_UPLOAD_BYTES + 64 * 1024

_UPLOAD_OPENAPI = {"requestBody": {"required": True, "content": {"multipart/form-data": {
    "schema": {"type": "object", "required": ["file"],
               "properties": {"file": {"type": "string", "format": "binary"}}}}}}}


async def _upload_form(request: Request) -> tuple[str, bytes]:
    """The `file` part of the multipart body, read only after the caller is
    known to be a Kemudi admin. A declared `File(...)` parameter would have
    FastAPI spool the body before any dependency (auth) runs, so the route
    takes the raw Request and parses here: Content-Length is checked first
    (required: the gateway buffers the request and always sends it; h11 never
    reads past it), then the form."""
    length = request.headers.get("content-length")
    if length is None:
        raise HTTPException(411, "Content-Length is required")
    try:
        size = int(length)
    except ValueError as e:
        raise HTTPException(400, "bad Content-Length") from e
    if size > MAX_UPLOAD_BODY:
        raise _problems(413, "the upload is too large",
                        [f"the archive is larger than {skills.MAX_UPLOAD_BYTES} bytes"],
                        code="too_large")
    try:
        form = await request.form(max_files=1, max_fields=8)
    except HTTPException:
        raise
    except Exception as e:  # malformed multipart
        raise _problems(422, "the upload was refused", ["not a multipart form upload"]) from e
    try:
        file = form.get("file")
        if not isinstance(file, StarletteUpload):
            raise _problems(422, "the upload was refused", ["no file in the upload"])
        return file.filename or "", await file.read(skills.MAX_UPLOAD_BYTES + 1)
    finally:
        await form.close()


@router.post("/upload", openapi_extra=_UPLOAD_OPENAPI)
async def upload_skill(request: Request, replace: bool = Query(False),
                       accept_findings: bool = Query(False),
                       user: TaigaUser = Depends(kemudi_admin), db: Session = Depends(get_db)):
    """A `.zip` / `.skill` archive or a lone SKILL.md (multipart field
    `file`): a new `local` skill (disabled), or with `replace=true` the next
    version of the `local` skill with that slug (see _add_version for
    `accept_findings`). Auth runs before the body is read (_upload_form)."""
    filename, data = "", b""
    try:
        filename, data = await _upload_form(request)
        up = skills.read_upload(filename, data)
        c = skills.check(up.slug, up.files)
    except (skills.SkillError, HTTPException) as e:
        probs = e.problems if isinstance(e, skills.SkillError) else (
            e.detail.get("problems", []) if isinstance(e.detail, dict) else [str(e.detail)])
        _record(db, user, "-", "upload_refused", filename=filename[:200], size=len(data),
                problems=probs[:20])
        if isinstance(e, HTTPException):
            raise
        raise _problems(422, "the upload was refused", e.problems) from e
    sk = db.get(AwakSkill, up.slug)
    if sk is not None:
        if sk.source != "local":
            raise _problems(409, f"{up.slug} is a {sk.source} skill; upload it under "
                            "another name", [], code="not_local", slug=up.slug,
                            source=sk.source)
        if not replace:
            raise _problems(409, f"a local skill named {up.slug} exists", [], code="exists",
                            slug=up.slug, source=sk.source,
                            version=sk.current_version, enabled=sk.enabled,
                            used_by=skills.used_by(db).get(up.slug, []))
        v, disabled, rise = _add_version(db, sk, up.files, c, user, accept_findings)
        if v is None:
            return {"skill": _detail(db, sk), "created": False, "unchanged": True,
                    "disabled": False, "warnings": list(up.warnings)}
        _record(db, user, sk.slug, "upload_version", filename=filename[:200],
                disabled=disabled, **_version_detail(v), **_rise_detail(rise))
        return {"skill": _detail(db, sk), "created": False, "unchanged": False,
                "disabled": disabled, "warnings": list(up.warnings)}
    v = _new_skill(db, up.slug, up.files, c, user,
                   {"uploaded_by": actor(user), "filename": filename[:200]})
    _record(db, user, up.slug, "upload", filename=filename[:200], **_version_detail(v))
    return {"skill": _detail(db, _get(db, up.slug)), "created": True, "unchanged": False,
            "disabled": False, "warnings": list(up.warnings)}


def _authored(slug: str, body: AuthoredIn) -> dict[str, bytes]:
    try:
        return skills.authored_files(slug, body.description, body.body, body.files,
                                     body.license)
    except skills.SkillError as e:
        raise _problems(422, "the skill is not valid", e.problems) from e


@router.post("")
def create_skill(body: AuthoredIn, user: TaigaUser = Depends(kemudi_admin),
                 db: Session = Depends(get_db)):
    """An authored skill: SKILL.md built from the fields, version 1, `local`,
    disabled until enabled."""
    files = _authored(body.slug, body)
    c = _check(body.slug, files)
    sk = db.get(AwakSkill, body.slug)
    if sk is not None:
        raise _problems(409, f"a skill named {body.slug} exists", [],
                        code="exists" if sk.source == "local" else "not_local",
                        slug=body.slug, source=sk.source)
    v = _new_skill(db, body.slug, files, c, user, {"authored_by": actor(user)})
    _record(db, user, body.slug, "create", **_version_detail(v))
    return _detail(db, _get(db, body.slug))


@router.put("/{slug}")
def new_authored_version(slug: str, body: AuthoredIn, accept_findings: bool = Query(False),
                         user: TaigaUser = Depends(kemudi_admin),
                         db: Session = Depends(get_db)):
    """The next version of a `local` skill from the editor. Binary files of
    the current version (assets/) are kept: the editor only edits text. See
    _add_version for `accept_findings`."""
    sk = _get(db, slug)
    if sk.source != "local":
        raise _problems(409, f"{slug} is a {sk.source} skill; only local skills are edited "
                        "here", [], code="not_local", slug=slug, source=sk.source)
    files = _authored(slug, body)
    cur = _current(db, sk)
    if cur is not None:
        for p, d in skills.decode_files(cur.files or {}).items():
            if p not in files and not skills._is_text(d):
                files[p] = d
    c = _check(slug, files)
    v, disabled, rise = _add_version(db, sk, files, c, user, accept_findings)
    if v is not None:
        _record(db, user, slug, "version", disabled=disabled, **_version_detail(v),
                **_rise_detail(rise))
    out = _detail(db, sk)
    out["unchanged"] = v is None
    out["disabled_now"] = disabled
    return out


@router.post("/{slug}/enable")
def enable_skill(slug: str, user: TaigaUser = Depends(kemudi_admin),
                 db: Session = Depends(get_db)):
    """Refused (422) when the current version has a high scan finding."""
    sk = _get(db, slug)
    v = _current(db, sk)
    if v is None or v.status != "active":
        raise _problems(409, "the skill has no active version", [], code="no_version")
    high = [f for f in (v.scan or {}).get("findings", []) if f.get("severity") == "high"]
    if high:
        _record(db, user, slug, "enable_refused", version=v.version, high=len(high))
        raise _problems(422, "a high scan finding blocks enabling this version",
                        [f"{f['path']}:{f['line']} {f['rule']}" for f in high],
                        code="high_finding", findings=high)
    if not sk.enabled:
        sk.enabled = True
        sk.updated_at = datetime.now(UTC)
        db.commit()
        _record(db, user, slug, "enable", version=v.version)
    return _detail(db, sk)


@router.post("/{slug}/disable")
def disable_skill(slug: str, user: TaigaUser = Depends(kemudi_admin),
                  db: Session = Depends(get_db)):
    """Allowed while roles use it: they show a warning and runs drop it."""
    sk = _get(db, slug)
    if sk.enabled:
        sk.enabled = False
        sk.updated_at = datetime.now(UTC)
        db.commit()
        _record(db, user, slug, "disable",
                used_by=[f"{u['project']}/{u['role']}" for u in skills.used_by(db).get(slug, [])])
    return _detail(db, sk)


@router.delete("/{slug}")
def delete_skill(slug: str, user: TaigaUser = Depends(kemudi_admin),
                 db: Session = Depends(get_db)):
    """Only a non-builtin skill no role lists (409 with `used_by` otherwise)."""
    sk = _get(db, slug)
    if sk.source == "builtin":
        raise _problems(409, "built-in skills cannot be deleted; disable it instead", [],
                        code="builtin")
    used = skills.used_by(db).get(slug, [])
    if used:
        raise _problems(409, "remove the skill from these roles first", [],
                        code="in_use", used_by=used)
    versions = db.query(AwakSkillVersion).filter_by(slug=slug).all()
    for v in versions:
        db.delete(v)
    db.delete(sk)
    db.commit()
    _record(db, user, slug, "delete", source=sk.source, versions=len(versions))
    return {"deleted": slug}


# --- marketplace updates ------------------------------------------------------------------

@router.post("/{slug}/check-update")
def check_update(slug: str, user: TaigaUser = Depends(kemudi_admin),
                 settings: Settings = Depends(get_settings),
                 runner: Runner = Depends(get_fetch_runner), db: Session = Depends(get_db)):
    """A marketplace skill: fetch its origin at the followed ref; a changed
    folder becomes a `pending` version (never used by runs) to approve or
    reject. `result.status`: up_to_date | pending | rejected | invalid | missing."""
    sk = _get(db, slug)
    if sk.source != "marketplace":
        raise _problems(409, "only marketplace skills have an upstream to check", [],
                        code="not_marketplace", source=sk.source)
    try:
        res = marketplace.check_update(db, runner, settings, sk, actor(user))
    except marketplace.MarketplaceError as e:
        raise _problems(422, str(e), [str(e)]) from e
    except FetchError as e:
        db.rollback()
        _record(db, user, slug, "check_update_failed", error=str(e)[:300])
        raise _problems(502, "the upstream repository could not be fetched", [str(e)],
                        code="fetch_failed") from e
    except IntegrityError as e:
        raise _conflict(db, slug) from e
    if res["status"] == "pending" and res.get("new"):
        v = (db.query(AwakSkillVersion)
             .filter_by(slug=slug, version=res["version"]).one())
        _record(db, user, slug, "update_pending", upstream_sha=res["sha"],
                **_version_detail(v))
    return {"result": res, "skill": _detail(db, sk)}


def _pending(db: Session, slug: str, version: int) -> tuple[AwakSkill, AwakSkillVersion]:
    sk = _get(db, slug)
    v = db.query(AwakSkillVersion).filter_by(slug=slug, version=version).one_or_none()
    if v is None:
        raise HTTPException(404, "no such version")
    if v.status != "pending":
        raise _problems(409, f"version {version} is not pending", [], code="not_pending")
    return sk, v


@router.post("/{slug}/versions/{version}/approve")
def approve_version(slug: str, version: int, accept_findings: bool = Query(False),
                    user: TaigaUser = Depends(kemudi_admin), db: Session = Depends(get_db)):
    """A pending version becomes current (every role using the skill gets it
    on its next run). A scan worse than the current version's on a skill in
    use is refused (409 `findings_rise`) unless `accept_findings`; a high
    finding disables the skill."""
    sk, v = _pending(db, slug, version)
    cur = _current(db, sk)
    worst = _scan_level(v)
    findings = (v.scan or {}).get("findings", [])
    rise = _findings_rise(db, sk, cur, worst)
    if rise is not None and not accept_findings:
        n = len(rise["used_by"])
        raise _problems(
            409, f"this version's scan ({rise['to']}) is worse than the current version's "
            f"({rise['from'] or 'clean'}) and {n} role{'s' if n != 1 else ''} will get it on "
            "the next run; send accept_findings=true to use it anyway",
            [f"{f['path']}:{f['line']} {f['rule']}" for f in findings],
            code="findings_rise", slug=slug, worst=rise["to"], previous=rise["from"],
            findings=findings, used_by=rise["used_by"])
    try:
        meta = skills.validate(slug, skills.decode_files(v.files or {}))
    except skills.SkillError as e:
        raise _problems(422, "the pending version is not valid", e.problems) from e
    vo = v.origin or {}
    v.status = "active"
    sk.current_version = v.version
    sk.description = meta.description
    sk.license = str(vo.get("license") or meta.license or "")[:100]
    origin = dict(sk.origin or {})
    if vo.get("sha"):
        origin["sha"] = vo["sha"]
    origin.pop("rejected", None)
    sk.origin = origin
    sk.updated_at = datetime.now(UTC)
    disabled = sk.enabled and worst == "high"
    if disabled:
        sk.enabled = False
    db.commit()
    _record(db, user, slug, "approve_version", upstream_sha=vo.get("sha", ""),
            disabled=disabled, **_version_detail(v), **_rise_detail(rise))
    out = _detail(db, sk)
    out["disabled_now"] = disabled
    return out


@router.post("/{slug}/versions/{version}/reject")
def reject_version(slug: str, version: int, user: TaigaUser = Depends(kemudi_admin),
                   db: Session = Depends(get_db)):
    """Deletes a pending version; the same upstream tree is not proposed again."""
    sk, v = _pending(db, slug, version)
    detail = _version_detail(v)
    upstream = (v.origin or {}).get("sha", "")
    origin = dict(sk.origin or {})
    origin["rejected"] = v.sha256
    sk.origin = origin
    db.delete(v)
    db.commit()
    _record(db, user, slug, "reject_version", upstream_sha=upstream, **detail)
    return _detail(db, sk)
