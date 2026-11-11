import io
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from kemudi_ai import auth
from kemudi_ai.api import _sessions, app, get_llm, get_sessions
from kemudi_ai.store import Decision, make_session

from .fakes import FakeLLM

USERS = {"admin-token": (1, "pm", True), "member-token": (2, "dev", False)}


def taiga(request: httpx.Request) -> httpx.Response:
    token = request.headers.get("authorization", "").split(" ")[-1]
    if token not in USERS:
        return httpx.Response(401)
    uid, name, is_admin = USERS[token]
    if request.url.path.endswith("/users/me"):
        return httpx.Response(200, json={"id": uid, "username": name})
    if request.url.path.endswith("/projects/by_slug"):
        return httpx.Response(200, json={"i_am_admin": is_admin})
    return httpx.Response(404)


@pytest.fixture
def client():
    S = make_session("sqlite:///:memory:")
    llm = FakeLLM({
        "baseline": [{"items": [{"kind": "epic", "title": "Payment", "clauses": ["S1"]}]}] * 3,
        "classify": [{"label": "cr_candidate", "reason": "baru", "effort_days": {"backend": 1}}] * 5,
    })
    auth._transport = httpx.MockTransport(taiga)
    app.dependency_overrides[get_sessions] = lambda: S
    app.dependency_overrides[get_llm] = lambda: llm
    with TestClient(app) as c:
        c.S = S
        yield c
    app.dependency_overrides.clear()
    auth._transport = None
    _sessions.cache_clear()


ADMIN = {"Authorization": "Bearer admin-token"}
MEMBER = {"Authorization": "Bearer member-token"}
CONTRACT = "RUANG LINGKUP PEKERJAAN\n1 Payment Gateway\n".encode()


def upload(client):
    return client.post(
        "/projects/demo/contract",
        headers=ADMIN,
        files={"file": ("contract.docx", _docx(CONTRACT.decode()), "application/octet-stream")},
        data={"lang": "id", "rate_card": json.dumps({"per_day": {"backend": 1_000_000}})},
    )


def _docx(text: str) -> bytes:
    from docx import Document

    d = Document()
    for line in text.splitlines():
        d.add_paragraph(line)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def test_401_without_token(client):
    assert client.get("/projects/demo/contract").status_code == 401
    assert client.get("/projects/demo/contract", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_403_member_cannot_approve(client):
    assert client.post("/projects/demo/baseline/approve", headers=MEMBER).status_code == 403


def test_approve_bumps_version_and_logs_decision(client):
    assert upload(client).status_code == 200
    assert client.post("/projects/demo/baseline/draft", headers=ADMIN).status_code == 200
    r = client.post("/projects/demo/baseline/approve", headers=ADMIN)
    assert r.json()["number"] == 1
    client.post("/projects/demo/baseline/draft", headers=ADMIN)
    assert client.post("/projects/demo/baseline/approve", headers=ADMIN).json()["number"] == 2
    body = client.get("/projects/demo/contract", headers=MEMBER).json()
    assert [v["number"] for v in body["baseline"]["history"]] == [2, 1]
    with client.S() as s:
        actions = [d.action for d in s.query(Decision)]
    assert actions.count("approve_baseline") == 2


def test_backtest_run_and_verdict_updates_metrics(client):
    upload(client)
    client.post("/projects/demo/baseline/draft", headers=ADMIN)
    client.post("/projects/demo/baseline/approve", headers=ADMIN)
    dataset = {"tickets": [{"id": "T1", "text": "tambah fitur", "expected": {"label": "cr_candidate"}}]}
    r = client.post(
        "/projects/demo/backtests",
        headers=ADMIN,
        files={"dataset": ("d.json", json.dumps(dataset).encode(), "application/json")},
    )
    run_id = r.json()["run_id"]
    body = client.get(f"/projects/demo/backtests/{run_id}", headers=MEMBER).json()
    assert body["run"]["finished_at"] is not None
    assert body["metrics"]["accuracy"] == 1.0
    assert body["results"][0]["predicted"]["price_idr"] == 1_000_000
    rid = body["results"][0]["id"]
    v = client.put(f"/projects/demo/backtests/{run_id}/results/{rid}/verdict", headers=ADMIN, json={"verdict": "right"})
    assert v.status_code == 200
    body = client.get(f"/projects/demo/backtests/{run_id}", headers=MEMBER).json()
    assert body["metrics"]["verdicts"] == {"right": 1, "wrong": 0, "pending": 0}


def test_backtest_needs_approved_baseline(client):
    upload(client)
    r = client.post(
        "/projects/demo/backtests",
        headers=ADMIN,
        files={"dataset": ("d.json", b'{"tickets": []}', "application/json")},
    )
    assert r.status_code == 409
