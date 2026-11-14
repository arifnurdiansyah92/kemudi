"""Calls to the tool-using Hermes (kemudi-awak): one run per call, logged.

Awak holds no model key. Each run gets a short-lived alias as its model name;
Hermes sends it to the orchestrator's /llm/v1 proxy, which maps it to the
run's resolved connection (agent > project > server default).
"""

import time
from typing import Protocol

import httpx
from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings
from ..store import record_ai_call
from . import llm_conn


class AgentError(Exception):
    """Hermes did not finish the run (timeout, HTTP error). An infra error."""


class Agent(Protocol):
    def run(self, purpose: str, model: str, system: str, task: str, *,
            slug: str = "", role_id: int | None = None) -> tuple[str, float]:
        """Run to completion; returns (final text, cost in IDR). `model` is the
        server-default model; `slug`/`role_id` pick the BYOK connection."""
        ...


class HermesAgent:
    def __init__(
        self,
        settings: Settings,
        sessions: sessionmaker[Session],
        transport: httpx.BaseTransport | None = None,
    ):
        self.settings = settings
        self.sessions = sessions
        self.client = httpx.Client(
            base_url=settings.awak_url.rstrip("/"),
            headers={"Authorization": f"Bearer {settings.awak_api_key}"},
            timeout=settings.awak_timeout_s,
            transport=transport,
        )

    def run(self, purpose: str, model: str, system: str, task: str, *,
            slug: str = "", role_id: int | None = None) -> tuple[str, float]:
        with self.sessions() as db:
            conn = llm_conn.describe(db, self.settings, slug, role_id, model)
            alias = llm_conn.register_alias(db, self.settings, slug, role_id, model, purpose)
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
            r = self.client.post("/chat/completions", json=body, headers=headers)
            r.raise_for_status()
            data = r.json()
            content = data["choices"][0]["message"].get("content") or ""
            usage = data.get("usage") or {}
            # Hermes turns a dead provider into a chatty final message; without
            # this the story would lose an attempt to an outage.
            with self.sessions() as s:
                failure = llm_conn.provider_failure(s, alias)
            if failure:
                raise AgentError(f"model provider failed for the whole run: {failure}")
            ok = True
            return content, self._cost(usage)
        except (httpx.HTTPError, KeyError, ValueError) as e:
            content = content or f"{type(e).__name__}: {e}"
            raise AgentError(f"Awak run failed: {type(e).__name__}: {e}") from e
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

    def _cost(self, usage: dict) -> float:
        tokens = int(usage.get("prompt_tokens") or 0) + int(usage.get("completion_tokens") or 0)
        return tokens / 1000 * self.settings.token_price_idr_per_1k
