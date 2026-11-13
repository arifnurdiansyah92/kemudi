"""BYOK: model connections per agent / project / server, and the /llm/v1 proxy."""

import json
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import create_engine, inspect, text

from kemudi_ai.api import app
from kemudi_ai.awak import agent_api, crypto, llm_conn, llm_proxy
from kemudi_ai.awak.agent import HermesAgent
from kemudi_ai.awak.worker import Worker
from kemudi_ai.config import Settings
from kemudi_ai.store import (
    AiCall,
    AwakLlmAlias,
    AwakProject,
    AwakRole,
    Decision,
    init_db,
    make_session,
)

from .conftest import ADMIN, MEMBER, SECRET_KEY

KEY = "sk-live-AbCdEfGh0123456789wxyz"
ROLE_KEY = "gsk_role0123456789abcdQRST"
ROLE = {"name": "Backend dev", "template": "backend", "area": "backend",
        "model": "", "repo_ids": [],"allowed_paths": [], "denied_paths": [],
        "prompt_overlay": "", "enabled": True}


def _settings(**kw) -> Settings:
    return Settings(secret_key=SECRET_KEY, ai_db_url="sqlite:///:memory:",
                    ai_base_url="https://server.example/v1", ai_api_key="server-key-123456",
                    awak_model="srv-model", **kw)


def _role(client) -> int:
    r = client.post("/projects/demo/agent/roles", headers=ADMIN, json=ROLE)
    assert r.status_code == 200, r.text
    return r.json()["id"]


# --- resolution -------------------------------------------------------------------


def test_resolution_agent_over_project_over_server_with_partial_levels():
    s = _settings()
    S = make_session("sqlite:///:memory:")
    with S() as db:
        db.add(AwakProject(slug="demo"))
        # The role sets no model of its own: it uses the effective level's model
        # (role-model overrides are covered in test_role_model_overrides_...).
        role = AwakRole(project_slug="demo", template="backend", name="B", area="backend",
                        model="")
        db.add(role)
        db.commit()
        # Nothing set: server default with the fallback, then KEMUDI_AWAK_MODEL.
        c = llm_conn.resolve(db, s, "demo", role.id)
        assert (c.source, c.base_url, c.api_key, c.model) == (
            "server", "https://server.example/v1", "server-key-123456", "srv-model")
        assert llm_conn.resolve(db, s, "demo", role.id, "role-fb").model == "role-fb"
        # No role: the fallback model, then KEMUDI_AWAK_MODEL.
        assert llm_conn.resolve(db, s, "demo", None, "qa-model").model == "qa-model"
        assert llm_conn.resolve(db, s, "demo", None).model == "srv-model"

        # A partial project level (no model) is not a level.
        p = db.get(AwakProject, "demo")
        p.llm_base_url = "https://proj.example/v1"
        db.commit()
        assert llm_conn.resolve(db, s, "demo", role.id).source == "server"
        llm_conn.set_level(s, p, "https://proj.example/v1", "proj-model", KEY)
        db.commit()
        c = llm_conn.resolve(db, s, "demo", role.id)
        assert (c.source, c.base_url, c.api_key, c.model) == (
            "project", "https://proj.example/v1", KEY, "proj-model")

        # A partial agent level (model only) inherits the project level whole.
        role.llm_model = "agent-model"
        db.commit()
        assert llm_conn.resolve(db, s, "demo", role.id).source == "project"
        # A keyless agent level never borrows the project's key.
        role.llm_base_url = "http://10.0.0.5:11434/v1"
        db.commit()
        c = llm_conn.resolve(db, s, "demo", role.id)
        assert (c.source, c.base_url, c.api_key, c.model) == (
            "agent", "http://10.0.0.5:11434/v1", "", "agent-model")
        # describe() never decrypts.
        llm_conn.set_level(s, role, role.llm_base_url, "agent-model", ROLE_KEY)
        db.commit()
        assert llm_conn.resolve(db, s, "demo", role.id).api_key == ROLE_KEY
        assert llm_conn.describe(db, s, "demo", role.id).api_key == ""
        # A role of another project is ignored.
        assert llm_conn.resolve(db, s, "other", role.id).source == "server"
        assert sorted(llm_conn.stored_keys(db, s)) == sorted([KEY, ROLE_KEY])


def test_role_model_overrides_inherited_connection_model():
    s = _settings()
    S = make_session("sqlite:///:memory:")
    with S() as db:
        p = AwakProject(slug="demo")
        llm_conn.set_level(s, p, "https://proj.example/v1", "proj-model", KEY)
        db.add(p)
        role = AwakRole(project_slug="demo", template="backend", name="B", area="backend",
                        model="role-model")
        db.add(role)
        db.commit()
        # The project's provider and key, the role's model.
        c = llm_conn.resolve(db, s, "demo", role.id)
        assert (c.source, c.base_url, c.api_key, c.model) == (
            "project", "https://proj.example/v1", KEY, "role-model")
        assert llm_conn.describe(db, s, "demo", role.id).public() == {
            "llm_source": "project", "llm_model": "role-model", "llm_host": "proj.example"}
        # The server default too, ahead of the fallback model.
        p.llm_base_url = ""
        db.commit()
        assert llm_conn.resolve(db, s, "demo", role.id, "fb").model == "role-model"
        # Its own connection: the role's model is the one model field.
        llm_conn.set_level(s, role, "https://r.example/v1", "old-level-model", ROLE_KEY)
        db.commit()
        c = llm_conn.resolve(db, s, "demo", role.id)
        assert (c.source, c.api_key, c.model) == ("agent", ROLE_KEY, "role-model")
        role.model = ""
        db.commit()
        assert llm_conn.resolve(db, s, "demo", role.id).model == "old-level-model"


def test_base_url_validation():
    ok = llm_conn.validate_base_url
    assert ok("https://api.openai.com/v1/") == "https://api.openai.com/v1"
    assert ok("http://127.0.0.1:11434/v1") == "http://127.0.0.1:11434/v1"
    assert ok("http://10.1.2.3/v1") == "http://10.1.2.3/v1"
    assert ok("http://localhost:8000/v1") == "http://localhost:8000/v1"
    assert ok("http://[::1]:8000/v1") == "http://[::1]:8000/v1"
    for bad in ("http://8.8.8.8/v1", "ftp://x.example/v1", "https://u:p@x.example/v1",
                "https://x.example/v1?a=1", "api.openai.com/v1", "", "https://a b/v1"):
        with pytest.raises(ValueError):
            ok(bad, resolve=False)
    with pytest.raises(ValueError):  # a public hostname over http
        ok("http://api.openai.com/v1", resolve=False)


# --- API ------------------------------------------------------------------------


def test_project_level_api_key_write_only(agent_client):
    url = "/projects/demo/agent/llm"
    body = {"base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini", "api_key": KEY}
    assert agent_client.put(url, headers=MEMBER, json=body).status_code == 403
    r = agent_client.put(url, headers=ADMIN, json=body)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["set"] and out["key_set"] and out["key_last4"] == "wxyz"
    assert out["effective"] == {"llm_source": "project", "llm_model": "gpt-4o-mini",
                                "llm_host": "api.openai.com"}
    # Empty key keeps the stored one.
    r = agent_client.put(url, headers=ADMIN, json={**body, "model": "gpt-4o", "api_key": ""})
    assert r.json()["key_last4"] == "wxyz" and r.json()["model"] == "gpt-4o"
    role_id = _role(agent_client)
    texts = [agent_client.get(url, headers=MEMBER).text,
             agent_client.get("/projects/demo/agent/roles", headers=MEMBER).text,
             agent_client.get(f"/projects/demo/agent/roles/{role_id}/llm", headers=MEMBER).text,
             r.text]
    assert all(KEY not in t for t in texts)
    roles = agent_client.get("/projects/demo/agent/roles", headers=MEMBER).json()["roles"]
    assert (roles[0]["llm_source"], roles[0]["llm_model"], roles[0]["llm_host"]) == (
        "project", "gpt-4o", "api.openai.com")
    with agent_client.S() as db:
        p = db.get(AwakProject, "demo")
        assert KEY not in p.llm_api_key_enc
        assert crypto.decrypt(agent_client.settings, p.llm_api_key_enc) == KEY
        details = [json.dumps(d.detail) for d in db.query(Decision).filter_by(action="awak_llm")]
    assert len(details) == 2 and all(KEY not in d for d in details)
    # Clear removes the level.
    r = agent_client.put(url, headers=ADMIN, json={"clear": True})
    assert r.json()["set"] is False and r.json()["key_set"] is False
    assert r.json()["effective"]["llm_source"] == "server"


def test_role_level_api_and_validation(agent_client):
    role_id = _role(agent_client)
    url = f"/projects/demo/agent/roles/{role_id}/llm"
    bad = {"base_url": "http://8.8.8.8/v1", "model": "m", "api_key": ROLE_KEY}
    assert agent_client.put(url, headers=ADMIN, json=bad).status_code == 422
    assert agent_client.put(url, headers=ADMIN,
                            json={"base_url": "https://x.example/v1", "model": ""}
                            ).status_code == 422
    body = {"base_url": "http://127.0.0.1:11434/v1", "model": "qwen3", "api_key": ROLE_KEY}
    assert agent_client.put(url, headers=MEMBER, json=body).status_code == 403
    r = agent_client.put(url, headers=ADMIN, json=body)
    assert r.status_code == 200 and ROLE_KEY not in r.text
    assert r.json()["effective"]["llm_source"] == "agent"
    assert agent_client.get("/projects/demo/agent/roles/999/llm",
                            headers=MEMBER).status_code == 404
    roles = agent_client.get("/projects/demo/agent/roles", headers=MEMBER).json()["roles"]
    assert (roles[0]["llm_source"], roles[0]["llm_model"], roles[0]["llm_host"]) == (
        "agent", "qwen3", "127.0.0.1")
    r = agent_client.put(url, headers=ADMIN, json={"clear": True})
    assert r.json()["effective"]["llm_source"] == "server"


def test_key_needs_secret_key(agent_client):
    agent_client.settings.secret_key = ""
    r = agent_client.put("/projects/demo/agent/llm", headers=ADMIN,
                         json={"base_url": "https://x.example/v1", "model": "m", "api_key": KEY})
    assert r.status_code == 503


def test_connection_test_endpoint(agent_client):
    seen: list[httpx.Request] = []

    def upstream(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if req.headers.get("authorization") == f"Bearer {KEY}":
            return httpx.Response(200, json={"choices": [{"message": {"content": "p"}}]})
        # A provider that echoes the key it got must not leak it.
        return httpx.Response(401, text=f"bad key {req.headers.get('authorization')}")

    app.dependency_overrides[agent_api.get_llm_transport] = lambda: httpx.MockTransport(upstream)
    url = "/projects/demo/agent/llm"
    agent_client.put(url, headers=ADMIN, json={"base_url": "https://p.example/v1",
                                               "model": "m1", "api_key": KEY})
    assert agent_client.post(f"{url}/test", headers=MEMBER).status_code == 403
    r = agent_client.post(f"{url}/test", headers=ADMIN)
    out = r.json()
    assert out["ok"] is True and out["llm_source"] == "project" and out["latency_ms"] >= 0
    sent = json.loads(seen[-1].content)
    assert sent["model"] == "m1" and sent["max_tokens"] == 1
    assert str(seen[-1].url) == "https://p.example/v1/chat/completions"
    # Unsaved values, same base URL: the stored key is reused.
    r = agent_client.post(f"{url}/test", headers=ADMIN,
                          json={"base_url": "https://p.example/v1", "model": "m2"})
    assert r.json()["ok"] is True
    # Another base URL never gets the stored key.
    r = agent_client.post(f"{url}/test", headers=ADMIN,
                          json={"base_url": "https://other.example/v1", "model": "m2"})
    assert r.json()["ok"] is False and "authorization" not in seen[-1].headers
    # A wrong key: error reported, key redacted.
    r = agent_client.post(f"{url}/test", headers=ADMIN,
                          json={"base_url": "https://p.example/v1", "model": "m2",
                                "api_key": "sk-wrongwrongwrongwrongwrong"})
    assert r.json()["ok"] is False and r.json()["status"] == 401
    assert "sk-wrongwrong" not in r.text
    role_id = _role(agent_client)
    r = agent_client.post(f"/projects/demo/agent/roles/{role_id}/llm/test", headers=ADMIN)
    assert r.json()["ok"] is True and r.json()["llm_source"] == "project"


def test_models_endpoint_uses_the_applicable_connection(agent_client):
    seen: list[httpx.Request] = []

    def upstream(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        auth = req.headers.get("authorization")
        if req.url.host == "p.example" and auth == f"Bearer {KEY}":
            return httpx.Response(200, json={"object": "list", "data": [
                {"id": "zeta"}, {"id": "alpha"}, {"id": "alpha"}]})
        if req.url.host == "r.example" and auth == f"Bearer {ROLE_KEY}":
            return httpx.Response(200, json={"data": [{"id": "role-only"}]})
        if req.url.host == "server.example":
            return httpx.Response(200, json={"data": [{"id": "srv-a"}]})
        return httpx.Response(401, text=f"bad key {auth}")

    app.dependency_overrides[agent_api.get_llm_transport] = lambda: httpx.MockTransport(upstream)
    agent_client.settings.ai_base_url = "https://server.example/v1"
    url = "/projects/demo/agent/llm/models"
    assert agent_client.post(url, headers=MEMBER).status_code == 403
    # Nothing saved: the server default.
    out = agent_client.post(url, headers=ADMIN).json()
    assert out == {"ok": True, "models": ["srv-a"], "source": "server",
                   "host": "server.example", "error": None}
    assert seen[-1].method == "GET" and str(seen[-1].url) == "https://server.example/v1/models"
    agent_client.put("/projects/demo/agent/llm", headers=ADMIN,
                     json={"base_url": "https://p.example/v1", "model": "m1", "api_key": KEY})
    r = agent_client.post(url, headers=ADMIN)
    assert r.json()["models"] == ["alpha", "zeta"] and r.json()["source"] == "project"
    assert KEY not in r.text
    # A role without its own connection lists the project's provider.
    role_id = _role(agent_client)
    r = agent_client.post(url, headers=ADMIN, json={"role_id": role_id})
    assert (r.json()["source"], r.json()["host"]) == ("project", "p.example")
    # Unsaved base URL equal to the saved one reuses the stored key ...
    r = agent_client.post(url, headers=ADMIN, json={"base_url": "https://p.example/v1"})
    assert r.json()["ok"] is True and r.json()["models"] == ["alpha", "zeta"]
    # ... another base URL never gets it.
    r = agent_client.post(url, headers=ADMIN, json={"base_url": "https://other.example/v1"})
    assert r.json()["ok"] is False and "authorization" not in seen[-1].headers
    # A wrong typed key: the error is scrubbed.
    r = agent_client.post(url, headers=ADMIN, json={"base_url": "https://p.example/v1",
                                                    "api_key": "sk-wrongwrongwrongwrongwrong"})
    assert r.json()["ok"] is False and "sk-wrongwrong" not in r.text
    # The role's own connection, and its key is never borrowed by the project.
    agent_client.put(f"/projects/demo/agent/roles/{role_id}/llm", headers=ADMIN,
                     json={"base_url": "https://r.example/v1", "model": "role-only",
                           "api_key": ROLE_KEY})
    r = agent_client.post(url, headers=ADMIN, json={"role_id": role_id})
    assert r.json()["models"] == ["role-only"] and r.json()["source"] == "agent"
    r = agent_client.post(url, headers=ADMIN, json={"role_id": role_id,
                                                    "base_url": "https://r.example/v1"})
    assert r.json()["ok"] is True and ROLE_KEY not in r.text
    r = agent_client.post(url, headers=ADMIN, json={"base_url": "https://r.example/v1"})
    assert r.json()["ok"] is False
    # Validation and unknown roles.
    assert agent_client.post(url, headers=ADMIN,
                             json={"base_url": "http://8.8.8.8/v1"}).status_code == 422
    assert agent_client.post(url, headers=ADMIN, json={"role_id": 999}).status_code == 404
    # Redirects are not followed.
    app.dependency_overrides[agent_api.get_llm_transport] = lambda: httpx.MockTransport(
        lambda req: httpx.Response(302, headers={"location": "https://evil.example/"}))
    r = agent_client.post(url, headers=ADMIN)
    assert r.json()["ok"] is False and "redirect" in r.json()["error"]


def test_role_model_is_optional_and_overrides_in_listing(agent_client):
    agent_client.put("/projects/demo/agent/llm", headers=ADMIN,
                     json={"base_url": "https://p.example/v1", "model": "proj-m", "api_key": KEY})
    inherit = _role(agent_client)
    r = agent_client.post("/projects/demo/agent/roles", headers=ADMIN,
                          json={**ROLE, "name": "Own", "model": "other-m"})
    own = r.json()["id"]
    roles = {x["id"]: x for x in
             agent_client.get("/projects/demo/agent/roles", headers=MEMBER).json()["roles"]}
    assert (roles[inherit]["model"], roles[inherit]["llm_model"]) == ("", "proj-m")
    assert (roles[own]["llm_source"], roles[own]["llm_model"]) == ("project", "other-m")


# --- the /llm/v1 proxy ------------------------------------------------------------


def _alias(client, role_id=None, fallback="fb-model") -> str:
    with client.S() as db:
        return llm_conn.register_alias(db, client.settings, "demo", role_id, fallback,
                                       "awak.code")


@pytest.fixture
def upstream(agent_client):
    seen: list[httpx.Request] = []
    replies: list[httpx.Response] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return replies.pop(0) if replies else httpx.Response(
            200, json={"id": "x", "choices": [{"message": {"content": "hi"}}],
                       "usage": {"prompt_tokens": 3, "completion_tokens": 1}})

    app.dependency_overrides[llm_proxy.get_upstream_transport] = (
        lambda: httpx.MockTransport(handler))
    return seen, replies


def test_proxy_swaps_model_and_key(agent_client, upstream):
    seen, _ = upstream
    role_id = _role(agent_client)
    agent_client.put(f"/projects/demo/agent/roles/{role_id}/llm", headers=ADMIN,
                     json={"base_url": "https://r.example/v1", "model": "real-model",
                           "api_key": ROLE_KEY})
    alias = _alias(agent_client, role_id)
    r = agent_client.post("/llm/v1/chat/completions",
                          headers={"Authorization": "Bearer whatever"},
                          json={"model": alias, "messages": [{"role": "user", "content": "x"}]})
    assert r.status_code == 200 and r.json()["choices"][0]["message"]["content"] == "hi"
    req = seen[-1]
    assert str(req.url) == "https://r.example/v1/chat/completions"
    assert req.headers["authorization"] == f"Bearer {ROLE_KEY}"
    assert json.loads(req.content)["model"] == "real-model"
    assert json.loads(req.content)["messages"][0]["content"] == "x"
    # Server default for a role-less alias: the fallback model and server key.
    agent_client.settings.ai_base_url = "https://server.example/v1"
    agent_client.settings.ai_api_key = "server-key-123456"
    r = agent_client.post("/llm/v1/chat/completions", json={"model": _alias(agent_client),
                                                            "messages": []})
    assert r.status_code == 200
    assert json.loads(seen[-1].content)["model"] == "fb-model"
    assert seen[-1].headers["authorization"] == "Bearer server-key-123456"


def test_proxy_streams_sse(agent_client, upstream):
    seen, replies = upstream
    agent_client.settings.ai_base_url = "https://server.example/v1"
    sse = (b'data: {"choices":[{"delta":{"content":"he"}}]}\n\n'
           b'data: {"choices":[{"delta":{"content":"llo"}}]}\n\ndata: [DONE]\n\n')
    replies.append(httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  content=sse))
    with agent_client.stream("POST", "/llm/v1/chat/completions",
                             json={"model": _alias(agent_client), "stream": True,
                                   "messages": []}) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        body = b"".join(r.iter_bytes())
    assert body == sse
    assert json.loads(seen[-1].content)["stream"] is True


def test_proxy_refuses_unknown_expired_alias_and_bad_token(agent_client, upstream):
    seen, replies = upstream
    agent_client.settings.ai_base_url = "https://server.example/v1"
    url = "/llm/v1/chat/completions"
    assert agent_client.post(url, json={"model": "awak-run-nope", "messages": []}
                             ).status_code == 403
    assert agent_client.post(url, json={"model": "deepseek-flash", "messages": []}
                             ).status_code == 403
    alias = _alias(agent_client)
    with agent_client.S() as db:
        row = db.get(AwakLlmAlias, alias)
        row.expires_at = row.expires_at - timedelta(days=1)
        db.commit()
    assert agent_client.post(url, json={"model": alias, "messages": []}).status_code == 403
    # Dropped at the end of a run.
    alias = _alias(agent_client)
    with agent_client.S() as db:
        llm_conn.drop_alias(db, alias)
    assert agent_client.post(url, json={"model": alias, "messages": []}).status_code == 403
    assert seen == []
    # The shared token, when configured.
    agent_client.settings.llm_proxy_token = "proxy-token"
    alias = _alias(agent_client)
    assert agent_client.post(url, json={"model": alias, "messages": []}).status_code == 403
    assert agent_client.post(url, headers={"Authorization": "Bearer proxy-token"},
                             json={"model": alias, "messages": []}).status_code == 200
    assert agent_client.get("/llm/v1/models").status_code == 403
    r = agent_client.get("/llm/v1/models", headers={"Authorization": "Bearer proxy-token"})
    assert r.json() == {"object": "list", "data": []}
    # Redirects are not followed.
    replies.append(httpx.Response(302, headers={"location": "https://evil.example/"}))
    r = agent_client.post(url, headers={"Authorization": "Bearer proxy-token"},
                          json={"model": alias, "messages": []})
    assert r.status_code == 502 and len(seen) == 2


# --- the agent run, cost log and secret scan --------------------------------------


def test_hermes_agent_sends_alias_and_logs_real_model():
    s = _settings()
    S = make_session("sqlite:///:memory:")
    with S() as db:
        p = AwakProject(slug="demo")
        llm_conn.set_level(s, p, "https://p.example/v1", "proj-model", KEY)
        db.add(p)
        db.commit()
    sent: list[dict] = []

    def hermes(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        sent.append(body)
        with S() as db:  # the alias is live during the run
            assert llm_conn.lookup_alias(db, body["model"]) is not None
        return httpx.Response(200, json={"choices": [{"message": {"content": "done"}}],
                                         "usage": {"prompt_tokens": 5, "completion_tokens": 2}})

    agent = HermesAgent(s, S, transport=httpx.MockTransport(hermes))
    text_, _ = agent.run("awak.code", "role-model", "sys", "task", slug="demo", role_id=None)
    assert text_ == "done"
    assert sent[0]["model"].startswith("awak-run-")
    with S() as db:
        assert db.query(AwakLlmAlias).count() == 0
        call = db.query(AiCall).one()
        assert (call.model, call.llm_source) == ("proj-model", "project")
        assert KEY not in call.prompt and KEY not in call.response


def test_worker_scans_for_stored_keys():
    s = _settings()
    S = make_session("sqlite:///:memory:")
    w = Worker(s, S, None, None, None, None, secret_values=["env-secret"])
    assert w.secret_values == ["env-secret"]
    with S() as db:
        p = AwakProject(slug="demo")
        llm_conn.set_level(s, p, "https://p.example/v1", "m", KEY)
        db.add(p)
        db.commit()
    assert w.secret_values == ["env-secret", KEY]


# --- migration ------------------------------------------------------------------

OLD = [
    """CREATE TABLE awak_projects (slug VARCHAR(200) NOT NULL PRIMARY KEY,
       enabled BOOLEAN NOT NULL, merge_mode VARCHAR(10) NOT NULL, deploy_command TEXT NOT NULL,
       executor VARCHAR(10) NOT NULL, ssh_host VARCHAR(255) NOT NULL, ssh_port INTEGER NOT NULL,
       ssh_user VARCHAR(64) NOT NULL, ssh_key_id INTEGER, preflight JSON NOT NULL,
       updated_by VARCHAR(200) NOT NULL, updated_at DATETIME NOT NULL)""",
    """CREATE TABLE awak_roles (id INTEGER NOT NULL PRIMARY KEY,
       project_slug VARCHAR(200) NOT NULL, template VARCHAR(20) NOT NULL,
       name VARCHAR(100) NOT NULL, area VARCHAR(20) NOT NULL, model VARCHAR(100) NOT NULL,
       repo_ids JSON NOT NULL, allowed_paths JSON NOT NULL, denied_paths JSON NOT NULL,
       prompt_overlay TEXT NOT NULL, enabled BOOLEAN NOT NULL, version INTEGER NOT NULL,
       updated_by VARCHAR(200) NOT NULL, updated_at DATETIME NOT NULL)""",
    """CREATE TABLE ai_calls (id INTEGER NOT NULL PRIMARY KEY, at DATETIME NOT NULL,
       purpose VARCHAR(50) NOT NULL, model VARCHAR(100) NOT NULL, prompt TEXT NOT NULL,
       response TEXT NOT NULL, prompt_tokens INTEGER NOT NULL,
       completion_tokens INTEGER NOT NULL, latency_ms INTEGER NOT NULL,
       cost_idr FLOAT NOT NULL, ok BOOLEAN NOT NULL)""",
    "INSERT INTO awak_projects VALUES ('demo', 1, 'approve', '', 'local', '', 22, '', NULL,"
    " '{}', 'pm', '2026-11-14 10:00:00')",
    "INSERT INTO awak_roles VALUES (1, 'demo', 'frontend', 'F', 'web', 'deepseek-flash',"
    " '[]', '[]', '[]', '', 1, 1, 'pm', '2026-11-14 10:00:00')",
    "INSERT INTO ai_calls VALUES (1, '2026-11-14 10:00:00', 'awak.code', 'm', 'p', 'r',"
    " 1, 1, 1, 0.0, 1)",
]


def test_migrate_adds_llm_columns(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'old.db'}"
    engine = create_engine(db_url)
    with engine.begin() as c:
        for stmt in OLD:
            c.execute(text(stmt))
    init_db(engine)
    init_db(engine)  # idempotent
    cols = {t: {c["name"] for c in inspect(engine).get_columns(t)}
            for t in ("awak_projects", "awak_roles", "ai_calls")}
    llm = {"llm_base_url", "llm_model", "llm_api_key_enc", "llm_key_last4"}
    assert llm <= cols["awak_projects"] and llm <= cols["awak_roles"]
    assert "llm_source" in cols["ai_calls"]
    assert "awak_llm_aliases" in inspect(engine).get_table_names()
    S = make_session(db_url)
    s = _settings()
    with S() as db:
        assert db.get(AwakProject, "demo").llm_base_url == ""
        assert db.get(AiCall, 1).llm_source == ""
        c = llm_conn.resolve(db, s, "demo", 1)
        assert (c.source, c.model) == ("server", "deepseek-flash")


def test_proxy_maps_non_alias_model_to_the_single_active_run(agent_client, upstream):
    """Hermes may send its configured default model, not the run alias."""
    seen, replies = upstream
    agent_client.settings.ai_base_url = "https://server.example/v1"
    url = "/llm/v1/chat/completions"
    first = _alias(agent_client)
    r = agent_client.post(url, json={"model": "deepseek-flash", "messages": []})
    assert r.status_code == 200 and len(seen) == 1
    # A new run replaces a leftover alias, so the fallback is never ambiguous.
    second = _alias(agent_client)
    with agent_client.S() as db:
        assert llm_conn.lookup_alias(db, first) is None
        assert llm_conn.active_alias(db).alias == second
    assert agent_client.post(url, json={"model": "deepseek-flash", "messages": []}
                             ).status_code == 200
    with agent_client.S() as db:
        llm_conn.drop_alias(db, second)
    assert agent_client.post(url, json={"model": "deepseek-flash", "messages": []}
                             ).status_code == 403
