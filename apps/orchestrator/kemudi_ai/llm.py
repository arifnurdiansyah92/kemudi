"""Every model call goes through Hermes (services/awak) and is logged."""

import json
import re
import time
from typing import Protocol

import httpx
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings
from .store import record_ai_call


class LLMError(Exception):
    """The model did not return usable JSON, or Hermes failed."""

    def __init__(self, message: str, raw: str = ""):
        super().__init__(message)
        self.raw = raw


class LLM(Protocol):
    def json(self, purpose: str, system: str, user: str) -> dict: ...


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def parse_json_object(text: str) -> dict:
    """The first JSON object in a reply, tolerating code fences and chatter."""
    m = _FENCE.search(text)
    candidate = m.group(1) if m else text
    start = candidate.find("{")
    if start < 0:
        raise ValueError("no JSON object")
    obj, _ = json.JSONDecoder().raw_decode(candidate[start:])
    if not isinstance(obj, dict):
        raise ValueError("JSON is not an object")
    return obj


class HermesLLM:
    def __init__(
        self,
        settings: Settings,
        session_factory: sessionmaker[Session],
        transport: httpx.BaseTransport | None = None,
    ):
        self.settings = settings
        self.sessions = session_factory
        self.client = httpx.Client(
            base_url=settings.hermes_url.rstrip("/"),
            headers={"Authorization": f"Bearer {settings.hermes_api_key}"},
            timeout=settings.llm_timeout_s,
            transport=transport,
        )

    def _call(self, purpose: str, messages: list[dict]) -> str:
        body = {
            "model": self.settings.ai_model,
            "messages": messages,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            # Hermes: no hidden reasoning for short structured tasks (faster).
            "model_options": {"reasoning": {"enabled": False}},
        }
        prompt = "\n\n".join(f"[{m['role']}]\n{m['content']}" for m in messages)
        t0 = time.monotonic()
        content, usage, ok = "", {}, False
        try:
            r = self.client.post("/chat/completions", json=body)
            r.raise_for_status()
            data = r.json()
            content = data["choices"][0]["message"].get("content") or ""
            usage = data.get("usage") or {}
            ok = True
            return content
        except (httpx.HTTPError, KeyError, ValueError) as e:
            content = content or f"{type(e).__name__}: {e}"
            raise LLMError(f"Hermes call failed: {e}", content) from e
        finally:
            pt = int(usage.get("prompt_tokens") or 0)
            ct = int(usage.get("completion_tokens") or 0)
            with self.sessions() as s:
                record_ai_call(
                    s,
                    purpose=purpose,
                    model=self.settings.ai_model,
                    prompt=prompt,
                    response=content,
                    prompt_tokens=pt,
                    completion_tokens=ct,
                    latency_ms=int((time.monotonic() - t0) * 1000),
                    cost_idr=(pt + ct) / 1000 * self.settings.token_price_idr_per_1k,
                    ok=ok,
                )

    def json(self, purpose: str, system: str, user: str) -> dict:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        reply = self._call(purpose, messages)
        try:
            return parse_json_object(reply)
        except ValueError:
            messages += [
                {"role": "assistant", "content": reply},
                {
                    "role": "user",
                    "content": "That was not valid JSON. Reply again with one "
                    "JSON object only, no other text.",
                },
            ]
            reply = self._call(purpose, messages)
            try:
                return parse_json_object(reply)
            except ValueError as e:
                raise LLMError("invalid JSON after retry", reply) from e
