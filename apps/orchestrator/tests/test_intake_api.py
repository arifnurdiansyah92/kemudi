import pytest

from kemudi_ai.api import app
from kemudi_ai.awak import taiga as taiga_mod
from kemudi_ai.awak.taiga import Taiga, TaigaError, tag_names
from kemudi_ai.deps import get_llm
from kemudi_ai.store import AwakProject, AwakRole, Decision

from .awak_fakes import FakeTaiga
from .conftest import ADMIN, MEMBER
from .fakes import FakeLLM

DRAFTS = {"stories": [
    {"subject": "Badge di kartu", "description": "d", "criteria": ["satu", "dua"],
     "area": "web"},
    {"subject": "API baru", "criteria": ["x"], "area": "backend"},
]}


@pytest.fixture
def intake(agent_client, monkeypatch):
    fake = FakeTaiga(username="dev")
    tokens: list[str] = []

    def with_token(cls, api_url, token, transport=None):
        tokens.append(token)
        return fake

    monkeypatch.setattr(taiga_mod.Taiga, "with_token", classmethod(with_token))
    llm = FakeLLM({"awak.intake": [DRAFTS]})
    app.dependency_overrides[get_llm] = lambda: llm
    agent_client.taiga, agent_client.tokens, agent_client.llm = fake, tokens, llm
    return agent_client


def roles(client, web=True, backend=False, enabled_project=True):
    with client.S() as db:
        db.add(AwakProject(slug="demo", enabled=enabled_project))
        db.add_all([
            AwakRole(project_slug="demo", template="frontend", name="FE", area="web",
                     model="m", enabled=web),
            AwakRole(project_slug="demo", template="backend", name="BE", area="backend",
                     model="m", enabled=backend),
        ])
        db.commit()


def draft(client, **form):
    return client.post("/projects/demo/intake/draft", headers=MEMBER,
                       data={"text": "butuh badge", "lang": "id", **form})


def test_draft_creates_nothing(intake):
    roles(intake)
    r = draft(intake)
    assert r.status_code == 200, r.text
    assert len(r.json()["drafts"]) == 2
    assert intake.taiga.stories_by_id == {}
    assert intake.tokens == []  # no Taiga client is even built


def test_draft_marks_ready_by_enabled_roles(intake):
    roles(intake, web=True, backend=False)
    web, backend = draft(intake).json()["drafts"]
    assert web == {"subject": "Badge di kartu", "description": "d", "criteria": ["satu", "dua"],
                   "area": "web", "ready": True, "reason": ""}
    assert backend["ready"] is False and "backend" in backend["reason"]
    assert "peran" in backend["reason"]


def test_create_recomputes_ready_and_honours_hold(intake):
    roles(intake, web=True, backend=False)
    body = {"drafts": [
        {"subject": "API baru", "criteria": ["x"], "area": "backend"},
        {"subject": "Badge", "criteria": ["a"], "area": "web", "hold": True},
        {"subject": "Tombol", "criteria": ["a"], "area": "web"},
    ]}
    r = intake.post("/projects/demo/intake/create", headers=MEMBER, json=body)
    assert r.status_code == 200, r.text
    out = r.json()["stories"]
    assert [s["ready"] for s in out] == [False, False, True]
    t = intake.taiga
    backend, held, ready = (t.stories_by_id[s["id"]] for s in out)
    assert t.status_of(backend["id"]) == "new" and "agent-ready" not in tag_names(backend)
    assert t.status_of(held["id"]) == "new" and "agent-ready" not in tag_names(held)
    assert t.status_of(ready["id"]) == "ready" and "agent-ready" in tag_names(ready)
    assert "PM" in out[1]["reason"]
    # held stories get the explanation comment from the caller's client
    assert t.comments_by_id[held["id"]][0]["user"]["username"] == "dev"
    with intake.S() as db:
        d = db.query(Decision).filter_by(action="awak_intake").one()
        assert d.actor == "dev (2)"
        assert d.detail["stories"] == [s["ref"] for s in out] and d.detail["chars"] > 0
        assert "Badge" not in str(d.detail)


def test_create_adds_area_tag(intake):
    roles(intake, backend=True)
    body = {"drafts": [{"subject": "Web", "criteria": ["a"], "area": "web"},
                       {"subject": "Api", "criteria": ["a"], "area": "backend"},
                       {"subject": "Both", "criteria": ["a"], "area": "both"}]}
    out = intake.post("/projects/demo/intake/create", headers=MEMBER, json=body).json()["stories"]
    tags = [tag_names(intake.taiga.stories_by_id[s["id"]]) for s in out]
    assert tags[0] == ["agent-ready", "area-web"]
    assert tags[1] == ["agent-ready", "area-backend"]
    assert tags[2] == ["area-both"] and out[2]["ready"] is False


def test_both_story_ready_with_an_enabled_fullstack_role(intake):
    roles(intake, web=False)
    with intake.S() as db:
        db.add(AwakRole(project_slug="demo", template="fullstack", name="FS", area="both",
                        model="m", enabled=True))
        db.commit()
    body = {"drafts": [{"subject": "Both", "criteria": ["a"], "area": "both"},
                       {"subject": "Api", "criteria": ["a"], "area": "backend"}]}
    out = intake.post("/projects/demo/intake/create", headers=MEMBER, json=body).json()["stories"]
    assert [s["ready"] for s in out] == [True, True]  # the Fullstack role serves both
    assert tag_names(intake.taiga.stories_by_id[out[0]["id"]]) == ["agent-ready", "area-both"]


def test_create_uses_caller_token(intake):
    roles(intake)
    body = {"drafts": [{"subject": "Web", "criteria": ["a"], "area": "web"}]}
    assert intake.post("/projects/demo/intake/create", headers=MEMBER,
                       json=body).status_code == 200
    assert intake.tokens == ["member-token"]


def test_create_works_when_agent_disabled(intake):
    roles(intake, enabled_project=False)
    body = {"drafts": [{"subject": "Web", "criteria": ["a"], "area": "web"}]}
    r = intake.post("/projects/demo/intake/create", headers=MEMBER, json=body)
    assert r.status_code == 200 and r.json()["stories"][0]["ready"] is True


def test_create_maps_taiga_403(intake, monkeypatch):
    def refuse(project_id, **fields):
        raise TaigaError("POST /userstories: HTTP 403 {}")

    monkeypatch.setattr(intake.taiga, "create_story", refuse)
    body = {"drafts": [{"subject": "Web", "criteria": ["a"], "area": "web"}]}
    r = intake.post("/projects/demo/intake/create", headers=MEMBER, json=body)
    assert r.status_code == 403


def test_draft_needs_text_or_file(intake):
    r = intake.post("/projects/demo/intake/draft", headers=MEMBER, data={"text": "  "})
    assert r.status_code == 400


def test_too_many_drafts(intake):
    body = {"drafts": [{"subject": f"Story {i}", "area": "web"} for i in range(31)]}
    r = intake.post("/projects/demo/intake/create", headers=MEMBER, json=body)
    assert r.status_code == 422
    r = intake.post("/projects/demo/intake/create", headers=MEMBER, json={"drafts": []})
    assert r.status_code == 422


def test_intake_needs_membership(intake):
    r = intake.post("/projects/demo/intake/draft", data={"text": "x"})
    assert r.status_code == 401


def test_with_token_keeps_local_guard():
    with pytest.raises(TaigaError, match="refusing"):
        Taiga.with_token("https://taiga.example.com/api/v1", "tok")
    t = Taiga.with_token("http://kemudi-back:8000/api/v1", "tok")
    assert t.c.headers["Authorization"] == "Bearer tok"
    with pytest.raises(TaigaError):
        t.login()  # a token client never logs in with a password


def test_area_both_tag_names_both_areas():
    from kemudi_ai.awak.intake import story_areas

    assert story_areas(["area-both"]) == ["backend", "web"]  # the worker asks to split it
    assert story_areas(["area-backend"]) == ["backend"] and story_areas([]) == ["web"]
