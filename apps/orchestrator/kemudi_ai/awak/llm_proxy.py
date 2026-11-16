"""The model proxy Awak (kemudi-awak) calls: `/llm/v1/...` on the internal
kemudi-sandbox network.

Awak holds no provider key. Each run's model name is a short-lived alias
(`awak-run-<hex>`); this route maps it to the run's resolved connection, swaps
in the real model and key, and forwards the request, streaming included. No
Taiga token: a request is admitted by the shared proxy token (required: an
empty KEMUDI_LLM_PROXY_TOKEN closes the proxy) plus a live alias. The public
gateway does not route here.

Every answered call is accounted (kemudi_ai/awak/usage.py): the provider's
usage, streamed answers included (the proxy asks for it with
`stream_options.include_usage`), and its cost. A project over its token
budget (or a story over its cap) gets 402 instead of a model call (not 429:
OpenAI clients retry that).
"""

import hmac
import json
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy.orm import Session, sessionmaker
from starlette.background import BackgroundTask

from ..config import Settings, get_settings
from ..deps import get_sessions
from . import llm_conn, usage
from .crypto import SecretKeyMissing

log = logging.getLogger(__name__)

router = APIRouter(prefix="/llm/v1")

# Response headers that describe the upstream connection, not the body.
_HOP = {"content-length", "transfer-encoding", "connection", "keep-alive", "content-encoding",
        "set-cookie"}


REASONING_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh")


def get_upstream_transport() -> httpx.AsyncBaseTransport | None:
    """Overridden in tests with an httpx.MockTransport."""
    return None


def _check_token(request: Request, settings: Settings) -> None:
    """The shared bearer token, compared in constant time. Without a configured
    token the proxy is closed (503), never open."""
    token = (settings.llm_proxy_token or "").strip()
    if not token:
        raise HTTPException(503, "the model proxy is not configured (KEMUDI_LLM_PROXY_TOKEN)")
    given = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(given.encode(), token.encode()):
        raise HTTPException(403, "not allowed")


def _error(status: int, message: str) -> JSONResponse:
    return JSONResponse({"error": {"message": message, "type": "kemudi_proxy"}},
                        status_code=status)


def _note(sessions: sessionmaker[Session], alias: str, ok: bool, error: str = "") -> None:
    try:
        with sessions() as db:
            llm_conn.note_upstream(db, alias, ok, error)
    except Exception:  # noqa: BLE001 - bookkeeping must never break a model call
        log.exception("could not record the upstream result")


def _record(sessions: sessionmaker[Session], settings: Settings, meta: usage.CallMeta,
            conn: llm_conn.Connection, data) -> None:
    try:
        with sessions() as db:
            usage.record_call(db, settings, meta, conn.model, conn.source, data)
    except Exception:  # noqa: BLE001 - bookkeeping must never break a model call
        log.exception("could not record the model usage")


def _sse_usage(line: bytes):
    """The `usage` of one SSE `data:` line, if it carries one."""
    line = line.strip()
    if not line.startswith(b"data:"):
        return None
    payload = line[5:].strip()
    if not payload or payload == b"[DONE]" or b'"usage"' not in payload:
        return None
    try:
        data = json.loads(payload)
    except ValueError:
        return None
    return data.get("usage") if isinstance(data, dict) and data.get("usage") else None


def _body_usage(content: bytes):
    try:
        data = json.loads(content)
    except ValueError:
        return None
    return data.get("usage") if isinstance(data, dict) else None


@router.get("/models")
def models(request: Request, settings: Settings = Depends(get_settings)):
    """Aliases are not listed: they are capabilities."""
    _check_token(request, settings)
    return {"object": "list", "data": []}


@router.post("/chat/completions")
async def chat_completions(
    request: Request,
    settings: Settings = Depends(get_settings),
    sessions: sessionmaker[Session] = Depends(get_sessions),
    transport: httpx.AsyncBaseTransport | None = Depends(get_upstream_transport),
):
    _check_token(request, settings)
    try:
        body = json.loads(await request.body())
    except ValueError:
        return _error(400, "the body is not JSON")
    if not isinstance(body, dict):
        return _error(400, "the body is not a JSON object")
    with sessions() as db:
        # Hermes' API server may answer with its configured default model instead
        # of the alias it was asked for. Awak runs one job at a time (worker
        # lease), so a non-alias model name maps to the single active run. Only
        # reached after the shared token was checked above.
        row = (llm_conn.lookup_alias(db, body.get("model"))
               or llm_conn.active_alias(db))
        if row is None:
            return _error(403, "unknown or expired model alias")
        alias = row.alias
        meta = usage.CallMeta.of(row)
        over = usage.problem(db, row.project_slug, row.job_id)
        if over is not None:
            # Not the provider's fault: not counted as an upstream error.
            row.budget_stop = str(over)
            db.commit()
            return JSONResponse({"error": {"message": str(over), "type": "kemudi_budget",
                                           "code": "budget_exceeded"}}, status_code=402)
        try:
            conn = llm_conn.resolve(db, settings, row.project_slug, row.role_id,
                                    row.fallback_model)
        except SecretKeyMissing:
            return _error(503, "the stored model key does not decrypt (KEMUDI_SECRET_KEY)")
    if not conn.base_url:
        return _error(503, "no model connection: set one in Project settings -> Agent, "
                           "or KEMUDI_AI_BASE_URL on the server")
    body["model"] = conn.model
    effort = settings.awak_reasoning_effort.strip().lower()
    if (effort in REASONING_EFFORTS and "reasoning_effort" not in body
            and "reasoning" not in body and "thinking" not in body):
        body["reasoning_effort"] = effort
    streaming = bool(body.get("stream"))
    if streaming and settings.llm_stream_usage and "stream_options" not in body:
        body["stream_options"] = {"include_usage": True}
    client = httpx.AsyncClient(
        transport=transport, follow_redirects=False,
        timeout=httpx.Timeout(settings.llm_proxy_timeout_s, connect=15.0))
    req = client.build_request("POST", f"{conn.base_url}/chat/completions",
                               content=json.dumps(body).encode(),
                               headers=llm_conn.upstream_headers(conn))
    try:
        upstream = await client.send(req, stream=True)
    except httpx.HTTPError as e:
        await client.aclose()
        message = llm_conn.scrub(f"provider unreachable: {type(e).__name__}: {e}", conn)[:300]
        _note(sessions, alias, False, message)
        return _error(502, message)
    if upstream.is_redirect:
        await upstream.aclose()
        await client.aclose()
        return _error(502, f"the provider answered with a redirect ({upstream.status_code}); "
                           "redirects are not followed")
    headers = {k: v for k, v in upstream.headers.items() if k.lower() not in _HOP}
    ok = 200 <= upstream.status_code < 300
    _note(sessions, alias, ok, "" if ok else f"provider answered HTTP {upstream.status_code}")

    async def close() -> None:
        await upstream.aclose()
        await client.aclose()

    if streaming:
        async def relay():
            buf, found = b"", None
            try:
                async for chunk in upstream.aiter_bytes():
                    yield chunk
                    if not ok:
                        continue
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        found = _sse_usage(line) or found
            finally:
                if ok:
                    _record(sessions, settings, meta, conn, found or _sse_usage(buf))

        return StreamingResponse(relay(), status_code=upstream.status_code,
                                 headers=headers, background=BackgroundTask(close))
    try:
        content = await upstream.aread()
    finally:
        await close()
    if ok:
        _record(sessions, settings, meta, conn, _body_usage(content))
    return Response(content, status_code=upstream.status_code, headers=headers)
