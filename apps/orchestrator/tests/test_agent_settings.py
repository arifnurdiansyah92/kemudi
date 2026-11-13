import pytest
from sqlalchemy import create_engine, inspect, text

from kemudi_ai.awak import config_store, crypto
from kemudi_ai.awak.crypto import SecretKeyMissing
from kemudi_ai.config import Settings
from kemudi_ai.store import AwakJob, AwakProject, AwakRepo, AwakRole, Decision, init_db, make_session

from .conftest import ADMIN, MEMBER, SECRET_KEY

SETTINGS = {"enabled": True, "merge_mode": "approve", "deploy_command": "make deploy",
            "executor": "local", "ssh_host": "", "ssh_port": 22, "ssh_user": ""}


def test_crypto_roundtrip_and_missing_key():
    s = Settings(secret_key=SECRET_KEY)
    private, public, fp = crypto.generate_keypair()
    assert "OPENSSH PRIVATE KEY" in private
    assert public.startswith("ssh-ed25519 ")
    assert fp.startswith("SHA256:") and fp == crypto.fingerprint(public)
    token = crypto.encrypt(s, private)
    assert crypto.decrypt(s, token) == private
    assert private not in token and "PRIVATE KEY" not in token
    with pytest.raises(SecretKeyMissing):
        crypto.fernet(Settings(secret_key=""))
    with pytest.raises(SecretKeyMissing):
        crypto.fernet(Settings(secret_key="not-a-fernet-key"))


OLD_JOBS = """CREATE TABLE awak_jobs (
    id INTEGER NOT NULL PRIMARY KEY, project_slug VARCHAR(200) NOT NULL,
    story_id INTEGER NOT NULL, story_ref INTEGER NOT NULL, branch VARCHAR(100) NOT NULL,
    state VARCHAR(20) NOT NULL, phase VARCHAR(20) NOT NULL, attempts INTEGER NOT NULL,
    infra_errors INTEGER NOT NULL, feedback TEXT NOT NULL, last_sha VARCHAR(64) NOT NULL,
    cost_idr FLOAT NOT NULL, started_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"""


def test_migrate_adds_job_columns(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as c:
        c.execute(text(OLD_JOBS))
        c.execute(text(
            "INSERT INTO awak_jobs VALUES (1, 'kemudi', 5, 12, 'awak/us-12', 'passed', '', 2, 0,"
            " '', 'abc', 10.0, '2026-11-13 10:00:00', '2026-11-13 10:00:00')"))
    init_db(engine)
    cols = {c["name"] for c in inspect(engine).get_columns("awak_jobs")}
    assert {"repo_id", "role_id", "prompt_version", "merge_mode", "merge_state",
            "merged_sha", "merge_error", "repo_url", "repo_branch"} <= cols
    init_db(engine)  # idempotent
    S = make_session(f"sqlite:///{tmp_path / 'old.db'}")
    with S() as db:
        job = db.get(AwakJob, 1)
        assert (job.state, job.attempts, job.last_sha) == ("passed", 2, "abc")
        assert job.merge_state == "" and job.repo_id is None
        db.add(AwakJob(project_slug="kemudi", story_id=6, story_ref=13, branch="awak/us-13"))
        db.commit()


def test_settings_defaults_to_approve_and_disabled(agent_client):
    r = agent_client.get("/projects/demo/agent/settings", headers=MEMBER)
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False and body["merge_mode"] == "approve"
    assert body["executor"] == "local" and body["remote_execution"] is False
    assert body["ssh_public_key"] is None and body["ssh_fingerprint"] is None
    assert body["deploy_command"] is None and body["deploy_command_set"] is False
    with agent_client.S() as db:
        assert db.query(AwakProject).count() == 0


def test_member_reads_admin_writes(agent_client):
    url = "/projects/demo/agent/settings"
    assert agent_client.put(url, headers=MEMBER, json=SETTINGS).status_code == 403
    r = agent_client.put(url, headers=ADMIN, json=SETTINGS)
    assert r.status_code == 200
    assert r.json()["enabled"] is True and r.json()["updated_by"] == "pm (1)"
    # the deploy command may hold a token: admins see it, members only that it is set
    member_view = agent_client.get(url, headers=MEMBER).json()
    assert member_view["deploy_command"] is None and member_view["deploy_command_set"] is True
    admin_view = agent_client.get(url, headers=ADMIN).json()
    assert admin_view["deploy_command"] == "make deploy" and admin_view["deploy_command_set"]
    assert r.json()["deploy_command"] == "make deploy"
    with agent_client.S() as db:
        d = db.query(Decision).filter_by(action="awak_settings").one()
        assert d.subject == "demo"
        assert set(d.detail["changed"]) == {"enabled", "deploy_command"}
        assert "make deploy" not in str(d.detail)
    assert agent_client.started == [True]  # enabling starts the worker if needed
    # nothing changed -> no new decision
    agent_client.put(url, headers=ADMIN, json=SETTINGS)
    with agent_client.S() as db:
        assert db.query(Decision).filter_by(action="awak_settings").count() == 1


def test_ssh_executor_needs_host_and_user(agent_client):
    url = "/projects/demo/agent/settings"
    body = {**SETTINGS, "executor": "ssh", "ssh_host": "", "ssh_user": "deploy"}
    assert agent_client.put(url, headers=ADMIN, json=body).status_code == 422
    body = {**SETTINGS, "executor": "ssh", "ssh_host": "vps.example.com", "ssh_user": ""}
    assert agent_client.put(url, headers=ADMIN, json=body).status_code == 422
    body = {**SETTINGS, "executor": "ssh", "ssh_host": "vps.example.com", "ssh_user": "deploy"}
    assert agent_client.put(url, headers=ADMIN, json=body).status_code == 200


def test_jobs_endpoint_lists_latest(agent_client):
    with agent_client.S() as db:
        db.add(AwakJob(project_slug="demo", story_id=5, story_ref=12, branch="awak/us-12",
                       state="passed", feedback="secret-ish feedback"))
        db.commit()
    jobs = agent_client.get("/projects/demo/agent/jobs", headers=MEMBER).json()["jobs"]
    assert jobs[0]["story_ref"] == 12 and jobs[0]["merge_state"] == ""
    assert "feedback" not in jobs[0]


def test_seed_from_env_is_manual_and_idempotent(tmp_path):
    settings = Settings(awak_projects="kemudi", host_git="/host-git")
    S = make_session("sqlite:///:memory:")
    with S() as db:
        config_store.seed_from_env(db, settings)
        config_store.seed_from_env(db, settings)
        assert db.query(AwakProject).count() == 1
        p = db.get(AwakProject, "kemudi")
        assert p.enabled and p.merge_mode == "manual"
        repos = db.query(AwakRepo).all()
        assert [(r.name, r.url, r.default_branch, r.subdir) for r in repos] == [
            ("kemudi", "/host-git", "main", "apps/web")]
        roles = {r.template: r for r in db.query(AwakRole)}
        assert set(roles) == {"frontend", "backend", "qa"}
        assert not roles["backend"].enabled
        assert "services/kemudi-back/" in roles["frontend"].denied_paths
        assert roles["frontend"].repo_ids == [repos[0].id]
        assert config_store.enabled_slugs(db) == ["kemudi"]
        cfg = config_store.load(db, "kemudi")
        assert cfg.merge_mode == "manual" and cfg.repos[0].url == "/host-git"
