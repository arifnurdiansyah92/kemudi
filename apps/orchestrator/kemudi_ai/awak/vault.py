"""Per-project env vault (`awak_env_vars`): the values a runbook's services,
init commands and QA read by name.

Values are Fernet tokens under a key derived from KEMUDI_SECRET_KEY with
HKDF-SHA256 (info `awak-vault`), so a vault token and an SSH-key token never
share a key. `fernet` returns a MultiFernet: a rotated key goes first and the
old one stays readable until every row is re-encrypted.

Values are test/dev values (the UI says so), yet they are handled as
secrets: never in prompts, redacted from comments, events, feedback and logs
(with their base64 and URL-encoded forms), and scanned for in diffs.
"""

import base64
import re
from datetime import UTC, datetime
from urllib.parse import quote, quote_plus

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from sqlalchemy.orm import Session

from ..config import Settings
from ..store import AwakEnvVar
from . import crypto, runbook
from .crypto import SecretKeyMissing

NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]{0,63}$")
INFO = b"awak-vault"
MAX_VALUE = 8192
# Shorter values ("1", "on") would redact ordinary words.
MIN_REDACT = 4
# A diff is refused for these; shorter values are ordinary code too often.
MIN_SCAN = 8


def name_problem(name: str) -> str | None:
    if not NAME_RE.fullmatch(name):
        return f"env name {name!r} must match [A-Z_][A-Z0-9_]* (at most 64 characters)"
    return runbook.env_name_problem(name)


def value_problem(value: str) -> str | None:
    if len(value) > MAX_VALUE:
        return f"the value is longer than {MAX_VALUE} characters"
    if "\x00" in value:
        return "the value cannot contain a NUL character"
    return None


def _derive(key: bytes) -> Fernet:
    raw = base64.urlsafe_b64decode(key)
    derived = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=INFO).derive(raw)
    return Fernet(base64.urlsafe_b64encode(derived))


def fernet(settings: Settings) -> MultiFernet:
    crypto.fernet(settings)  # raises SecretKeyMissing for an empty or invalid key
    return MultiFernet([_derive(settings.secret_key.strip().encode())])


def now() -> datetime:
    return datetime.now(UTC)


def _row(db: Session, slug: str, name: str) -> AwakEnvVar | None:
    return db.query(AwakEnvVar).filter_by(project_slug=slug, name=name).one_or_none()


def _decrypt(f: MultiFernet, row: AwakEnvVar) -> str:
    try:
        return f.decrypt(row.value_enc.encode()).decode()
    except InvalidToken as e:
        raise SecretKeyMissing(f"{row.name} does not decrypt with KEMUDI_SECRET_KEY") from e


def put(db: Session, settings: Settings, slug: str, name: str, value: str | None,
        secret: bool, by: str) -> bool:
    """Set a value (None keeps the stored one and changes the flag only).
    Returns True when the name is new."""
    row = _row(db, slug, name)
    created = row is None
    if row is None:
        if value is None:
            raise ValueError(f"{name} has no value yet")
        row = AwakEnvVar(project_slug=slug, name=name)
        db.add(row)
    if value is not None:
        try:
            row.value_enc = fernet(settings).encrypt(value.encode()).decode()
        except SecretKeyMissing:
            db.rollback()
            raise
    row.secret = secret
    row.updated_by, row.updated_at = by, now()
    db.commit()
    return created


def delete(db: Session, slug: str, name: str) -> bool:
    row = _row(db, slug, name)
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def rows(db: Session, slug: str) -> list[AwakEnvVar]:
    return db.query(AwakEnvVar).filter_by(project_slug=slug).order_by(AwakEnvVar.name).all()


def values(db: Session, settings: Settings, slug: str) -> dict[str, str]:
    """Every value of the project, decrypted (for services and QA)."""
    found = rows(db, slug)
    if not found:
        return {}
    f = fernet(settings)
    return {r.name: _decrypt(f, r) for r in found}


def _readable(db: Session, settings: Settings, slug: str,
              secret_only: bool = False) -> list[str]:
    """The values that decrypt; without a key there are none (nothing can use
    them either). `secret_only`: the values stored as secret."""
    found = [r for r in rows(db, slug) if r.secret or not secret_only]
    if not found:
        return []
    try:
        f = fernet(settings)
    except SecretKeyMissing:
        return []
    out = []
    for r in found:
        try:
            out.append(_decrypt(f, r))
        except SecretKeyMissing:
            continue
    return out


def _variants(value: str) -> set[str]:
    raw = value.encode()
    std = base64.b64encode(raw).decode()
    url = base64.urlsafe_b64encode(raw).decode()
    return {value, std, std.rstrip("="), url, url.rstrip("="),
            quote(value, safe=""), quote(value), quote_plus(value)}


def redaction_values(db: Session, settings: Settings, slug: str,
                     secret_only: bool = False) -> list[str]:
    """What the project's comments, events, feedback and logs never show:
    every value of 4+ characters and its base64/URL-encoded forms, longest
    first (so a value inside a longer one is replaced whole). `secret_only`:
    of the secret values only (a plain APP_ENV=development need not be)."""
    out: set[str] = set()
    for v in _readable(db, settings, slug, secret_only):
        if len(v) >= MIN_REDACT:
            out |= {x for x in _variants(v) if len(x) >= MIN_REDACT}
    return sorted(out, key=len, reverse=True)


def scan_values(db: Session, settings: Settings, slug: str,
                secret_only: bool = False) -> list[str]:
    """What a diff of the project must not add: the values of 8+ characters
    (`secret_only`: of the secret values only)."""
    return sorted({v for v in _readable(db, settings, slug, secret_only) if len(v) >= MIN_SCAN},
                  key=len, reverse=True)


def listing(db: Session, settings: Settings, slug: str) -> list[dict]:
    """Stored values plus the runbook's env names not set yet. A secret's
    value is never included; a plain value is (null when it does not decrypt)."""
    rb = runbook.load(db, slug)
    declared = {e.name: e for e in rb.env} if rb is not None else {}
    stored = rows(db, slug)
    f = None
    if any(not r.secret for r in stored):
        try:
            f = fernet(settings)
        except SecretKeyMissing:
            f = None
    out = []
    for r in stored:
        value = None
        if not r.secret and f is not None:
            try:
                value = _decrypt(f, r)
            except SecretKeyMissing:
                value = None
        d = declared.get(r.name)
        out.append({"name": r.name, "secret": r.secret, "set": True, "value": value,
                    "required": bool(d and d.required),
                    "description": d.description if d else "",
                    "in_runbook": d is not None,
                    "updated_by": r.updated_by, "updated_at": r.updated_at})
    have = {r.name for r in stored}
    for name, d in declared.items():
        if name not in have:
            out.append({"name": name, "secret": d.secret, "set": False, "value": None,
                        "required": d.required, "description": d.description,
                        "in_runbook": True, "updated_by": "", "updated_at": None})
    return sorted(out, key=lambda v: v["name"])
