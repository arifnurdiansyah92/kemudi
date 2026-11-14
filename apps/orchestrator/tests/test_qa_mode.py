"""QA mode per project (stage 1a): off, gates, browser."""

import pytest
from sqlalchemy import create_engine, text

from kemudi_ai.awak import config_store
from kemudi_ai.awak.gitops import Repo
from kemudi_ai.config import Settings
from kemudi_ai.store import (AwakJob, AwakProject, AwakRepo, Base, Decision, init_db,
                             make_session)

from .awak_fakes import FakeAgent, FakeRunner, commit_file
from .conftest import ADMIN
from .test_awak import DESC, host, job_of, make_worker, repo  # noqa: F401 (fixtures)
from .test_merge import advance, remote, request, rev  # noqa: F401 (fixtures)
from .test_merge import make as make_merge

SETTINGS = {"enabled": False, "merge_mode": "approve", "deploy_command": "",
            "executor": "local", "ssh_host": "", "ssh_port": 22, "ssh_user": ""}


def set_mode(sessions, slug="kemudi", **fields):
    with sessions() as db:
        p = db.get(AwakProject, slug)
        for k, v in fields.items():
            setattr(p, k, v)
        db.commit()


def _worker(tmp_path, repo, qa_mode, runner=None, agent=None):
    runner = runner or FakeRunner(tmp_path / "ws")
    w, taiga, sessions = make_worker(tmp_path, repo, agent or FakeAgent(), runner)
    w._seed()
    set_mode(sessions, qa_mode=qa_mode)
    return w, taiga, sessions, runner


# --- worker -----------------------------------------------------------------------

def test_seeded_kemudi_project_uses_browser(tmp_path, repo):
    w, taiga, sessions = make_worker(tmp_path, repo, FakeAgent(), FakeRunner(tmp_path / "ws"))
    w._seed()
    with sessions() as db:
        assert config_store.load(db, "kemudi").qa_mode == "browser"


def test_gates_mode_skips_qa_and_says_what_was_checked(tmp_path, repo):
    w, taiga, sessions, runner = _worker(tmp_path, repo, "gates")
    set_mode(sessions, merge_mode="approve")
    taiga.add(1, 12, "Badge jumlah", "Tanpa kriteria.")  # no criteria needed without QA
    assert w.tick()
    assert taiga.status_of(1) == "done"
    assert ["awaiting-merge", None] in taiga.story(1)["tags"]
    assert runner.calls == ["install", "commit", "gates", "clean_check"]
    assert not taiga.attachments
    assert not (tmp_path / "repos" / "qa-specs").exists()
    text = taiga.texts(1)[-1]
    assert "Gates only" in text and "tsc" in text
    assert "Tidak diperiksa" in text and "QA browser" in text
    assert "menunggu Merge di Kemudi" in text
    assert job_of(sessions).state == "passed"
    assert [p for p, _ in w.agent.calls] == ["awak.code"]


def test_gates_mode_failed_gate_reworks(tmp_path, repo):
    runner = FakeRunner(tmp_path / "ws", gates=[
        {"gates": [{"name": "pnpm lint", "ok": False, "output": "no-unused-vars"}]}])
    w, taiga, sessions, _ = _worker(tmp_path, repo, "gates", runner=runner)
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    assert taiga.status_of(1) == "done" and job_of(sessions).attempts == 2
    assert any("gagal di pemeriksaan otomatis" in t for t in taiga.texts(1))
    assert "qa" not in runner.calls


def test_gates_mode_clean_check_runs_after_gates(tmp_path, repo):
    def code(d, n):
        if n == 1:
            commit_file(d, ".gitignore", "local.env\n")
            (d / "local.env").write_text("FEATURE=on")  # ignored: never committed
        commit_file(d, f"feature{n}.txt", "x")

    w, taiga, sessions, runner = _worker(tmp_path, repo, "gates", agent=FakeAgent(code=code))
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    # Only an ignored file is left: a human decides (runbook `generated`), the
    # agent is not told to commit it (it would commit build artefacts).
    stop = next(t for t in taiga.texts(1) if "Berhenti" in t)
    assert "local.env" in stop and "generated" in stop
    assert taiga.status_of(1) != "done" and job_of(sessions).state == "stopped"
    assert runner.calls[:4] == ["install", "commit", "gates", "clean_check"]


def test_auto_merge_without_browser_qa_waits_for_the_merge_button(tmp_path, repo):
    """Auto merge only follows browser QA. A story done without it is an
    approve story for good: the Merge button works and nothing auto-merges."""
    from kemudi_ai.awak.agent_api import _merge_blocker

    w, taiga, sessions, runner = _worker(tmp_path, repo, "gates")
    set_mode(sessions, merge_mode="auto")
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    job = job_of(sessions)
    assert job.state == "passed" and job.merge_mode == "approve" and job.merge_state == ""
    assert "menunggu Merge di Kemudi" in taiga.texts(1)[-1]
    assert "qa" not in runner.calls
    with sessions() as db:
        assert _merge_blocker(db, "kemudi", db.get(AwakJob, job.id)) is None


def test_off_mode_runs_no_gates(tmp_path, repo):
    w, taiga, sessions, runner = _worker(tmp_path, repo, "off")
    set_mode(sessions, merge_mode="manual")
    taiga.add(1, 12, "Badge jumlah", DESC)
    assert w.tick()
    assert taiga.status_of(1) == "done"
    assert runner.calls == ["install", "commit", "clean_check"]
    text = taiga.texts(1)[-1]
    assert "Mode QA proyek: Off" in text
    assert "Tidak diperiksa" in text and "pemeriksaan otomatis" in text
    assert "belum di-merge" in text


def test_browser_mode_runs_qa(tmp_path, repo):
    w, taiga, sessions, runner = _worker(tmp_path, repo, "browser",
                                         runner=FakeRunner(tmp_path / "ws", qa=["pass"]))
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    assert "qa" in runner.calls and "QA lulus" in taiga.texts(1)[-1]


def test_browser_without_a_way_to_run_qa_is_gates(tmp_path):
    """Browser QA needs the Kemudi repo (or, later, a runbook)."""
    from .test_workspace import _project, make_remote
    from kemudi_ai.awak.worker import Worker
    from .awak_fakes import FakeTaiga

    web = make_remote(tmp_path, "web", {"README.md": "web"})
    settings = Settings(awak_projects="", ai_db_url="sqlite:///:memory:",
                        repos_dir=str(tmp_path / "repos"), workspace_dir=str(tmp_path / "ws"),
                        awak_uid=0)
    sessions = make_session(settings.ai_db_url)
    _project(sessions, "demo", [("web", str(web))])
    set_mode(sessions, "demo", qa_mode="browser")
    taiga = FakeTaiga()
    runner = FakeRunner(tmp_path / "ws")
    w = Worker(settings, sessions, taiga, FakeTaiga("awak-qa"), FakeAgent(), runner, None,
               secret_values=[], sleep=lambda s: None)
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    assert taiga.status_of(1) == "done" and "qa" not in runner.calls
    text = taiga.texts(1)[-1]
    assert "Browser" in text and "Gates only" in text


# --- merge --------------------------------------------------------------------------

@pytest.fixture
def merge_repo(tmp_path, remote):
    return Repo(str(tmp_path / "bare.git"), str(remote), str(tmp_path / "ws"), uid=0,
                slug="kemudi", name="kemudi")


def test_gates_mode_merge_regates_without_qa(tmp_path, merge_repo, remote):
    w, taiga, sessions, runner = make_merge(tmp_path, merge_repo)
    set_mode(sessions, qa_mode="gates")
    w.tick()
    assert "qa" not in runner.calls
    other = advance(tmp_path, remote)
    request(sessions)
    n = len(runner.calls)
    w.tick()
    job = job_of(sessions)
    assert runner.calls[n:] == ["install", "gates"]
    assert job.merge_state == "merged" and rev(remote) == job.merged_sha != other


# --- settings API -------------------------------------------------------------------

def test_put_settings_qa_mode_rules(agent_client):
    url = "/projects/demo/agent/settings"
    r = agent_client.put(url, headers=ADMIN, json=SETTINGS)
    assert r.status_code == 200 and r.json()["qa_mode"] == "gates"
    r = agent_client.put(url, headers=ADMIN, json={**SETTINGS, "qa_mode": "off"})
    assert r.status_code == 200 and r.json()["qa_mode"] == "off"
    # omitted: kept
    assert agent_client.put(url, headers=ADMIN, json=SETTINGS).json()["qa_mode"] == "off"
    # auto merge needs browser QA
    r = agent_client.put(url, headers=ADMIN, json={**SETTINGS, "merge_mode": "auto",
                                                   "qa_mode": "gates"})
    assert r.status_code == 422 and "browser" in r.text.lower()
    r = agent_client.put(url, headers=ADMIN, json={**SETTINGS, "merge_mode": "auto"})
    assert r.status_code == 422  # the stored mode (off) counts when omitted
    # browser needs a way to run QA: no runbook yet, and no Kemudi repo
    r = agent_client.put(url, headers=ADMIN, json={**SETTINGS, "qa_mode": "browser"})
    assert r.status_code == 422 and "runbook" in r.text
    assert agent_client.put(url, headers=ADMIN, json={**SETTINGS, "qa_mode": "nope"}
                            ).status_code == 422
    with agent_client.S() as db:
        db.add(AwakRepo(project_slug="demo", name="kemudi",
                        url=agent_client.settings.host_git))
        db.commit()
    r = agent_client.put(url, headers=ADMIN, json={**SETTINGS, "merge_mode": "auto",
                                                   "qa_mode": "browser"})
    assert r.status_code == 200 and r.json()["merge_mode"] == "auto"
    with agent_client.S() as db:
        d = db.query(Decision).filter_by(action="awak_settings").all()[-1]
        assert d.detail["changed"]["qa_mode"] == "browser"


# --- migration ----------------------------------------------------------------------

def test_migration_sets_qa_mode_once(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as c:
        c.execute(text("ALTER TABLE awak_projects DROP COLUMN qa_mode"))
        for slug, mode in (("kemudi", "auto"), ("playfast", "auto"), ("other", "manual")):
            c.execute(text(
                "INSERT INTO awak_projects (slug, enabled, merge_mode, deploy_command, executor,"
                " ssh_host, ssh_port, ssh_user, preflight, llm_base_url, llm_model,"
                " llm_api_key_enc, llm_key_last4, last_error, updated_by, updated_at) VALUES"
                f" ('{slug}', 1, '{mode}', '', 'local', '', 22, '', '{{}}', '', '', '', '', '',"
                " '', '2026-11-14 10:00:00')"))
        for i, (slug, url) in enumerate((("kemudi", "/host-git"),
                                         ("playfast", "git@github.com:acme/pf.git"))):
            c.execute(text(
                "INSERT INTO awak_repos (id, project_slug, name, role, url, default_branch,"
                " subdir, install_cmd, check_cmd, build_cmd, run_cmd, last_check, position,"
                f" updated_by, updated_at) VALUES ({i + 1}, '{slug}', 'r', 'web', '{url}', 'main',"
                " '', '', '', '', '', '{}', 0, '', '2026-11-14 10:00:00')"))
    init_db(engine, host_git="/host-git")
    S = make_session(f"sqlite:///{tmp_path / 'old.db'}")
    with S() as db:
        modes = {p.slug: (p.qa_mode, p.merge_mode) for p in db.query(AwakProject)}
        assert modes == {"kemudi": ("browser", "auto"), "playfast": ("gates", "approve"),
                         "other": ("gates", "manual")}
        d = db.query(Decision).filter_by(action="awak_settings").one()
        assert d.subject == "playfast" and d.detail["changed"] == {"merge_mode": "approve"}
        db.get(AwakProject, "playfast").merge_mode = "auto"
        db.commit()
    init_db(engine, host_git="/host-git")  # every row has a mode: no second fix-up
    with S() as db:
        assert db.get(AwakProject, "playfast").merge_mode == "auto"


def test_migration_fix_up_resumes_after_a_crash(tmp_path):
    """The column was added but the process died before the fix-up: the next
    start still sets the modes (NULL marks a project not yet fixed up)."""
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as c:
        c.execute(text("ALTER TABLE awak_projects DROP COLUMN qa_mode"))
        c.execute(text(
            "INSERT INTO awak_projects (slug, enabled, merge_mode, deploy_command, executor,"
            " ssh_host, ssh_port, ssh_user, preflight, llm_base_url, llm_model,"
            " llm_api_key_enc, llm_key_last4, last_error, updated_by, updated_at) VALUES"
            " ('playfast', 1, 'auto', '', 'local', '', 22, '', '{}', '', '', '', '', '',"
            " '', '2026-11-14 10:00:00')"))
        c.execute(text("ALTER TABLE awak_projects ADD COLUMN qa_mode VARCHAR(10)"))  # crash
    init_db(engine, host_git="/host-git")
    S = make_session(f"sqlite:///{tmp_path / 'old.db'}")
    with S() as db:
        p = db.get(AwakProject, "playfast")
        assert (p.qa_mode, p.merge_mode) == ("gates", "approve")
        db.add(AwakProject(slug="new", enabled=False, merge_mode="auto", qa_mode="browser"))
        db.commit()
    init_db(engine, host_git="/host-git")
    with S() as db:
        assert db.get(AwakProject, "new").qa_mode == "browser"
