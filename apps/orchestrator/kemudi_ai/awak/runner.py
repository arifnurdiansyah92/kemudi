"""Client for kemudi-runner (infra/runner): installs, gates and QA spec runs.

The runner executes branch code, so it holds no secrets; the QA token it
gets per request belongs to a user that can only reach the QA sandbox
project.
"""

from typing import Any, Protocol

import httpx


class RunnerError(Exception):
    """The runner could not do the job (down, timeout). An infra error."""


class Runner(Protocol):
    def call(self, op: str, **payload: Any) -> dict: ...


class HttpRunner:
    def __init__(self, url: str, key: str, transport: httpx.BaseTransport | None = None):
        self.client = httpx.Client(
            base_url=url.rstrip("/"),
            headers={"Authorization": f"Bearer {key}"},
            timeout=1800,
            transport=transport,
        )

    def call(self, op: str, **payload: Any) -> dict:
        try:
            r = self.client.post(f"/{op}", json=payload)
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise RunnerError(f"runner {op} failed: {type(e).__name__}: {e}") from e
