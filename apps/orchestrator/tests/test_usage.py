"""Awak usage accounting and budgets: the price table, the proxy's per-call
usage rows, budget refusals, the worker and Setup Assistant stops, and the
Usage and budget API."""

import json
from datetime import timedelta

import httpx
import pytest

from kemudi_ai.api import app
from kemudi_ai.awak import llm_conn, llm_proxy, setup, usage
from kemudi_ai.awak.agent import HermesAgent
from kemudi_ai.awak.usage import BudgetExceeded, Price
from kemudi_ai.config import Settings
from kemudi_ai.store import (
    AiCall,
    AwakJob,
    AwakLlmAlias,
    AwakLlmUsage,
    AwakProject,
    Decision,
    make_session,
)

from .awak_fakes import FakeAgent, FakeRunner, commit_file
from .conftest import ADMIN, MEMBER, SECRET_KEY
from .test_awak import DESC, host, job_of, make_worker, repo  # noqa: F401 (fixtures)
from .test_setup import drive, make, project_host, run_of  # noqa: F401 (fixtures)

PROFILE = "sk-e3b0c44298fc1c149afbf4c8996fb924"


def _settings(**kw) -> Settings:
    return Settings(secret_key=SECRET_KEY, ai_db_url="sqlite:///:memory:",
                    ai_base_url="https://server.example/v1", ai_api_key="server-key-123456",
                    **kw)


def _project(S, slug="demo", **fields) -> None:
    with S() as db:
        p = db.get(AwakProject, slug)
        if p is None:
            p = AwakProject(slug=slug)
            db.add(p)
        for k, v in fields.items():
            setattr(p, k, v)
        db.commit()


def _spend(S, tokens, slug="demo", job_id=None, at=None, cost=1.0):
    with S() as db:
        db.add(AwakLlmUsage(at=at or usage._naive_now(), project_slug=slug, job_id=job_id,
                            prompt_tokens=tokens, completion_tokens=0, cost_idr=cost))
        db.commit()


# --- prices ---------------------------------------------------------------------


def test_deepseek_models_have_a_price_and_cost_is_never_a_silent_zero():
    s = _settings()
    S = make_session("sqlite:///:memory:")
    with S() as db:
        price, src = usage.price_for(db, s, "demo", "deepseek-flash")
        assert src == "table" and price.input > 0 and price.output > 0
        # a provider prefix and case do not matter
        assert usage.price_for(db, s, "demo", "DeepSeek/deepseek-chat")[1] == "table"
        # an unknown model: unknown, not 0
        assert usage.price_for(db, s, "demo", "my-finetune") == (None, "")
    assert usage.cost_idr(s, None, 1000, 0, 10) is None


def test_cost_uses_cached_prompt_tokens_and_the_usd_rate():
    s = _settings(usd_idr_rate=16000.0)
    p = Price(input=0.28, cached_input=0.028, output=0.42)
    # 1M prompt (400k cached) + 100k completion
    usd = (600_000 * 0.28 + 400_000 * 0.028 + 100_000 * 0.42) / 1e6
    assert usage.cost_idr(s, p, 1_000_000, 400_000, 100_000) == pytest.approx(usd * 16000)
    # IDR prices are not converted; no cached price: billed as input
    idr = Price(input=5000, output=10000, currency="IDR")
    assert usage.cost_idr(s, idr, 2_000_000, 1_000_000, 0) == pytest.approx(10000)


def test_parse_usage_reads_openai_and_deepseek_cache_fields():
    assert usage.parse_usage(None) is None
    assert usage.parse_usage({}) is None
    assert usage.parse_usage({"prompt_tokens": 10, "completion_tokens": 2,
                              "prompt_tokens_details": {"cached_tokens": 4}}) == (10, 4, 2)
    assert usage.parse_usage({"prompt_tokens": 10, "completion_tokens": 2,
                              "prompt_cache_hit_tokens": 6}) == (10, 6, 2)


def test_price_table_env_override_and_project_override():
    s = _settings(llm_prices=json.dumps({
        "my-model": {"input": 1, "output": 2, "currency": "USD"},
        "deepseek-flash": {"input": 3000, "output": 6000, "currency": "IDR"},
        "broken": {"input": "x"}}))
    S = make_session("sqlite:///:memory:")
    with S() as db:
        assert usage.price_for(db, s, "demo", "my-model")[0] == Price(1.0, 2.0)
        assert usage.price_for(db, s, "demo", "deepseek-flash")[0].currency == "IDR"
        assert usage.price_for(db, s, "demo", "broken") == (None, "")
    _project(S, price_input_per_1m=0.5, price_output_per_1m=1.0, price_currency="USD")
    with S() as db:
        price, src = usage.price_for(db, s, "demo", "anything")
        assert src == "project" and price == Price(0.5, 1.0)
    # The legacy flat price still prices an unknown model.
    s2 = _settings(token_price_idr_per_1k=10.0)
    with S() as db:
        assert usage.price_for(db, s2, "other", "my-finetune")[1] == "flat"


# --- the proxy ------------------------------------------------------------------


@pytest.fixture
def upstream(agent_client):
    seen: list[httpx.Request] = []
    replies: list[httpx.Response] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return replies.pop(0) if replies else httpx.Response(
            200, json={"id": "x", "choices": [{"message": {"content": "hi"}}],
                       "usage": {"prompt_tokens": 1_000_000, "completion_tokens": 1000,
                                 "prompt_tokens_details": {"cached_tokens": 500_000}}})

    app.dependency_overrides[llm_proxy.get_upstream_transport] = (
        lambda: httpx.MockTransport(handler))
    agent_client.settings.ai_base_url = "https://server.example/v1"
    return seen, replies


def _alias(client, fallback="deepseek-flash", job_id=None, setup_run_id=None) -> str:
    with client.S() as db:
        return llm_conn.register_alias(db, client.settings, "demo", None, fallback,
                                       "awak.code", job_id=job_id, setup_run_id=setup_run_id)


URL = "/llm/v1/chat/completions"


def test_proxy_records_tokens_and_cost_per_call(agent_client, upstream):
    with agent_client.S() as db:
        db.add(AwakJob(project_slug="demo", story_id=1, story_ref=12, branch="awak/us-12"))
        db.commit()
    alias = _alias(agent_client, job_id=1)
    r = agent_client.post(URL, json={"model": alias, "messages": []})
    assert r.status_code == 200
    with agent_client.S() as db:
        row = db.query(AwakLlmUsage).one()
    assert (row.project_slug, row.job_id, row.alias, row.model) == (
        "demo", 1, alias, "deepseek-flash")
    assert (row.prompt_tokens, row.cached_tokens, row.completion_tokens) == (
        1_000_000, 500_000, 1000)
    assert row.cost_idr and row.cost_idr > 0 and row.price_source == "table"
    # An unknown model: the tokens count, the cost is unknown (NULL).
    alias = _alias(agent_client, fallback="my-finetune")
    agent_client.post(URL, json={"model": alias, "messages": []})
    with agent_client.S() as db:
        row = db.query(AwakLlmUsage).order_by(AwakLlmUsage.id.desc()).first()
    assert row.prompt_tokens == 1_000_000 and row.cost_idr is None
    # An answer without usage is recorded as unreported; an error is not recorded.
    _, replies = upstream
    replies.append(httpx.Response(200, json={"choices": [{"message": {"content": "x"}}]}))
    replies.append(httpx.Response(500, json={"error": "down"}))
    agent_client.post(URL, json={"model": alias, "messages": []})
    agent_client.post(URL, json={"model": alias, "messages": []})
    with agent_client.S() as db:
        rows = db.query(AwakLlmUsage).all()
    assert len(rows) == 3 and rows[-1].usage_reported is False and rows[-1].cost_idr is None


def test_proxy_asks_for_and_records_streamed_usage(agent_client, upstream):
    seen, replies = upstream
    sse = (b'data: {"choices":[{"delta":{"content":"he"}}]}\n\n'
           b'data: {"choices":[],"usage":{"prompt_tokens":120,"completion_tokens":30}}\n\n'
           b"data: [DONE]\n\n")
    replies.append(httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  content=sse))
    with agent_client.stream("POST", URL, json={"model": _alias(agent_client),
                                                "stream": True, "messages": []}) as r:
        body = b"".join(r.iter_bytes())
    assert body == sse  # relayed unchanged
    assert json.loads(seen[-1].content)["stream_options"] == {"include_usage": True}
    with agent_client.S() as db:
        row = db.query(AwakLlmUsage).one()
    assert (row.prompt_tokens, row.completion_tokens) == (120, 30)
    # A client's own stream_options are left alone.
    replies.append(httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  content=b"data: [DONE]\n\n"))
    with agent_client.stream("POST", URL, json={
            "model": _alias(agent_client), "stream": True,
            "stream_options": {"include_usage": False}, "messages": []}) as r:
        b"".join(r.iter_bytes())
    assert json.loads(seen[-1].content)["stream_options"] == {"include_usage": False}


def test_proxy_refuses_a_project_over_its_monthly_budget(agent_client, upstream):
    seen, _ = upstream
    _project(agent_client.S, token_budget_monthly=1_000_000)
    # last month's tokens do not count
    _spend(agent_client.S, 5_000_000, at=usage.month_start() - timedelta(days=2))
    alias = _alias(agent_client)
    assert agent_client.post(URL, json={"model": alias, "messages": []}).status_code == 200
    r = agent_client.post(URL, json={"model": alias, "messages": []})
    assert r.status_code == 402
    err = r.json()["error"]
    assert err["type"] == "kemudi_budget" and "monthly token budget" in err["message"]
    assert len(seen) == 1  # the provider was not called
    with agent_client.S() as db:
        row = db.get(AwakLlmAlias, alias)
        assert "monthly token budget" in row.budget_stop
        # not the provider's fault
        assert row.upstream_errors == 0 and llm_conn.provider_failure(db, alias) is None


def test_proxy_refuses_a_story_over_its_cap(agent_client, upstream):
    _project(agent_client.S, token_cap_story=500_000)
    with agent_client.S() as db:
        db.add(AwakJob(project_slug="demo", story_id=1, story_ref=12, branch="awak/us-12"))
        db.add(AwakJob(project_slug="demo", story_id=2, story_ref=13, branch="awak/us-13"))
        db.commit()
    _spend(agent_client.S, 600_000, job_id=1)
    r = agent_client.post(URL, json={"model": _alias(agent_client, job_id=1), "messages": []})
    assert r.status_code == 402 and "token cap" in r.json()["error"]["message"]
    # another story, and the Setup Assistant, are not capped
    assert agent_client.post(URL, json={"model": _alias(agent_client, job_id=2),
                                        "messages": []}).status_code == 200
    assert agent_client.post(URL, json={"model": _alias(agent_client, setup_run_id=3),
                                        "messages": []}).status_code == 200


# --- the agent run --------------------------------------------------------------


def test_hermes_run_cost_comes_from_the_proxied_calls():
    s = _settings()
    S = make_session("sqlite:///:memory:")

    def hermes(req: httpx.Request) -> httpx.Response:
        alias = json.loads(req.content)["model"]
        with S() as db:  # what the proxy records for two model calls of the run
            row = db.get(AwakLlmAlias, alias)
            assert row.job_id == 4
            meta = usage.CallMeta.of(row)
            for _ in range(2):
                usage.record_call(db, s, meta, "deepseek-flash", "server",
                                  {"prompt_tokens": 1_000_000, "completion_tokens": 0})
        # Hermes reports no usage of its own
        return httpx.Response(200, json={"choices": [{"message": {"content": "done"}}]})

    agent = HermesAgent(s, S, transport=httpx.MockTransport(hermes))
    _, cost = agent.run("awak.code", "deepseek-flash", "sys", "task", slug="demo",
                        profile=PROFILE, job_id=4)
    expected = 2 * 0.14 * s.usd_idr_rate
    assert cost == pytest.approx(expected)
    with S() as db:
        call = db.query(AiCall).one()
        assert call.prompt_tokens == 2_000_000 and call.cost_idr == pytest.approx(expected)


def test_hermes_run_without_proxied_calls_prices_hermes_usage():
    s = _settings()
    S = make_session("sqlite:///:memory:")

    def hermes(req):
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}],
                                         "usage": {"prompt_tokens": 1_000_000,
                                                   "completion_tokens": 0}})

    agent = HermesAgent(s, S, transport=httpx.MockTransport(hermes))
    _, cost = agent.run("awak.code", "deepseek-flash", "s", "t", slug="demo", profile=PROFILE)
    assert cost == pytest.approx(0.14 * s.usd_idr_rate)  # no longer 0


def test_hermes_run_raises_budget_exceeded_when_the_proxy_refused():
    s = _settings()
    S = make_session("sqlite:///:memory:")
    _project(S, token_budget_monthly=100)
    _spend(S, 150, cost=2.5)

    def hermes(req: httpx.Request) -> httpx.Response:
        alias = json.loads(req.content)["model"]
        with S() as db:
            db.get(AwakLlmAlias, alias).budget_stop = "Stopped: over budget"
            db.commit()
        return httpx.Response(200, json={"choices": [{"message": {
            "content": "the provider refused: budget"}}]})

    agent = HermesAgent(s, S, transport=httpx.MockTransport(hermes))
    with pytest.raises(BudgetExceeded) as e:
        agent.run("awak.code", "m", "s", "t", slug="demo", profile=PROFILE)
    assert (e.value.kind, e.value.used, e.value.limit) == ("monthly", 150, 100)
    with S() as db:
        assert db.query(AwakLlmAlias).count() == 0
        assert db.query(AiCall).one().ok is False


# --- the worker -----------------------------------------------------------------


def test_story_over_its_cap_is_blocked_for_a_human_with_a_comment(tmp_path, repo):
    holder: dict = {}

    def code(workdir, n):
        commit_file(workdir, f"feature{n}.txt", "x")
        _spend(holder["S"], 2_000_000, slug="kemudi", job_id=job_of(holder["S"]).id)

    runner = FakeRunner(tmp_path / "ws", qa=["pass"])
    agent = FakeAgent(code=code)
    w, taiga, sessions = make_worker(tmp_path, repo, agent, runner)
    holder["S"] = sessions
    w._seed()
    _project(sessions, "kemudi", token_cap_story=1_000_000)
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    # coding ran, QA did not: the cap was hit in between
    assert [p for p, _ in agent.calls] == ["awak.code"]
    st = taiga.story(1)
    assert st["is_blocked"] and ["needs-human", None] in st["tags"]
    last = taiga.texts(1)[-1]
    assert "Butuh bantuan manusia" in last and "Batas token per story" in last
    assert "2.000.000 dari 1.000.000 token" in last
    assert job_of(sessions).state == "failed"
    assert w._last_event(job_of(sessions).id, "budget")["kind"] == "story"


def test_budget_stop_inside_a_run_blocks_the_story(tmp_path, repo):
    agent = FakeAgent(fail_with=[BudgetExceeded("monthly", 120, 100, cost_idr=5.0)])
    runner = FakeRunner(tmp_path / "ws", qa=["pass"])
    w, taiga, sessions = make_worker(tmp_path, repo, agent, runner)
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    st = taiga.story(1)
    assert st["is_blocked"] and ["needs-human", None] in st["tags"]
    assert "Anggaran token bulanan proyek" in taiga.texts(1)[-1]
    job = job_of(sessions)
    assert job.state == "failed" and job.cost_idr == 5.0 and job.infra_errors == 0


def test_no_story_is_picked_over_the_monthly_budget(tmp_path, repo):
    agent = FakeAgent()
    w, taiga, sessions = make_worker(tmp_path, repo, agent,
                                     FakeRunner(tmp_path / "ws", qa=["pass"]))
    w._seed()
    _project(sessions, "kemudi", token_budget_monthly=1000)
    _spend(sessions, 1000, slug="kemudi")
    taiga.add(1, 12, "Badge jumlah", DESC)
    assert not w.tick()
    assert agent.calls == [] and taiga.status_of(1) == "ready"
    assert not taiga.story(1)["is_blocked"]
    with sessions() as db:
        assert "monthly token budget" in db.get(AwakProject, "kemudi").last_error


def test_setup_assistant_stops_over_the_budget(tmp_path, repo, project_host):
    w, sessions, settings, runner, agent, run_id, _ = make(tmp_path, repo)
    _project(sessions, "kemudi", token_budget_monthly=1000)
    _spend(sessions, 5000, slug="kemudi")
    seen = drive(w, sessions, run_id)
    assert seen[-1] == "failed" and agent.tasks == []
    run = run_of(sessions, run_id)
    assert "monthly token budget" in run.error and "Usage and budget" in run.error
    assert setup.SetupRunner(w).next_run() is None


# --- the API --------------------------------------------------------------------


def test_usage_summary_and_budget_api(agent_client):
    S = agent_client.S
    with S() as db:
        db.add(AwakJob(project_slug="demo", story_id=1, story_ref=12, branch="awak/us-12"))
        db.commit()
    _spend(S, 300, job_id=1, cost=1500.0)
    _spend(S, 100, cost=None)  # an unknown price
    r = agent_client.get("/projects/demo/agent/usage", headers=MEMBER)
    assert r.status_code == 200, r.text
    u = r.json()
    assert u["tokens"] == 400 and u["cost_idr"] == 1500.0 and u["unknown_cost_calls"] == 1
    assert u["budget"]["monthly_tokens"] is None and u["budget"]["warning"] is False
    assert u["budget"]["recommended_monthly_tokens"] == 50_000_000
    assert u["stories"][0]["story_ref"] == 12 and u["stories"][0]["tokens"] == 300
    assert u["price"]["model"] == "deepseek-flash" and u["price"]["source"] == "table"

    body = {"monthly_tokens": 480, "story_cap": 0,
            "price": {"input": 0.3, "output": 0.5, "currency": "USD"}}
    assert agent_client.put("/projects/demo/agent/usage/budget", headers=MEMBER,
                            json=body).status_code == 403
    r = agent_client.put("/projects/demo/agent/usage/budget", headers=ADMIN, json=body)
    assert r.status_code == 200, r.text
    b = r.json()["budget"]
    assert b["monthly_tokens"] == 480 and b["story_cap"] is None
    assert b["warning"] is True and b["exceeded"] is False  # 400 of 480 = 83%
    assert r.json()["price"]["source"] == "project"
    assert r.json()["price_override"]["input"] == 0.3
    with S() as db:
        d = db.query(Decision).filter_by(action="awak_budget").one()
        assert d.detail["changed"]["token_budget_monthly"] == 480
    assert agent_client.put("/projects/demo/agent/usage/budget", headers=ADMIN,
                            json={"monthly_tokens": -1}).status_code == 422
    # Clearing returns to unlimited and the price table.
    r = agent_client.put("/projects/demo/agent/usage/budget", headers=ADMIN, json={})
    assert r.json()["budget"]["monthly_tokens"] is None and r.json()["price_override"] is None
