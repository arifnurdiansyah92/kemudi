import csv
import io

import httpx
import pytest
from fastapi.testclient import TestClient

from kemudi_ai import auth
from kemudi_ai.api import _sessions, app, get_llm, get_sessions
from kemudi_ai.cr_check import cited_items, to_csv
from kemudi_ai.baseline import BaselineItem
from kemudi_ai.store import BaselineVersion, Contract, CrCheck, Decision, make_session

from .fakes import FakeLLM

USERS = {"admin-token": (1, "pm", True), "member-token": (2, "dev", False)}
ADMIN = {"Authorization": "Bearer admin-token"}
MEMBER = {"Authorization": "Bearer member-token"}
TICKETS = {
    ("userstories", 12): {"subject": "Export laporan ke Excel", "description": "Tambah tombol export."},
    ("issues", 3): {"subject": "Login error", "description": ""},
}
ITEMS = [
    {"ref": "B1", "kind": "epic", "title": "Payment", "clauses": ["S1: Payment"]},
    {"ref": "B2", "kind": "story", "title": "Laporan", "clauses": ["S2: Laporan harian"]},
]
CR = {"label": "cr_candidate", "reason": "Export belum ada di baseline.",
      "clause": "B2: Laporan harian", "effort_days": {"backend": 1.5}}


def taiga(request: httpx.Request) -> httpx.Response:
    token = request.headers.get("authorization", "").split(" ")[-1]
    if token not in USERS:
        return httpx.Response(401)
    uid, name, is_admin = USERS[token]
    path = request.url.path
    if path.endswith("/users/me"):
        return httpx.Response(200, json={"id": uid, "username": name})
    if path.endswith("/projects/by_slug"):
        return httpx.Response(200, json={"i_am_admin": is_admin})
    if path.endswith("/by_ref"):
        assert request.url.params["project__slug"] == "demo"
        key = (path.split("/")[-2], int(request.url.params["ref"]))
        if key in TICKETS:
            return httpx.Response(200, json=TICKETS[key])
    return httpx.Response(404)


def make_client(replies):
    S = make_session("sqlite:///:memory:")
    llm = FakeLLM({"classify": replies})
    auth._transport = httpx.MockTransport(taiga)
    app.dependency_overrides[get_sessions] = lambda: S
    app.dependency_overrides[get_llm] = lambda: llm
    c = TestClient(app)
    c.S, c.llm = S, llm
    return c


@pytest.fixture
def client():
    with make_client([CR] * 5) as c:
        yield c
    app.dependency_overrides.clear()
    auth._transport = None
    _sessions.cache_clear()


def seed(c, approved=True, show_prices=False):
    with c.S() as s:
        k = Contract(project_slug="demo", filename="c.docx", lang="id",
                     rate_card={"per_day": {"backend": 1_000_000}}, show_prices=show_prices)
        s.add(k)
        s.commit()
        s.add(BaselineVersion(contract_id=k.id, number=1 if approved else 0,
                              status="approved" if approved else "draft", items=ITEMS))
        s.commit()


def check(c, kind="userstory", ref=12, headers=ADMIN, **extra):
    return c.post("/projects/demo/cr-check", headers=headers, json={"kind": kind, "ref": ref, **extra})


def test_needs_an_approved_baseline(client):
    r = check(client)
    assert r.status_code == 409
    assert "approved contract baseline" in r.json()["detail"]
    seed(client, approved=False)
    assert check(client).status_code == 409
    t = client.get("/projects/demo/cr-checks/userstory/12", headers=MEMBER).json()
    assert t["baseline"] is None and t["checks"] == []


def test_member_cannot_run_or_decide(client):
    seed(client)
    assert check(client, headers=MEMBER).status_code == 403
    cid = check(client).json()["id"]
    r = client.post(f"/projects/demo/cr-checks/{cid}/verdict", headers=MEMBER, json={"verdict": "agree"})
    assert r.status_code == 403


def test_story_check_reads_taiga_and_stores_the_result(client):
    seed(client)
    r = check(client)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["label"] == "cr_candidate"
    assert body["reasoning"] == "Export belum ada di baseline."
    assert body["cited"] == [{"ref": "B2", "title": "Laporan", "clauses": ["S2: Laporan harian"]}]
    assert body["effort_days"] == {"backend": 1.5}
    assert body["effort_total_days"] == 1.5
    assert body["price_idr"] is None  # prices are off by default
    assert body["checked_by"] == "pm (1)"
    assert body["baseline_number"] == 1
    assert body["subject"] == "Export laporan ke Excel"
    # The ticket text reached the model.
    assert "Tambah tombol export." in client.llm.calls[0][2]
    with client.S() as s:
        row = s.query(CrCheck).one()
        assert row.price_idr == 1_500_000  # stored, only hidden
        assert [d.action for d in s.query(Decision)] == ["cr_check"]


def test_issue_and_unknown_ticket(client):
    seed(client)
    assert check(client, kind="issue", ref=3).status_code == 200
    assert check(client, kind="issue", ref=99).status_code == 404
    assert check(client, kind="epic", ref=3).status_code == 422


def test_text_instead_of_taiga(client):
    seed(client)
    r = check(client, ref=500, subject="Dari email", text="Klien minta fitur baru")
    assert r.status_code == 200
    assert "Klien minta fitur baru" in client.llm.calls[0][2]


def test_prices_show_when_enabled(client):
    seed(client)
    assert client.put("/projects/demo/contract/settings", headers=MEMBER,
                      json={"show_prices": True}).status_code == 403
    r = client.put("/projects/demo/contract/settings", headers=ADMIN, json={"show_prices": True})
    assert r.json() == {"show_prices": True}
    assert client.get("/projects/demo/contract", headers=MEMBER).json()["contract"]["show_prices"] is True
    assert check(client).json()["price_idr"] == 1_500_000


def test_history_per_ticket_and_project(client):
    seed(client)
    first = check(client).json()["id"]
    second = check(client).json()["id"]
    check(client, kind="issue", ref=3)
    t = client.get("/projects/demo/cr-checks/userstory/12", headers=MEMBER).json()
    assert t["baseline"] == {"number": 1}
    assert [c["id"] for c in t["checks"]] == [second, first]
    p = client.get("/projects/demo/cr-checks", headers=MEMBER).json()
    assert len(p["checks"]) == 3 and p["show_prices"] is False


def test_verdict(client):
    seed(client)
    cid = check(client).json()["id"]
    r = client.post(f"/projects/demo/cr-checks/{cid}/verdict", headers=ADMIN,
                    json={"verdict": "disagree", "corrected_label": "in_baseline", "note": "Garansi"})
    assert r.status_code == 200
    v = r.json()
    assert (v["verdict"], v["corrected_label"], v["verdict_note"], v["decided_by"]) == \
        ("disagree", "in_baseline", "Garansi", "pm (1)")
    assert v["label"] == "cr_candidate"  # the suggestion is kept
    # Agreeing clears a corrected label.
    v = client.post(f"/projects/demo/cr-checks/{cid}/verdict", headers=ADMIN,
                    json={"verdict": "agree"}).json()
    assert v["corrected_label"] is None
    bad = client.post(f"/projects/demo/cr-checks/{cid}/verdict", headers=ADMIN,
                      json={"verdict": "disagree", "corrected_label": "cr_candidate"})
    assert bad.status_code == 422
    assert client.post("/projects/demo/cr-checks/999/verdict", headers=ADMIN,
                       json={"verdict": "agree"}).status_code == 404
    with client.S() as s:
        assert [d.action for d in s.query(Decision)].count("cr_verdict") == 2


def test_export_csv(client):
    seed(client)
    cid = check(client).json()["id"]
    client.post(f"/projects/demo/cr-checks/{cid}/verdict", headers=ADMIN, json={"verdict": "agree"})
    r = client.get("/projects/demo/cr-checks/export", headers=MEMBER)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(r.text.lstrip("﻿"))))
    assert rows[0]["ref"] == "#12"
    assert rows[0]["label"] == "cr_candidate"
    assert rows[0]["clauses"] == "B2: Laporan harian"
    assert rows[0]["effort_days"] == "1.5"
    assert rows[0]["price_idr"] == ""  # hidden while prices are off
    assert rows[0]["verdict"] == "agree"
    assert rows[0]["decided_by"] == "pm (1)"


def test_ai_failure_is_a_502():
    with make_client([{"label": "maybe"}]) as c:
        seed(c)
        r = check(c)
        assert r.status_code == 502
        with c.S() as s:
            assert s.query(CrCheck).count() == 0
    app.dependency_overrides.clear()
    auth._transport = None
    _sessions.cache_clear()


def test_cited_items_and_csv_formula_guard():
    items = [BaselineItem.model_validate(i) for i in ITEMS]
    assert [c["ref"] for c in cited_items("B2 and B1, B2, B9", items)] == ["B2", "B1"]
    row = CrCheck(ticket_kind="issue", ticket_ref=1, subject="=HYPERLINK(1)", label="in_baseline",
                  reasoning="", clause="", cited=[], effort_days={}, price_idr=0,
                  checked_by="pm", verdict_note="", model="m")
    out = list(csv.reader(io.StringIO(to_csv([row], True))))
    assert out[1][2] == "'=HYPERLINK(1)"


def test_migrate_adds_show_prices(tmp_path):
    from sqlalchemy import create_engine, inspect, text

    from kemudi_ai.store import init_db

    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as c:
        c.execute(text(
            "CREATE TABLE contracts (id INTEGER PRIMARY KEY, project_slug VARCHAR(200) UNIQUE,"
            " filename VARCHAR(300), sections JSON, lang VARCHAR(5), rate_card JSON,"
            " created_at DATETIME)"))
        c.execute(text("INSERT INTO contracts VALUES (1, 'demo', 'c.pdf', '[]', 'id', '{}',"
                       " '2026-11-11 10:00:00')"))
    init_db(engine)
    assert "show_prices" in {c["name"] for c in inspect(engine).get_columns("contracts")}
    assert "cr_checks" in inspect(engine).get_table_names()
    S = make_session(f"sqlite:///{tmp_path / 'old.db'}")
    with S() as db:
        assert db.get(Contract, 1).show_prices is False


class RecordingLLM(FakeLLM):
    """Logs each call like HermesLLM does, so the project tag can be checked."""

    def __init__(self, S, replies):
        super().__init__(replies)
        self.S = S

    def json(self, purpose, system, user):
        from kemudi_ai.store import record_ai_call

        with self.S() as db:
            record_ai_call(db, log_prompts=False, purpose=purpose, model="m", prompt=user)
        return super().json(purpose, system, user)


def test_checks_are_audited_and_deleted_with_the_contract(client):
    from kemudi_ai.store import AiCall, AuditEvent

    seed(client)
    app.dependency_overrides[get_llm] = lambda: RecordingLLM(client.S, {"classify": [CR]})
    cid = check(client).json()["id"]
    with client.S() as s:
        assert [(c.project_slug, c.purpose) for c in s.query(AiCall)] == [("demo", "classify")]
    client.post(f"/projects/demo/cr-checks/{cid}/verdict", headers=ADMIN,
                json={"verdict": "disagree", "note": "garansi"})
    client.put("/projects/demo/contract/settings", headers=ADMIN, json={"show_prices": True})
    with client.S() as s:
        events = {e.action: e for e in s.query(AuditEvent)}
        assert {"cr_check", "cr_verdict", "contract_settings"} <= set(events)
        v = events["cr_verdict"]
        assert (v.project_slug, v.actor_id, v.detail["ticket"]) == ("demo", 1, "userstory#12")

    r = client.delete("/projects/demo/contract", headers=ADMIN)
    assert r.status_code == 200, r.text
    assert r.json()["deleted"]["cr_checks"] == 1
    with client.S() as s:
        assert s.query(CrCheck).count() == 0 and s.query(AiCall).count() == 0
        assert s.query(AuditEvent).filter_by(action="cr_verdict").count() == 1
    t = client.get("/projects/demo/cr-checks/userstory/12", headers=MEMBER).json()
    assert t == {"baseline": None, "show_prices": False, "checks": []}
