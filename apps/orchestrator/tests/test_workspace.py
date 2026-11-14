"""Stage 1a workspace layout: `<workspace>/<slug>/us-<ref>/<repo>`, the runner
`path` contract, sibling repos and the sweep of the old `awak-us-<n>` folders."""

import subprocess
from pathlib import Path

import pytest

from kemudi_ai.awak.gitops import GitError, Repo
from kemudi_ai.awak.worker import Worker, runner_path
from kemudi_ai.config import Settings
from kemudi_ai.store import AwakJob, AwakProject, AwakRepo, AwakRole, make_session

from .awak_fakes import FakeAgent, FakeRunner, FakeTaiga, git
from .conftest import ADMIN
from .test_awak import DESC


def make_remote(tmp_path: Path, name: str, files: dict[str, str]) -> Path:
    src = tmp_path / f"{name}-src"
    src.mkdir()
    git(src, "init", "-b", "main")
    git(src, "config", "user.email", "t@t")
    git(src, "config", "user.name", "t")
    for path, content in files.items():
        (src / path).write_text(content, newline="\n")
    git(src, "add", "-A")
    git(src, "commit", "-m", "init")
    remote = tmp_path / f"{name}.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(src), str(remote)], check=True)
    return remote


def test_two_projects_get_different_folders_for_us_1(tmp_path):
    remote = make_remote(tmp_path, "app", {"README.md": "hi"})
    ws = tmp_path / "ws"
    a = Repo(str(tmp_path / "a.git"), str(remote), str(ws), 0, slug="kemudi", name="web")
    b = Repo(str(tmp_path / "b.git"), str(remote), str(ws), 0, slug="playfast", name="web")
    assert a.job_dir("awak/us-1") == ws / "kemudi" / "us-1" / "web"
    assert b.job_dir("awak/us-1") == ws / "playfast" / "us-1" / "web"
    for r in (a, b):
        r.sync_default()
        assert (r.prepare("awak/us-1") / "README.md").exists()
    assert runner_path(str(ws), a.job_dir("awak/us-1")) == "kemudi/us-1/web"
    assert runner_path(str(ws), b.job_dir("awak/us-1")) == "playfast/us-1/web"


def test_job_dir_refuses_bad_names(tmp_path):
    for slug, name in (("", "web"), ("kemudi", ""), ("../x", "web"), ("kemudi", "../x"),
                       ("Kemudi", "web"), ("kemudi", ".git")):
        r = Repo("bare", "remote", str(tmp_path), 0, slug=slug, name=name)
        with pytest.raises(GitError):
            r.job_dir("awak/us-1")
    with pytest.raises(GitError):
        Repo("bare", "remote", str(tmp_path), 0, slug="k", name="w").job_dir("main")


def test_prepare_empties_the_story_folder_and_siblings_check_out_default(tmp_path):
    web = make_remote(tmp_path, "web", {"README.md": "web"})
    api = make_remote(tmp_path, "api", {"openapi.yaml": "v1"})
    ws = tmp_path / "ws"
    r = Repo(str(tmp_path / "web-bare.git"), str(web), str(ws), 0, slug="p", name="web")
    s = Repo(str(tmp_path / "api-bare.git"), str(api), str(ws), 0, slug="p", name="api")
    r.sync_default()
    s.sync_default()
    stale = ws / "p" / "us-2" / "removed-repo"
    stale.mkdir(parents=True)
    d = r.prepare("awak/us-2")
    assert not stale.exists()
    sib = s.checkout_default("awak/us-2")
    assert sib == ws / "p" / "us-2" / "api" and (sib / "openapi.yaml").read_text() == "v1"
    assert subprocess.run(["git", "remote"], cwd=sib, capture_output=True,
                          text=True).stdout == ""
    assert (d / "README.md").exists()


def _project(sessions, slug, repos):
    """Enabled project with a frontend role on the first repo."""
    with sessions() as db:
        db.add(AwakProject(slug=slug, enabled=True, merge_mode="manual"))
        rows = []
        for i, (name, url) in enumerate(repos):
            row = AwakRepo(project_slug=slug, name=name, url=url, position=i)
            db.add(row)
            db.flush()
            rows.append(row)
        db.add(AwakRole(project_slug=slug, template="frontend", name="FE", area="web",
                        model="m", repo_ids=[rows[0].id]))
        db.commit()


def test_story_checkout_has_sibling_repos_and_runner_gets_paths(tmp_path):
    web = make_remote(tmp_path, "web", {"README.md": "web"})
    api = make_remote(tmp_path, "api", {"openapi.yaml": "v1"})
    settings = Settings(awak_projects="", ai_db_url="sqlite:///:memory:",
                        repos_dir=str(tmp_path / "repos"), workspace_dir=str(tmp_path / "ws"),
                        awak_uid=0)
    sessions = make_session(settings.ai_db_url)
    _project(sessions, "demo", [("web", str(web)), ("api", str(api))])
    seen = {}

    def code(d, n):
        sib = d.parent / "api"
        seen["sibling"] = (sib / "openapi.yaml").read_text()
        (sib / "openapi.yaml").write_text("v2")  # discarded: never collected
        (d / "f.txt").write_text("x", newline="\n")
        git(d, "add", "-A")
        git(d, "commit", "-m", "f")

    agent = FakeAgent(code=code)
    runner = FakeRunner(tmp_path / "ws", qa=["pass"])
    taiga = FakeTaiga()
    w = Worker(settings, sessions, taiga, FakeTaiga("awak-qa"), agent, runner, None,
               secret_values=[], sleep=lambda s: None)
    taiga.add(1, 12, "Badge jumlah", DESC)
    assert w.tick()
    assert taiga.status_of(1) == "done"
    assert seen["sibling"] == "v1"
    task = next(t for p, t in agent.calls if p == "awak.code")
    assert str(tmp_path / "ws" / "demo" / "us-12" / "api") in task
    assert "read-only" in task and "discarded" in task
    paths = {p["path"] for _, p in runner.payloads}
    assert paths == {"demo/us-12/web"}
    assert all("job" not in p for _, p in runner.payloads)
    with sessions() as db:
        assert db.query(AwakJob).one().state == "passed"


# An unreachable sibling: tests/test_siblings.py (left out, not an infra error).


def test_recover_sweeps_old_job_folders_once(tmp_path):
    ws = tmp_path / "ws"
    old = ws / "awak-us-1"
    (old / "node_modules").mkdir(parents=True)
    (old / "x.txt").write_text("x")
    keep = ws / "demo" / "us-1" / "web"
    keep.mkdir(parents=True)
    settings = Settings(awak_projects="", ai_db_url="sqlite:///:memory:", workspace_dir=str(ws))
    sessions = make_session(settings.ai_db_url)
    w = Worker(settings, sessions, FakeTaiga(), FakeTaiga("awak-qa"), FakeAgent(),
               FakeRunner(ws), None, secret_values=[], sleep=lambda s: None)
    w.recover()
    assert not old.exists() and keep.exists()
    (ws / "awak-us-2").mkdir()
    w.recover()  # once per worker
    assert (ws / "awak-us-2").exists()


def test_recover_keeps_old_folders_while_a_job_runs(tmp_path):
    ws = tmp_path / "ws"
    (ws / "awak-us-1").mkdir(parents=True)
    settings = Settings(awak_projects="", ai_db_url="sqlite:///:memory:", workspace_dir=str(ws))
    sessions = make_session(settings.ai_db_url)
    with sessions() as db:
        db.add(AwakJob(project_slug="demo", story_id=1, story_ref=1, branch="awak/us-1",
                       state="running"))
        db.commit()
    w = Worker(settings, sessions, FakeTaiga(), FakeTaiga("awak-qa"), FakeAgent(),
               FakeRunner(ws), None, secret_values=[], sleep=lambda s: None)
    w.recover()
    assert (ws / "awak-us-1").exists()


def test_repo_names_are_validated(agent_client):
    base = {"role": "web", "url": "git@github.com:acme/web.git"}
    for name in ("kemudi", "pf-web", "My.Repo_2"):
        r = agent_client.post("/projects/demo/agent/repos", headers=ADMIN,
                              json={**base, "name": name})
        assert r.status_code == 200, r.text
    for name in ("", ".git", "-x", "a/b", "..", "a b", "x" * 101):
        r = agent_client.post("/projects/demo/agent/repos", headers=ADMIN,
                              json={**base, "name": name})
        assert r.status_code == 422, name
    rid = agent_client.get("/projects/demo/agent/repos", headers=ADMIN).json()["repos"][0]["id"]
    r = agent_client.put(f"/projects/demo/agent/repos/{rid}", headers=ADMIN,
                         json={**base, "name": "../up"})
    assert r.status_code == 422
