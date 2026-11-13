import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from kemudi_ai import auth
from kemudi_ai.api import _sessions, app, get_sessions
from kemudi_ai.awak import agent_api
from kemudi_ai.config import Settings, get_settings
from kemudi_ai.store import make_session

SECRET_KEY = Fernet.generate_key().decode()
ADMIN = {"Authorization": "Bearer admin-token"}
MEMBER = {"Authorization": "Bearer member-token"}
_USERS = {"admin-token": (1, "pm", True), "member-token": (2, "dev", False)}


def taiga_auth(request: httpx.Request) -> httpx.Response:
    token = request.headers.get("authorization", "").split(" ")[-1]
    if token not in _USERS:
        return httpx.Response(401)
    uid, name, is_admin = _USERS[token]
    if request.url.path.endswith("/users/me"):
        return httpx.Response(200, json={"id": uid, "username": name})
    if request.url.path.endswith("/projects/by_slug"):
        return httpx.Response(200, json={"i_am_admin": is_admin})
    return httpx.Response(404)


@pytest.fixture
def agent_settings(tmp_path):
    return Settings(
        secret_key=SECRET_KEY,
        ssh_dir=str(tmp_path / "ssh"),
        repos_dir=str(tmp_path / "repos"),
        bare_repo=str(tmp_path / "awak.git"),
        host_git=str(tmp_path / "host-git"),
        workspace_dir=str(tmp_path / "ws"),
        ai_db_url="sqlite:///:memory:",
    )


@pytest.fixture
def agent_client(agent_settings):
    """A TestClient for the agent router, with an in-memory DB and fake Taiga auth."""
    S = make_session("sqlite:///:memory:")
    auth._transport = httpx.MockTransport(taiga_auth)
    started: list[bool] = []
    app.dependency_overrides[get_sessions] = lambda: S
    app.dependency_overrides[get_settings] = lambda: agent_settings
    app.dependency_overrides[agent_api.get_worker_starter] = lambda: lambda: started.append(True)
    with TestClient(app) as c:
        c.S = S
        c.settings = agent_settings
        c.started = started
        yield c
    app.dependency_overrides.clear()
    auth._transport = None
    _sessions.cache_clear()
