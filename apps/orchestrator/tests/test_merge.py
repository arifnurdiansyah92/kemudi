import subprocess
from pathlib import Path

import pytest

from kemudi_ai.awak import agent_api, crypto, gitops
from kemudi_ai.awak.gitops import Repo
from kemudi_ai.awak.merge import effective_mode
from kemudi_ai.awak.worker import Worker
from kemudi_ai.config import Settings
from kemudi_ai.store import AwakJob, AwakKey, AwakProject, Decision, make_session

from .awak_fakes import FakeAgent, FakeRunner, FakeTaiga, commit_file, git
from .conftest import ADMIN, MEMBER, SECRET_KEY
from .test_awak import DESC

SECRET = "super-secret-value"


# --- fixtures -----------------------------------------------------------------------

@pytest.fixture
def remote(tmp_path) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    git(src, "init", "-b", "main")
    git(src, "config", "user.email", "t@t")
    git(src, "config", "user.name", "t")
    (src / "README.md").write_text("hi\n")
    git(src, "add", "-A")
    git(src, "commit", "-m", "init")
    r = tmp_path / "remote.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(src), str(r)], check=True)
    return r


@pytest.fixture
def repo(tmp_path, remote) -> Repo:
    return Repo(str(tmp_path / "bare.git"), str(remote), str(tmp_path / "ws"), uid=0)


def rev(remote: Path, ref: str = "main") -> str:
    return subprocess.run(["git", "--git-dir", str(remote), "rev-parse", ref],
                          capture_output=True, text=True).stdout.strip()


def parents(remote: Path, ref: str = "main") -> list[str]:
    out = subprocess.run(["git", "--git-dir", str(remote), "rev-list", "--parents", "-n1", ref],
                         capture_output=True, text=True).stdout.split()
    return out[1:]


_adv = {"n": 0}


def advance(tmp_path: Path, remote: Path, name="other.txt", content="other\n") -> str:
    """Someone else pushes to the remote's main."""
    _adv["n"] += 1
    d = tmp_path / f"adv{_adv['n']}"
    subprocess.run(["git", "clone", "-q", str(remote), str(d)], check=True)
    git(d, "config", "user.email", "o@o")
    git(d, "config", "user.name", "o")
    commit_file(d, name, content)
    git(d, "push", "-q", "origin", "main")
    return rev(remote)


def make(tmp_path, repo, mode="approve", agent=None, runner=None, deploy_command="",
         executor="local", command_runner=None, **settings_kw):
    settings = Settings(awak_projects="kemudi", ai_db_url="sqlite:///:memory:",
                        repos_dir=str(tmp_path / "repos"), workspace_dir=str(tmp_path / "ws"),
                        awak_uid=0, **settings_kw)
    sessions = make_session(settings.ai_db_url)
    taiga = FakeTaiga()
    runner = runner or FakeRunner(tmp_path / "ws", qa=["pass"])
    kw = {"command_runner": command_runner} if command_runner else {}
    w = Worker(settings, sessions, taiga, FakeTaiga("awak-qa"), agent or FakeAgent(), runner,
               repo, secret_values=[SECRET], sleep=lambda s: None, **kw)
    w._seed()
    with sessions() as db:
        p = db.get(AwakProject, "kemudi")
        p.merge_mode, p.deploy_command, p.executor = mode, deploy_command, executor
        db.commit()
    taiga.add(1, 12, "Badge jumlah", DESC)
    return w, taiga, sessions, runner


def job_of(sessions) -> AwakJob:
    with sessions() as db:
        return db.query(AwakJob).one()


def request(sessions):
    with sessions() as db:
        db.query(AwakJob).one().merge_state = "requested"
        db.commit()


def tags(taiga) -> set[str]:
    return {t[0] for t in taiga.story(1)["tags"]}


# --- pure ---------------------------------------------------------------------------

def test_effective_mode_is_stricter():
    assert effective_mode("auto", "approve") == "approve"
    assert effective_mode("approve", "auto") == "approve"
    assert effective_mode("auto", "auto") == "auto"
    assert effective_mode("manual", "auto") == "manual"
    assert effective_mode("", "auto") == "manual"  # iteration 1 jobs


# --- modes --------------------------------------------------------------------------

def test_manual_mode_unchanged(tmp_path, repo, remote):
    before = rev(remote)
    w, taiga, sessions, _ = make(tmp_path, repo, mode="manual")
    assert w.tick()
    assert taiga.status_of(1) == "done" and "awaiting-merge" in tags(taiga)
    assert "belum di-merge" in taiga.texts(1)[-1]
    assert rev(remote) == before
    job = job_of(sessions)
    assert job.merge_mode == "manual" and job.merge_state == ""
    assert not (tmp_path / "repos" / "qa-specs").exists()


def test_approve_mode_waits_then_merges_fast_forward(tmp_path, repo, remote):
    before = rev(remote)
    w, taiga, sessions, runner = make(tmp_path, repo)
    assert w.tick()
    assert rev(remote) == before
    assert "menunggu Merge di Kemudi" in taiga.texts(1)[-1]
    assert not w.tick()  # nothing happens until someone clicks Merge
    request(sessions)
    n = len(runner.calls)
    assert w.tick()
    job = job_of(sessions)
    assert rev(remote) == job.last_sha == job.merged_sha
    assert job.merge_state == "merged"
    assert "merged" in tags(taiga) and "awaiting-merge" not in tags(taiga)
    assert runner.calls[n:] == []  # a fast-forward of the QA'd commit: no re-run
    assert "fast-forward" in taiga.texts(1)[-1]


def test_non_ff_merge_reruns_gates_before_push(tmp_path, repo, remote):
    w, taiga, sessions, runner = make(tmp_path, repo)
    w.tick()
    other = advance(tmp_path, remote)
    request(sessions)
    n = len(runner.calls)
    w.tick()
    job = job_of(sessions)
    assert runner.calls[n:] == ["install", "gates"]
    assert job.merge_state == "merged" and rev(remote) == job.merged_sha
    assert parents(remote) == [other, job.last_sha]
    assert "gates ulang lulus" in taiga.texts(1)[-1]
    assert not list((tmp_path / "scratch").iterdir())  # scratch next to the bare repo


def test_failed_regate_never_pushes(tmp_path, repo, remote):
    runner = FakeRunner(tmp_path / "ws", qa=["pass"], gates=[
        {"gates": [{"name": "tsc", "ok": True}]},
        {"gates": [{"name": "tsc", "ok": False, "output": "TS2322"}]},
    ])
    w, taiga, sessions, _ = make(tmp_path, repo, runner=runner)
    w.tick()
    other = advance(tmp_path, remote)
    request(sessions)
    w.tick()
    job = job_of(sessions)
    assert rev(remote) == other
    assert job.merge_state == "failed" and "tsc" in job.merge_error
    assert {"needs-human", "awaiting-merge"} <= tags(taiga)
    assert taiga.status_of(1) == "done"
    assert "tidak ada yang di-push" in taiga.texts(1)[-1]


def _advance_during_code(tmp_path, remote, **kw):
    def code(d, n):
        commit_file(d, f"feature{n}.txt", "x")
        advance(tmp_path, remote, **kw)
    return FakeAgent(code=code)


def test_auto_mode_non_ff_reruns_qa(tmp_path, repo, remote):
    runner = FakeRunner(tmp_path / "ws", qa=["pass", "fail"])
    w, taiga, sessions, _ = make(tmp_path, repo, mode="auto", runner=runner,
                                 agent=_advance_during_code(tmp_path, remote))
    w.tick()
    other = rev(remote)
    job = job_of(sessions)
    assert runner.calls.count("qa") == 2
    assert runner.calls[-4:] == ["install", "gates", "qa_reset", "qa"]
    spec = tmp_path / "ws" / "awak-us-12" / ".qa" / "spec" / "story.spec.ts"
    assert spec.read_text().startswith("test(")  # the spec that passed QA, restored
    assert rev(remote) == other and parents(remote) != [other, job.last_sha]
    assert job.merge_state == "failed" and "QA ulang" in job.merge_error
    assert "needs-human" in tags(taiga)


def test_auto_mode_non_ff_pushes_after_gates_and_qa(tmp_path, repo, remote):
    runner = FakeRunner(tmp_path / "ws", qa=["pass", "pass"])
    w, taiga, sessions, _ = make(tmp_path, repo, mode="auto", runner=runner,
                                 agent=_advance_during_code(tmp_path, remote))
    w.tick()
    job = job_of(sessions)
    other = parents(remote)[0]
    assert job.merge_state == "merged" and parents(remote) == [other, job.last_sha]
    assert "QA ulang lulus" in taiga.texts(1)[-1]


def test_auto_mode_fast_forward_pushes_after_qa(tmp_path, repo, remote):
    w, taiga, sessions, runner = make(tmp_path, repo, mode="auto")
    w.tick()
    job = job_of(sessions)
    assert job.merge_state == "merged" and rev(remote) == job.last_sha
    assert runner.calls.count("qa") == 1 and runner.calls.count("gates") == 1
    assert "merged" in tags(taiga)


def test_branch_moved_since_qa_refuses(tmp_path, repo, remote):
    before = rev(remote)
    w, taiga, sessions, _ = make(tmp_path, repo)
    w.tick()
    subprocess.run(["git", "--git-dir", repo.bare, "update-ref", "refs/heads/awak/us-12",
                    before], check=True)
    request(sessions)
    w.tick()
    job = job_of(sessions)
    assert rev(remote) == before
    assert job.merge_state == "failed" and "branch berubah" in job.merge_error


def test_card_changed_refuses(tmp_path, repo, remote):
    before = rev(remote)
    w, taiga, sessions, _ = make(tmp_path, repo)
    w.tick()
    taiga.update_story(1, status=3)  # someone moved it back to In progress
    request(sessions)
    # (not tick(): the card in In progress would be picked as rework first)
    w._requested_merge(w.taiga.project("kemudi"), job_of(sessions))
    assert rev(remote) == before
    assert "kartu sudah diubah" in job_of(sessions).merge_error


def test_push_is_never_forced(tmp_path, repo, remote, monkeypatch):
    seen: list[tuple] = []
    real = gitops._git

    def spy(*args, **kw):
        seen.append(args)
        return real(*args, **kw)

    monkeypatch.setattr(gitops, "_git", spy)
    w, taiga, sessions, _ = make(tmp_path, repo)
    w.tick()
    advance(tmp_path, remote)
    request(sessions)
    w.tick()
    assert job_of(sessions).merge_state == "merged"
    to_main = [a for a in seen if "push" in a and any("refs/heads/main" in str(x) for x in a)]
    assert to_main
    for args in to_main:
        assert "--force" not in args and "-f" not in args
        assert not any(str(x).startswith("+") for x in args)


def test_push_rejected_retries_from_latest_default(tmp_path, repo, remote, monkeypatch):
    w, taiga, sessions, _ = make(tmp_path, repo)
    w.tick()
    real_push = Repo.push_default
    calls = []

    def racing_push(self, sha):
        calls.append(sha)
        if len(calls) == 1:
            advance(tmp_path, remote, name="race.txt")  # the remote moves first
        return real_push(self, sha)

    monkeypatch.setattr(Repo, "push_default", racing_push)
    request(sessions)
    w.tick()
    job = job_of(sessions)
    assert len(calls) == 2 and job.merge_state == "merged"
    assert parents(remote)[1] == job.last_sha


def test_merge_conflict_fails_cleanly(tmp_path, repo, remote):
    agent = FakeAgent(code=lambda d, n: commit_file(d, "README.md", "ours\n"))
    w, taiga, sessions, _ = make(tmp_path, repo, agent=agent)
    w.tick()
    other = advance(tmp_path, remote, name="README.md", content="theirs\n")
    request(sessions)
    w.tick()
    job = job_of(sessions)
    assert rev(remote) == other
    assert job.merge_state == "failed" and "konflik" in job.merge_error
    assert not list((tmp_path / "scratch").glob("*"))  # scratch next to the bare repo
    assert "needs-human" in tags(taiga)


def test_switching_to_auto_mid_job_does_not_auto_merge(tmp_path, repo, remote):
    before = rev(remote)
    holder = {}

    def code(d, n):
        commit_file(d, "f.txt", "x")
        with holder["S"]() as db:
            db.get(AwakProject, "kemudi").merge_mode = "auto"
            db.commit()

    w, taiga, sessions, _ = make(tmp_path, repo, agent=FakeAgent(code=code))
    holder["S"] = sessions
    w.tick()
    assert rev(remote) == before
    assert job_of(sessions).merge_mode == "approve" and job_of(sessions).merge_state == ""
    assert "menunggu Merge" in taiga.texts(1)[-1]


def test_switching_to_manual_after_request_cancels(tmp_path, repo, remote):
    before = rev(remote)
    w, taiga, sessions, _ = make(tmp_path, repo)
    w.tick()
    request(sessions)
    with sessions() as db:
        db.get(AwakProject, "kemudi").merge_mode = "manual"
        db.commit()
    w.tick()
    assert rev(remote) == before and job_of(sessions).merge_state == "failed"


def test_crash_mid_merge_retries_from_top(tmp_path, repo, remote):
    w, taiga, sessions, _ = make(tmp_path, repo)
    w.tick()
    with sessions() as db:
        db.query(AwakJob).one().merge_state = "merging"
        db.commit()
    assert not w.tick()  # a "merging" job is never pushed blindly
    w.recover()
    assert job_of(sessions).merge_state == "requested"
    w.tick()
    assert job_of(sessions).merge_state == "merged"


# --- deploy -------------------------------------------------------------------------

def test_deploy_output_is_redacted_and_posted(tmp_path, repo, remote):
    runner = FakeRunner(tmp_path / "ws", qa=["pass"], deploy=[
        {"ok": True, "exit": 0, "output": f"pulled\ntoken {SECRET} and sk-{'a' * 30}\nup"}])
    w, taiga, sessions, _ = make(tmp_path, repo, runner=runner, deploy_command="make deploy")
    w.tick()
    request(sessions)
    w.tick()
    payload = next(p for op, p in runner.payloads if op == "deploy")
    assert payload["command"] == "make deploy" and payload["job"] == "awak-us-12"
    text = taiga.texts(1)[-1]
    assert "Deploy selesai" in text and "pulled" in text
    assert SECRET not in text and "sk-aaaa" not in text
    assert "needs-human" not in tags(taiga)


def test_deploy_command_is_redacted_from_output(tmp_path, repo, remote):
    command = "DEPLOY_TOKEN=tok-9f8e7d6c make deploy URL=https://hooks.example.com/x/abcdef0123456789"
    runner = FakeRunner(tmp_path / "ws", qa=["pass"], deploy=[{
        "ok": False, "exit": 1,
        "output": f"+ {command}\nauth tok-9f8e7d6c failed\nposting https://hooks.example.com/"
                  "x/abcdef0123456789\nmake: *** [deploy] Error 1"}])
    w, taiga, sessions, _ = make(tmp_path, repo, runner=runner, deploy_command=command)
    w.tick()
    request(sessions)
    w.tick()
    text = taiga.texts(1)[-1]
    assert "Deploy gagal" in text and "Error 1" in text
    assert "tok-9f8e7d6c" not in text and "abcdef0123456789" not in text


def test_deploy_failure_keeps_merge(tmp_path, repo, remote):
    runner = FakeRunner(tmp_path / "ws", qa=["pass"],
                        deploy=[{"ok": False, "exit": 1, "output": "boom"}])
    w, taiga, sessions, _ = make(tmp_path, repo, runner=runner, deploy_command="make deploy")
    w.tick()
    request(sessions)
    w.tick()
    job = job_of(sessions)
    assert job.merge_state == "merged" and rev(remote) == job.merged_sha
    assert {"merged", "needs-human"} <= tags(taiga)
    assert "Deploy gagal" in taiga.texts(1)[-1] and "boom" in taiga.texts(1)[-1]


def test_deploy_over_ssh(tmp_path, repo, remote):
    seen = []

    def fake(argv, env, timeout):
        key = argv[argv.index("-i") + 1]
        seen.append((argv, timeout, Path(key).exists(), key))
        return 0, f"deployed with key at {key}"

    w, taiga, sessions, _ = make(tmp_path, repo, deploy_command="cd app && make deploy",
                                 executor="ssh", command_runner=fake, secret_key=SECRET_KEY,
                                 ssh_dir=str(tmp_path / "ssh"))
    private, public, fp = crypto.generate_keypair()
    with sessions() as db:
        key = AwakKey(owner_kind="machine", owner_id=0, public_key=public, fingerprint=fp,
                      private_key_enc=crypto.encrypt(w.s, private))
        db.add(key)
        db.flush()
        p = db.get(AwakProject, "kemudi")
        p.ssh_host, p.ssh_port, p.ssh_user, p.ssh_key_id = "vps.example.com", 2222, "deploy", key.id
        db.commit()
    w.tick()
    request(sessions)
    w.tick()
    argv, timeout, existed, key_path = seen[0]
    assert argv[-2:] == ["deploy@vps.example.com", "cd app && make deploy"]
    assert "BatchMode=yes" in argv and "StrictHostKeyChecking=accept-new" in argv
    assert argv[argv.index("-p") + 1] == "2222" and timeout == 900
    assert existed and not Path(key_path).exists()
    text = taiga.texts(1)[-1]
    assert "Deploy selesai" in text and key_path not in text


# --- endpoints ----------------------------------------------------------------------

def test_merge_endpoint_rules(agent_client):
    from kemudi_ai.api import app

    taiga = FakeTaiga()
    taiga.add(5, 12, "Badge", DESC, status="done", tags=("agent-ready", "awaiting-merge"))
    app.dependency_overrides[agent_api.get_bot_taiga] = lambda: taiga
    with agent_client.S() as db:
        db.add(AwakProject(slug="demo", enabled=True, merge_mode="manual"))
        db.add(AwakJob(project_slug="demo", story_id=5, story_ref=12, branch="awak/us-12",
                       state="passed", merge_mode="approve", last_sha="a" * 40))
        db.commit()
    url = "/projects/demo/agent/stories/5/merge"
    assert agent_client.post(url, headers=MEMBER).status_code == 403
    assert agent_client.post(url, headers=ADMIN).status_code == 409  # manual now wins
    info = agent_client.get("/projects/demo/agent/stories/5", headers=MEMBER).json()
    assert info["merge_mode"] == "manual" and info["can_merge"] is False
    with agent_client.S() as db:
        db.get(AwakProject, "demo").merge_mode = "approve"
        db.commit()
    taiga.stories_by_id[5]["tags"] = [["agent-ready", None]]
    assert agent_client.post(url, headers=ADMIN).status_code == 409  # no awaiting-merge
    taiga.stories_by_id[5]["tags"] = [["awaiting-merge", None]]
    info = agent_client.get("/projects/demo/agent/stories/5", headers=MEMBER).json()
    assert info["merge_mode"] == "approve" and info["can_merge"] is True
    r = agent_client.post(url, headers=ADMIN)
    assert r.status_code == 202 and r.json() == {"merge_state": "requested"}
    assert agent_client.post(url, headers=ADMIN).status_code == 409  # twice
    info = agent_client.get("/projects/demo/agent/stories/5", headers=MEMBER).json()
    assert info["merge_state"] == "requested" and info["job"]["branch"] == "awak/us-12"
    assert agent_client.get("/projects/demo/agent/stories/6", headers=MEMBER).json()["job"] is None
    with agent_client.S() as db:
        d = db.query(Decision).filter_by(action="awak_merge_requested").one()
        assert d.detail == {"story_ref": 12, "branch": "awak/us-12", "last_sha": "a" * 40}
    assert agent_client.started
