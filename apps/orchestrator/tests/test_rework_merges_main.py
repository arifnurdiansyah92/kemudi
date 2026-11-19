"""A branch made before other stories landed: a rework brings the default
branch into it first, and the coder resolves what conflicts."""

import subprocess

from kemudi_ai.awak.worker import conflict_task, unresolved
from kemudi_ai.store import AwakEvent

from .awak_fakes import FakeAgent, FakeRunner, commit_file, git
from .test_awak import DESC, host, job_of, make_worker, repo  # noqa: F401 (fixtures)


def land(host, name, content):  # noqa: F811
    """Another story's commit lands on the default branch."""
    commit_file(host, name, content)


def log(d):
    return subprocess.run(["git", "log", "--format=%s"], cwd=d, capture_output=True,
                          text=True).stdout.splitlines()


def events(sessions, kind):
    with sessions() as db:
        return [e.detail for e in db.query(AwakEvent).filter_by(kind=kind).order_by(AwakEvent.id)]


# --- git --------------------------------------------------------------------------

def test_merge_default_is_a_noop_when_the_branch_has_it(repo, host):  # noqa: F811
    repo.sync_default()
    d = repo.prepare("awak/us-3")
    commit_file(d, "x.txt", "x\n")
    repo.collect("awak/us-3")
    repo.prepare("awak/us-3")
    assert repo.merge_default("awak/us-3") is None


def test_merge_default_brings_in_what_landed(repo, host):  # noqa: F811
    repo.sync_default()
    d = repo.prepare("awak/us-3")
    commit_file(d, "x.txt", "x\n")
    repo.collect("awak/us-3")
    land(host, "other.txt", "theirs\n")
    repo.sync_default()
    d = repo.prepare("awak/us-3")
    assert repo.merge_default("awak/us-3") == []
    assert (d / "other.txt").exists() and (d / "x.txt").exists()
    assert log(d)[0] == "Merge main into awak/us-3"
    repo.collect("awak/us-3")
    assert repo.changed_files("awak/us-3") == ["x.txt"]  # only the story's own change


def test_merge_default_leaves_a_conflict_open(repo, host):  # noqa: F811
    repo.sync_default()
    d = repo.prepare("awak/us-3")
    commit_file(d, "README.md", "ours\n")
    repo.collect("awak/us-3")
    land(host, "README.md", "theirs\n")
    repo.sync_default()
    d = repo.prepare("awak/us-3")
    assert repo.merge_default("awak/us-3") == ["README.md"]
    assert unresolved(d, ["README.md"]) == ["README.md"]
    (d / "README.md").write_text("ours and theirs\n", newline="\n")
    assert unresolved(d, ["README.md", "gone.txt"]) == []
    git(d, "add", "-A")
    git(d, "commit", "--no-edit")  # the coder finishes the merge
    assert log(d)[0] == "Merge main into awak/us-3"


def test_conflict_task_names_the_files_and_how_to_finish():
    text = conflict_task("master", ["backend/app/security.py", "a b.txt"])
    assert "- backend/app/security.py" in text and "- a b.txt" in text
    assert "git add -A && git commit --no-edit" in text and "`master`" in text


# --- the loop ---------------------------------------------------------------------

def rework(tmp_path, repo, host, code):  # noqa: F811
    """Attempt 1 fails QA; before attempt 2 another story lands a change to
    README.md on main. `code(workdir, n)` is the coder."""
    def coder(d, n):
        if n == 1:
            commit_file(d, "README.md", "ours\n")
            land(host, "README.md", "theirs\n")
        else:
            code(d, n)

    agent = FakeAgent(code=coder)
    runner = FakeRunner(tmp_path / "ws", qa=["fail", "pass", "pass"])
    w, taiga, sessions = make_worker(tmp_path, repo, agent, runner)
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    return agent, taiga, sessions


def test_rework_merges_main_and_the_coder_resolves_the_conflict(tmp_path, repo, host):  # noqa: F811
    def resolve(d, n):
        (d / "README.md").write_text("ours and theirs\n", newline="\n")
        git(d, "add", "-A")
        git(d, "commit", "--no-edit")

    agent, taiga, sessions = rework(tmp_path, repo, host, resolve)
    assert taiga.status_of(1) == "done"
    tasks = [t for p, t in agent.calls if p == "awak.code"]
    assert "conflict markers" in tasks[1] and "- README.md" in tasks[1]
    assert "AC1" in tasks[1]  # the QA failure is still there, after the conflict
    (ev,) = events(sessions, "main_merged")
    assert ev["conflicts"] == ["README.md"]
    assert repo.is_ancestor(repo.sha("main"), job_of(sessions).last_sha)


def test_markers_left_in_a_file_fail_the_attempt(tmp_path, repo, host):  # noqa: F811
    seen = []

    def lazy(d, n):
        seen.append(n)
        if n == 2:  # commits the file as the merge left it
            git(d, "add", "-A")
            git(d, "commit", "--no-edit")
        else:
            (d / "README.md").write_text("ours and theirs\n", newline="\n")
            git(d, "add", "-A")
            git(d, "commit", "-m", "resolve")

    agent, taiga, sessions = rework(tmp_path, repo, host, lazy)
    assert any("Konflik dengan `main` belum selesai di `README.md`" in t for t in taiga.texts(1))
    tasks = [t for p, t in agent.calls if p == "awak.code"]
    assert "Conflict markers" in tasks[2] and "README.md" in tasks[2]
    assert taiga.status_of(1) == "done" and seen == [2, 3]
