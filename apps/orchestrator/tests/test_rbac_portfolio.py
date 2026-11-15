"""RBAC: money and agent settings are for project admins; the portfolio is for
superadmins; Kemudi data is for the project team only, even on a public
Taiga project."""

from datetime import datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

from kemudi_ai import auth
from kemudi_ai.api import _sessions, app, get_sessions
from kemudi_ai.config import Settings, get_settings
from kemudi_ai.portfolio import collect
from kemudi_ai.store import (
    AwakJob,
    AwakLlmUsage,
    AwakProject,
    BacktestResult,
    BacktestRun,
    BaselineVersion,
    Contract,
    CrCheck,
    make_session,
)

# token: (id, username, i_am_admin, i_am_member, is_superuser)
USERS = {
    "admin-token": (1, "pm", True, True, False),
    "member-token": (2, "dev", False, True, False),
    "outsider-token": (3, "guest", False, False, False),
    "super-token": (4, "root", True, True, True),
    "ops-token": (5, "ops", False, True, False),  # Kemudi admin via settings
}


def H(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


ADMIN, MEMBER, OUTSIDER, SUPER, OPS = (H(t) for t in USERS)
ITEMS = [
    {"ref": "B1", "kind": "epic", "title": "Payment", "clauses": ["S1"], "price_idr": 50_000_000},
    {"ref": "B2", "kind": "story", "title": "Laporan", "clauses": ["S2"], "price_idr": 25_000_000},
]


def taiga(request: httpx.Request) -> httpx.Response:
    token = request.headers.get("authorization", "").split(" ")[-1]
    if token not in USERS:
        return httpx.Response(401)
    uid, name, is_admin, is_member, su = USERS[token]
    if request.url.path.endswith("/users/me"):
        return httpx.Response(200, json={"id": uid, "username": name, "is_superuser": su})
    if request.url.path.endswith("/projects/by_slug"):
        # Taiga answers anyone on a public project.
        return httpx.Response(200, json={"i_am_admin": is_admin, "i_am_member": is_member})
    return httpx.Response(404)


@pytest.fixture
def client():
    S = make_session("sqlite:///:memory:")
    auth._transport = httpx.MockTransport(taiga)
    app.dependency_overrides[get_sessions] = lambda: S
    app.dependency_overrides[get_settings] = lambda: Settings(
        ai_db_url="sqlite:///:memory:", admin_user_ids="5")
    with TestClient(app) as c:
        c.S = S
        yield c
    app.dependency_overrides.clear()
    auth._transport = None
    _sessions.cache_clear()


def seed(c, slug="demo", show_prices=False):
    with c.S() as s:
        k = Contract(project_slug=slug, filename="c.docx", lang="id",
                     rate_card={"per_day": {"backend": 1_000_000}}, show_prices=show_prices)
        s.add(k)
        s.commit()
        b = BaselineVersion(contract_id=k.id, number=1, status="approved", items=ITEMS)
        s.add(b)
        s.commit()
        run = BacktestRun(contract_id=k.id, baseline_version_id=b.id, dataset_name="d.csv",
                          finished_at=datetime(2026, 11, 1))
        s.add(run)
        s.commit()
        s.add(BacktestResult(run_id=run.id, ticket_id="T1", text="x",
                             expected={"label": "cr_candidate", "price_idr": 3_000_000},
                             predicted={"label": "cr_candidate", "price_idr": 2_000_000}))
        s.add(AwakJob(project_slug=slug, story_id=9, story_ref=9, branch="awak/9",
                      state="passed", cost_idr=12_345.0))
        s.commit()
        return run.id


# --- who is a member ----------------------------------------------------------


def test_outsider_on_a_public_project_sees_nothing(client):
    seed(client)
    assert client.get("/projects/demo/contract", headers=OUTSIDER).status_code == 404
    assert client.get("/projects/demo/cr-checks", headers=OUTSIDER).status_code == 404
    assert client.get("/projects/demo/agent/jobs", headers=OUTSIDER).status_code == 404


# --- money --------------------------------------------------------------------


def test_member_gets_contract_without_money(client):
    seed(client)
    body = client.get("/projects/demo/contract", headers=MEMBER).json()
    assert body["contract"]["rate_card"] is None
    items = body["baseline"]["approved"]["items"]
    assert [i["title"] for i in items] == ["Payment", "Laporan"]
    assert all(i["price_idr"] is None for i in items)
    assert all(i["price_idr"] is None for v in body["baseline"]["history"] for i in v["items"])


def test_admin_always_gets_money(client):
    seed(client, show_prices=False)
    body = client.get("/projects/demo/contract", headers=ADMIN).json()
    assert body["contract"]["rate_card"] == {"per_day": {"backend": 1_000_000}}
    assert [i["price_idr"] for i in body["baseline"]["approved"]["items"]] == [50_000_000, 25_000_000]


def test_show_prices_opens_money_to_members(client):
    seed(client, show_prices=True)
    body = client.get("/projects/demo/contract", headers=MEMBER).json()
    assert body["contract"]["rate_card"] is not None
    assert body["baseline"]["approved"]["items"][0]["price_idr"] == 50_000_000


def test_backtest_value_hidden_from_members(client):
    run_id = seed(client)
    m = client.get(f"/projects/demo/backtests/{run_id}", headers=MEMBER).json()
    assert m["metrics"]["value_expected_idr"] is None
    assert m["metrics"]["value_caught_idr"] is None
    assert m["results"][0]["expected"] == {"label": "cr_candidate", "price_idr": None}
    assert m["results"][0]["predicted"]["price_idr"] is None
    a = client.get(f"/projects/demo/backtests/{run_id}", headers=ADMIN).json()
    assert a["metrics"]["value_expected_idr"] == 3_000_000
    assert a["results"][0]["expected"]["price_idr"] == 3_000_000


def test_awak_cost_is_for_admins(client):
    seed(client)
    for path in ("/projects/demo/agent/jobs", "/projects/demo/awak/jobs"):
        assert client.get(path, headers=MEMBER).json()["jobs"][0]["cost_idr"] is None
        assert client.get(path, headers=ADMIN).json()["jobs"][0]["cost_idr"] == 12_345.0
    assert client.get("/projects/demo/agent/stories/9", headers=MEMBER).json()["job"]["cost_idr"] is None
    assert client.get("/projects/demo/agent/usage", headers=MEMBER).status_code == 403


# --- settings stay admin-only -------------------------------------------------


@pytest.mark.parametrize("method,path,body", [
    ("put", "/projects/demo/contract/rate-card", {"per_day": {"backend": 1}}),
    ("put", "/projects/demo/contract/settings", {"show_prices": True}),
    ("put", "/projects/demo/baseline/draft", {"items": []}),
    ("post", "/projects/demo/baseline/approve", None),
    ("put", "/projects/demo/agent/settings", {"enabled": True}),
    ("put", "/projects/demo/agent/usage/budget", {"monthly_tokens": 1}),
    ("put", "/projects/demo/agent/llm", {"base_url": "", "model": ""}),
])
def test_members_cannot_change_contract_money_or_agent(client, method, path, body):
    seed(client)
    r = getattr(client, method)(path, headers=MEMBER, **({"json": body} if body is not None else {}))
    assert r.status_code == 403, (path, r.text)


# --- superadmin and the portfolio -----------------------------------------------


def test_me_reports_superadmin(client):
    assert client.get("/me", headers=SUPER).json()["superadmin"] is True
    assert client.get("/me", headers=SUPER).json()["is_superuser"] is True
    assert client.get("/me", headers=OPS).json()["superadmin"] is True  # KEMUDI_ADMIN_USER_IDS
    assert client.get("/me", headers=ADMIN).json()["superadmin"] is False


def test_portfolio_is_for_superadmins(client):
    seed(client)
    assert client.get("/portfolio", headers=ADMIN).status_code == 403
    assert client.get("/portfolio", headers=MEMBER).status_code == 403
    assert client.get("/portfolio", headers=SUPER).status_code == 200
    assert client.get("/portfolio", headers=OPS).status_code == 200


def test_superuser_reads_any_project_as_admin(client):
    seed(client)
    body = client.get("/projects/demo/contract", headers=SUPER).json()
    assert body["contract"]["rate_card"] is not None


def test_portfolio_aggregates_every_project(client):
    seed(client, "alpha")
    seed(client, "beta", show_prices=True)
    now = datetime(2026, 11, 15, 12)
    with client.S() as s:
        base = s.query(BaselineVersion).first()
        for i, (label, verdict, corrected, price) in enumerate([
            ("cr_candidate", None, None, 1_000_000),
            ("cr_candidate", "agree", None, 2_000_000),
            ("in_baseline", "disagree", "cr_candidate", 4_000_000),
            ("needs_clarification", None, None, 0),
        ]):
            s.add(CrCheck(project_slug="alpha", ticket_kind="userstory", ticket_ref=i,
                          baseline_version_id=base.id, label=label, verdict=verdict,
                          corrected_label=corrected, price_idr=price, checked_by="pm"))
        s.add(AwakJob(project_slug="alpha", story_id=1, story_ref=1, branch="b", state="failed",
                      updated_at=now - timedelta(days=1)))
        s.add(AwakJob(project_slug="alpha", story_id=2, story_ref=2, branch="b", state="failed",
                      updated_at=now - timedelta(days=30)))
        s.add(AwakProject(slug="alpha", enabled=True, token_budget_monthly=1000))
        s.add(AwakLlmUsage(at=now - timedelta(days=2), project_slug="alpha",
                           prompt_tokens=600, completion_tokens=200, cost_idr=500.0))
        s.add(AwakLlmUsage(at=datetime(2026, 10, 30), project_slug="alpha",
                           prompt_tokens=9999, completion_tokens=0, cost_idr=9.0))
        s.commit()
        out = collect(s, now)

    a, b = out["projects"]["alpha"], out["projects"]["beta"]
    assert a["contract"] == {"exists": True, "baseline_approved": 1, "has_draft": False,
                             "approved_at": None, "value_idr": 75_000_000, "show_prices": False}
    assert b["contract"]["show_prices"] is True
    assert a["cr"]["total"] == 4
    assert a["cr"]["cr_candidate"] == 3  # the PM's correction counts
    assert a["cr"]["in_baseline"] == 0
    assert a["cr"]["unreviewed"] == 2 and a["cr"]["unreviewed_cr"] == 1
    assert a["cr"]["agreed_cr"] == 2 and a["cr"]["agreed_cr_value_idr"] == 6_000_000
    assert a["awak"]["failed"] == 2 and a["awak"]["failed_recent"] == 1
    assert a["awak"]["passed"] == 1 and a["awak"]["enabled"] is True
    assert a["usage"]["tokens"] == 800 and a["usage"]["used_ratio"] == 0.8
    assert a["backtest"]["runs"] == 1
    assert b["awak"]["enabled"] is False and b["usage"]["used_ratio"] is None


def test_portfolio_filter_is_remembered_per_superadmin(client):
    assert client.get("/portfolio", headers=SUPER).json()["excluded"] == []
    r = client.put("/portfolio/excluded", headers=SUPER, json={"excluded": ["beta", " alpha ", "beta"]})
    assert r.json() == {"excluded": ["alpha", "beta"]}
    assert client.get("/portfolio", headers=SUPER).json()["excluded"] == ["alpha", "beta"]
    assert client.get("/portfolio", headers=OPS).json()["excluded"] == []  # their own
    assert client.put("/portfolio/excluded", headers=ADMIN, json={"excluded": []}).status_code == 403
