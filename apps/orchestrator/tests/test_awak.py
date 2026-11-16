import subprocess
from pathlib import Path

import pytest

from kemudi_ai.awak import secrets
from kemudi_ai.awak.agent import AgentError
from kemudi_ai.awak.gitops import GitError, Repo
from kemudi_ai.awak.intake import StoryDraft, create_stories, draft_stories
from kemudi_ai.awak.stories import criteria, format_description
from kemudi_ai.awak.taiga import TaigaError, assert_local
from kemudi_ai.awak.verdict import evaluate, safe_screenshot
from kemudi_ai.awak.worker import Worker
from kemudi_ai.config import Settings
from kemudi_ai.store import AwakJob, AwakProject, AwakRepo, AwakRole, make_session

from .awak_fakes import PNG, FakeAgent, FakeRunner, FakeTaiga, commit_file, git, qa_report
from .fakes import FakeLLM

DESC = format_description("Tampilkan jumlah story.", ["Badge jumlah tampil", "Angka benar"])


# --- pure pieces ----------------------------------------------------------------

def test_criteria_roundtrip_and_human_formats():
    assert criteria(DESC) == ["Badge jumlah tampil", "Angka benar"]
    assert criteria("Intro\n\nKriteria penerimaan:\n- [ ] satu\n* dua\n\nCatatan:\n- bukan") == [
        "satu", "dua"]
    assert criteria("no criteria here") == []
    # a plain-text heading, as people type it in the board
    assert criteria("Acceptance Criteria\n- klik gambar membuka modal") == [
        "klik gambar membuka modal"]
    assert criteria("Intro\n\n**Acceptance criteria**\n- satu") == ["satu"]


def test_auto_ready_rules():
    assert StoryDraft(subject="a", criteria=["x"]).auto_ready() == (True, "")
    assert not StoryDraft(subject="a", criteria=["x"], area="backend").auto_ready()[0]
    assert not StoryDraft(subject="a", criteria=["1", "2", "3", "4", "5"]).auto_ready()[0]
    assert not StoryDraft(subject="a").auto_ready()[0]
    assert StoryDraft(subject="a", area="weird").area == "both"


def test_intake_creates_ready_and_held_stories():
    llm = FakeLLM({"awak.intake": [{"stories": [
        {"subject": "Badge", "description": "d", "criteria": "- satu\n- dua", "area": "web"},
        {"subject": "API baru", "criteria": ["x"], "area": "backend"},
    ]}]})
    taiga = FakeTaiga()
    created = create_stories(taiga, "kemudi", draft_stories(llm, "butuh badge"))
    assert [c["ready"] for c in created] == [True, False]
    first, second = (taiga.stories_by_id[c["id"]] for c in created)
    assert taiga.status_of(first["id"]) == "ready"
    assert first["tags"] == [["agent-ready", None], ["area-web", None]]
    assert taiga.status_of(second["id"]) == "new" and second["tags"] == [["area-backend", None]]
    assert "backend" in taiga.texts(second["id"])[0]
    assert criteria(first["description"]) == ["satu", "dua"]


def test_refuses_non_local_taiga():
    assert_local("http://kemudi-back:8000/api/v1")
    with pytest.raises(TaigaError, match="refusing"):
        assert_local("https://taiga.aegis.co.id/api/v1")


def test_verdict_rules(tmp_path):
    crit = ["a", "b"]
    assert evaluate({"infra_error": "vite down"}, crit).outcome == "infra"
    assert evaluate(qa_report(["passed"], ["s"]), crit).outcome == "spec"  # AC2 missing
    flaky = qa_report(["passed", "passed"], ["s", "s"])
    flaky["runs"][1]["tests"][1]["status"] = "failed"
    assert evaluate(flaky, crit).outcome == "infra"
    assert evaluate(qa_report(["passed", "failed"], ["s", "s"]), crit).outcome == "fail"
    no_shots = evaluate(qa_report(["passed", "passed"]), crit)
    assert no_shots.outcome == "fail" and "screenshot" in no_shots.criteria[0].error
    assert evaluate(qa_report(["passed", "passed"], ["s", "s"]), crit).outcome == "pass"


def test_safe_screenshot(tmp_path):
    qa = tmp_path / "job" / ".qa"
    qa.mkdir(parents=True)
    good = qa / "a.png"
    good.write_bytes(PNG)
    fake = qa / "b.png"
    fake.write_bytes(b"not a png")
    outside = tmp_path / "secret.png"
    outside.write_bytes(PNG)
    assert safe_screenshot(str(good), qa) == good.resolve()
    assert safe_screenshot(str(fake), qa) is None
    assert safe_screenshot(str(outside), qa) is None
    assert safe_screenshot(str(qa / ".." / ".." / "secret.png"), qa) is None


def test_secret_scan():
    values = secrets.known_values({"KEMUDI_AI_API_KEY": "sk-live-abcdefgh12345678",
                                   "KEMUDI_AI_MODEL": "deepseek-flash"})
    assert values == ["sk-live-abcdefgh12345678"]
    diff = ("+++ b/src/a.ts\n+const k = 'sk-live-abcdefgh12345678'\n"
            "+++ b/src/b.ts\n+const ok = 1\n")
    assert secrets.files_with_secrets(diff, values) == ["src/a.ts"]
    assert "sk-live" not in secrets.redact("key sk-live-abcdefgh12345678", values)


# --- git ------------------------------------------------------------------------

@pytest.fixture
def host(tmp_path):
    h = tmp_path / "host"
    h.mkdir()
    git(h, "init", "-b", "main")
    git(h, "config", "user.email", "t@t")
    git(h, "config", "user.name", "t")
    (h / "README.md").write_text("hi")
    git(h, "add", "-A")
    git(h, "commit", "-m", "init")
    return h


@pytest.fixture
def repo(tmp_path, host):
    return Repo(str(tmp_path / "bare.git"), str(host / ".git"), str(tmp_path / "ws"), uid=0,
                slug="kemudi", name="kemudi")


def test_git_roundtrip_pushes_only_awak_branches(repo, host):
    repo.sync_main()
    d = repo.prepare("awak/us-3")
    commit_file(d, "x.txt", "x")
    sha = repo.collect("awak/us-3")
    assert repo.changed_files("awak/us-3") == ["x.txt"]
    repo.push_host("awak/us-3")
    out = subprocess.run(["git", "rev-parse", "awak/us-3"], cwd=host, capture_output=True,
                         text=True).stdout.strip()
    assert out == sha
    # the workspace cannot push anywhere: no remote
    assert subprocess.run(["git", "remote"], cwd=d, capture_output=True, text=True).stdout == ""
    with pytest.raises(GitError):
        repo.push_host("main")
    with pytest.raises(GitError):
        repo.prepare("feature/x")


def test_changed_files_lists_both_sides_of_a_rename(repo):
    repo.sync_main()
    d = repo.prepare("awak/us-4")
    (d / "apps" / "web").mkdir(parents=True)
    git(d, "mv", "README.md", "apps/web/README.md")
    git(d, "commit", "-m", "move")
    repo.collect("awak/us-4")
    assert sorted(repo.changed_files("awak/us-4")) == ["README.md", "apps/web/README.md"]


def test_rework_reuses_branch(repo):
    repo.sync_main()
    d = repo.prepare("awak/us-3")
    commit_file(d, "x.txt", "x")
    repo.collect("awak/us-3")
    d2 = repo.prepare("awak/us-3")
    assert (d2 / "x.txt").exists()


# --- the loop -------------------------------------------------------------------

def make_worker(tmp_path, repo, agent, runner, taiga=None):
    settings = Settings(awak_projects="kemudi", ai_db_url="sqlite:///:memory:",
                        workspace_dir=str(tmp_path / "ws"))
    sessions = make_session(settings.ai_db_url)
    taiga = taiga or FakeTaiga()
    w = Worker(settings, sessions, taiga, FakeTaiga("awak-qa"), agent, runner, repo,
               secret_values=["super-secret-value"], sleep=lambda s: None)
    return w, taiga, sessions


def job_of(sessions):
    with sessions() as db:
        return db.query(AwakJob).one()


def test_happy_path_moves_to_done_with_evidence(tmp_path, repo):
    runner = FakeRunner(tmp_path / "ws", qa=["pass"])
    w, taiga, sessions = make_worker(tmp_path, repo, FakeAgent(), runner)
    taiga.add(1, 12, "Badge jumlah", DESC)
    assert w.tick()
    assert taiga.status_of(1) == "done"
    st = taiga.story(1)
    assert ["awaiting-merge", None] in st["tags"]
    assert len(taiga.attachments) == 2
    texts = taiga.texts(1)
    assert "QA lulus" in texts[-1] and "belum di-merge" in texts[-1]
    assert job_of(sessions).state == "passed"
    assert runner.calls == ["install", "commit", "gates", "discard", "qa_reset", "qa",
                            "clean_check"]
    assert not w.tick()  # nothing left


def test_qa_fail_reworks_with_feedback_then_passes(tmp_path, repo):
    runner = FakeRunner(tmp_path / "ws", qa=["fail", "pass"])
    agent = FakeAgent()
    w, taiga, sessions = make_worker(tmp_path, repo, agent, runner)
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    assert taiga.status_of(1) == "done"
    code_tasks = [t for p, t in agent.calls if p == "awak.code"]
    assert len(code_tasks) == 2
    assert "rework" in code_tasks[1] and "AC1" in code_tasks[1]
    assert any("QA gagal" in t for t in taiga.texts(1))
    assert job_of(sessions).attempts == 2


def test_gate_failure_feeds_output_back(tmp_path, repo):
    runner = FakeRunner(tmp_path / "ws", qa=["pass"], gates=[
        {"gates": [{"name": "tsc -b", "ok": False, "output": "error TS2322: nope"}]},
    ])
    agent = FakeAgent()
    w, taiga, _ = make_worker(tmp_path, repo, agent, runner)
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    code_tasks = [t for p, t in agent.calls if p == "awak.code"]
    assert "TS2322" in code_tasks[1]
    assert taiga.status_of(1) == "done"


def test_gives_up_after_max_attempts_and_blocks(tmp_path, repo):
    runner = FakeRunner(tmp_path / "ws", qa=["fail", "fail", "fail"])
    w, taiga, sessions = make_worker(tmp_path, repo, FakeAgent(), runner)
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    st = taiga.story(1)
    assert st["is_blocked"] and ["needs-human", None] in st["tags"]
    assert st["assigned_to"] == 5  # the owner
    assert job_of(sessions).state == "failed"
    assert not w.tick()  # blocked stories are left alone


def test_moving_a_blocked_story_back_unblocks_it_and_reworks(tmp_path, repo):
    runner = FakeRunner(tmp_path / "ws", qa=["fail", "fail", "fail", "pass"])
    agent = FakeAgent()
    w, taiga, sessions = make_worker(tmp_path, repo, agent, runner)
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    assert taiga.story(1)["is_blocked"]
    assert "pindahkan kartu ke In progress" in taiga.texts(1)[-1]
    taiga.human_comment(1, "Pakai warna merah untuk badge")
    assert not w.tick()  # a comment alone is no answer yet
    taiga.human_move(1, "in-progress")
    assert w.tick()
    st = taiga.story(1)
    assert not st["is_blocked"] and st["blocked_note"] == ""
    assert ["needs-human", None] not in st["tags"] and ["agent-ready", None] in st["tags"]
    assert "Pakai warna merah" in [t for p, t in agent.calls if p == "awak.code"][-1]
    assert taiga.status_of(1) == "done"
    assert job_of(sessions).attempts == 1  # a fresh set of attempts


def test_a_human_block_or_an_unanswered_one_stays(tmp_path, repo):
    runner = FakeRunner(tmp_path / "ws", qa=["fail", "fail", "fail"])
    w, taiga, sessions = make_worker(tmp_path, repo, FakeAgent(), runner)
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    taiga.human_comment(1, "nanti saya cek")
    assert not w.tick() and taiga.story(1)["is_blocked"]
    # Blocked by a person (no needs-human tag): never lifted by Awak.
    taiga.add(2, 13, "Lain", DESC, status="in-progress")
    taiga.update_story(2, is_blocked=True)
    taiga.human_move(2, "ready")
    assert not w.tick()
    assert taiga.story(2)["is_blocked"]


def test_human_moved_after_block_reads_the_history():
    from kemudi_ai.awak.worker import human_moved_after_block

    bots = {"awak"}

    def h(t, user, diff):
        return {"created_at": f"2026-11-16T00:00:{t:02d}Z", "user": {"username": user},
                "values_diff": diff}

    blocked = h(2, "awak", {"is_blocked": [False, True]})
    assert human_moved_after_block([h(3, "pm", {"status": [4, 3]}), blocked], bots) == "pm"
    assert human_moved_after_block([blocked, h(1, "pm", {"status": [2, 3]})], bots) == ""
    assert human_moved_after_block([h(3, "pm", {"status": [4, 3]})], bots) == ""
    assert human_moved_after_block([blocked, h(3, "awak", {"status": [3, 4]}),
                                    h(4, "pm", {"tags": [[], ["x"]]})], bots) == ""


def test_no_commit_is_fixed_in_the_same_attempt(tmp_path, repo):
    agent = FakeAgent(code=lambda d, n: None if n == 1 else commit_file(d, "f.txt", "x"))
    runner = FakeRunner(tmp_path / "ws", qa=["pass"])
    w, taiga, sessions = make_worker(tmp_path, repo, agent, runner)
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    assert any("tidak menghasilkan commit" in t for t in taiga.texts(1))
    assert taiga.status_of(1) == "done" and job_of(sessions).attempts == 1


def test_secret_in_diff_is_never_pushed(tmp_path, repo, host):
    agent = FakeAgent(code=lambda d, n: commit_file(
        d, f"cfg{n}.ts", "k='super-secret-value'" if n == 1 else "ok"))
    runner = FakeRunner(tmp_path / "ws", qa=["pass"])
    w, taiga, _ = make_worker(tmp_path, repo, agent, runner)
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    first_fail = next(t for t in taiga.texts(1) if "secret" in t)
    assert "cfg1.ts" in first_fail and "super-secret-value" not in first_fail
    # The second attempt still carries the secret in history -> fails again; the
    # branch never reaches the host repo.
    branches = subprocess.run(["git", "branch", "--list", "awak/*"], cwd=host,
                              capture_output=True, text=True).stdout
    assert branches.strip() == ""


def test_backend_change_is_rejected(tmp_path, repo):
    def code(d, n):
        if n == 1:
            (d / "services" / "kemudi-back").mkdir(parents=True)
            commit_file(d, "services/kemudi-back/x.py", "x")
        else:
            git(d, "rm", "-q", "services/kemudi-back/x.py")
            commit_file(d, "web.txt", "x")
    runner = FakeRunner(tmp_path / "ws", qa=["pass"])
    w, taiga, _ = make_worker(tmp_path, repo, FakeAgent(code=code), runner)
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    assert any("di luar cakupan peran Frontend dev" in t and "services/kemudi-back/x.py" in t
               for t in taiga.texts(1))
    assert taiga.status_of(1) == "done"


def test_infra_error_does_not_use_an_attempt(tmp_path, repo):
    agent = FakeAgent(fail_with=[AgentError("timeout")])
    runner = FakeRunner(tmp_path / "ws", qa=["pass"])
    w, taiga, sessions = make_worker(tmp_path, repo, agent, runner)
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    job = job_of(sessions)
    assert taiga.status_of(1) == "done"
    assert job.attempts == 1 and job.infra_errors == 1
    assert any("Gangguan lingkungan" in t for t in taiga.texts(1))


def test_human_moving_the_card_stops_the_job(tmp_path, repo):
    taiga = FakeTaiga()

    def code(d, n):
        commit_file(d, "f.txt", "x")
        taiga.stories_by_id[1]["status"] = 1  # PM drags it back to New mid-run

    w, taiga, sessions = make_worker(tmp_path, repo, FakeAgent(code=code),
                                     FakeRunner(tmp_path / "ws"), taiga)
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    assert job_of(sessions).state == "stopped"
    assert "Berhenti" in taiga.texts(1)[-1]


def test_human_sends_done_story_back_for_rework(tmp_path, repo):
    runner = FakeRunner(tmp_path / "ws", qa=["pass", "pass"])
    agent = FakeAgent()
    w, taiga, sessions = make_worker(tmp_path, repo, agent, runner)
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    taiga.human_comment(1, "Warnanya harus hijau, bukan biru.")
    taiga.update_story(1, status=3)  # PM moves it back to In progress
    assert w.tick()
    code_tasks = [t for p, t in agent.calls if p == "awak.code"]
    assert "Warnanya harus hijau" in code_tasks[-1]
    assert taiga.status_of(1) == "done"


def test_recover_marks_running_jobs_queued(tmp_path, repo):
    w, taiga, sessions = make_worker(tmp_path, repo, FakeAgent(),
                                     FakeRunner(tmp_path / "ws", qa=["pass"]))
    taiga.add(1, 12, "Badge jumlah", DESC, status="in-progress")
    with sessions() as db:
        db.add(AwakJob(project_slug="kemudi", story_id=1, story_ref=12,
                       branch="awak/us-12", state="running"))
        db.commit()
    w.recover()
    assert w.tick()
    assert taiga.status_of(1) == "done"


def test_story_without_criteria_stops(tmp_path, repo):
    runner = FakeRunner(tmp_path / "ws")
    w, taiga, sessions = make_worker(tmp_path, repo, FakeAgent(), runner)
    taiga.add(1, 12, "Badge jumlah", "Tanpa kriteria.")
    w.tick()
    assert job_of(sessions).state == "failed"
    assert "kriteria" in taiga.texts(1)[-1]
    # Blocked for a human, so the next tick does not pick it again.
    assert taiga.story(1)["is_blocked"] and ["needs-human", None] in taiga.story(1)["tags"]
    assert not w.tick()


def test_infra_error_after_coding_resumes_without_recoding(tmp_path, repo):
    agent = FakeAgent()
    runner = FakeRunner(tmp_path / "ws", qa=["pass"])
    w, taiga, sessions = make_worker(tmp_path, repo, agent, runner)
    taiga.add(1, 12, "Badge jumlah", DESC)
    real_collect, calls = repo.collect, []

    def flaky_collect(branch):
        calls.append(branch)
        if len(calls) == 1:
            raise GitError("dubious ownership")
        return real_collect(branch)

    repo.collect = flaky_collect
    w.tick()
    assert taiga.status_of(1) == "done"
    assert [p for p, _ in agent.calls].count("awak.code") == 1
    assert job_of(sessions).infra_errors == 1


# --- iteration 2: projects come from the database -------------------------------

def test_worker_serves_db_enabled_projects(tmp_path, repo):
    settings = Settings(awak_projects="", ai_db_url="sqlite:///:memory:",
                        workspace_dir=str(tmp_path / "ws"))
    sessions = make_session(settings.ai_db_url)
    with sessions() as db:
        db.add(AwakProject(slug="kemudi", enabled=True, merge_mode="manual"))
        repo_row = AwakRepo(project_slug="kemudi", name="kemudi", url=settings.host_git,
                            subdir="apps/web")
        db.add(repo_row)
        db.flush()
        db.add(AwakRole(project_slug="kemudi", template="frontend", name="FE", area="web",
                        model="m", repo_ids=[repo_row.id]))
        db.commit()
    taiga = FakeTaiga()
    w = Worker(settings, sessions, taiga, FakeTaiga("awak-qa"), FakeAgent(),
               FakeRunner(tmp_path / "ws", qa=["pass"]), repo,
               secret_values=["super-secret-value"], sleep=lambda s: None)
    taiga.add(1, 12, "Badge jumlah", DESC)
    assert w.tick()
    assert taiga.status_of(1) == "done"
    with sessions() as db:
        db.get(AwakProject, "kemudi").enabled = False
        db.commit()
    taiga.add(2, 13, "Lain", DESC)
    assert not w.tick()  # disabled projects are not served


def test_disabling_mid_job_stops(tmp_path, repo):
    holder = {}

    def code(d, n):
        commit_file(d, "f.txt", "x")
        with holder["S"]() as db:
            db.get(AwakProject, "kemudi").enabled = False
            db.commit()

    w, taiga, sessions = make_worker(tmp_path, repo, FakeAgent(code=code),
                                     FakeRunner(tmp_path / "ws", qa=["pass"]))
    holder["S"] = sessions
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    assert job_of(sessions).state == "stopped"
    assert taiga.status_of(1) == "in-progress"
    assert "dimatikan" in taiga.texts(1)[-1]


def test_build_output_allowlist():
    from kemudi_ai.awak.worker import build_output

    ok = [("??", ".qa/"), ("!!", ".qa/logs/web.log"), ("??", ".qa/spec/story.spec.ts"),
          ("!!", "node_modules/"), ("!!", "apps/web/node_modules/"),
          ("!!", "apps/web/dist/"), ("??", "dist/"), ("!!", "tsconfig.app.tsbuildinfo"),
          ("!!", "svc/pkg/__pycache__/"), ("!!", "apps/web/.vite/")]
    bad = [(" M", "dist/"), ("??", "src/dist/"), ("!!", ".env.local"), ("??", "apps/.qa/"),
           ("!!", "src/generated.ts"), ("??", "dist"), ("D ", "README.md")]
    assert all(build_output(s, p, "apps/web") for s, p in ok)
    assert not any(build_output(s, p, "apps/web") for s, p in bad)
    # runbook app dirs (Next.js leaves .next/ after QA's dev server)
    assert build_output("!!", "frontend/.next/", ["", "frontend", "backend"])
    assert build_output("!!", "backend/.pytest_cache/", ["frontend", "backend"])
    assert not build_output("!!", "frontend/.next/", "apps/web")
    # Ignored files an install writes: next-env.d.ts in an app dir, runbook globs.
    assert build_output("!!", "frontend/next-env.d.ts", ["frontend"])
    assert not build_output("??", "frontend/next-env.d.ts", ["frontend"])
    assert not build_output("!!", "frontend/src/next-env.d.ts", ["frontend"])
    gen = ["frontend/src/assets/iconify-icons/generated-*.css"]
    assert build_output("!!", "frontend/src/assets/iconify-icons/generated-icons.css",
                        ["frontend"], gen)
    assert not build_output("??", "frontend/src/assets/iconify-icons/generated-icons.css",
                            ["frontend"], gen)
    assert not build_output("!!", "frontend/src/other.css", ["frontend"], gen)


def test_runbook_generated_globs_are_validated():
    from kemudi_ai.awak.runbook import validate

    def app(generated):
        return {"apps": [{"name": "web", "repo": "r", "dir": "frontend",
                          "generated": generated}], "services": [], "env": []}

    rb, problems = validate(app(["src/assets/generated-*.css", "next-env.d.ts"]), {"r"})
    assert rb is not None and problems == []
    for bad in (["../x"], ["/etc/x"], ["*"], ["src/**"], ["a b"]):
        _, problems = validate(app(bad), {"r"})
        assert any("generated" in p for p in problems), bad


def test_ignored_file_during_qa_stops_for_a_human(tmp_path, repo):
    """A QA pass with an unknown ignored file in the workspace is not used,
    and a human decides (runbook `generated`) instead of the agent."""
    def code(d, n):
        if n == 1:
            commit_file(d, ".gitignore", "local.env\n")
            (d / "local.env").write_text("FEATURE=on")  # ignored: never committed
        commit_file(d, f"feature{n}.txt", "x")

    runner = FakeRunner(tmp_path / "ws", qa=["pass", "pass"])
    w, taiga, sessions = make_worker(tmp_path, repo, FakeAgent(code=code), runner)
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    stop = next(t for t in taiga.texts(1) if "Berhenti" in t)
    assert "local.env" in stop and "feature1.txt" not in stop
    assert taiga.status_of(1) != "done" and job_of(sessions).state == "failed"


def test_head_moved_after_gates_fails_the_attempt(tmp_path, repo):
    runner = FakeRunner(tmp_path / "ws", qa=["pass", "pass"],
                        clean=[{"ok": True, "head": "f" * 40, "entries": []}])
    agent = FakeAgent()
    w, taiga, sessions = make_worker(tmp_path, repo, agent, runner)
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    assert any("tidak sama dengan commit" in t and "HEAD ffffffff" in t
               for t in taiga.texts(1))
    code_tasks = [t for p, t in agent.calls if p == "awak.code"]
    assert "HEAD was not your commit" in code_tasks[1]
    assert taiga.status_of(1) == "done" and job_of(sessions).attempts == 2


# --- one worker at a time --------------------------------------------------------

def test_only_one_worker_holds_the_lease(tmp_path, repo):
    from datetime import datetime

    from kemudi_ai.store import AwakWorkerLease

    w1, taiga, sessions = make_worker(tmp_path, repo, FakeAgent(),
                                      FakeRunner(tmp_path / "ws", qa=["pass"]))
    w2 = Worker(w1.s, sessions, taiga, FakeTaiga("awak-qa"), FakeAgent(),
                FakeRunner(tmp_path / "ws", qa=["pass"]), repo,
                secret_values=["super-secret-value"], sleep=lambda s: None)
    assert w1.claim_lease() and not w2.claim_lease()
    assert w1.claim_lease()  # renewing
    # A crash-left running job: the worker without the lease neither recovers
    # nor works on anything.
    taiga.add(1, 12, "Badge jumlah", DESC, status="in-progress")
    with sessions() as db:
        db.add(AwakJob(project_slug="kemudi", story_id=1, story_ref=12,
                       branch="awak/us-12", state="running"))
        db.commit()
    loops = iter([False, True])
    w2.run_forever(stop_flag=lambda: next(loops))
    assert job_of(sessions).state == "running" and taiga.status_of(1) == "in-progress"
    # The holder's lease lapses (it crashed): the other takes over and recovers.
    with sessions() as db:
        db.get(AwakWorkerLease, 1).expires_at = datetime(2000, 1, 1)
        db.commit()
    loops = iter([False, True])
    w2.run_forever(stop_flag=lambda: next(loops))
    assert taiga.status_of(1) == "done"
    assert w1.claim_lease()  # w2 released the lease when its loop ended


def test_human_feedback_is_the_latest_human_comment(tmp_path, repo):
    w, taiga, _ = make_worker(tmp_path, repo, FakeAgent(), FakeRunner(tmp_path / "ws"))
    taiga.add(1, 12, "Badge jumlah", DESC)
    # Newest first, as Taiga's history endpoint returns it.
    taiga.comments_by_id[1] = [
        {"user": {"username": "awak"}, "comment": "bot", "created_at": "2026-11-14T02:05:00Z"},
        {"user": {"username": "pm"}, "comment": "new", "created_at": "2026-11-14T02:01:00Z"},
        {"user": {"username": "pm"}, "comment": "old", "created_at": "2026-11-13T09:00:00Z"},
    ]
    assert w._human_feedback(1) == "new"


def test_runbook_generated_trailing_slash_is_the_same_path():
    from kemudi_ai.awak.runbook import validate

    rb, problems = validate({"apps": [{"name": "web", "repo": "r", "dir": "frontend",
                                       "generated": ["out/", "public/sw.js"]}],
                             "services": [], "env": []}, {"r"})
    assert problems == [] and rb.apps[0].generated == ["out", "public/sw.js"]


# --- fix rounds and review inside one attempt -----------------------------------

CHANGES = ('Looked at it.\n{"verdict": "changes", "issues": [{"file": "a.ts", '
           '"problem": "AC2 count ignores archived stories", "fix": "filter them"}]}')


def test_parse_review():
    from kemudi_ai.awak.stories import parse_review
    r = parse_review(CHANGES)
    assert r.blocking() and r.issues[0]["file"] == "a.ts"
    assert "AC2 count" in r.feedback() and "Fix: filter them" in r.feedback()
    fenced = parse_review('```json\n{"verdict": "approve", "issues": []}\n```')
    assert fenced.verdict == "approve" and not fenced.blocking()
    # Unreadable or "changes" without issues never blocks.
    assert parse_review("no json {here").verdict == "unparsed"
    assert not parse_review('{"verdict": "changes", "issues": []}').blocking()
    assert not parse_review('{"verdict": "maybe"}').blocking()


def test_gate_failure_is_fixed_inside_the_attempt(tmp_path, repo):
    runner = FakeRunner(tmp_path / "ws", qa=["pass"], gates=[
        {"gates": [{"name": "tsc -b", "ok": False, "output": "error TS2322: nope"}]},
    ])
    agent = FakeAgent()
    w, taiga, sessions = make_worker(tmp_path, repo, agent, runner)
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    assert taiga.status_of(1) == "done"
    code_tasks = [t for p, t in agent.calls if p == "awak.code"]
    assert len(code_tasks) == 2
    assert "fix round" in code_tasks[1] and "TS2322" in code_tasks[1]
    assert "changed things" in code_tasks[1]  # its previous report
    assert job_of(sessions).attempts == 1  # no attempt used, no card bounce
    assert any("putaran 2/3" in t for t in taiga.texts(1))


def test_review_findings_go_back_to_the_coder(tmp_path, repo):
    runner = FakeRunner(tmp_path / "ws", qa=["pass"])
    agent = FakeAgent(reviews=[CHANGES])
    w, taiga, sessions = make_worker(tmp_path, repo, agent, runner)
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    assert taiga.status_of(1) == "done" and job_of(sessions).attempts == 1
    purposes = [p for p, _ in agent.calls]
    assert purposes == ["awak.code", "awak.review", "awak.code", "awak.review", "awak.qa"]
    code_tasks = [t for p, t in agent.calls if p == "awak.code"]
    assert "AC2 count ignores archived stories" in code_tasks[1]
    review = next(r for r in agent.runs if r["purpose"] == "awak.review")
    assert "senior engineer reviewing" in review["system"]
    assert "git diff " in review["task"] and "...HEAD" in review["task"]
    assert any("Review kode" in t for t in taiga.texts(1))
    # The reviewer's workspace is put back to the reviewed commit each time.
    discards = [p for op, p in runner.payloads if op == "discard"]
    assert len(discards) == 2 and all(len(p["sha"]) == 40 for p in discards)


def test_review_in_the_last_round_does_not_block(tmp_path, repo):
    runner = FakeRunner(tmp_path / "ws", qa=["pass"])
    agent = FakeAgent(reviews=[CHANGES] * 3)
    w, taiga, sessions = make_worker(tmp_path, repo, agent, runner)
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    assert [p for p, _ in agent.calls].count("awak.code") == 3
    assert taiga.status_of(1) == "done" and job_of(sessions).attempts == 1


def test_coder_may_decline_a_review(tmp_path, repo):
    agent = FakeAgent(reviews=[CHANGES],
                      code=lambda d, n: commit_file(d, "f.txt", "x") if n == 1 else None)
    runner = FakeRunner(tmp_path / "ws", qa=["pass"])
    w, taiga, sessions = make_worker(tmp_path, repo, agent, runner)
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    assert taiga.status_of(1) == "done" and job_of(sessions).attempts == 1
    assert [p for p, _ in agent.calls].count("awak.review") == 1
    assert runner.calls.count("gates") == 1  # the reviewed commit is not re-checked


def test_fix_rounds_used_up_cost_one_attempt(tmp_path, repo):
    bad = {"gates": [{"name": "eslint", "ok": False, "output": "no-unused-vars"}]}
    runner = FakeRunner(tmp_path / "ws", qa=["pass"], gates=[bad, bad, bad])
    agent = FakeAgent()
    w, taiga, sessions = make_worker(tmp_path, repo, agent, runner)
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    assert taiga.status_of(1) == "done" and job_of(sessions).attempts == 2
    code_tasks = [t for p, t in agent.calls if p == "awak.code"]
    assert len(code_tasks) == 4
    assert "rework attempt" in code_tasks[3] and "Your report from that attempt" in code_tasks[3]


def test_no_new_commit_in_a_fix_round_fails_the_round(tmp_path, repo):
    bad = {"gates": [{"name": "eslint", "ok": False, "output": "no-unused-vars"}]}
    agent = FakeAgent(code=lambda d, n: commit_file(d, f"f{n}.txt", "x") if n != 2 else None)
    runner = FakeRunner(tmp_path / "ws", qa=["pass"], gates=[bad])
    w, taiga, sessions = make_worker(tmp_path, repo, agent, runner)
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    assert any("tidak membuat commit baru" in t for t in taiga.texts(1))
    assert taiga.status_of(1) == "done" and job_of(sessions).attempts == 1


def test_review_and_fix_rounds_can_be_turned_off(tmp_path, repo):
    runner = FakeRunner(tmp_path / "ws", qa=["pass"], gates=[
        {"gates": [{"name": "tsc -b", "ok": False, "output": "error TS2322: nope"}]},
    ])
    agent = FakeAgent()
    w, taiga, sessions = make_worker(tmp_path, repo, agent, runner)
    w.s.awak_fix_rounds, w.s.awak_review = 0, False
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    assert "awak.review" not in [p for p, _ in agent.calls]
    assert taiga.status_of(1) == "done" and job_of(sessions).attempts == 2
