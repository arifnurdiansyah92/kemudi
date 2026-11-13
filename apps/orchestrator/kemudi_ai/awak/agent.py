"""Calls to the tool-using Hermes (kemudi-awak): one run per call, logged."""

import time
from typing import Protocol

import httpx
from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings
from ..store import record_ai_call


class AgentError(Exception):
    """Hermes did not finish the run (timeout, HTTP error). An infra error."""


class Agent(Protocol):
    def run(self, purpose: str, model: str, system: str, task: str) -> tuple[str, float]:
        """Run to completion; returns (final text, cost in IDR)."""
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

    def run(self, purpose: str, model: str, system: str, task: str) -> tuple[str, float]:
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": task},
            ],
            "stream": False,
        }
        t0 = time.monotonic()
        content, usage, ok = "", {}, False
        try:
            r = self.client.post("/chat/completions", json=body)
            r.raise_for_status()
            data = r.json()
            content = data["choices"][0]["message"].get("content") or ""
            usage = data.get("usage") or {}
            ok = True
            return content, self._cost(usage)
        except (httpx.HTTPError, KeyError, ValueError) as e:
            content = content or f"{type(e).__name__}: {e}"
            raise AgentError(f"Awak run failed: {type(e).__name__}: {e}") from e
        finally:
            pt = int(usage.get("prompt_tokens") or 0)
            ct = int(usage.get("completion_tokens") or 0)
            with self.sessions() as s:
                record_ai_call(
                    s,
                    purpose=purpose,
                    model=model,
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
