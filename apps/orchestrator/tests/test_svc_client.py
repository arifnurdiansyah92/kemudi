import httpx
import pytest

from kemudi_ai.awak.svc import SvcClient, SvcError, SvcRejected
from kemudi_ai.config import Settings


def test_svc_settings_default():
    s = Settings()
    assert s.svc_url == "http://kemudi-svc:8810"
    assert s.svc_key == ""


def test_svc_client_sends_key_and_payload():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers.get("Authorization")
        seen["path"] = request.url.path
        seen["body"] = request.content
        return httpx.Response(200, json={"ok": True, "url": "http://kemudi-dind:32768"})

    key = "k" * 8
    c = SvcClient("http://svc/", key, transport=httpx.MockTransport(handler))
    res = c.call("svc_up", path="demo/us-1/web", project="demo-us1")
    assert res["url"] == "http://kemudi-dind:32768"
    assert seen["auth"] == f"Bearer {key}" and seen["path"] == "/svc_up"
    assert b'"project":"demo-us1"' in seen["body"].replace(b" ", b"")


def test_svc_client_400_is_a_refusal_other_errors_are_infra():
    def handler(request):
        if request.url.path == "/svc_up":
            return httpx.Response(400, json={"error": "service backend: key 'privileged' is not allowed"})
        return httpx.Response(500, text="boom")

    c = SvcClient("http://svc", "k", transport=httpx.MockTransport(handler))
    with pytest.raises(SvcRejected, match="privileged"):
        c.call("svc_up", path="p")
    with pytest.raises(SvcError) as e:
        c.call("svc_down", project="p")
    assert not isinstance(e.value, SvcRejected)
