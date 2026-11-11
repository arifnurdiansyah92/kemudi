import json

import httpx
import pytest

from kemudi_ai.config import Settings
from kemudi_ai.llm import HermesLLM, LLMError
from kemudi_ai.store import AiCall, make_session


def make(replies):
    replies = list(replies)
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        content = replies.pop(0)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    S = make_session("sqlite:///:memory:")
    llm = HermesLLM(
        Settings(hermes_url="http://hermes/v1", token_price_idr_per_1k=100),
        S,
        transport=httpx.MockTransport(handler),
    )
    return llm, S, seen


def test_parses_fenced_json():
    llm, _, seen = make(['Here:\n```json\n{"a": 1}\n```'])
    assert llm.json("t", "sys", "user") == {"a": 1}
    assert seen[0]["model"] == "deepseek-flash"
    assert seen[0]["response_format"] == {"type": "json_object"}


def test_retries_once_then_raises():
    llm, S, _ = make(["nope", "still nope"])
    with pytest.raises(LLMError) as e:
        llm.json("t", "sys", "user")
    assert e.value.raw == "still nope"
    with S() as s:
        assert s.query(AiCall).count() == 2


def test_records_tokens_and_latency():
    llm, S, _ = make(['{"ok": true}'])
    llm.json("classify", "sys", "user")
    with S() as s:
        row = s.query(AiCall).one()
    assert (row.purpose, row.prompt_tokens, row.completion_tokens) == ("classify", 10, 5)
    assert row.cost_idr == pytest.approx(1.5)
    assert row.latency_ms >= 0 and "[user]\nuser" in row.prompt


def test_http_error_is_llmerror_and_logged():
    S = make_session("sqlite:///:memory:")
    llm = HermesLLM(
        Settings(hermes_url="http://hermes/v1"),
        S,
        transport=httpx.MockTransport(lambda r: httpx.Response(502)),
    )
    with pytest.raises(LLMError):
        llm.json("t", "s", "u")
    with S() as s:
        assert s.query(AiCall).one().ok is False
