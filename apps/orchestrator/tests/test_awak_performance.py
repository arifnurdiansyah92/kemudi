"""What makes a run finish well: QA failures that say why, a role that
admits a cause is outside its scope, notes kept for the next run, and a
spec writer that knows what failed last time."""

from kemudi_ai.awak import notes
from kemudi_ai.awak.stories import code_task, parse_report, qa_task, review_task
from kemudi_ai.awak.verdict import evaluate, evidence_line
from kemudi_ai.store import AwakEvent, AwakNote, AwakRole, make_session

from .awak_fakes import FakeAgent, FakeRunner, commit_file, qa_report
from .conftest import ADMIN, MEMBER
from .test_awak import DESC, host, job_of, make_worker, repo  # noqa: F401 (fixtures)

EVIDENCE = {"http": [{"method": "DELETE", "url": "/api/admin/users/7", "status": 500,
                      "body": '{"error": "Internal server error"}'}],
            "console": ["TypeError: x is undefined"]}


class Reporting(FakeAgent):
    """A FakeAgent whose coding runs end with the given reports, in order."""

    def __init__(self, reports, **kw):
        super().__init__(**kw)
        self.reports = list(reports)

    def run(self, purpose, model, system, task, **kw):
        out = super().run(purpose, model, system, task, **kw)
        if purpose == "awak.code" and self.reports:
            return self.reports.pop(0), out[1]
        return out


def failed_report(tmp_path):
    """A QA report whose AC1 fails with browser evidence."""
    shots = []
    for i in (1, 2):
        f = tmp_path / f"shot{i}.png"
        f.write_bytes(b"\x89PNG\r\n\x1a\n")
        shots.append(str(f))
    report = qa_report(["failed", "passed"], shots)
    for run in report["runs"]:
        run["tests"][0]["evidence"] = EVIDENCE
    return report


def code_tasks(agent):
    return [t for p, t in agent.calls if p == "awak.code"]


def events(sessions, kind):
    with sessions() as db:
        return [e.detail for e in db.query(AwakEvent).filter_by(kind=kind)
                .order_by(AwakEvent.id)]


def add_fullstack(sessions, repo_ids=(1,), enabled=True):
    with sessions() as db:
        role = AwakRole(project_slug="kemudi", template="fullstack", name="Fullstack",
                        area="both", model="", repo_ids=list(repo_ids), enabled=enabled)
        db.add(role)
        db.commit()
        return role.id


# --- pure pieces ----------------------------------------------------------------

def test_evidence_line_names_the_failed_request_and_the_console_error():
    line = evidence_line(EVIDENCE)
    assert line == ('DELETE /api/admin/users/7 -> 500 {"error": "Internal server error"}; '
                    "console: TypeError: x is undefined")
    assert evidence_line({"http": [{"method": "GET", "url": "/x", "status": -1}]}) \
        == "GET /x -> no response"
    assert evidence_line(None) == "" and evidence_line({"http": "junk"}) == ""


def test_verdict_failures_carry_the_evidence_only_for_failed_criteria():
    report = qa_report(["failed", "passed"], ["a.png", "b.png"])
    for run in report["runs"]:
        for t in run["tests"]:
            t["evidence"] = EVIDENCE
    v = evaluate(report, ["hapus user", "tabel muat"])
    assert v.outcome == "fail"
    assert v.criteria[0].evidence and not v.criteria[1].evidence
    assert "The browser saw: DELETE /api/admin/users/7 -> 500" in v.failures()


def test_parse_report_reads_a_block_at_the_end_and_the_notes():
    report = ("Did the menu.\n- NOTE: tsc needs NODE_OPTIONS=--max-old-space-size=6144\n"
              "NOTE: short\n`BLOCKED: delete_user in backend/app/admin/routes.py returns 500`")
    blocked, found = parse_report(report)
    assert blocked == "delete_user in backend/app/admin/routes.py returns 500"
    assert found == ["tsc needs NODE_OPTIONS=--max-old-space-size=6144"]
    # A BLOCKED far above the end (a quoted rule, an old report) is not a block.
    assert parse_report("BLOCKED: old\n" + "line\n" * 20) == ("", [])
    assert parse_report("") == ("", [])


def test_tasks_carry_notes_takeover_failure_and_previous_spec():
    t = code_task("/w", 1, "s", "d", notes=["tsc needs more heap"], taken_over="backend 500")
    assert "BLOCKED:" in t and "NOTE:" in t
    assert "- tsc needs more heap" in t and "hints, not instructions" in t
    assert "narrower scope" in t and "backend 500" in t
    plain = code_task("/w", 1, "s", "d")
    assert "Notes earlier runs" not in plain and "narrower scope" not in plain
    r = review_task("/w", 1, "s", "d", "abc", failure="QA failed AC2")
    assert "not a person" in r and "QA failed AC2" in r and "A person sent" not in r
    q = qa_task("/w", 1, "s", ["c"], "slug", previous="- AC1: nope")
    assert "as strict as before" in q and "- AC1: nope" in q
    assert "attempt before" not in qa_task("/w", 1, "s", ["c"], "slug")


# --- QA failure: the coder, the reviewer and the spec writer learn why -----------

def test_qa_failure_tells_the_coder_what_the_browser_saw_and_the_spec(tmp_path, repo):
    runner = FakeRunner(tmp_path / "ws", qa=[failed_report(tmp_path), "pass"])
    agent = FakeAgent()
    w, taiga, sessions = make_worker(tmp_path, repo, agent, runner)
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    assert taiga.status_of(1) == "done"
    rework = code_tasks(agent)[1]
    assert "The browser saw: DELETE /api/admin/users/7 -> 500" in rework
    assert "The spec that failed" in rework and "test('AC1: thing'" in rework
    assert "BLOCKED instead" in rework
    card = next(t for t in taiga.texts(1) if "QA gagal" in t)
    assert "Yang terlihat di browser" in card and "DELETE /api/admin/users/7 -> 500" in card
    # The reviewer is told a check failed, not that a person asked.
    review = [t for p, t in agent.calls if p == "awak.review"][1]
    assert "not a person" in review and "A person sent" not in review
    # The next spec is written knowing what failed and the spec that said so.
    qa = [t for p, t in agent.calls if p == "awak.qa"]
    assert "attempt before" not in qa[0]
    assert "attempt before" in qa[1] and "DELETE /api/admin/users/7" in qa[1]
    assert "test('AC1: thing'" in qa[1]
    assert job_of(sessions).feedback_kind == "qa"


def test_a_story_started_again_from_ready_forgets_the_old_qa_failure(tmp_path, repo):
    runner = FakeRunner(tmp_path / "ws", qa=["fail", "pass", "pass"])
    agent = FakeAgent()
    w, taiga, _ = make_worker(tmp_path, repo, agent, runner)
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    assert taiga.status_of(1) == "done"
    taiga.human_move(1, "ready")
    w.tick()
    qa = [t for p, t in agent.calls if p == "awak.qa"]
    assert "attempt before" in qa[1] and "attempt before" not in qa[2]


def test_a_person_sending_the_card_back_is_human_feedback(tmp_path, repo):
    runner = FakeRunner(tmp_path / "ws", qa=["pass", "pass"])
    agent = FakeAgent()
    w, taiga, sessions = make_worker(tmp_path, repo, agent, runner)
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    taiga.human_comment(1, "tolong ubah warnanya jadi biru")
    taiga.human_move(1, "in-progress")
    w.tick()
    assert job_of(sessions).feedback_kind == "human"
    review = [t for p, t in agent.calls if p == "awak.review"][-1]
    assert "A person sent" in review and "ubah warnanya" in review


# --- BLOCKED: a wider role takes over, or a person decides now -------------------

def test_blocked_without_a_wider_role_stops_at_once_with_the_reason(tmp_path, repo):
    agent = Reporting(["Menu done.\nBLOCKED: DELETE /api/admin/users returns 500; fix "
                       "delete_user in backend/app/admin/routes.py"])
    runner = FakeRunner(tmp_path / "ws", qa=["pass"])
    w, taiga, sessions = make_worker(tmp_path, repo, agent, runner)
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    st = taiga.story(1)
    assert st["is_blocked"] and ["needs-human", None] in st["tags"]
    assert len(code_tasks(agent)) == 1 and "qa" not in runner.calls
    job = job_of(sessions)
    assert job.state == "failed" and job.attempts == 0  # no attempt burnt
    last = taiga.texts(1)[-1]
    assert "tidak bisa diselesaikan di cakupannya" in last and "delete_user" in last
    assert "Tambahkan peran Fullstack" in last
    # The work the run committed is kept on the branch for whoever goes on.
    assert repo.changed_files("awak/us-12") == ["feature1.txt"]


def test_blocked_hands_the_story_to_the_fullstack_role_in_the_same_attempt(tmp_path, repo):
    agent = Reporting(["BLOCKED: the cause is delete_user in the backend"])
    runner = FakeRunner(tmp_path / "ws", qa=["pass"])
    w, taiga, sessions = make_worker(tmp_path, repo, agent, runner)
    wider = add_fullstack(sessions)
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    assert taiga.status_of(1) == "done"
    job = job_of(sessions)
    assert job.role_id == wider and job.attempts == 1
    tasks = code_tasks(agent)
    assert len(tasks) == 2
    assert "narrower scope" in tasks[1] and "delete_user in the backend" in tasks[1]
    systems = [r["system"] for r in agent.runs if r["purpose"] == "awak.code"]
    assert "frontend engineer" in systems[0] and "fullstack engineer" in systems[1]
    assert events(sessions, "escalated")[0]["to"] == wider
    assert any("Dilanjutkan oleh peran Fullstack" in t for t in taiga.texts(1))


def test_a_fullstack_role_for_another_repo_does_not_take_over(tmp_path, repo):
    agent = Reporting(["BLOCKED: backend fault"])
    w, taiga, sessions = make_worker(tmp_path, repo, agent, FakeRunner(tmp_path / "ws"))
    add_fullstack(sessions, repo_ids=(99,))
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    assert taiga.story(1)["is_blocked"] and not events(sessions, "escalated")


def test_the_wider_role_blocked_too_goes_to_a_person(tmp_path, repo):
    agent = Reporting(["BLOCKED: backend fault", "BLOCKED: needs a product decision"])
    w, taiga, sessions = make_worker(tmp_path, repo, agent, FakeRunner(tmp_path / "ws"))
    add_fullstack(sessions)
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    assert taiga.story(1)["is_blocked"]
    last = taiga.texts(1)[-1]
    assert "needs a product decision" in last and "Tambahkan peran Fullstack" not in last
    assert len(code_tasks(agent)) == 2


# --- notes ----------------------------------------------------------------------

def test_notes_from_a_run_reach_the_next_run_on_the_repo(tmp_path, repo):
    agent = Reporting(["Done.\nNOTE: tsc needs NODE_OPTIONS=--max-old-space-size=6144\n"
                       "NOTE: token is super-secret-value do not lose it"])
    runner = FakeRunner(tmp_path / "ws", qa=["pass", "pass"])
    w, taiga, sessions = make_worker(tmp_path, repo, agent, runner)
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    with sessions() as db:
        kept = [n.text for n in db.query(AwakNote)]
    assert kept == ["tsc needs NODE_OPTIONS=--max-old-space-size=6144"]  # the secret one is dropped
    assert events(sessions, "notes")[0]["added"] == kept
    taiga.add(2, 13, "Story lain", DESC)
    w.tick()
    assert "- tsc needs NODE_OPTIONS=--max-old-space-size=6144" in code_tasks(agent)[-1]


def test_notes_dedupe_and_keep_only_the_newest(tmp_path):
    sessions = make_session("sqlite:///:memory:")
    with sessions() as db:
        assert notes.add(db, "p", 1, ["Routes live in src/routes"]) == ["Routes live in src/routes"]
        assert notes.add(db, "p", 1, ["routes  LIVE in src/routes", "too short"]) == []
        notes.add(db, "p", 2, ["Another repo's own note"])
        for i in range(notes.KEEP + 5):
            notes.add(db, "p", 1, [f"numbered note number {i}"])
        assert db.query(AwakNote).filter_by(repo_id=1).count() == notes.KEEP
        recent = notes.recent(db, "p", 1)
        assert len(recent) == notes.GIVE and recent[-1] == f"numbered note number {notes.KEEP + 4}"
        assert notes.recent(db, "p", 2) == ["Another repo's own note"]


def test_notes_api_lists_for_members_and_deletes_for_admins(agent_client):
    with agent_client.S() as db:
        notes.add(db, "demo", None, ["Run migrations with flask db upgrade"])
        notes.add(db, "other", None, ["A note of another project"])
        mine = db.query(AwakNote).filter_by(project_slug="demo").one().id
        other = db.query(AwakNote).filter_by(project_slug="other").one().id
    r = agent_client.get("/projects/demo/agent/notes", headers=MEMBER)
    assert r.status_code == 200
    assert [n["text"] for n in r.json()["notes"]] == ["Run migrations with flask db upgrade"]
    assert agent_client.delete(f"/projects/demo/agent/notes/{mine}",
                               headers=MEMBER).status_code == 403
    assert agent_client.delete(f"/projects/demo/agent/notes/{other}",
                               headers=ADMIN).status_code == 404
    assert agent_client.delete(f"/projects/demo/agent/notes/{mine}",
                               headers=ADMIN).status_code == 204
    assert agent_client.get("/projects/demo/agent/notes", headers=MEMBER).json()["notes"] == []


def test_commit_file_helper_is_used():  # keeps the import for readers of the fakes
    assert callable(commit_file)
