"""Client for kemudi-runner (infra/runner): installs, gates and QA spec runs.

The runner executes branch code, so it holds no secrets; the QA token it
gets per request belongs to a user that can only reach the QA sandbox
project.
"""

from typing import Any, Protocol

import httpx


class RunnerError(Exception):
    """The runner could not do the job (down, timeout). An infra error."""


class RunnerRejected(RunnerError):
    """The runner refused the request (HTTP 400): a path, folder, command or
    env it cannot accept. Retrying sends the same request: not an infra error."""


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
            if r.status_code == 400:
                try:
                    body = r.json()
                except ValueError:
                    body = None
                why = str(body.get("error") or r.text) if isinstance(body, dict) else r.text
                raise RunnerRejected(f"runner {op} refused: {why[:500]}")
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise RunnerError(f"runner {op} failed: {type(e).__name__}: {e}") from e
