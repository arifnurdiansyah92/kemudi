"""The web researcher: one call to kemudi-riset (Hermes with web_search and
web_extract, nothing else), which works until it has an answer.

It is the only part of Kemudi that reads the open web. It gets a brief and a
short product summary; no code, no backlog, no keys (the model key lives in
that service's own environment).
"""

import time
import uuid
from typing import Protocol

import httpx
from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings
from ..store import record_ai_call


class WebError(Exception):
    """kemudi-riset did not finish the research (timeout, HTTP error)."""


class Researcher(Protocol):
    def research(self, purpose: str, system: str, task: str, slug: str = "") -> str: ...


class HermesResearcher:
    def __init__(self, settings: Settings, sessions: sessionmaker[Session],
                 transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self.sessions = sessions
        self.client = httpx.Client(
            base_url=settings.riset_url.rstrip("/"),
            headers={"Authorization": f"Bearer {settings.riset_api_key}"},
            timeout=settings.riset_timeout_s,
            transport=transport,
        )

    def research(self, purpose: str, system: str, task: str, slug: str = "") -> str:
        body = {
            "model": self.settings.ai_model,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": task}],
            "stream": False,
        }
        t0 = time.monotonic()
        content, usage, ok = "", {}, False
        try:
            # One Hermes session per run: a retry never lands in a cut-off one.
            r = self.client.post("/chat/completions", json=body,
                                 headers={"X-Hermes-Session-Id": "riset-" + uuid.uuid4().hex})
            r.raise_for_status()
            data = r.json()
            content = data["choices"][0]["message"].get("content") or ""
            usage = data.get("usage") or {}
            if not content.strip():
                raise WebError("the web researcher returned nothing")
            ok = True
            return content
        except (httpx.HTTPError, KeyError, ValueError) as e:
            content = content or f"{type(e).__name__}: {e}"
            raise WebError(f"web research failed: {type(e).__name__}: {e}") from e
        finally:
            pt = int(usage.get("prompt_tokens") or 0)
            ct = int(usage.get("completion_tokens") or 0)
            with self.sessions() as s:
                record_ai_call(
                    s, purpose=purpose, model=self.settings.ai_model,
                    prompt=f"[system]\n{system}\n\n[user]\n{task}", response=content,
                    prompt_tokens=pt, completion_tokens=ct, project_slug=slug,
                    latency_ms=int((time.monotonic() - t0) * 1000),
                    cost_idr=(pt + ct) / 1000 * self.settings.token_price_idr_per_1k,
                    log_prompts=self.settings.ai_log_prompts, ok=ok,
                )
