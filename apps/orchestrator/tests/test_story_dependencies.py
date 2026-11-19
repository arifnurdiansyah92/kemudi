"""Stories that wait for others: intake writes the order down, Awak keeps it,
and a missing tool in the sandbox is not a reason to stop a story."""

from kemudi_ai.awak.intake import StoryDraft, create_stories, draft_stories, earlier
from kemudi_ai.awak.stories import (
    INTAKE_CODE_RULES,
    INTAKE_SYSTEM,
    REPORT_RULES,
    criteria,
    depends_line,
    depends_on,
    format_description,
)


from .awak_fakes import STATUSES, FakeAgent, FakeRunner, FakeTaiga
from .fakes import FakeLLM
from .test_awak import DESC, host, make_worker, repo  # noqa: F401 (fixtures)


def waiting(desc_refs):
    return format_description(f"Pakai model Role.\n\n{depends_line(desc_refs)}", ["Angka benar"])


# --- the line in the description ---------------------------------------------------

def test_depends_line_roundtrip_and_what_people_type():
    assert depends_on(waiting([17, 18])) == [17, 18]
    assert criteria(waiting([17])) == ["Angka benar"]  # the line is not a criterion
    assert depends_on("Intro\n**Bergantung pada:** #3 dan #4, #3\n") == [3, 4]
    assert depends_on("- depends on: #9") == [9]
    assert depends_on(DESC) == []
    # prose that mentions a story is not a dependency
    assert depends_on("Kebutuhan #3 tidak menyertakannya, lihat #5.") == []


# --- intake ----------------------------------------------------------------------

def test_draft_keeps_only_earlier_positions():
    d = StoryDraft(subject="a", depends_on=[3, "1", 1, 0, -2, "x", True, 2.0])
    assert d.depends_on == [1, 2, 3]
    assert earlier(d.depends_on, 3) == [1, 2]  # never itself or a later one
    assert StoryDraft(subject="a", depends_on="1").depends_on == []


def test_intake_writes_dependencies_as_story_refs():
    llm = FakeLLM({"awak.intake": [{"stories": [
        {"subject": "Model Role", "criteria": ["x"], "area": "web"},
        {"subject": "Seed role", "criteria": ["x"], "area": "web", "depends_on": [1]},
        {"subject": "Halaman role", "description": "Di /admin/roles.", "criteria": ["x"],
         "area": "web", "depends_on": [1, 2, 3, 9]},
    ]}]})
    taiga = FakeTaiga()
    created = create_stories(taiga, "kemudi", draft_stories(llm, "rbac"))
    refs = [c["ref"] for c in created]
    assert [c["depends_on"] for c in created] == [[], refs[:1], refs[:2]]
    texts = [taiga.stories_by_id[c["id"]]["description"] for c in created]
    assert depends_on(texts[0]) == [] and depends_on(texts[1]) == refs[:1]
    assert depends_on(texts[2]) == refs[:2] and texts[2].startswith("Di /admin/roles.")
    assert criteria(texts[2]) == ["x"]


def test_dropped_draft_clears_the_positions():
    llm = FakeLLM({"awak.intake": [{"stories": [
        {"description": "no subject: dropped"},
        {"subject": "A", "criteria": ["x"]},
        {"subject": "B", "criteria": ["x"], "depends_on": [2]},
    ]}]})
    assert [d.depends_on for d in draft_stories(llm, "t")] == [[], []]


def test_prompts_ask_for_order_and_area_by_code():
    for lang in ("id", "en"):
        assert '"depends_on"' in INTAKE_SYSTEM[lang]
        assert "repo" in INTAKE_CODE_RULES[lang]
    assert "frontend and a backend" in INTAKE_CODE_RULES["en"]


# --- the worker keeps the order ----------------------------------------------------

def worker(tmp_path, repo):
    runner = FakeRunner(tmp_path / "ws", qa=["pass", "pass", "pass"])
    return make_worker(tmp_path, repo, FakeAgent(), runner)


def test_a_story_waits_until_its_dependency_is_merged(tmp_path, repo):
    w, taiga, sessions = worker(tmp_path, repo)
    taiga.add(1, 17, "Model Role", DESC, status="new", tags=())
    taiga.add(2, 18, "Seed role", waiting([17]))
    assert not w.tick()  # #17 is not even started
    assert taiga.status_of(2) == "ready"
    (said,) = taiga.texts(2)
    assert "#17 (belum selesai)" in said and "Depends on:" in said
    assert not w.tick() and len(taiga.texts(2)) == 1  # said once

    # Done but its merge is still waiting: the code is not on main yet.
    taiga.stories_by_id[1].update(status=STATUSES["done"],
                                  tags=[["agent-ready", None], ["awaiting-merge", None]])
    assert not w.tick()
    assert len(taiga.texts(2)) == 1  # the same wait: not said again

    taiga.stories_by_id[1]["tags"] = [["agent-ready", None], ["merged", None]]
    assert w.tick()
    assert taiga.status_of(2) == "done"


def test_a_blocked_dependency_holds_the_chain_but_not_other_stories(tmp_path, repo):
    w, taiga, sessions = worker(tmp_path, repo)
    taiga.add(1, 17, "Seed role", DESC, status="in-progress")
    taiga.stories_by_id[1]["is_blocked"] = True
    taiga.add(2, 18, "Pakai seed", waiting([17]))
    taiga.add(3, 19, "Tidak terkait", DESC)
    assert w.tick()
    assert taiga.status_of(3) == "done" and taiga.status_of(2) == "ready"
    assert "#17 (terblokir, butuh orang)" in taiga.texts(2)[0]


def test_a_ref_that_names_no_story_or_itself_does_not_hold(tmp_path, repo):
    w, taiga, sessions = worker(tmp_path, repo)
    taiga.add(1, 18, "Seed role", waiting([18, 404]))
    assert w.tick()
    assert taiga.status_of(1) == "done"


def test_the_wait_is_not_said_again_after_a_restart(tmp_path, repo):
    w, taiga, sessions = worker(tmp_path, repo)
    taiga.add(1, 17, "Model Role", DESC, status="new", tags=())
    taiga.add(2, 18, "Seed role", waiting([17]))
    w.tick()
    w._wait_said.clear()  # a new process
    w.tick()
    assert len(taiga.texts(2)) == 1


# --- BLOCKED is for scope and decisions --------------------------------------------

def test_waiting_text_names_each_reason():
    from kemudi_ai.awak.worker import waiting_text

    text = waiting_text([{"ref": 9, "tags": [["awaiting-merge", None]]},
                         {"ref": 3, "is_blocked": True}, {"ref": 5}])
    assert ("#3 (terblokir, butuh orang), #5 (belum selesai), #9 (menunggu merge)") in text


def test_report_rules_say_a_missing_tool_is_not_a_block():
    assert "not blocks" in REPORT_RULES
    assert "missing in your sandbox" in REPORT_RULES and "say what you chose" in REPORT_RULES
