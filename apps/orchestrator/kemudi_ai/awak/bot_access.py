"""Whether the Awak bot user can open a project, and giving it access.

The worker acts in Taiga as one bot user (`settings.awak_username`). Taiga
answers 404 for a project the bot is not a member of, so nothing gets picked
up. An admin's own token adds the bot as a member; the bot's password never
leaves the server and no error text carries it.
"""

import threading
import time

import httpx

from ..config import Settings
from . import secrets
from .taiga import Taiga, TaigaError

# A developer-ish role first; otherwise the first role that is not an owner one.
PREFERRED_ROLE_SLUGS = ("back", "front", "developer")
CHECK_TTL_S = 10.0


class BotAccessError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def pick_role(roles: list[dict]) -> dict | None:
    by_slug = {str(r.get("slug") or ""): r for r in roles}
    for slug in PREFERRED_ROLE_SLUGS:
        if slug in by_slug:
            return by_slug[slug]
    ordered = sorted(roles, key=lambda r: (r.get("order") or 0, r.get("id") or 0))
    for r in ordered:
        text = f"{r.get('slug') or ''} {r.get('name') or ''}".lower()
        if "owner" not in text:
            return r
    return None


def _clean(text: str) -> str:
    return secrets.redact(str(text), secrets.known_values())[:300]


class BotAccess:
    """`check` (cached a few seconds) and `grant`; one per process is enough."""

    _cache: dict[str, tuple[float, dict]] = {}
    _lock = threading.Lock()

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None,
                 clock=time.monotonic):
        self.s = settings
        self.transport = transport
        self.clock = clock

    @property
    def username(self) -> str:
        return self.s.awak_username

    def check(self, slug: str, fresh: bool = False) -> dict:
        """`{ok, member, error}`: `member` is None when it could not be told."""
        key = f"{self.s.taiga_api_url}|{self.username}|{slug}"
        now = self.clock()
        with self._lock:
            hit = self._cache.get(key)
            if hit and not fresh and now - hit[0] < CHECK_TTL_S:
                return dict(hit[1])
        out = self._check(slug)
        with self._lock:
            self._cache[key] = (now, out)
        return dict(out)

    def _check(self, slug: str) -> dict:
        if not self.s.awak_password:
            return {"ok": False, "member": None,
                    "error": "the Awak bot account is not configured on this server"}
        try:
            bot = Taiga(self.s.taiga_api_url, self.username, self.s.awak_password,
                        self.transport)
            bot.project_detail(slug)
        except TaigaError as e:
            msg = str(e)
            if "HTTP 404" in msg or "HTTP 403" in msg:
                return {"ok": False, "member": False,
                        "error": f"Awak (user {self.username}) is not a member of this project"}
            if msg.startswith("login as"):
                return {"ok": False, "member": None,
                        "error": f"Awak (user {self.username}) cannot sign in to Taiga"}
            return {"ok": False, "member": None, "error": _clean(msg)}
        except httpx.HTTPError as e:
            return {"ok": False, "member": None,
                    "error": f"Taiga is unreachable ({type(e).__name__})"}
        return {"ok": True, "member": True, "error": None}

    def grant(self, slug: str, token: str) -> dict:
        """Make the bot a member using the caller's token. `{added, role}`;
        raises BotAccessError (with an HTTP status) when Taiga refuses."""
        try:
            caller = Taiga.with_token(self.s.taiga_api_url, token, self.transport)
            project = caller.project_detail(slug)
            members = {str(m.get("username") or "") for m in project.get("members") or []}
            if self.username in members:
                return {"added": False, "role": None}
            role = pick_role(project.get("roles") or [])
            if role is None:
                raise BotAccessError("the project has no role Awak could be given", 409)
            caller.add_membership(project["id"], role["id"], self.username)
        except TaigaError as e:
            msg = str(e)
            if "HTTP 403" in msg:
                raise BotAccessError("Taiga does not let you add members to this project",
                                     403) from e
            if "HTTP 401" in msg:
                raise BotAccessError("your Taiga session expired; sign in again", 401) from e
            if "HTTP 400" in msg and "already" in msg.lower():
                return {"added": False, "role": None}
            raise BotAccessError(f"Taiga refused to add Awak: {_clean(msg)}") from e
        except httpx.HTTPError as e:
            raise BotAccessError(f"Taiga is unreachable ({type(e).__name__})") from e
        finally:
            self.forget(slug)
        return {"added": True, "role": role.get("name")}

    def forget(self, slug: str) -> None:
        key = f"{self.s.taiga_api_url}|{self.username}|{slug}"
        with self._lock:
            self._cache.pop(key, None)
