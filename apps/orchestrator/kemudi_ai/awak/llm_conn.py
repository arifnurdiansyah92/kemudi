"""BYOK model connections: agent > project > Kemudi server default.

A level either supplies a whole connection (base URL, model, key) or inherits
from the level below; base URL and key are never mixed across levels, so a key
is only ever sent to the base URL it was saved with. A role's own model, when
set, replaces the effective level's model (it carries no secret). Keys are Fernet tokens at rest and
only leave this module decrypted towards the provider (proxy, test) and the
secret scanner.
"""

import ipaddress
import secrets as pysecrets
import socket
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import httpx
from sqlalchemy.orm import Session

from ..config import Settings
from ..store import AwakLlmAlias, AwakProject, AwakRole
from . import crypto, secrets
from .crypto import SecretKeyMissing

SOURCES = ("agent", "project", "server")
ALIAS_PREFIX = "awak-run-"


@dataclass(frozen=True)
class Connection:
    base_url: str
    api_key: str = ""
    model: str = ""
    source: str = "server"  # agent | project | server

    @property
    def host(self) -> str:
        return urlsplit(self.base_url).hostname or ""

    def public(self) -> dict:
        """What the API may show: never the key."""
        return {"llm_source": self.source, "llm_model": self.model, "llm_host": self.host}


# --- base URL ------------------------------------------------------------------


def _private(host: str, resolve: bool) -> bool:
    try:
        addrs = [ipaddress.ip_address(host.strip("[]"))]
    except ValueError:
        if host == "localhost":
            return True
        if not resolve:
            return False
        try:
            infos = socket.getaddrinfo(host, None)
        except OSError:
            return False
        addrs = [ipaddress.ip_address(i[4][0].split("%")[0]) for i in infos]
    return bool(addrs) and all(a.is_private or a.is_loopback for a in addrs)


def validate_base_url(url: str, resolve: bool = True) -> str:
    """`https://...`, or `http://` to a private or loopback address (a
    self-hosted model). Returns it without a trailing slash."""
    url = url.strip()
    if not url or any(c.isspace() for c in url) or len(url) > 500:
        raise ValueError("enter a base URL such as https://api.openai.com/v1")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("the base URL must start with https://")
    if parts.username or parts.password:
        raise ValueError("put the key in the API key field, not in the URL")
    if parts.query or parts.fragment:
        raise ValueError("the base URL cannot have a query or fragment")
    if parts.scheme == "http" and not _private(parts.hostname, resolve):
        raise ValueError("http:// is only allowed to a private or loopback address; "
                         "use https://")
    return url.rstrip("/")


# --- levels --------------------------------------------------------------------


def _is_set(row) -> bool:
    return bool(row is not None and row.llm_base_url and row.llm_model)


def stored_key(settings: Settings, row) -> str:
    return crypto.decrypt(settings, row.llm_api_key_enc) if row.llm_api_key_enc else ""


def level_out(row) -> dict:
    """A level as the API shows it (key write-only)."""
    return {
        "set": _is_set(row),
        "base_url": (row.llm_base_url if row is not None else "") or "",
        "model": (row.llm_model if row is not None else "") or "",
        "key_set": bool(row is not None and row.llm_api_key_enc),
        "key_last4": (row.llm_key_last4 if row is not None and row.llm_api_key_enc else None),
    }


def set_level(settings: Settings, row, base_url: str, model: str, api_key: str) -> bool:
    """Write a level onto a project or role row; an empty key keeps the stored
    one. Returns whether the key changed."""
    row.llm_base_url, row.llm_model = base_url, model
    if api_key:
        row.llm_api_key_enc = crypto.encrypt(settings, api_key)
        row.llm_key_last4 = api_key[-4:]
        return True
    return False


LEVEL_FIELDS = ("llm_base_url", "llm_model", "llm_api_key_enc", "llm_key_last4")


def clear_level(row) -> None:
    for field in LEVEL_FIELDS:
        setattr(row, field, "")


def server_default(settings: Settings, model: str) -> Connection:
    return Connection(base_url=(settings.ai_base_url or "").rstrip("/"),
                      api_key=settings.ai_api_key or "", model=model, source="server")


def resolve(db: Session, settings: Settings, slug: str, role_id: int | None,
            fallback_model: str = "", decrypt: bool = True) -> Connection:
    """The connection (base URL + key) resolves agent > project > server
    default, as whole groups. The model is the role's own model when it sets
    one, else the effective level's model (for the server default: the
    fallback model, then KEMUDI_AWAK_MODEL). So a role can use the project's
    provider and key with a model of its own. With decrypt=False the key stays
    empty (for display). Raises SecretKeyMissing if a stored key does not
    decrypt."""
    role = db.get(AwakRole, role_id) if role_id else None
    if role is not None and role.project_slug != slug:
        role = None
    own_model = (role.model if role is not None else "") or ""
    p = db.get(AwakProject, slug)
    for row, source in ((role, "agent"), (p, "project")):
        if _is_set(row):
            key = stored_key(settings, row) if decrypt else ""
            return Connection(row.llm_base_url, key, own_model or row.llm_model, source)
    conn = server_default(settings, own_model or fallback_model or settings.awak_model)
    return conn if decrypt else Connection(conn.base_url, "", conn.model, conn.source)


def describe(db: Session, settings: Settings, slug: str, role_id: int | None,
             fallback_model: str = "") -> Connection:
    return resolve(db, settings, slug, role_id, fallback_model, decrypt=False)


def stored_keys(db: Session, settings: Settings) -> list[str]:
    """Every BYOK key, decrypted, for the secret scanner. Keys that do not
    decrypt are skipped (they cannot be used either)."""
    out: list[str] = []
    for model in (AwakProject, AwakRole):
        for row in db.query(model).filter(model.llm_api_key_enc != ""):
            try:
                key = stored_key(settings, row)
            except SecretKeyMissing:
                continue
            if key and len(key) >= 8:
                out.append(key)
    return out


# --- per-run aliases -----------------------------------------------------------


def _naive_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def register_alias(db: Session, settings: Settings, slug: str, role_id: int | None,
                   fallback_model: str, purpose: str) -> str:
    """A fresh `awak-run-<hex>` model name for one run. Expired rows go."""
    now = _naive_now()
    # One job at a time (worker lease): any alias still here belongs to a run
    # that crashed or was cut off, and would make the active-run fallback in
    # the proxy ambiguous.
    db.query(AwakLlmAlias).delete(synchronize_session=False)
    alias = ALIAS_PREFIX + pysecrets.token_hex(16)
    ttl = settings.awak_timeout_s + 600
    db.add(AwakLlmAlias(alias=alias, project_slug=slug, role_id=role_id,
                        fallback_model=fallback_model, purpose=purpose,
                        expires_at=now + timedelta(seconds=ttl)))
    db.commit()
    return alias


def lookup_alias(db: Session, alias: str) -> AwakLlmAlias | None:
    if not isinstance(alias, str) or not alias.startswith(ALIAS_PREFIX) or len(alias) > 64:
        return None
    row = db.get(AwakLlmAlias, alias)
    if row is None or row.expires_at < _naive_now():
        return None
    return row


def active_alias(db: Session) -> AwakLlmAlias | None:
    """The one unexpired run alias, if exactly one exists.

    Hermes may not pass the per-run alias through as the model name; with one
    job at a time there is exactly one live run to attribute a call to. Two or
    more live aliases are ambiguous, so the caller refuses the request.
    """
    rows = (db.query(AwakLlmAlias)
            .filter(AwakLlmAlias.expires_at >= _naive_now())
            .limit(2).all())
    return rows[0] if len(rows) == 1 else None


def drop_alias(db: Session, alias: str) -> None:
    db.query(AwakLlmAlias).filter_by(alias=alias).delete(synchronize_session=False)
    db.commit()


# --- upstream ------------------------------------------------------------------


def upstream_headers(conn: Connection) -> dict[str, str]:
    h = {"Content-Type": "application/json", "Accept-Encoding": "identity"}
    if conn.api_key:
        h["Authorization"] = f"Bearer {conn.api_key}"
    return h


def scrub(text: str, conn: Connection) -> str:
    values = [conn.api_key] if conn.api_key else []
    return secrets.redact(text, values + secrets.known_values())


def check_connection(conn: Connection, transport: httpx.BaseTransport | None = None,
                    timeout: float = 30.0) -> dict:
    """A 1-token chat completion. Never returns the key."""
    out = {"ok": False, "latency_ms": 0, "status": None, "error": None, **conn.public()}
    if not conn.base_url:
        out["error"] = "no base URL: set one here, or KEMUDI_AI_BASE_URL on the server"
        return out
    body = {"model": conn.model, "max_tokens": 1, "stream": False,
            "messages": [{"role": "user", "content": "ping"}]}
    t0 = time.monotonic()
    try:
        with httpx.Client(transport=transport, timeout=timeout, follow_redirects=False) as c:
            r = c.post(f"{conn.base_url}/chat/completions", json=body,
                       headers=upstream_headers(conn))
        out["status"] = r.status_code
        if r.is_redirect:
            out["error"] = f"the provider answered with a redirect ({r.status_code}); " \
                           "use the final URL"
        elif r.status_code >= 400:
            out["error"] = scrub(f"HTTP {r.status_code}: {r.text[:300]}", conn)
        else:
            out["ok"] = True
    except httpx.HTTPError as e:
        out["error"] = scrub(f"{type(e).__name__}: {e}", conn)[:300]
    out["latency_ms"] = int((time.monotonic() - t0) * 1000)
    return out


def list_models(conn: Connection, transport: httpx.BaseTransport | None = None,
                timeout: float = 10.0) -> dict:
    """The provider's model ids (`GET {base_url}/models`, OpenAI shape).
    Never returns the key; errors are scrubbed."""
    out: dict = {"ok": False, "models": [], "source": conn.source, "host": conn.host,
                 "error": None}
    if not conn.base_url:
        out["error"] = "no base URL: set one here, or KEMUDI_AI_BASE_URL on the server"
        return out
    headers = {k: v for k, v in upstream_headers(conn).items() if k != "Content-Type"}
    try:
        with httpx.Client(transport=transport, timeout=timeout, follow_redirects=False) as c:
            r = c.get(f"{conn.base_url}/models", headers=headers)
        if r.is_redirect:
            out["error"] = f"the provider answered with a redirect ({r.status_code}); " \
                           "use the final URL"
            return out
        if r.status_code >= 400:
            out["error"] = scrub(f"HTTP {r.status_code}: {r.text[:300]}", conn)
            return out
        data = r.json()
    except httpx.HTTPError as e:
        out["error"] = scrub(f"{type(e).__name__}: {e}", conn)[:300]
        return out
    except ValueError:
        out["error"] = "the provider's /models answer is not JSON"
        return out
    items = data.get("data") if isinstance(data, dict) else data
    if not isinstance(items, list):
        out["error"] = "the provider's /models answer has no model list"
        return out
    ids = {str(i.get("id") if isinstance(i, dict) else i).strip() for i in items}
    out["models"] = sorted(m for m in ids if m and m != "None" and len(m) <= 100)
    out["ok"] = True
    return out
