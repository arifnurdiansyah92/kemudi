"""What Awak learned about a repo, kept for its next run there.

Every coding run starts from nothing: it finds again that the type check
needs more heap, or where the routes live. A run may end its report with
`NOTE:` lines (stories.REPORT_RULES); they are stored per repo and given to
later runs as hints. They are model-written text, so they are treated as
data everywhere: redacted for secrets, short, capped in number, shown to the
project's admins (Agent settings), who can delete any of them.
"""

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from ..store import AwakNote
from . import secrets

KEEP = 30        # per repo; the oldest go
GIVE = 12        # how many a run gets, newest first
MIN_CHARS = 12
MAX_CHARS = 240


def _norm(text: str) -> str:
    return " ".join(text.lower().split())


def add(db: Session, slug: str, repo_id: int | None, texts: list[str],
        job_id: int | None = None, secret_values: list[str] | None = None) -> list[str]:
    """Stores the new notes; returns the ones added. A note that carries a
    secret-like value is dropped, not redacted: half a command is no hint."""
    rows = db.query(AwakNote).filter_by(project_slug=slug, repo_id=repo_id).all()
    known = {_norm(r.text) for r in rows}
    added = []
    for raw in texts:
        text = " ".join(str(raw).split())[:MAX_CHARS]
        if len(text) < MIN_CHARS or _norm(text) in known:
            continue
        if secrets.find(text, secret_values or []):
            continue
        known.add(_norm(text))
        db.add(AwakNote(project_slug=slug, repo_id=repo_id, text=text, job_id=job_id,
                        at=datetime.now(UTC)))
        added.append(text)
    if added:
        db.flush()
        rows = (db.query(AwakNote).filter_by(project_slug=slug, repo_id=repo_id)
                .order_by(AwakNote.id.desc()).all())
        for old in rows[KEEP:]:
            db.delete(old)
        db.commit()
    return added


def recent(db: Session, slug: str, repo_id: int | None, limit: int = GIVE) -> list[str]:
    rows = (db.query(AwakNote).filter_by(project_slug=slug, repo_id=repo_id)
            .order_by(AwakNote.id.desc()).limit(limit).all())
    return [r.text for r in reversed(rows)]


def listing(db: Session, slug: str) -> list[dict]:
    rows = (db.query(AwakNote).filter_by(project_slug=slug)
            .order_by(AwakNote.id.desc()).all())
    return [{"id": r.id, "repo_id": r.repo_id, "text": r.text, "job_id": r.job_id,
             "at": _iso(r.at)} for r in rows]


def _iso(at: datetime | None) -> str | None:
    """SQLite hands the time back without its zone; it is UTC."""
    if at is None:
        return None
    return (at if at.tzinfo else at.replace(tzinfo=UTC)).isoformat()


def delete(db: Session, slug: str, note_id: int) -> bool:
    row = db.get(AwakNote, note_id)
    if row is None or row.project_slug != slug:
        return False
    db.delete(row)
    db.commit()
    return True
