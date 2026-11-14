"""Client for kemudi-svc (infra/svc): a project's compose services, started in
the sandboxed Docker daemon (kemudi-dind).

kemudi-svc is the only container that reaches that daemon. It reads the
project's compose file from the (read-only) workspace, refuses anything
outside its allowlist and runs only the normalized copy. Ops and payloads are
documented in infra/svc/svc.py.
"""

from typing import Any, Protocol

import httpx


class SvcError(Exception):
    """kemudi-svc could not do the job (down, timeout). An infra error."""


class SvcRejected(SvcError):
    """kemudi-svc refused the request (HTTP 400): a path, compose key, service
    or env it cannot accept. Retrying sends the same request: not an infra
    error. (Anything else that goes wrong in kemudi-svc comes back as
    `{infra_error}`.)"""


class Svc(Protocol):
    def call(self, op: str, **payload: Any) -> dict: ...


class SvcClient:
    # How long the client waits per op. kemudi-svc keeps below these
    # (infra/svc/svc.py, checked by infra/svc/tests/test_ops.py):
    # - svc_up: one budget of 1400 s for config, build (900 s, one retry),
    #   start (300 s) and port, plus up to 60 s of logs;
    # - svc_exec: waiting for an svc_up of the same project and the run
    #   (<= 1500 s) together stay within 1650 s;
    # - svc_down: waits up to 1500 s for an svc_up of the same project, then
    #   takes a few minutes at most.
    TIMEOUT_S = 1800
    OP_TIMEOUT_S = {"svc_up": 1500, "svc_down": 2400}

    def __init__(self, url: str, key: str, transport: httpx.BaseTransport | None = None):
        self.client = httpx.Client(
            base_url=url.rstrip("/"),
            headers={"Authorization": f"Bearer {key}"},
            timeout=self.TIMEOUT_S,
            transport=transport,
        )

    def call(self, op: str, **payload: Any) -> dict:
        try:
            r = self.client.post(f"/{op}", json=payload,
                                 timeout=self.OP_TIMEOUT_S.get(op, self.TIMEOUT_S))
            if r.status_code == 400:
                try:
                    body = r.json()
                except ValueError:
                    body = None
                why = str(body.get("error") or r.text) if isinstance(body, dict) else r.text
                raise SvcRejected(f"svc {op} refused: {why[:500]}")
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise SvcError(f"svc {op} failed: {type(e).__name__}: {e}") from e
