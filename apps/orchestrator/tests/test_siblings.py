"""Sibling repos in browser QA and in the merge QA re-run, unavailable
siblings, and runbook entries that point at a repo or folder that is gone."""

import subprocess
from pathlib import Path

import httpx
import pytest

from kemudi_ai.awak import runbook
from kemudi_ai.awak.runner import HttpRunner, RunnerRejected
from kemudi_ai.awak.worker import Worker
from kemudi_ai.config import Settings
from kemudi_ai.store import AwakEvent, AwakJob, AwakProject, AwakRepo, make_session

from .awak_fakes import FakeAgent, FakeRunner, FakeTaiga, commit_file, git
from .test_awak import DESC
from .test_workspace import _project, make_remote

# The story's repo `web` runs a Next app; its QA needs the `api` sibling's
# server, started from the api repo.
RB = {
    "apps": [
        {"name": "web", "repo": "web", "install": ["npm ci"],
         "env": {"API_URL": "{services.api.url}"}},
        {"name": "api", "repo": "api", "install": ["uv sync"]},
    ],
    "services": [
        {"name": "api", "kind": "process", "app": "api", "command": "uv run serve {port}"},
        {"name": "web", "kind": "process", "app": "web", "command": "npm run dev"},
    ],
    "qa": {"service": "web"},
}


def _settings(tmp_path, **kw):
    return Settings(awak_projects="", ai_db_url="sqlite:///:memory:",
                    repos_dir=str(tmp_path / "repos"), workspace_dir=str(tmp_path / "ws"),
                    awak_uid=0, **kw)


def _save(sessions, spec, slug="demo", repos=("web", "api")):
    rb, errs = runbook.validate(spec, set(repos))
    assert not errs, errs
    with sessions() as db:
        runbook.save(db, slug, rb, "pm")


def _mode(sessions, slug="demo", **fields):
    with sessions() as db:
        p = db.get(AwakProject, slug)
        for k, v in fields.items():
            setattr(p, k, v)
        db.commit()


def advance(tmp_path: Path, remote: Path, name: str, content: str) -> None:
    """A new commit on the remote's main, as someone else's push."""
    d = tmp_path / f"push-{remote.stem}-{name}"
    subprocess.run(["git", "clone", "-q", str(remote), str(d)], check=True)
    git(d, "config", "user.email", "t@t")
    git(d, "config", "user.name", "t")
    commit_file(d, name, content)
    git(d, "push", "-q", "origin", "HEAD:main")


class SeeingRunner(FakeRunner):
    """Records the sibling's file at each `qa` call; `on_qa` runs first."""

    def __init__(self, workspace, sibling: Path, on_qa=None, **kw):
        super().__init__(workspace, **kw)
        self.sibling = sibling
        self.on_qa = on_qa
        self.seen: list[str] = []

    def call(self, op, **payload):
        if op == "qa":
            f = self.sibling / "openapi.yaml"
            self.seen.append(f.read_text() if f.exists() else "(missing)")
            if self.on_qa:
                self.on_qa(len(self.seen))
        return super().call(op, **payload)


def _world(tmp_path, runner_factory, agent=None, **settings):
    web = make_remote(tmp_path, "web", {"README.md": "web"})
    api = make_remote(tmp_path, "api", {"openapi.yaml": "v1"})
    s = _settings(tmp_path, **settings)
    sessions = make_session(s.ai_db_url)
    _project(sessions, "demo", [("web", str(web)), ("api", str(api))])
    _save(sessions, RB)
    _mode(sessions, qa_mode="browser", merge_mode="approve")
    sib = tmp_path / "ws" / "demo" / "us-12" / "api"
    runner = runner_factory(sib)
    taiga = FakeTaiga()

    def tamper(d, n):
        (d.parent / "api" / "openapi.yaml").write_text("tampered")
        (d.parent / "api" / "evil.py").write_text("x")
        commit_file(d, f"feature{n}.txt", "x")

    agent = agent or FakeAgent(code=tamper)
    w = Worker(s, sessions, taiga, FakeTaiga("awak-qa"), agent, runner, None,
               secret_values=[], sleep=lambda s: None)
    taiga.add(1, 12, "Badge jumlah", DESC)
    return w, taiga, sessions, runner, web, api


def _job(sessions) -> AwakJob:
    with sessions() as db:
        return db.query(AwakJob).one()


def test_qa_runs_siblings_fresh_at_their_default_branch_and_installed(tmp_path):
    w, taiga, sessions, runner, _, _ = _world(
        tmp_path, lambda sib: SeeingRunner(tmp_path / "ws", sib, qa=["pass"]))
    w.tick()
    assert taiga.status_of(1) == "done", taiga.texts(1)
    assert runner.seen == ["v1"]  # the coding agent's edit never reached QA
    assert not (tmp_path / "ws" / "demo" / "us-12" / "api" / "evil.py").exists()
    installs = [(p["path"], p["commands"][0]["argv"]) for op, p in runner.payloads
                if op == "install"]
    assert installs == [("demo/us-12/web", ["npm", "ci"]), ("demo/us-12/api", ["uv", "sync"])]
    qa_i = runner.calls.index("qa")
    assert runner.calls[qa_i - 1] == "install"  # the sibling's install right before QA
    qa = next(p for op, p in runner.payloads if op == "qa")
    assert [s["repo"] for s in qa["services"]] == ["api", "web"]


def test_merge_qa_rerun_uses_fresh_siblings(tmp_path):
    """Auto merge onto a moved default branch re-runs QA: the sibling is
    checked out again at its (new) default branch, not the stale copy."""
    remotes = {}

    def on_qa(n):
        if n == 1:  # during the story's QA, both default branches move on
            advance(tmp_path, remotes["web"], "other.txt", "o")
            advance(tmp_path, remotes["api"], "openapi.yaml", "v2")

    w, taiga, sessions, runner, web, api = _world(
        tmp_path, lambda sib: SeeingRunner(tmp_path / "ws", sib, on_qa=on_qa,
                                           qa=["pass", "pass"]))
    remotes.update(web=web, api=api)
    _mode(sessions, merge_mode="auto")
    w.tick()
    job = _job(sessions)
    assert job.merge_state == "merged", job.merge_error
    assert runner.seen == ["v1", "v2"]
    api_installs = [p for op, p in runner.payloads
                    if op == "install" and p["path"] == "demo/us-12/api"]
    assert len(api_installs) == 2


def test_an_unreachable_sibling_is_left_out_and_named_in_the_task(tmp_path):
    web = make_remote(tmp_path, "web", {"README.md": "web"})
    s = _settings(tmp_path)
    sessions = make_session(s.ai_db_url)
    _project(sessions, "demo", [("web", str(web)), ("api", str(tmp_path / "missing.git"))])
    _mode(sessions, qa_mode="gates")
    taiga = FakeTaiga()
    agent = FakeAgent()
    w = Worker(s, sessions, taiga, FakeTaiga("awak-qa"), agent, FakeRunner(tmp_path / "ws"),
               None, secret_values=[], sleep=lambda s: None)
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    assert taiga.status_of(1) == "done"
    task = next(t for p, t in agent.calls if p == "awak.code")
    assert "could not be fetched" in task and "api" in task
    with sessions() as db:
        ev = db.query(AwakEvent).filter_by(kind="sibling_unavailable").one()
        assert ev.detail["repo"] == "api"


def test_qa_needing_an_unreachable_sibling_is_an_infra_error(tmp_path):
    web = make_remote(tmp_path, "web", {"README.md": "web"})
    s = _settings(tmp_path, max_infra_errors=1)
    sessions = make_session(s.ai_db_url)
    _project(sessions, "demo", [("web", str(web)), ("api", str(tmp_path / "missing.git"))])
    _save(sessions, RB)
    _mode(sessions, qa_mode="browser")
    taiga = FakeTaiga()
    runner = FakeRunner(tmp_path / "ws", qa=["pass"])
    w = Worker(s, sessions, taiga, FakeTaiga("awak-qa"), FakeAgent(), runner, None,
               secret_values=[], sleep=lambda s: None)
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    assert "qa" not in runner.calls
    assert taiga.story(1)["is_blocked"]
    assert any("repo api" in t and "service QA" in t for t in taiga.texts(1))


def test_runbook_app_in_a_missing_folder_stops_the_story(tmp_path):
    web = make_remote(tmp_path, "web", {"README.md": "web"})
    s = _settings(tmp_path)
    sessions = make_session(s.ai_db_url)
    _project(sessions, "demo", [("web", str(web))])
    _save(sessions, {"apps": [{"name": "web", "repo": "web", "dir": "frontend",
                               "checks": ["npm test"]}]}, repos=("web",))
    _mode(sessions, qa_mode="gates")
    taiga = FakeTaiga()
    runner = FakeRunner(tmp_path / "ws")
    w = Worker(s, sessions, taiga, FakeTaiga("awak-qa"), FakeAgent(), runner, None,
               secret_values=[], sleep=lambda s: None)
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    job = _job(sessions)
    assert job.state == "stopped" and job.infra_errors == 0
    assert any("Berhenti" in t and "`frontend`" in t for t in taiga.texts(1))
    assert "install" not in runner.calls


def test_qa_service_of_a_repo_that_is_gone_stops_the_story(tmp_path):
    w, taiga, sessions, runner, _, _ = _world(
        tmp_path, lambda sib: SeeingRunner(tmp_path / "ws", sib, qa=["pass"]))
    with sessions() as db:  # removed behind the API's back (the API refuses it)
        db.delete(db.query(AwakRepo).filter_by(name="api").one())
        db.commit()
    w.tick()
    job = _job(sessions)
    assert job.state == "stopped" and job.infra_errors == 0
    assert any("Berhenti" in t and "repo api" in t for t in taiga.texts(1))


class RejectingRunner(FakeRunner):
    def call(self, op, **payload):
        if op == "gates":
            self.calls.append(op)
            raise RunnerRejected("runner gates refused: no directory 'x' in the workspace")
        return super().call(op, **payload)


def test_runner_refusal_stops_instead_of_retrying(tmp_path):
    web = make_remote(tmp_path, "web", {"README.md": "web"})
    s = _settings(tmp_path)
    sessions = make_session(s.ai_db_url)
    _project(sessions, "demo", [("web", str(web))])
    _mode(sessions, qa_mode="gates")
    with sessions() as db:
        db.query(AwakRepo).one().check_cmd = "npm test"
        db.commit()
    taiga = FakeTaiga()
    w = Worker(s, sessions, taiga, FakeTaiga("awak-qa"), FakeAgent(),
               RejectingRunner(tmp_path / "ws"), None, secret_values=[], sleep=lambda s: None)
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    job = _job(sessions)
    assert job.state == "stopped" and job.infra_errors == 0
    assert any("no directory 'x'" in t and "runbook" in t for t in taiga.texts(1))


def test_http_runner_400_is_a_refusal():
    def handler(request):
        if request.url.path == "/gates":
            return httpx.Response(400, json={"error": "no directory 'x' in the workspace"})
        return httpx.Response(500, text="boom")

    r = HttpRunner("http://runner", "k", transport=httpx.MockTransport(handler))
    with pytest.raises(RunnerRejected, match="no directory 'x'"):
        r.call("gates", path="p")
    with pytest.raises(Exception) as e:
        r.call("qa", path="p")
    assert not isinstance(e.value, RunnerRejected)
