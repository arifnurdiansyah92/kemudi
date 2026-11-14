"""Release security fixes: the model proxy token, production secrets, AI call
logging and retention, contract deletion, encrypted deploy commands and the
audit trail."""

import csv
import io
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from kemudi_ai import __main__ as cli
from kemudi_ai import auth, retention, store
from kemudi_ai.api import _sessions, app, get_llm, get_sessions
from kemudi_ai.audit import mirror_decision, parse_actor, record_audit, scrub
from kemudi_ai.awak import llm_conn, llm_proxy
from kemudi_ai.config import (
    InsecureConfig,
    Settings,
    check_production,
    get_settings,
    is_placeholder,
    production_problems,
)
from kemudi_ai.store import (
    AiCall,
    AuditEvent,
    AwakProject,
    BacktestRun,
    BaselineVersion,
    Contract,
    Decision,
    ai_project,
    init_db,
    make_session,
    record_ai_call,
)

from .conftest import ADMIN, MEMBER, SECRET_KEY
from .test_api import upload
from .test_api import client  # noqa: F401 - fixture
from .test_merge import make as make_worker
from .test_merge import remote, repo  # noqa: F401 - fixtures
from .test_merge import request as request_merge

PROXY = {"Authorization": "Bearer the-proxy-token"}
URL = "/llm/v1/chat/completions"


# --- 1. the model proxy ------------------------------------------------------------


@pytest.fixture
def upstream(agent_client):
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"choices": [{"message": {"content": "hi"}}]})

    app.dependency_overrides[llm_proxy.get_upstream_transport] = (
        lambda: httpx.MockTransport(handler))
    agent_client.settings.ai_base_url = "https://server.example/v1"
    return seen


def _alias(client) -> str:
    with client.S() as db:
        return llm_conn.register_alias(db, client.settings, "demo", None, "fb", "awak.code")


def test_proxy_is_closed_without_a_token(agent_client, upstream):
    agent_client.settings.llm_proxy_token = ""
    alias = _alias(agent_client)
    # A live alias alone no longer admits a request, nor the active-run fallback.
    assert agent_client.post(URL, json={"model": alias, "messages": []}).status_code == 503
    assert agent_client.post(URL, json={"model": "deepseek-flash", "messages": []}
                             ).status_code == 503
    assert agent_client.post(URL, headers={"Authorization": "Bearer "},
                             json={"model": alias, "messages": []}).status_code == 503
    assert agent_client.get("/llm/v1/models").status_code == 503
    agent_client.settings.llm_proxy_token = "   "
    assert agent_client.post(URL, json={"model": alias, "messages": []}).status_code == 503
    assert upstream == []


def test_proxy_active_alias_fallback_needs_the_token(agent_client, upstream):
    agent_client.settings.llm_proxy_token = "the-proxy-token"
    _alias(agent_client)
    body = {"model": "deepseek-flash", "messages": []}
    assert agent_client.post(URL, json=body).status_code == 403
    assert agent_client.post(URL, headers={"Authorization": "Bearer wrong"},
                             json=body).status_code == 403
    assert agent_client.post(URL, headers={"Authorization": "Bearer the-proxy-token-x"},
                             json=body).status_code == 403
    assert upstream == []
    r = agent_client.post(URL, headers=PROXY, json=body)
    assert r.status_code == 200 and len(upstream) == 1


# --- 2. production secrets ---------------------------------------------------------


@pytest.mark.parametrize("value", ["", "  ", "unset", "change-me-local-dev-only", "CHANGEME",
                                   "replace-me", "<token>", "secret"])
def test_placeholders(value):
    assert is_placeholder(value)


def test_production_refuses_missing_or_placeholder_secrets():
    good = {"secret_key": SECRET_KEY, "llm_proxy_token": "a" * 64}
    assert production_problems(Settings(env="dev")) == []  # dev stays permissive
    check_production(Settings(env="dev"))
    assert production_problems(Settings(env="production", **good)) == []
    check_production(Settings(env="production", **good))
    for field, bad in [("secret_key", ""), ("secret_key", "change-me"),
                       ("secret_key", "not-a-fernet-key"), ("llm_proxy_token", ""),
                       ("llm_proxy_token", "unset"), ("llm_proxy_token", "change-me-now")]:
        s = Settings(env="production", **{**good, field: bad})
        problems = production_problems(s)
        assert len(problems) == 1, (field, bad)
        assert ("KEMUDI_SECRET_KEY" if field == "secret_key" else "KEMUDI_LLM_PROXY_TOKEN"
                ) in problems[0]
        with pytest.raises(InsecureConfig, match="KEMUDI_ENV=production"):
            check_production(s)
    assert len(production_problems(Settings(env="PRODUCTION"))) == 2


@pytest.fixture
def prod_env(monkeypatch):
    monkeypatch.setenv("KEMUDI_ENV", "production")
    monkeypatch.setenv("KEMUDI_SECRET_KEY", "")
    monkeypatch.setenv("KEMUDI_LLM_PROXY_TOKEN", "unset")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_api_and_cli_refuse_to_start_in_production(prod_env, capsys):
    S = make_session("sqlite:///:memory:")
    app.dependency_overrides[get_sessions] = lambda: S
    try:
        with pytest.raises(InsecureConfig):
            with TestClient(app):
                pass
    finally:
        app.dependency_overrides.clear()
        _sessions.cache_clear()
    assert cli.main(["awak-tick"]) == 2
    err = capsys.readouterr().err
    assert "KEMUDI_SECRET_KEY" in err and "KEMUDI_LLM_PROXY_TOKEN" in err


# --- 3. AI call logging, retention, contract deletion ----------------------------


def test_ai_calls_keep_hashes_not_text_by_default():
    assert Settings().ai_log_prompts is False and Settings().ai_log_retention_days == 90
    S = make_session("sqlite:///:memory:")
    with S() as db:
        row = record_ai_call(db, log_prompts=False, purpose="baseline", model="m",
                             prompt="PASAL 1 confidential", response="{}", prompt_tokens=7)
        assert (row.prompt, row.response) == ("", "")
        assert row.prompt_sha256 == store.sha256_text("PASAL 1 confidential")
        assert row.response_sha256 == store.sha256_text("{}")
        assert (row.prompt_tokens, row.model) == (7, "m")
        kept = record_ai_call(db, log_prompts=True, purpose="baseline", model="m",
                              prompt="visible", response="r")
        assert (kept.prompt, kept.response) == ("visible", "r") and kept.prompt_sha256
        # The project comes from the context.
        with ai_project("demo"):
            tagged = record_ai_call(db, log_prompts=False, purpose="classify", model="m",
                                    prompt="p")
        assert tagged.project_slug == "demo"
        assert record_ai_call(db, log_prompts=False, purpose="x", model="m",
                              prompt="p").project_slug == ""


def test_hermes_llm_follows_the_setting():
    from .test_llm import make

    llm, S, _ = make(['{"ok": true}'])
    llm.json("classify", "sys", "secret contract clause")
    llm, S2, _ = make(['{"ok": true}'])
    llm.settings.ai_log_prompts = True
    llm.json("classify", "sys", "visible clause")
    with S() as s:
        row = s.query(AiCall).one()
        assert row.prompt == "" and row.response == "" and len(row.prompt_sha256) == 64
    with S2() as s:
        assert "visible clause" in s.query(AiCall).one().prompt


def test_purge_deletes_old_rows_and_scrubs_text():
    S = make_session("sqlite:///:memory:")
    now = datetime.now(UTC)
    with S() as db:
        db.add_all([
            AiCall(purpose="baseline", model="m", prompt="old", at=now - timedelta(days=91)),
            AiCall(purpose="baseline", model="m", prompt="recent text", response="resp",
                   at=now - timedelta(days=5)),
        ])
        db.commit()
        assert retention.purge_ai_calls(db, 90, log_prompts=True) == {"deleted": 1,
                                                                      "scrubbed": 0}
        assert db.query(AiCall).one().prompt == "recent text"
        assert retention.purge_ai_calls(db, 0, log_prompts=False) == {"deleted": 0,
                                                                      "scrubbed": 1}
        row = db.query(AiCall).one()
        assert (row.prompt, row.response) == ("", "")
        assert row.prompt_sha256 == store.sha256_text("recent text")
        assert row.response_sha256 == store.sha256_text("resp")


def test_purge_runs_at_startup():
    S = make_session("sqlite:///:memory:")
    with S() as db:
        db.add(AiCall(purpose="baseline", model="m", prompt="x",
                      at=datetime.now(UTC) - timedelta(days=400)))
        db.commit()
    app.dependency_overrides[get_sessions] = lambda: S
    try:
        with TestClient(app):
            with S() as db:
                assert db.query(AiCall).count() == 0
    finally:
        app.dependency_overrides.clear()
        _sessions.cache_clear()


class RecordingLLM:
    """Records an ai_calls row per call, like HermesLLM, with a fixed reply."""

    def __init__(self, S, replies):
        self.S, self.replies = S, replies

    def json(self, purpose, system, user):
        with self.S() as db:
            record_ai_call(db, log_prompts=False, purpose=purpose, model="m", prompt=user)
        return self.replies[purpose]


def test_contract_delete(client):  # noqa: F811
    assert client.delete("/projects/demo/contract", headers=ADMIN).status_code == 404
    app.dependency_overrides[get_llm] = lambda: RecordingLLM(client.S, {
        "baseline": {"items": [{"kind": "epic", "title": "Payment", "clauses": ["S1"]}]},
        "classify": {"label": "cr_candidate", "reason": "baru",
                     "effort_days": {"backend": 1}}})
    assert upload(client).status_code == 200
    assert client.post("/projects/demo/baseline/draft", headers=ADMIN).status_code == 200
    assert client.post("/projects/demo/baseline/approve", headers=ADMIN).status_code == 200
    dataset = b'{"tickets": [{"id": "T1", "text": "tambah", "expected": {"label": "cr_candidate"}}]}'
    r = client.post("/projects/demo/backtests", headers=ADMIN,
                    files={"dataset": ("d.json", dataset, "application/json")})
    assert r.status_code == 200
    with client.S() as db:
        assert {c.purpose for c in db.query(AiCall).filter_by(project_slug="demo")} == {
            "baseline", "classify"}
        db.add_all([AiCall(purpose="awak.code", model="m", prompt="", project_slug="demo"),
                    AiCall(purpose="baseline", model="m", prompt="", project_slug="other")])
        db.commit()

    assert client.delete("/projects/demo/contract", headers=MEMBER).status_code == 403
    r = client.delete("/projects/demo/contract", headers=ADMIN)
    assert r.status_code == 200, r.text
    deleted = r.json()["deleted"]
    assert deleted["contracts"] == 1 and deleted["baseline_versions"] == 1
    assert deleted["backtest_runs"] == 1 and deleted["backtest_results"] == 1
    assert deleted["ai_calls"] == 2
    with client.S() as db:
        assert db.query(Contract).count() == 0 and db.query(BaselineVersion).count() == 0
        assert db.query(BacktestRun).count() == 0
        assert sorted((c.project_slug, c.purpose) for c in db.query(AiCall)) == [
            ("demo", "awak.code"), ("other", "baseline")]
        assert db.query(Decision).filter_by(action="delete_contract").count() == 1
        ev = db.query(AuditEvent).filter_by(action="delete_contract").one()
        assert (ev.project_slug, ev.actor_id, ev.actor_username) == ("demo", 1, "pm")
    body = client.get("/projects/demo/contract", headers=MEMBER).json()
    assert body["contract"] is None


# --- 4. deploy command encrypted at rest --------------------------------------------


@pytest.fixture
def field_key(monkeypatch):
    monkeypatch.setattr(store, "_field_settings", lambda: Settings(secret_key=SECRET_KEY))


def _raw_deploy(S, slug="demo") -> str:
    with S() as db:
        return db.execute(text("SELECT deploy_command FROM awak_projects WHERE slug = :s"),
                          {"s": slug}).scalar_one()


def test_deploy_command_encrypted_through_the_api(agent_client, field_key):
    settings = {"enabled": False, "merge_mode": "approve", "deploy_command":
                "TOKEN=abc123secret make deploy", "executor": "local", "ssh_host": "",
                "ssh_port": 22, "ssh_user": ""}
    r = agent_client.put("/projects/demo/agent/settings", headers=ADMIN, json=settings)
    assert r.status_code == 200, r.text
    raw = _raw_deploy(agent_client.S)
    assert raw.startswith("enc:v1:") and "abc123secret" not in raw
    r = agent_client.get("/projects/demo/agent/settings", headers=ADMIN)
    assert r.json()["deploy_command"] == "TOKEN=abc123secret make deploy"
    with agent_client.S() as db:
        assert db.get(AwakProject, "demo").deploy_command == "TOKEN=abc123secret make deploy"


def test_deploy_command_migration_and_bad_key(tmp_path, field_key, monkeypatch):
    url = f"sqlite:///{tmp_path / 'k.db'}"
    S = make_session(url)
    with S() as db:  # rows written before the encryption: plain text
        db.execute(text(
            "INSERT INTO awak_projects (slug, enabled, merge_mode, qa_mode, deploy_command, "
            "executor, ssh_host, ssh_port, ssh_user, preflight, llm_base_url, llm_model, "
            "llm_api_key_enc, llm_key_last4, last_error, updated_by, updated_at) VALUES "
            "('p', 0, 'approve', 'gates', 'make deploy KEY=s3cr3t', 'local', '', 22, '', "
            "'{}', '', '', '', '', '', '', '2026-11-13 10:00:00')"))
        db.commit()
    assert _raw_deploy(S, "p") == "make deploy KEY=s3cr3t"
    init_db(create_engine(url))
    raw = _raw_deploy(S, "p")
    assert raw.startswith("enc:v1:") and "s3cr3t" not in raw
    init_db(create_engine(url))  # idempotent: not encrypted twice
    assert _raw_deploy(S, "p") == raw
    with S() as db:
        assert db.get(AwakProject, "p").deploy_command == "make deploy KEY=s3cr3t"
    # Another key: the row still loads, the command reads as empty.
    from cryptography.fernet import Fernet

    other = Fernet.generate_key().decode()
    monkeypatch.setattr(store, "_field_settings", lambda: Settings(secret_key=other))
    S2 = make_session(url)
    with S2() as db:
        assert db.get(AwakProject, "p").deploy_command == ""


def test_deploy_command_plain_without_a_key(monkeypatch):
    monkeypatch.setattr(store, "_field_settings", lambda: Settings(secret_key=""))
    assert store.encrypt_field("make deploy") == "make deploy"
    assert store.decrypt_field("make deploy") == "make deploy"


# --- 5. audit trail -----------------------------------------------------------------


def test_scrub_and_actor():
    out = scrub({"name": "DB_PASS", "value": "hunter2", "secret": True,
                 "changed": {"deploy_command": "(changed)", "api_key": "sk-x"},
                 "list": [{"token": "t"}]})
    assert out == {"name": "DB_PASS", "value": "(redacted)", "secret": True,
                   "changed": {"deploy_command": "(changed)", "api_key": "(redacted)"},
                   "list": [{"token": "(redacted)"}]}
    assert parse_actor("pm (1)") == (1, "pm")
    assert parse_actor("migration") == (None, "migration")
    S = make_session("sqlite:///:memory:")
    with S() as db:
        d = Decision(actor="pm (1)", action="verdict", subject="demo", detail={})
        assert mirror_decision(db, d) is None  # not an audited action
        row = record_audit(db, actor_id=None, actor_username="x", project="demo",
                           action="awak_env", detail={"value": "plain"})
        assert row.detail == {"value": "(redacted)"}


def _events(client, slug="demo", **params):
    r = client.get(f"/projects/{slug}/audit", headers=ADMIN, params=params)
    assert r.status_code == 200, r.text
    return r.json()["events"]


def test_audit_trail_records_admin_changes(agent_client):
    c = agent_client
    base = {"enabled": False, "merge_mode": "approve", "deploy_command": "", "executor": "ssh",
            "ssh_host": "vps.example.com", "ssh_port": 22, "ssh_user": "deploy"}
    assert c.put("/projects/demo/agent/settings", headers=ADMIN, json=base).status_code == 200
    r = c.put("/projects/demo/agent/settings", headers=ADMIN,
              json={**base, "merge_mode": "manual", "qa_mode": "off",
                    "deploy_command": "make deploy TOKEN=zzz-top-secret"})
    assert r.status_code == 200, r.text
    assert c.put("/projects/demo/agent/env/DB_PASSWORD", headers=ADMIN,
                 json={"value": "hunter2-very-secret", "secret": True}).status_code == 200
    assert c.delete("/projects/demo/agent/env/DB_PASSWORD", headers=ADMIN).status_code == 204
    assert c.post("/projects/demo/agent/machine/key", headers=ADMIN).status_code == 200
    r = c.put("/projects/demo/agent/llm", headers=ADMIN,
              json={"base_url": "http://8.8.8.8/v1", "model": "m", "api_key": "sk-llm-key-123456",
                    "allow_insecure_http": True})
    assert r.status_code == 200, r.text

    events = _events(c)
    actions = [e["action"] for e in reversed(events)]
    assert actions.count("awak_settings") == 2
    for a in ("awak_env", "awak_machine_key", "awak_llm"):
        assert a in actions
    assert all(e["actor_id"] == 1 and e["actor_username"] == "pm" for e in events)
    changed = next(e for e in events if e["action"] == "awak_settings")["detail"]["changed"]
    assert changed["merge_mode"] == "manual" and changed["qa_mode"] == "off"
    assert changed["deploy_command"] == "(changed)"
    llm = next(e for e in events if e["action"] == "awak_llm")["detail"]
    assert llm["insecure_http"] is True and llm["key_changed"] is True
    env_ops = [e["detail"]["op"] for e in events if e["action"] == "awak_env"]
    assert sorted(env_ops) == ["delete", "set"]
    dump = str(events)
    for secret in ("hunter2-very-secret", "sk-llm-key-123456", "zzz-top-secret"):
        assert secret not in dump
    # Filter and CSV export.
    assert {e["action"] for e in _events(c, action="awak_env")} == {"awak_env"}
    r = c.get("/projects/demo/audit", headers=ADMIN, params={"format": "csv"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0] == ["id", "ts", "actor_id", "actor_username", "project", "action", "detail"]
    assert len(rows) == len(events) + 1
    assert "hunter2-very-secret" not in r.text
    # Project admins only; other projects see nothing of it.
    assert c.get("/projects/demo/audit", headers=MEMBER).status_code == 403
    assert c.get("/projects/demo/audit").status_code == 401
    assert _events(c, slug="other") == []
    # Append-only: decisions are mirrored, nothing else.
    with c.S() as db:
        assert db.query(AuditEvent).count() == len(events)


def test_audit_csv_neutralises_formulas(agent_client):
    with agent_client.S() as db:
        record_audit(db, actor_id=1, actor_username="=HYPERLINK(1)", project="demo",
                     action="awak_repo", detail={"repo": "x"})
    r = agent_client.get("/projects/demo/audit", headers=ADMIN, params={"format": "csv"})
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[1][3] == "'=HYPERLINK(1)"


def test_instance_audit_for_skills(agent_client):
    with agent_client.S() as db:
        store.record_decision(db, "pm (1)", "awak_skill", "my-skill",
                              {"op": "enable", "version": 2})
    agent_client.settings.admin_user_ids = "1"
    r = agent_client.get("/audit", headers=ADMIN)
    assert r.status_code == 200, r.text
    (ev,) = r.json()["events"]
    assert ev["project"] == "" and ev["action"] == "awak_skill"
    assert ev["detail"] == {"skill": "my-skill", "op": "enable", "version": 2}
    assert agent_client.get("/audit", headers=MEMBER).status_code == 403


def test_merge_and_deploy_are_audited(tmp_path, repo, remote):  # noqa: F811
    from .awak_fakes import FakeRunner

    runner = FakeRunner(tmp_path / "ws", qa=["pass"],
                        deploy=[{"ok": True, "exit": 0, "output": "up"}])
    w, _, sessions, _ = make_worker(tmp_path, repo, runner=runner, deploy_command="make deploy")
    w.tick()
    request_merge(sessions)
    w.tick()
    with sessions() as db:
        events = db.query(AuditEvent).order_by(AuditEvent.id).all()
    assert [e.action for e in events] == ["awak_merged", "awak_deploy"]
    merged, deploy = events
    assert merged.project_slug == "kemudi" and merged.actor_username == "awak"
    assert merged.detail["story_ref"] == 12 and len(merged.detail["sha"]) == 40
    assert deploy.detail["ok"] is True and "make deploy" not in str(deploy.detail)
