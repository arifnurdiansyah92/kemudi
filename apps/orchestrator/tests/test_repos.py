import json
import shlex
import subprocess
from pathlib import Path

import pytest

from kemudi_ai.awak import agent_api, crypto, ssh
from kemudi_ai.awak.detect import detect_commands
from kemudi_ai.awak.worker import Worker
from kemudi_ai.config import Settings
from kemudi_ai.store import (AwakJob, AwakKey, AwakProject, AwakRepo, AwakRole, Decision,
                             make_session)

from .awak_fakes import FakeAgent, FakeRunner, FakeTaiga, git
from .conftest import ADMIN, MEMBER
from .test_awak import DESC

SSH_REPO = {"name": "web", "role": "web", "url": "git@github.com:acme/web.git",
            "default_branch": "main"}


def add_repo(client, **over):
    r = client.post("/projects/demo/agent/repos", headers=ADMIN, json={**SSH_REPO, **over})
    assert r.status_code == 200, r.text
    return r.json()


def make_remote(tmp_path: Path, files: dict[str, str], branch="main") -> Path:
    src = tmp_path / "src"
    src.mkdir()
    git(src, "init", "-b", branch)
    git(src, "config", "user.email", "t@t")
    git(src, "config", "user.name", "t")
    for name, content in files.items():
        p = src / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    git(src, "add", "-A")
    git(src, "commit", "-m", "init")
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(src), str(remote)], check=True)
    return remote


def refs(remote: Path) -> str:
    return subprocess.run(["git", "--git-dir", str(remote), "for-each-ref"],
                          capture_output=True, text=True).stdout


# --- pure pieces ------------------------------------------------------------------

@pytest.mark.parametrize("url,local,host", [
    ("/host-git", True, ""),
    ("file:///srv/repo.git", True, ""),
    ("C:\\Users\\me\\repo.git", True, ""),
    ("C:/Users/me/repo.git", True, ""),
    ("git@github.com:acme/web.git", False, "github.com"),
    ("ssh://git@gitlab.example.com:2222/acme/web.git", False, "gitlab.example.com"),
    ("ssh://git@[::1]:22/x.git", False, "::1"),
])
def test_url_parsing(url, local, host):
    assert ssh.is_local_url(url) is local
    assert ssh.url_host(url) == host


def test_detect_commands():
    pkg = json.dumps({"scripts": {"test": "vitest", "build": "vite build", "dev": "vite"}})
    files = {"package.json": pkg, "pnpm-lock.yaml": "", "tsconfig.json": "{}"}
    d = detect_commands(files.get)
    assert d["install_cmd"].startswith("pnpm install --frozen-lockfile")
    assert "pnpm exec tsc -b" in d["check_cmd"] and "pnpm test" in d["check_cmd"]
    assert d["build_cmd"] == "pnpm build" and d["run_cmd"] == "pnpm dev"
    d = detect_commands({"pyproject.toml": "[project]"}.get)
    assert d["install_cmd"] == "uv sync" and d["check_cmd"] == "uv run pytest"
    assert detect_commands({"go.mod": "module x"}.get)["check_cmd"].startswith("go ")
    assert detect_commands({}.get) == {"install_cmd": "", "check_cmd": "", "build_cmd": "",
                                       "run_cmd": ""}


# --- endpoints --------------------------------------------------------------------

def test_key_endpoint_returns_public_only(agent_client):
    repo = add_repo(agent_client)
    assert repo["has_key"] is False and repo["local"] is False
    r = agent_client.post(f"/projects/demo/agent/repos/{repo['id']}/key", headers=ADMIN)
    assert r.status_code == 200
    assert r.json()["public_key"].startswith("ssh-ed25519 ")
    assert r.json()["fingerprint"].startswith("SHA256:")
    listing = agent_client.get("/projects/demo/agent/repos", headers=MEMBER)
    assert listing.json()["repos"][0]["has_key"] is True
    with agent_client.S() as db:
        decisions = [d.detail for d in db.query(Decision)]
        key = db.query(AwakKey).one()
        assert crypto.decrypt(agent_client.settings, key.private_key_enc).startswith(
            "-----BEGIN OPENSSH PRIVATE KEY-----")
    for text in (r.text, listing.text, json.dumps(decisions)):
        assert "PRIVATE KEY" not in text
    # regenerating replaces the old key
    agent_client.post(f"/projects/demo/agent/repos/{repo['id']}/key", headers=ADMIN)
    with agent_client.S() as db:
        assert db.query(AwakKey).count() == 1


def test_key_needs_secret_key(agent_client):
    repo = add_repo(agent_client)
    agent_client.settings.secret_key = ""
    r = agent_client.post(f"/projects/demo/agent/repos/{repo['id']}/key", headers=ADMIN)
    assert r.status_code == 503 and "KEMUDI_SECRET_KEY" in r.text


def test_key_refused_for_local_repo_and_member(agent_client):
    repo = add_repo(agent_client, url=agent_client.settings.host_git)
    assert repo["local"] is True
    url = f"/projects/demo/agent/repos/{repo['id']}/key"
    assert agent_client.post(url, headers=MEMBER).status_code == 403
    assert agent_client.post(url, headers=ADMIN).status_code == 409


def test_https_url_rejected(agent_client):
    r = agent_client.post("/projects/demo/agent/repos", headers=ADMIN,
                          json={**SSH_REPO, "url": "https://github.com/acme/web.git"})
    assert r.status_code == 422
    r = agent_client.post("/projects/demo/agent/repos", headers=ADMIN,
                          json={**SSH_REPO, "url": "git@-oProxyCommand=x:a/b.git"})
    assert r.status_code == 422


def test_subdir_dotdot_rejected(agent_client):
    for subdir in ("../x", "apps/../../etc", "/abs"):
        r = agent_client.post("/projects/demo/agent/repos", headers=ADMIN,
                              json={**SSH_REPO, "subdir": subdir})
        assert r.status_code == 422, subdir


def test_duplicate_name_and_delete_rules(agent_client):
    repo = add_repo(agent_client)
    r = agent_client.post("/projects/demo/agent/repos", headers=ADMIN, json=SSH_REPO)
    assert r.status_code == 409
    agent_client.post(f"/projects/demo/agent/repos/{repo['id']}/key", headers=ADMIN)
    with agent_client.S() as db:
        db.add(AwakJob(project_slug="demo", story_id=1, story_ref=1, branch="awak/us-1",
                       state="running", repo_id=repo["id"]))
        db.commit()
    url = f"/projects/demo/agent/repos/{repo['id']}"
    assert agent_client.delete(url, headers=ADMIN).status_code == 409
    with agent_client.S() as db:
        db.query(AwakJob).one().state = "passed"
        db.commit()
    assert agent_client.delete(url, headers=ADMIN).status_code == 204
    with agent_client.S() as db:
        assert db.query(AwakRepo).count() == 0 and db.query(AwakKey).count() == 0
        assert {d.action for d in db.query(Decision)} >= {"awak_repo", "awak_repo_key",
                                                          "awak_repo_delete"}


def test_check_local_remote_detects_commands(agent_client, tmp_path):
    pkg = json.dumps({"scripts": {"test": "vitest run", "build": "vite build"}})
    remote = make_remote(tmp_path, {"package.json": pkg, "pnpm-lock.yaml": "lock",
                                     "tsconfig.json": "{}"})
    agent_client.settings.host_git = str(remote)  # local paths: only the Kemudi repo
    repo = add_repo(agent_client, url=str(remote), install_cmd="", build_cmd="make it")
    r = agent_client.post(f"/projects/demo/agent/repos/{repo['id']}/check", headers=ADMIN)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] and body["clone"] and body["push"] and body["default_branch_found"]
    assert body["error"] is None and body["host_key"] is None
    assert "pnpm install" in body["detected"]["install_cmd"]
    saved = agent_client.get("/projects/demo/agent/repos", headers=MEMBER).json()["repos"][0]
    assert "pnpm install" in saved["install_cmd"]
    assert saved["build_cmd"] == "make it"  # detection fills empty fields only
    assert saved["last_check"]["ok"] is True
    assert "awak/kemudi-access-check" not in refs(remote)


def test_check_missing_branch_is_not_ok(agent_client, tmp_path):
    remote = make_remote(tmp_path, {"README.md": "hi"})
    agent_client.settings.host_git = str(remote)
    repo = add_repo(agent_client, url=str(remote), default_branch="trunk")
    body = agent_client.post(f"/projects/demo/agent/repos/{repo['id']}/check",
                             headers=ADMIN).json()
    assert body["clone"] and not body["default_branch_found"] and not body["ok"]
    assert body["error"]


def test_check_ssh_builds_git_ssh_command(agent_client):
    seen: list[tuple[list[str], dict]] = []

    def fake(argv, env, timeout):
        cmd = env.get("GIT_SSH_COMMAND", "")
        key_path = shlex.split(cmd)[shlex.split(cmd).index("-i") + 1] if cmd else ""
        seen.append((argv, dict(env), key_path, Path(key_path).exists() if key_path else None))
        if "ls-remote" in argv:
            return 0, "a" * 40 + "\trefs/heads/main\n"
        return 0, ""

    from kemudi_ai.api import app
    app.dependency_overrides[agent_api.get_command_runner] = lambda: fake
    repo = add_repo(agent_client)
    agent_client.post(f"/projects/demo/agent/repos/{repo['id']}/key", headers=ADMIN)
    body = agent_client.post(f"/projects/demo/agent/repos/{repo['id']}/check",
                             headers=ADMIN).json()
    assert body["clone"] and body["push"]
    remote_calls = [s for s in seen if "GIT_SSH_COMMAND" in s[1]]
    assert {"ls-remote", "push"} <= {a for s in remote_calls for a in s[0]}
    known_hosts = ssh.known_hosts_path(agent_client.settings, "demo")
    for argv, env, key_path, existed in remote_calls:
        cmd = env["GIT_SSH_COMMAND"]
        assert "StrictHostKeyChecking=accept-new" in cmd and "IdentitiesOnly=yes" in cmd
        assert "BatchMode=yes" in cmd
        assert f"UserKnownHostsFile={known_hosts}" in shlex.split(cmd)
        assert existed is True  # the key file existed during the call
        assert not Path(key_path).exists()  # and is gone afterwards
    assert "--dry-run" in next(s[0] for s in remote_calls if "push" in s[0])


def test_check_without_key_for_ssh_repo_is_409(agent_client):
    repo = add_repo(agent_client)
    r = agent_client.post(f"/projects/demo/agent/repos/{repo['id']}/check", headers=ADMIN)
    assert r.status_code == 409


def test_forget_host_on_url_change(agent_client):
    repo = add_repo(agent_client)
    kh = ssh.known_hosts_path(agent_client.settings, "demo")
    kh.parent.mkdir(parents=True, exist_ok=True)
    kh.write_text("github.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl\n"
                  "vps.example.com ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl\n")
    assert ssh.host_key_fingerprint(kh, "github.com").startswith("SHA256:")
    r = agent_client.put(f"/projects/demo/agent/repos/{repo['id']}", headers=ADMIN,
                         json={**SSH_REPO, "url": "git@gitlab.com:acme/web.git"})
    assert r.status_code == 200
    assert "github.com" not in kh.read_text()
    assert "vps.example.com" in kh.read_text()
    assert ssh.host_key_fingerprint(kh, "github.com") is None


def test_key_file_is_removed_on_error(agent_settings):
    _, public, fp = crypto.generate_keypair()
    row = AwakKey(owner_kind="repo", owner_id=1, public_key=public, fingerprint=fp,
                  private_key_enc=crypto.encrypt(agent_settings, crypto.generate_keypair()[0]))
    with pytest.raises(RuntimeError):
        with ssh.key_file(agent_settings, row) as path:
            assert "OPENSSH PRIVATE KEY" in path.read_text()
            kept = path
            raise RuntimeError("boom")
    assert not kept.exists()


# --- the worker uses the repo row -------------------------------------------------

def test_worker_uses_repo_default_branch(tmp_path):
    remote = make_remote(tmp_path, {"README.md": "hi"}, branch="trunk")
    trunk = subprocess.run(["git", "--git-dir", str(remote), "rev-parse", "trunk"],
                           capture_output=True, text=True).stdout.strip()
    settings = Settings(awak_projects="", ai_db_url="sqlite:///:memory:",
                        repos_dir=str(tmp_path / "repos"), workspace_dir=str(tmp_path / "ws"),
                        awak_uid=0)
    sessions = make_session(settings.ai_db_url)
    with sessions() as db:
        db.add(AwakProject(slug="demo", enabled=True, merge_mode="manual"))
        row = AwakRepo(project_slug="demo", name="app", url=str(remote),
                       default_branch="trunk", install_cmd="pnpm install", check_cmd="pnpm test")
        db.add(row)
        db.flush()
        db.add(AwakRole(project_slug="demo", template="frontend", name="FE", area="web",
                        model="m", repo_ids=[row.id]))
        db.commit()
    taiga = FakeTaiga()
    runner = FakeRunner(tmp_path / "ws", qa=["pass"])
    w = Worker(settings, sessions, taiga, FakeTaiga("awak-qa"), FakeAgent(), runner, None,
               secret_values=[], sleep=lambda s: None)
    taiga.add(1, 12, "Badge jumlah", DESC)
    assert w.tick()
    assert taiga.status_of(1) == "done"
    pushed = subprocess.run(["git", "--git-dir", str(remote), "rev-parse", "awak/us-12^"],
                            capture_output=True, text=True).stdout.strip()
    assert pushed == trunk
    assert (tmp_path / "repos").exists()
    with sessions() as db:
        job = db.query(AwakJob).one()
        assert job.repo_id == db.query(AwakRepo).one().id
    install = next(p for op, p in runner.payloads if op == "install")
    assert install["subdir"] == ""
    assert install["commands"][0]["argv"] == ["pnpm", "install"]
    gates = next(p for op, p in runner.payloads if op == "gates")
    assert [c["argv"] for c in gates["commands"]] == [["pnpm", "test"]]


def test_url_change_keeps_a_host_still_in_use(agent_client):
    first = add_repo(agent_client)
    add_repo(agent_client, name="api", url="git@github.com:acme/api.git")
    vps = add_repo(agent_client, name="ops", url="git@vps.example.com:ops.git")
    agent_client.put("/projects/demo/agent/settings", headers=ADMIN, json={
        "enabled": False, "merge_mode": "approve", "deploy_command": "", "executor": "ssh",
        "ssh_host": "vps.example.com", "ssh_port": 22, "ssh_user": "deploy"})
    kh = ssh.known_hosts_path(agent_client.settings, "demo")
    kh.parent.mkdir(parents=True, exist_ok=True)
    key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl\n"
    kh.write_text(f"github.com {key}vps.example.com {key}")
    # another repo still uses github.com
    r = agent_client.put(f"/projects/demo/agent/repos/{first['id']}", headers=ADMIN,
                         json={**SSH_REPO, "url": "git@gitlab.com:acme/web.git"})
    assert r.status_code == 200
    assert ssh.host_key_fingerprint(kh, "github.com") is not None
    # the machine still uses vps.example.com
    r = agent_client.put(f"/projects/demo/agent/repos/{vps['id']}", headers=ADMIN,
                         json={**SSH_REPO, "name": "ops", "url": "git@gitlab.com:acme/ops.git"})
    assert r.status_code == 200
    assert ssh.host_key_fingerprint(kh, "vps.example.com") is not None
