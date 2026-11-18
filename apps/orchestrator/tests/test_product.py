"""Product agents (kemudi_ai/product/): competitor research, feature
suggestions, the data report and custom research."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest

from kemudi_ai.config import Settings
from kemudi_ai.llm import LLMError
from kemudi_ai.product import agents, data
from kemudi_ai.product import api as product_api
from kemudi_ai.product import service as product_service
from kemudi_ai.product.web import HermesResearcher, WebError
from kemudi_ai.store import AiCall, AwakJob, ProductRun, make_session

from .conftest import ADMIN, MEMBER
from .fakes import FakeLLM

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)


def iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")


def story(ref, status="New", closed=False, created=40, finished=None, **kw):
    return {"ref": ref, "subject": f"Story {ref}", "is_closed": closed,
            "status_extra_info": {"name": status}, "created_date": iso(created),
            "finish_date": iso(finished) if finished is not None else None, **kw}


PROJECT = {"id": 7, "name": "Toko Online", "description": "Aplikasi pesanan untuk UMKM.",
           "us_statuses": [{"name": "New", "order": 1}, {"name": "In progress", "order": 2},
                           {"name": "Done", "order": 3}]}
STORIES = [
    story(1, "Done", True, created=20, finished=10),
    story(2, "Done", True, created=12, finished=2),
    story(3, "Done", True, created=200, finished=100),   # closed before the period
    story(4, "In progress", created=90, assigned_to=5,
          assigned_to_extra_info={"full_name_display": "Sari"}),
    story(5, "New", created=3, is_blocked=True, blocked_note="menunggu API"),
    story(6, "New", created=50),
]
MILESTONES = [{"name": "Sprint 4", "closed": False,
               "estimated_start": (NOW - timedelta(days=5)).date().isoformat(),
               "estimated_finish": (NOW + timedelta(days=9)).date().isoformat(),
               "user_stories": [{"is_closed": True}, {"is_closed": False}],
               "total_points": 13, "closed_points": 5},
              {"name": "Sprint 3", "closed": True, "estimated_start": "2026-10-01",
               "estimated_finish": "2026-10-14", "user_stories": []}]
ISSUES = [{"is_closed": False, "created_date": iso(4)},
          {"is_closed": True, "created_date": iso(60), "finished_date": iso(6)}]


class FakeSource:
    def __init__(self, fail=False):
        self.fail = fail

    def project(self, slug):
        if self.fail:
            raise RuntimeError("HTTP 403")
        return PROJECT

    def stories(self, project_id):
        return STORIES

    def milestones(self, project_id):
        return MILESTONES

    def issues(self, project_id):
        return ISSUES


class FakeResearcher:
    def __init__(self, reply="", error=None):
        self.reply, self.error = reply, error
        self.calls: list[tuple[str, str, str]] = []

    def research(self, purpose, system, task, slug=""):
        self.calls.append((purpose, system, task))
        if self.error:
            raise self.error
        return self.reply


SUMMARY = {"summary": "Aplikasi pesanan online untuk UMKM.", "category": "order management",
           "keywords": ["aplikasi pesanan UMKM"]}
WEB_REPORT = ("Baik, ini laporannya.\n\n# Riset kompetitor\n\n## Ringkasan\nAda dua pemain.\n\n"
              "## Peta kompetitor\n| Kompetitor | Harga |\n| --- | --- |\n"
              "| Moka | Rp299rb/bln [harga Moka](https://moka.example/pricing) |\n\n"
              "## Sumber\n- [harga Moka](https://moka.example/pricing)\n"
              "- https://olsera.example/fitur.\n")
SUGGESTIONS = {"summary": "Fokus ke retensi.", "suggestions": [
    {"title": "Tambah filter status pesanan", "problem": "Admin sulit mencari pesanan.",
     "proposal": "Filter di halaman /orders.", "value": "Lebih cepat", "effort": "s",
     "area": "WEB", "evidence": "src/pages/Orders.tsx"},
    {"title": "", "problem": "tanpa judul"},
    {"title": "Ekspor laporan", "effort": "XL", "area": "mobile"},
]}
NARRATIVE = {"summary": "Dua story selesai dalam 30 hari.", "highlights": ["Sprint 4 berjalan."],
             "risks": ["#4 terbuka 90 hari."], "recommendations": []}


def make_deps(llm=None, researcher=None, source=None, overview="README toko\nPeta file (2 file)"):
    sessions = make_session("sqlite:///:memory:")
    deps = agents.Deps(settings=Settings(ai_db_url="sqlite:///:memory:"), sessions=sessions,
                       llm=llm or FakeLLM({}), researcher=researcher,
                       source=lambda token: source or FakeSource(),
                       overview=lambda db, slug: overview, now=lambda: NOW)
    return deps, sessions


def add_run(sessions, kind, brief="", options=None, lang="id", **kw):
    with sessions() as db:
        row = ProductRun(project_slug="demo", kind=kind, brief=brief, lang=lang,
                         options=options or {}, created_by="pm", created_by_id=1,
                         title="t", **kw)
        db.add(row)
        db.commit()
        return row.id


def run_of(sessions, run_id) -> ProductRun:
    with sessions() as db:
        return db.get(ProductRun, run_id)


# --- the numbers ----------------------------------------------------------------

def test_metrics_are_computed_from_the_data():
    jobs = [{"ref": 1, "state": "passed", "attempts": 1, "merge_state": "merged",
             "started_at": NOW - timedelta(minutes=30), "updated_at": NOW},
            {"ref": 2, "state": "passed", "attempts": 3, "merge_state": "",
             "started_at": NOW - timedelta(minutes=70), "updated_at": NOW},
            {"ref": 3, "state": "failed", "attempts": 3, "merge_state": "",
             "started_at": NOW - timedelta(minutes=70), "updated_at": NOW},
            {"ref": 4, "state": "running", "attempts": 0, "merge_state": "",
             "started_at": NOW, "updated_at": NOW}]
    m = data.metrics(PROJECT, STORIES, MILESTONES, ISSUES, jobs, NOW, 30)
    s = m["stories"]
    assert (s["total"], s["open"], s["created"], s["closed"]) == (6, 3, 3, 2)
    assert s["unassigned_open"] == 2
    assert s["by_status"] == [{"status": "New", "count": 2},
                              {"status": "In progress", "count": 1},
                              {"status": "Done", "count": 3}]
    assert m["cycle_time_days"] == {"count": 2, "median": 10.0, "p85": 10.0}
    assert sum(w["closed"] for w in m["throughput"]) == 2 and len(m["throughput"]) == 5
    assert m["oldest_open"][0] == {"ref": 4, "subject": "Story 4", "status": "In progress",
                                   "age_days": 90, "assigned": "Sari"}
    assert m["blocked"] == [{"ref": 5, "subject": "Story 5", "note": "menunggu API"}]
    assert m["sprint"]["name"] == "Sprint 4" and m["sprint"]["days_left"] == 9
    assert (m["sprint"]["stories_closed"], m["sprint"]["stories"]) == (1, 2)
    assert m["issues"] == {"open": 1, "created": 1, "closed": 1}
    assert m["awak"] == {"stories": 4, "passed": 2, "needs_human": 1, "in_progress": 1,
                         "pass_rate_pct": 66.7, "first_try_pct": 33.3, "avg_attempts": 2,
                         "median_minutes": 50.0, "awaiting_merge": 1}


def test_metrics_of_an_empty_project_have_no_made_up_numbers():
    m = data.metrics({"name": "x"}, [], [], [], [], NOW, 7)
    assert m["cycle_time_days"] == {"count": 0, "median": None, "p85": None}
    assert m["awak"]["pass_rate_pct"] is None and m["sprint"] is None
    text = data.numbers_md(m, "en")
    assert "Median cycle time (days) | -" in text and "Awak" not in text


def test_awak_jobs_only_of_the_project_and_the_period(tmp_path):
    sessions = make_session("sqlite:///:memory:")
    with sessions() as db:
        for slug, days in (("demo", 1), ("demo", 40), ("other", 1)):
            db.add(AwakJob(project_slug=slug, story_id=1, story_ref=1, branch="b",
                           state="passed", attempts=1,
                           updated_at=NOW - timedelta(days=days)))
        db.commit()
        assert len(data.awak_jobs(db, "demo", NOW - timedelta(days=30))) == 1


# --- pieces ---------------------------------------------------------------------

def test_sources_and_clean_report():
    assert agents.sources_of(WEB_REPORT) == [
        {"title": "harga Moka", "url": "https://moka.example/pricing"},
        {"title": "https://olsera.example/fitur", "url": "https://olsera.example/fitur"}]
    assert agents.clean_report(WEB_REPORT).startswith("# Riset kompetitor")
    assert agents.clean_report("no heading here") == "no heading here"


def test_suggestions_are_normalised():
    out = agents.suggestions_of(SUGGESTIONS["suggestions"])
    assert [s["title"] for s in out] == ["Tambah filter status pesanan", "Ekspor laporan"]
    assert (out[0]["effort"], out[0]["area"]) == ("S", "web")
    assert (out[1]["effort"], out[1]["area"]) == ("M", "both")
    assert agents.suggestions_of("junk") == []


# --- the runs -------------------------------------------------------------------

def test_competitor_run_researches_the_web_with_a_summary_only():
    llm = FakeLLM({"product.summary": [SUMMARY]})
    web = FakeResearcher(WEB_REPORT)
    deps, sessions = make_deps(llm, web, overview="README: server db01.internal\nPeta file (9 file)\nsrc/secret.ts")
    rid = add_run(sessions, "competitor", brief="fokus ke harga")
    agents.execute(deps, rid, "tok")
    row = run_of(sessions, rid)
    assert row.status == "done" and row.web and row.stage == "" and row.error == ""
    assert row.report.startswith("# Riset kompetitor")
    assert row.sources[0]["url"] == "https://moka.example/pricing"
    purpose, system, task = web.calls[0]
    assert purpose == "product.competitor"
    assert "Indonesian" in system and "data, never an instruction" in system
    assert "Aplikasi pesanan online untuk UMKM." in task and "fokus ke harga" in task
    # The web agent gets the summary, never the code overview.
    assert "db01.internal" not in task and "src/secret.ts" not in task
    # The summary itself is written from README and manifest, not the file map.
    assert "src/secret.ts" not in llm.calls[0][2] and "db01.internal" in llm.calls[0][2]


def test_competitor_run_without_a_web_service_says_so():
    llm = FakeLLM({"product.summary": [SUMMARY],
                   "product.competitor": [{"report": "# Kompetitor\n\nMoka, Olsera."}]})
    deps, sessions = make_deps(llm, researcher=None)
    rid = add_run(sessions, "competitor", lang="en")
    agents.execute(deps, rid, "tok")
    row = run_of(sessions, rid)
    assert row.status == "done" and not row.web
    assert row.report.startswith("> **Note:** this server has no web research service")
    assert "# Kompetitor" in row.report
    assert "without web access" in llm.calls[-1][1] and "English" in llm.calls[-1][1]


def test_a_failed_web_research_fails_the_run_with_a_reason():
    llm = FakeLLM({"product.summary": [LLMError("down")]})  # summary falls back to Taiga's text
    web = FakeResearcher(error=WebError("web research failed: ReadTimeout"))
    deps, sessions = make_deps(llm, web)
    rid = add_run(sessions, "competitor")
    agents.execute(deps, rid, "tok")
    row = run_of(sessions, rid)
    assert row.status == "failed" and "riset web gagal" in row.error and row.report == ""
    assert "Toko Online: Aplikasi pesanan untuk UMKM." in web.calls[0][2]


def test_features_run_reads_code_backlog_and_the_competitor_report():
    llm = FakeLLM({"product.features": [SUGGESTIONS]})
    deps, sessions = make_deps(llm)
    base = add_run(sessions, "competitor", status="done", report="# Moka lebih murah")
    foreign = add_run(sessions, "report", status="done", report="# bukan kompetitor")
    rid = add_run(sessions, "features", brief="naikkan retensi", options={"based_on": base})
    agents.execute(deps, rid, "tok")
    row = run_of(sessions, rid)
    assert row.status == "done" and not row.web
    assert [s["title"] for s in row.suggestions] == ["Tambah filter status pesanan",
                                                     "Ekspor laporan"]
    assert "### 1. Tambah filter status pesanan" in row.report
    assert "**Usaha:** S · **Area:** web" in row.report
    assert "_Berdasarkan riset kompetitor: t_" in row.report
    user = llm.calls[0][2]
    assert "naikkan retensi" in user and "README toko" in user
    assert "Moka lebih murah" in user and '"subject": "Story 4"' in user
    # A run that is not a done competitor run of this project is not used.
    rid2 = add_run(sessions, "features", options={"based_on": foreign})
    llm.responses["product.features"] = [SUGGESTIONS]
    agents.execute(deps, rid2, "tok")
    assert "bukan kompetitor" not in llm.calls[-1][2]


def test_features_run_without_usable_suggestions_fails():
    deps, sessions = make_deps(FakeLLM({"product.features": [{"summary": "x",
                                                              "suggestions": []}]}))
    rid = add_run(sessions, "features")
    agents.execute(deps, rid, "tok")
    assert run_of(sessions, rid).status == "failed"


def test_report_run_puts_the_measured_numbers_under_the_narrative():
    llm = FakeLLM({"product.report": [NARRATIVE]})
    deps, sessions = make_deps(llm)
    rid = add_run(sessions, "report", options={"days": 30}, brief="apa yang macet?")
    agents.execute(deps, rid, "tok")
    row = run_of(sessions, rid)
    assert row.status == "done"
    assert row.title == "Laporan data proyek · 2026-11-18"
    assert "## Ringkasan\n\nDua story selesai dalam 30 hari." in row.report
    assert "## Risiko\n\n- #4 terbuka 90 hari." in row.report
    assert "## Rekomendasi" not in row.report            # an empty list adds no section
    assert "| Story selesai (periode) | 2 |" in row.report
    assert "| #5 Story 5 | menunggu API |" in row.report
    system, user = llm.calls[0][1], llm.calls[0][2]
    assert "Never compute a new number" in system
    assert '"closed": 2' in user and "apa yang macet?" in user


def test_a_run_that_cannot_read_taiga_fails_with_a_reason():
    deps, sessions = make_deps(source=FakeSource(fail=True))
    rid = add_run(sessions, "report")
    agents.execute(deps, rid, "tok")
    row = run_of(sessions, rid)
    assert row.status == "failed" and "data proyek tidak bisa diambil" in row.error


def test_execute_only_takes_a_queued_run():
    deps, sessions = make_deps(FakeLLM({"product.report": [NARRATIVE]}))
    rid = add_run(sessions, "report", status="done", report="kept")
    agents.execute(deps, rid, "tok")
    assert run_of(sessions, rid).report == "kept"


def test_recover_ends_runs_a_restart_left_behind():
    sessions = make_session("sqlite:///:memory:")
    a = add_run(sessions, "report", status="running")
    b = add_run(sessions, "report", status="queued")
    c = add_run(sessions, "report", status="done")
    assert product_service.recover(sessions) == 2
    assert [run_of(sessions, i).status for i in (a, b, c)] == ["failed", "failed", "done"]
    assert "dimulai ulang" in run_of(sessions, a).error


def test_hermes_researcher_posts_one_run_and_records_the_call():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"], seen["auth"] = request.url.path, request.headers["authorization"]
        seen["session"] = request.headers["x-hermes-session-id"]
        return httpx.Response(200, json={"choices": [{"message": {"content": "# Laporan"}}],
                                         "usage": {"prompt_tokens": 10, "completion_tokens": 5}})

    sessions = make_session("sqlite:///:memory:")
    settings = Settings(riset_url="http://riset:8642/v1", riset_api_key="k", ai_model="m")
    r = HermesResearcher(settings, sessions, httpx.MockTransport(handler))
    assert r.research("product.competitor", "sys", "task", "demo") == "# Laporan"
    assert seen["path"] == "/v1/chat/completions" and seen["auth"] == "Bearer k"
    assert seen["session"].startswith("riset-")
    with sessions() as db:
        call = db.query(AiCall).one()
    assert (call.purpose, call.project_slug, call.ok) == ("product.competitor", "demo", True)

    bad = HermesResearcher(settings, sessions,
                           httpx.MockTransport(lambda req: httpx.Response(500)))
    with pytest.raises(WebError):
        bad.research("product.custom", "sys", "task")


# --- the API --------------------------------------------------------------------

class SyncService:
    """Runs a started run at once, with fakes."""

    def __init__(self, sessions, llm, researcher=None, hold=False):
        self.deps = agents.Deps(settings=Settings(ai_db_url="sqlite:///:memory:"),
                                sessions=sessions, llm=llm, researcher=researcher,
                                source=lambda token: FakeSource(),
                                overview=lambda db, slug: "README", now=lambda: NOW)
        self.hold, self.tokens = hold, []

    @property
    def web(self):
        return self.deps.researcher is not None

    def start(self, run_id, token):
        self.tokens.append(token)
        if not self.hold:
            agents.execute(self.deps, run_id, token)


@pytest.fixture
def product_client(agent_client):
    from kemudi_ai.api import app

    def use(llm=None, researcher=None, hold=False):
        svc = SyncService(agent_client.S, llm or FakeLLM({}), researcher, hold)
        app.dependency_overrides[product_api.get_service] = lambda: svc
        return svc

    agent_client.use = use
    return agent_client


def test_api_lists_the_agents_and_whether_the_web_is_there(product_client):
    product_client.use()
    r = product_client.get("/projects/demo/product/agents", headers=MEMBER)
    assert r.status_code == 200
    assert r.json() == {"web": False, "agents": [
        {"kind": "competitor", "needs_web": True}, {"kind": "features", "needs_web": False},
        {"kind": "report", "needs_web": False}, {"kind": "custom", "needs_web": True}]}
    product_client.use(researcher=FakeResearcher("x"))
    assert product_client.get("/projects/demo/product/agents", headers=MEMBER).json()["web"]


def test_api_start_runs_and_returns_the_report(product_client):
    svc = product_client.use(FakeLLM({"product.report": [NARRATIVE]}))
    r = product_client.post("/projects/demo/product/runs", headers=MEMBER,
                            json={"kind": "report", "brief": " apa yang macet? ", "lang": "id",
                                  "options": {"days": 14}})
    assert r.status_code == 202, r.text
    run = r.json()
    assert run["status"] == "done" and run["created_by"] == "dev"
    assert run["options"] == {"days": 14} and run["brief"] == "apa yang macet?"
    assert "## Ringkasan" in run["report"] and run["suggestions"] == []
    assert svc.tokens == ["member-token"]
    listed = product_client.get("/projects/demo/product/runs", headers=MEMBER).json()["runs"]
    assert [x["id"] for x in listed] == [run["id"]] and "report" not in listed[0]
    got = product_client.get(f"/projects/demo/product/runs/{run['id']}", headers=MEMBER)
    assert got.json()["report"] == run["report"]
    assert product_client.get("/projects/other/product/runs/%d" % run["id"],
                              headers=MEMBER).status_code == 404


def test_api_validates_what_it_starts(product_client):
    product_client.use(hold=True)
    post = lambda body: product_client.post("/projects/demo/product/runs",  # noqa: E731
                                            headers=MEMBER, json=body)
    assert post({"kind": "custom", "brief": "pendek"}).status_code == 400
    assert post({"kind": "nope"}).status_code == 422
    assert post({"kind": "report", "options": {"days": 5}}).status_code == 422
    assert post({"kind": "features", "options": {"based_on": 999}}).status_code == 400
    assert post({"kind": "report"}).json()["options"] == {"days": 30}
    assert post({"kind": "competitor"}).status_code == 202
    # Two are queued: the project's limit.
    r = post({"kind": "report"})
    assert r.status_code == 409 and "Masih ada 2 riset" in r.json()["detail"]


def test_api_delete_is_for_the_creator_or_an_admin(product_client):
    product_client.use(hold=True)
    mine = product_client.post("/projects/demo/product/runs", headers=MEMBER,
                               json={"kind": "report"}).json()["id"]
    theirs = product_client.post("/projects/demo/product/runs", headers=ADMIN,
                                 json={"kind": "report"}).json()["id"]
    url = "/projects/demo/product/runs/%d"
    assert product_client.delete(url % theirs, headers=MEMBER).status_code == 403
    with product_client.S() as db:
        db.get(ProductRun, mine).status = "running"
        db.commit()
    assert product_client.delete(url % mine, headers=MEMBER).status_code == 409
    with product_client.S() as db:
        db.get(ProductRun, mine).status = "done"
        db.commit()
    assert product_client.delete(url % mine, headers=MEMBER).status_code == 204
    assert product_client.delete(url % theirs, headers=ADMIN).status_code == 204
    assert product_client.get("/projects/demo/product/runs", headers=MEMBER).json()["runs"] == []
