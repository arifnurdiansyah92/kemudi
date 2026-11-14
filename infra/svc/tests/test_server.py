"""kemudi-svc's HTTP surface: health, key, op routing, error shapes.

Run: python -m pytest infra/svc -q
"""

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest


@pytest.fixture
def server(svc):
    def echo(body):
        if body.get("bad"):
            raise svc.Refused("bad thing")
        if body.get("oops"):
            int("abc")  # an unexpected ValueError is svc's trouble, not a refusal
        if body.get("boom"):
            raise RuntimeError("daemon gone")
        return {"ok": True, "got": body}

    svc.OPS["echo"] = echo
    srv = ThreadingHTTPServer(("127.0.0.1", 0), svc.Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield svc, f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def post(url, body, key):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {key}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_health_and_auth(server):
    svc, base = server
    with urllib.request.urlopen(base + "/health", timeout=10) as r:
        assert r.status == 200
    assert post(base + "/echo", {}, "wrong")[0] == 401
    assert post(base + "/echo", {"a": 1}, svc.KEY) == (200, {"ok": True, "got": {"a": 1}})
    assert post(base + "/nope", {}, svc.KEY)[0] == 404


def test_errors(server):
    svc, base = server
    assert post(base + "/echo", {"bad": 1}, svc.KEY) == (400, {"error": "bad thing"})
    code, body = post(base + "/echo", {"boom": 1}, svc.KEY)
    assert code == 200 and "daemon gone" in body["infra_error"]
    code, body = post(base + "/echo", {"oops": 1}, svc.KEY)
    assert code == 200 and body["infra_error"].startswith("ValueError")
    assert post(base + "/echo", [1], svc.KEY)[0] == 400


def test_int_field(svc):
    for bad in ("abc", 1.5, True, "-3"):
        with pytest.raises(svc.Refused, match="tail"):
            svc.int_field({"tail": bad}, "tail", 1)
    assert svc.int_field({"tail": "50"}, "tail", 1) == 50
    assert svc.int_field({}, "tail", 7) == 7


def test_empty_key_refuses_everything(server, monkeypatch):
    svc, base = server
    monkeypatch.setattr(svc, "KEY", "")
    assert post(base + "/echo", {}, "")[0] == 401


def test_job_dir(svc):
    assert svc.job_dir({"path": "demo/us-1/web"}) == svc.WORKSPACE / "demo" / "us-1" / "web"
    for bad in ("", "../x", "demo/us-1/../../etc", "/etc/passwd", "demo/us-1/missing",
                "Demo/us-1/web", "demo/x/web"):
        with pytest.raises(ValueError):
            svc.job_dir({"path": bad})
