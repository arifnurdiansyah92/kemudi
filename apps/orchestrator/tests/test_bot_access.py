"""Bot access (the Awak user must be a project member), per-project isolation
in the worker tick, and the Fullstack role (area `both`)."""

import json

import httpx
import pytest
from sqlalchemy import create_engine, inspect, text

from kemudi_ai.awak import prompts
from kemudi_ai.awak.bot_access import BotAccess, BotAccessError, pick_role
from kemudi_ai.awak.intake import StoryDraft
from kemudi_ai.awak.taiga import TaigaError
from kemudi_ai.awak.worker import Worker
from kemudi_ai.config import Settings
from kemudi_ai.store import AwakProject, AwakRepo, AwakRole, Decision, init_db, make_session

from .awak_fakes import FakeAgent, FakeRunner, FakeTaiga
from .conftest import ADMIN, MEMBER
from .test_awak import DESC, job_of, make_worker, repo, host  # noqa: F401 (fixtures)

# A made-up bot credential for the fake Taiga, built at runtime so secret
# scanners do not read a literal as a leaked password.
BOT_PW = "-".join(["fake", "bot", "credential"])

SETTINGS = {"enabled": True, "merge_mode": "approve", "deploy_command": "",
            "executor": "local", "ssh_host": "", "ssh_port": 22, "ssh_user": ""}
URL = "/projects/demo/agent/settings"


# --- BotAccess against a fake Taiga -------------------------------------------------

ROLES = [{"id": 1, "slug": "product-owner", "name": "Product Owner", "order": 1},
         {"id": 2, "slug": "ux", "name": "UX", "order": 2},
         {"id": 3, "slug": "back", "name": "Back", "order": 5}]


def test_pick_role_prefers_developer_roles():
    assert pick_role(ROLES)["slug"] == "back"
    assert pick_role(ROLES[:2])["slug"] == "ux"  # the first non-owner role
    assert pick_role([ROLES[0]]) is None
    assert pick_role([{"id": 9, "slug": "developer", "name": "Dev"}, *ROLES])["slug"] == "back"


class FakeTaigaHttp:
    """Taiga's /auth, /projects/by_slug and /memberships."""

    def __init__(self, members=("pm",), bot_member=False, membership_status=201):
        self.members = list(members)
        self.bot_member = bot_member
        self.membership_status = membership_status
        self.posts: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        auth = request.headers.get("authorization", "")
        path = request.url.path
        if path.endswith("/auth"):
            body = json.loads(request.content)
            if body["password"] != BOT_PW:
                return httpx.Response(401)
            return httpx.Response(200, json={"auth_token": "bot-token", "id": 99})
        if path.endswith("/projects/by_slug"):
            if auth == "Bearer bot-token" and not self.bot_member:
                return httpx.Response(404, json={"_error_message": "No Project matches"})
            return httpx.Response(200, json={
                "id": 7, "slug": "demo", "us_statuses": [], "roles": ROLES,
                "members": [{"id": i, "username": u} for i, u in enumerate(self.members)]})
        if path.endswith("/memberships") and request.method == "POST":
            body = json.loads(request.content)
            self.posts.append(body)
            if self.membership_status >= 400:
                return httpx.Response(self.membership_status, json={"detail": "nope"})
            self.members.append(body["username"])
            self.bot_member = True
            return httpx.Response(201, json={"id": 50, **body})
        return httpx.Response(404)


def _bot(fake, secret=BOT_PW, clock=None):
    s = Settings(taiga_api_url="http://localhost:9100/api/v1")
    s.awak_password = secret  # the bot's name stays the default ("awak")
    BotAccess._cache.clear()
    kw = {"clock": clock} if clock else {}
    return BotAccess(s, httpx.MockTransport(fake), **kw)


def test_check_reports_membership_and_caches():
    fake = FakeTaigaHttp()
    t = [0.0]
    bot = _bot(fake, clock=lambda: t[0])
    out = bot.check("demo")
    assert out == {"ok": False, "member": False,
                   "error": "Awak (user awak) is not a member of this project"}
    fake.bot_member = True
    assert bot.check("demo")["ok"] is False  # cached for a few seconds
    t[0] = 60.0
    assert bot.check("demo") == {"ok": True, "member": True, "error": None}


def test_check_without_bot_password_or_with_a_wrong_one():
    assert _bot(FakeTaigaHttp(), secret="").check("demo")["member"] is None
    out = _bot(FakeTaigaHttp(), secret="wrong").check("demo")
    assert out["ok"] is False and out["member"] is None and "sign in" in out["error"]
    assert "wrong" not in out["error"]


def test_grant_adds_the_bot_with_a_developer_role():
    fake = FakeTaigaHttp()
    bot = _bot(fake)
    assert bot.check("demo")["member"] is False
    assert bot.grant("demo", "admin-token") == {"added": True, "role": "Back"}
    assert fake.posts == [{"project": 7, "role": 3, "username": "awak"}]
    assert bot.check("demo")["ok"] is True  # the cached "not a member" was dropped
    # already a member: nothing posted
    assert bot.grant("demo", "admin-token") == {"added": False, "role": None}
    assert len(fake.posts) == 1


def test_grant_refused_by_taiga():
    bot = _bot(FakeTaigaHttp(membership_status=403))
    with pytest.raises(BotAccessError) as e:
        bot.grant("demo", "admin-token")
    assert e.value.status == 403


# --- API --------------------------------------------------------------------------

def test_settings_show_bot_access_and_last_error(agent_client):
    agent_client.bot.member = False
    body = agent_client.get(URL, headers=MEMBER).json()
    assert body["bot_access"]["ok"] is False and body["bot_access"]["member"] is False
    assert body["last_error"] is None
    with agent_client.S() as db:
        db.add(AwakProject(slug="demo", last_error="cannot open project demo"))
        db.commit()
    assert agent_client.get(URL, headers=MEMBER).json()["last_error"] == (
        "cannot open project demo")
    assert agent_client.bot.grants == []  # reading never changes Taiga


def test_enabling_gives_the_bot_access(agent_client):
    agent_client.bot.member = False
    off = agent_client.put(URL, headers=ADMIN, json={**SETTINGS, "enabled": False}).json()
    assert agent_client.bot.grants == [] and off["bot_access"]["ok"] is False
    on = agent_client.put(URL, headers=ADMIN, json=SETTINGS).json()
    assert agent_client.bot.grants == [("demo", "admin-token")]
    assert on["bot_access"] == {"ok": True, "member": True, "error": None}
    with agent_client.S() as db:
        d = db.query(Decision).filter_by(action="awak_bot_access").one()
        assert d.detail == {"username": "awak", "role": "Back"}
    assert "token" not in json.dumps(on).replace("admin-token", "")


def test_enabling_still_saves_when_the_grant_fails(agent_client):
    agent_client.bot.member = False
    agent_client.bot.fail = BotAccessError("Taiga does not let you add members", 403)
    r = agent_client.put(URL, headers=ADMIN, json=SETTINGS)
    assert r.status_code == 200 and r.json()["enabled"] is True
    assert r.json()["bot_access"]["error"] == "Taiga does not let you add members"


def test_bot_access_endpoint(agent_client):
    url = "/projects/demo/agent/bot-access"
    agent_client.bot.member = False
    assert agent_client.post(url, headers=MEMBER).status_code == 403
    r = agent_client.post(url, headers=ADMIN)
    assert r.status_code == 200
    assert r.json() == {"added": True, "role": "Back",
                        "bot_access": {"ok": True, "member": True, "error": None}}
    agent_client.bot.fail = BotAccessError("Taiga does not let you add members", 403)
    r = agent_client.post(url, headers=ADMIN)
    assert r.status_code == 403 and "add members" in r.json()["detail"]


def test_fullstack_role_accepted(agent_client):
    role = {"name": "Fullstack", "template": "fullstack", "area": "both", "model": "",
            "repo_ids": [], "allowed_paths": [], "denied_paths": [], "prompt_overlay": "",
            "enabled": True}
    r = agent_client.post("/projects/demo/agent/roles", headers=ADMIN, json=role)
    assert r.status_code == 200 and r.json()["area"] == "both"
    prompt = agent_client.get(f"/projects/demo/agent/roles/{r.json()['id']}/prompt",
                              headers=MEMBER).json()
    assert prompt["role"] == prompts.ROLE_TEMPLATES["fullstack"]


# --- migration ----------------------------------------------------------------------

def test_migrate_adds_last_error_columns(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as c:
        c.execute(text("CREATE TABLE awak_projects (slug VARCHAR(200) NOT NULL PRIMARY KEY,"
                       " enabled BOOLEAN NOT NULL)"))
        c.execute(text("INSERT INTO awak_projects VALUES ('playfast', 1)"))
    init_db(engine)
    cols = {c["name"] for c in inspect(engine).get_columns("awak_projects")}
    assert {"last_error", "last_error_at"} <= cols
    S = make_session(f"sqlite:///{tmp_path / 'old.db'}")
    with S() as db:
        p = db.get(AwakProject, "playfast")
        assert p.last_error == "" and p.last_error_at is None


# --- the tick serves every project ---------------------------------------------------

class PartlyBlindTaiga(FakeTaiga):
    """The bot is not a member of `blind` projects (Taiga 404s them)."""

    def __init__(self, blind=()):
        super().__init__()
        self.blind = set(blind)

    def project(self, slug):
        if slug in self.blind:
            raise TaigaError("GET /projects/by_slug: HTTP 404 No Project matches")
        return super().project(slug)


def test_one_broken_project_does_not_stop_the_others(tmp_path, repo):
    settings = Settings(awak_projects="", ai_db_url="sqlite:///:memory:",
                        workspace_dir=str(tmp_path / "ws"))
    sessions = make_session(settings.ai_db_url)
    with sessions() as db:
        for slug in ("aaa-playfast", "kemudi"):
            db.add(AwakProject(slug=slug, enabled=True, merge_mode="manual"))
            repo_row = AwakRepo(project_slug=slug, name="kemudi", url=settings.host_git,
                                subdir="apps/web")
            db.add(repo_row)
            db.flush()
            db.add(AwakRole(project_slug=slug, template="frontend", name="FE", area="web",
                            model="m", repo_ids=[repo_row.id]))
        db.commit()
    taiga = PartlyBlindTaiga(blind={"aaa-playfast"})
    w = Worker(settings, sessions, taiga, FakeTaiga("awak-qa"), FakeAgent(),
               FakeRunner(tmp_path / "ws", qa=["pass"]), repo,
               secret_values=["super-secret-value"], sleep=lambda s: None)
    taiga.add(1, 12, "Badge jumlah", DESC)
    assert w.tick()  # aaa-playfast fails first, kemudi is still served
    assert taiga.status_of(1) == "done"
    with sessions() as db:
        p = db.get(AwakProject, "aaa-playfast")
        assert "not a member" in p.last_error and p.last_error_at is not None
        assert db.get(AwakProject, "kemudi").last_error == ""
    taiga.blind.clear()
    assert not w.tick()
    with sessions() as db:
        p = db.get(AwakProject, "aaa-playfast")
        assert p.last_error == "" and p.last_error_at is None


# --- Fullstack routing ----------------------------------------------------------------

def _add_fullstack(sessions, enabled=True):
    with sessions() as db:
        fe = db.query(AwakRole).filter_by(template="frontend").one()
        db.add(AwakRole(project_slug=fe.project_slug, template="fullstack", name="Fullstack",
                        area="both", model="fs-model", repo_ids=list(fe.repo_ids),
                        enabled=enabled))
        db.commit()


def _set_role(sessions, template, **fields):
    with sessions() as db:
        r = db.query(AwakRole).filter_by(template=template).one()
        for k, v in fields.items():
            setattr(r, k, v)
        db.commit()


def _role_id(sessions, template):
    with sessions() as db:
        return db.query(AwakRole).filter_by(template=template).one().id


@pytest.mark.parametrize("tags", [("agent-ready", "area-both"),
                                  ("agent-ready", "area-web", "area-backend")])
def test_two_area_story_goes_to_the_fullstack_role(tmp_path, repo, tags):
    agent = FakeAgent()
    w, taiga, sessions = make_worker(tmp_path, repo, agent,
                                     FakeRunner(tmp_path / "ws", qa=["pass"]))
    w._seed()
    _set_role(sessions, "backend", enabled=True)
    _add_fullstack(sessions)
    taiga.add(1, 12, "Badge + API", DESC, tags=tags)
    assert w.tick()
    code = next(r for r in agent.runs if r["purpose"] == "awak.code")
    assert code["model"] == "fs-model"
    assert prompts.ROLE_TEMPLATES["fullstack"] in code["system"]
    assert job_of(sessions).role_id == _role_id(sessions, "fullstack")
    assert taiga.status_of(1) == "done"


def test_two_area_story_without_fullstack_role_stops_and_suggests_it(tmp_path, repo):
    w, taiga, sessions = make_worker(tmp_path, repo, FakeAgent(), FakeRunner(tmp_path / "ws"))
    taiga.add(1, 12, "Badge + API", DESC, tags=("agent-ready", "area-both"))
    w.tick()
    assert job_of(sessions).state == "failed"
    last = taiga.texts(1)[-1]
    assert "lebih dari satu tag area" in last and "Fullstack" in last


def test_single_area_story_falls_back_to_the_fullstack_role(tmp_path, repo):
    agent = FakeAgent()
    w, taiga, sessions = make_worker(tmp_path, repo, agent,
                                     FakeRunner(tmp_path / "ws", qa=["pass"]))
    w._seed()
    _add_fullstack(sessions)  # the seeded backend role stays disabled
    taiga.add(1, 12, "API baru", DESC, tags=("agent-ready", "area-backend"))
    assert w.tick()
    assert job_of(sessions).role_id == _role_id(sessions, "fullstack")


def test_single_area_story_prefers_its_own_role(tmp_path, repo):
    w, taiga, sessions = make_worker(tmp_path, repo, FakeAgent(),
                                     FakeRunner(tmp_path / "ws", qa=["pass"]))
    w._seed()
    _add_fullstack(sessions)
    taiga.add(1, 12, "Badge", DESC, tags=("agent-ready", "area-web"))
    assert w.tick()
    assert job_of(sessions).role_id == _role_id(sessions, "frontend")


# --- intake ---------------------------------------------------------------------------

def test_auto_ready_with_a_fullstack_role():
    both = StoryDraft(subject="a", criteria=["x"], area="both")
    ok, why = both.auto_ready({"web"})
    assert not ok and "Fullstack" in why
    assert both.auto_ready({"web", "both"}) == (True, "")
    backend = StoryDraft(subject="a", criteria=["x"], area="backend")
    assert backend.auto_ready({"both"}) == (True, "")
    assert not backend.auto_ready({"web"})[0]
