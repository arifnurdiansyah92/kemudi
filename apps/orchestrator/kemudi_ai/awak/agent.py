"""Calls to the tool-using Hermes (kemudi-awak): one run per call, logged.

Awak holds no model key. Each run gets a short-lived alias as its model name;
Hermes sends it to the orchestrator's /llm/v1 proxy, which maps it to the
run's resolved connection (agent > project > server default).

Every run goes through a Hermes profile, `/p/sk-<setid>/v1/chat/completions`:
the run's skill set (kemudi_ai/awak/skills.py, `prepare_set`), an empty one
included, so Hermes' bundled skills never reach a run.
"""

import time
from typing import Protocol

import httpx
from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings
from ..store import record_ai_call
from . import llm_conn, skills


class AgentError(Exception):
    """Hermes did not finish the run (timeout, HTTP error). An infra error.
    `cost_idr`: what the run cost anyway (the usage Hermes reported, if any)."""

    def __init__(self, message: str = "", cost_idr: float = 0.0):
        super().__init__(message)
        self.cost_idr = cost_idr


class Agent(Protocol):
    def run(self, purpose: str, model: str, system: str, task: str, *,
            slug: str = "", role_id: int | None = None,
            profile: str) -> tuple[str, float]:
        """Run to completion; returns (final text, cost in IDR). `model` is the
        server-default model; `slug`/`role_id` pick the BYOK connection;
        `profile` is the run's skill-set profile (skills.prepare_set)."""
        ...


# A profile Hermes has not picked up yet (its watcher rescans every 30 s).
_NOT_SERVED = "profile_mismatch"


class HermesAgent:
    def __init__(
        self,
        settings: Settings,
        sessions: sessionmaker[Session],
        transport: httpx.BaseTransport | None = None,
    ):
        self.settings = settings
        self.sessions = sessions
        self.sleep = time.sleep
        # Profiles live under /p/<profile>/v1/...; awak_url names /v1.
        self.client = httpx.Client(
            base_url=settings.awak_url.rstrip("/").removesuffix("/v1"),
            headers={"Authorization": f"Bearer {settings.awak_api_key}"},
            timeout=settings.awak_timeout_s,
            transport=transport,
        )

    def run(self, purpose: str, model: str, system: str, task: str, *,
            slug: str = "", role_id: int | None = None,
            profile: str) -> tuple[str, float]:
        if not skills.PROFILE_RE.match(profile or ""):
            raise AgentError(f"not a skill-set profile: {profile!r}")
        with self.sessions() as db:
            conn = llm_conn.describe(db, self.settings, slug, role_id, model)
            alias = llm_conn.register_alias(db, self.settings, slug, role_id, model, purpose,
                                            profile=profile)
        body = {
            "model": alias,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": task},
            ],
            "stream": False,
        }
        # Hermes derives a chat session id from the system prompt + first user
        # message. A retry of the same attempt would land in the session of the
        # cut-off run, which Hermes still holds as active (409). One session per
        # run: the alias is unique per run.
        headers = {"X-Hermes-Session-Id": alias}
        t0 = time.monotonic()
        content, usage, ok = "", {}, False
        try:
            r = self._post(profile, body, headers)
            r.raise_for_status()
            data = r.json()
            content = data["choices"][0]["message"].get("content") or ""
            usage = data.get("usage") or {}
            # Hermes turns a dead provider into a chatty final message; without
            # this the story would lose an attempt to an outage.
            with self.sessions() as s:
                failure = llm_conn.provider_failure(s, alias)
            if failure:
                raise AgentError(f"model provider failed for the whole run: {failure}",
                                 self._cost(usage))
            ok = True
            return content, self._cost(usage)
        except (httpx.HTTPError, KeyError, ValueError) as e:
            content = content or f"{type(e).__name__}: {e}"
            raise AgentError(f"Awak run failed: {type(e).__name__}: {e}",
                             self._cost(usage)) from e
        finally:
            pt = int(usage.get("prompt_tokens") or 0)
            ct = int(usage.get("completion_tokens") or 0)
            with self.sessions() as s:
                llm_conn.drop_alias(s, alias)
                record_ai_call(
                    s,
                    purpose=purpose,
                    model=conn.model,
                    llm_source=conn.source,
                    prompt=f"[system]\n{system}\n\n[user]\n{task}",
                    response=content,
                    prompt_tokens=pt,
                    completion_tokens=ct,
                    latency_ms=int((time.monotonic() - t0) * 1000),
                    cost_idr=self._cost(usage),
                    ok=ok,
                )

    def _post(self, profile: str, body: dict, headers: dict) -> httpx.Response:
        """A new profile is served at Hermes' next watcher pass: wait for its
        marker, then retry `409 profile_mismatch` until the same deadline."""
        wait_s = self.settings.awak_profile_wait_s
        deadline = time.monotonic() + wait_s
        skills.wait_served(self.settings, profile, wait_s, sleep=self.sleep)
        url = f"/p/{profile}/v1/chat/completions"
        while True:
            r = self.client.post(url, json=body, headers=headers)
            if not (r.status_code == 409 and _NOT_SERVED in r.text
                    and time.monotonic() < deadline):
                return r
            self.sleep(3.0)

    def _cost(self, usage: dict) -> float:
        tokens = int(usage.get("prompt_tokens") or 0) + int(usage.get("completion_tokens") or 0)
        return tokens / 1000 * self.settings.token_price_idr_per_1k
