"""Per-project env vault: encryption, redaction variants, API, worker use."""

import base64
import secrets as pysecrets
from urllib.parse import quote, quote_plus

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import inspect

from kemudi_ai.awak import secrets, vault
from kemudi_ai.awak.crypto import SecretKeyMissing
from kemudi_ai.config import Settings
from kemudi_ai.store import AwakEnvVar, AwakJob, Decision, make_session

from .awak_fakes import FakeAgent, FakeRunner, FakeTaiga, commit_file
from .conftest import ADMIN, MEMBER, SECRET_KEY
from .test_awak import DESC, host, repo  # noqa: F401 (fixtures)


def made_value() -> str:
    """A credential-shaped test value, made at run time."""
    return "v" + pysecrets.token_urlsafe(18)


def _db():
    return make_session("sqlite:///:memory:")


S = Settings(secret_key=SECRET_KEY)


# --- storage -----------------------------------------------------------------


def test_values_are_encrypted_with_a_key_derived_for_the_vault():
    sessions = _db()
    value = made_value()
    with sessions() as db:
        vault.put(db, S, "demo", "JWT_SECRET_KEY", value, True, "pm")
        row = db.query(AwakEnvVar).one()
        assert value not in row.value_enc
        # not the plain KEMUDI_SECRET_KEY: the SSH-key Fernet cannot read it
        with pytest.raises(Exception):
            Fernet(SECRET_KEY.encode()).decrypt(row.value_enc.encode())
        assert vault.values(db, S, "demo") == {"JWT_SECRET_KEY": value}
        assert vault.values(db, S, "other") == {}
        # derived the same way on every start (HKDF, info "awak-vault")
        assert vault.fernet(Settings(secret_key=SECRET_KEY)).decrypt(
            row.value_enc.encode()).decode() == value


def test_vault_needs_the_secret_key():
    with _db()() as db, pytest.raises(SecretKeyMissing):
        vault.put(db, Settings(secret_key=""), "demo", "API_URL", "http://x", False, "pm")


def test_put_replaces_and_delete_removes():
    sessions = _db()
    with sessions() as db:
        assert vault.put(db, S, "demo", "API_URL", "http://a", False, "pm") is True
        assert vault.put(db, S, "demo", "API_URL", "http://b", False, "dev") is False
        assert vault.values(db, S, "demo") == {"API_URL": "http://b"}
        assert db.query(AwakEnvVar).one().updated_by == "dev"
        assert vault.delete(db, "demo", "API_URL") is True
        assert vault.delete(db, "demo", "API_URL") is False
        assert vault.values(db, S, "demo") == {}


def test_table_is_unique_per_project_and_name():
    sessions = _db()
    with sessions() as db:
        uniques = inspect(db.get_bind()).get_unique_constraints("awak_env_vars")
        assert any(set(u["column_names"]) == {"project_slug", "name"} for u in uniques)


@pytest.mark.parametrize("name, ok", [
    ("JWT_SECRET_KEY", True), ("_X", True), ("A" * 64, True), ("A" * 65, False),
    ("lower", False), ("1ABC", False), ("A-B", False), ("", False),
    ("PATH", False), ("HOME", False), ("KEMUDI_SECRET_KEY", False), ("GIT_DIR", False),
    ("DOCKER_HOST", False), ("COMPOSE_FILE", False), ("NODE_OPTIONS", False),
])
def test_names(name, ok):
    assert (vault.name_problem(name) is None) is ok


def test_redaction_values_cover_encodings_and_short_values():
    sessions = _db()
    value = made_value()
    with sessions() as db:
        vault.put(db, S, "demo", "QA_ADMIN_PASSWORD", value + "/+ x", True, "pm")
        vault.put(db, S, "demo", "PIN", "4821", True, "pm")
        vault.put(db, S, "demo", "ON", "yes", False, "pm")  # shorter than 4: kept
        red = vault.redaction_values(db, S, "demo")
        raw = value + "/+ x"
        assert raw in red and "4821" in red and "yes" not in red
        assert base64.b64encode(raw.encode()).decode() in red
        assert base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=") in red
        assert quote(raw, safe="") in red and quote_plus(raw) in red
        assert red == sorted(red, key=len, reverse=True)
        assert vault.redaction_values(db, S, "other") == []
        # what a diff is scanned for: the values themselves, 8 chars and more
        assert vault.scan_values(db, S, "demo") == [raw]


def test_redaction_values_without_a_key_are_empty():
    sessions = _db()
    with sessions() as db:
        vault.put(db, S, "demo", "PIN", "4821", True, "pm")
        assert vault.redaction_values(db, Settings(secret_key=""), "demo") == []
        other = Settings(secret_key=Fernet.generate_key().decode())
        assert vault.redaction_values(db, other, "demo") == []


# --- API ---------------------------------------------------------------------

URL = "/projects/demo/agent/env"


def test_env_api(agent_client):
    value = made_value()
    assert agent_client.get(URL, headers=MEMBER).json() == {"vars": []}
    r = agent_client.put(f"{URL}/JWT_SECRET_KEY", headers=MEMBER,
                         json={"value": value, "secret": True})
    assert r.status_code == 403
    r = agent_client.put(f"{URL}/JWT_SECRET_KEY", headers=ADMIN,
                         json={"value": value, "secret": True})
    assert r.status_code == 200, r.text
    assert value not in r.text
    agent_client.put(f"{URL}/API_URL", headers=ADMIN,
                     json={"value": "http://api:5000", "secret": False})
    body = agent_client.get(URL, headers=MEMBER).json()
    assert value not in str(body)
    by = {v["name"]: v for v in body["vars"]}
    assert by["JWT_SECRET_KEY"]["set"] is True and by["JWT_SECRET_KEY"]["value"] is None
    assert by["JWT_SECRET_KEY"]["secret"] is True
    assert by["API_URL"]["value"] == "http://api:5000" and by["API_URL"]["secret"] is False
    assert by["API_URL"]["updated_by"].startswith("pm") and by["API_URL"]["updated_at"]
    assert [v["name"] for v in body["vars"]] == ["API_URL", "JWT_SECRET_KEY"]
    with agent_client.S() as db:
        d = db.query(Decision).filter_by(action="awak_env").all()
        assert [x.detail for x in d] == [
            {"op": "set", "name": "JWT_SECRET_KEY", "secret": True, "created": True},
            {"op": "set", "name": "API_URL", "secret": False, "created": True}]
        assert value not in str([x.detail for x in d])
    assert agent_client.delete(f"{URL}/API_URL", headers=MEMBER).status_code == 403
    assert agent_client.delete(f"{URL}/API_URL", headers=ADMIN).status_code == 204
    assert agent_client.delete(f"{URL}/API_URL", headers=ADMIN).status_code == 404
    assert [v["name"] for v in agent_client.get(URL, headers=ADMIN).json()["vars"]] == [
        "JWT_SECRET_KEY"]


def test_env_api_keeps_a_secret_when_the_value_is_left_empty(agent_client):
    value = made_value()
    agent_client.put(f"{URL}/TOKEN_X", headers=ADMIN, json={"value": value, "secret": True})
    # an edit that only changes the flag keeps the stored value
    r = agent_client.put(f"{URL}/TOKEN_X", headers=ADMIN, json={"value": None, "secret": True})
    assert r.status_code == 200
    with agent_client.S() as db:
        assert vault.values(db, agent_client.settings, "demo") == {"TOKEN_X": value}
    # a secret turned plain needs its value again (it would be shown)
    r = agent_client.put(f"{URL}/TOKEN_X", headers=ADMIN, json={"value": None, "secret": False})
    assert r.status_code == 422
    # a new name needs a value
    r = agent_client.put(f"{URL}/NEW_ONE", headers=ADMIN, json={"value": None, "secret": True})
    assert r.status_code == 422


@pytest.mark.parametrize("name", ["lower", "PATH", "KEMUDI_SECRET_KEY", "A" * 65])
def test_env_api_refuses_reserved_and_bad_names(agent_client, name):
    r = agent_client.put(f"{URL}/{name}", headers=ADMIN, json={"value": "x", "secret": False})
    assert r.status_code == 422


def test_env_api_value_limits(agent_client):
    r = agent_client.put(f"{URL}/BIG", headers=ADMIN, json={"value": "x" * 8193, "secret": True})
    assert r.status_code == 422
    r = agent_client.put(f"{URL}/NUL", headers=ADMIN, json={"value": "a\x00b", "secret": True})
    assert r.status_code == 422


def test_env_api_without_secret_key(agent_client):
    agent_client.settings.secret_key = ""
    r = agent_client.put(f"{URL}/API_URL", headers=ADMIN, json={"value": "x", "secret": False})
    assert r.status_code == 503 and "KEMUDI_SECRET_KEY" in r.text


def test_env_api_lists_runbook_names_not_set_yet(agent_client):
    from .test_runbook import PLAYFAST, _repo

    _repo(agent_client)
    spec = {**PLAYFAST, "env": [{"name": "JWT_SECRET_KEY", "secret": True, "required": True,
                                 "description": "any 64-char hex"}]}
    r = agent_client.put("/projects/demo/agent/runbook", headers=ADMIN, json={"runbook": spec})
    assert r.status_code == 200, r.text
    body = agent_client.get(URL, headers=MEMBER).json()
    assert body["vars"] == [{"name": "JWT_SECRET_KEY", "secret": True, "set": False,
                             "value": None, "required": True,
                             "description": "any 64-char hex", "in_runbook": True,
                             "updated_by": "", "updated_at": None}]


# --- worker --------------------------------------------------------------------


def _worker(tmp_path, repo=None, agent=None, runner=None):
    from kemudi_ai.awak.worker import Worker

    settings = Settings(awak_projects="kemudi", ai_db_url="sqlite:///:memory:",
                        workspace_dir=str(tmp_path / "ws"), secret_key=SECRET_KEY)
    sessions = make_session(settings.ai_db_url)
    taiga = FakeTaiga()
    w = Worker(settings, sessions, taiga, FakeTaiga("awak-qa"), agent or FakeAgent(),
               runner or FakeRunner(tmp_path / "ws"), repo, secret_values=[],
               sleep=lambda s: None)
    return w, taiga, sessions, settings


def test_worker_redacts_the_project_vault_values(tmp_path):
    w, taiga, sessions, settings = _worker(tmp_path)
    value = made_value()
    encoded = base64.b64encode(value.encode()).decode()
    with sessions() as db:
        vault.put(db, settings, "kemudi", "JWT_SECRET_KEY", value, True, "pm")
        vault.put(db, settings, "other", "OTHER_PIN", "9137", True, "pm")
        db.add(AwakJob(project_slug="kemudi", story_id=1, story_ref=12, branch="awak/us-12"))
        db.commit()
        job_id = db.query(AwakJob).one().id
    taiga.add(1, 12, "Badge", "desc")
    w._say(1, job_id, f"log: {value} and {encoded}, pin 9137")
    text = taiga.texts(1)[-1]
    assert value not in text and encoded not in text and "pin 9137" in text
    w._event(job_id, "infra", {"error": f"boom {value}", "n": 1})
    assert value not in str(w._last_event(job_id, "infra"))
    assert w._last_event(job_id, "infra")["n"] == 1
    assert value in w.redact_values_for("kemudi") and "9137" not in w.redact_values_for("kemudi")
    assert value in w.scan_values_for("kemudi") and value not in w.scan_values_for("other")
    assert secrets.files_with_secrets(f"+++ b/a.ts\n+const k = '{value}'\n",
                                      w.scan_values_for("kemudi")) == ["a.ts"]


def test_vault_value_in_the_diff_is_never_pushed(tmp_path, repo):
    value = made_value()
    agent = FakeAgent(code=lambda d, n: commit_file(d, f"cfg{n}.ts", f"k='{value}'"))
    w, taiga, sessions, settings = _worker(tmp_path, repo, agent,
                                           FakeRunner(tmp_path / "ws", qa=["pass"]))
    with sessions() as db:
        vault.put(db, settings, "kemudi", "JWT_SECRET_KEY", value, True, "pm")
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    fail = next(t for t in taiga.texts(1) if "secret" in t)
    assert "cfg1.ts" in fail and value not in fail
    with sessions() as db:
        assert value not in db.query(AwakJob).one().feedback
