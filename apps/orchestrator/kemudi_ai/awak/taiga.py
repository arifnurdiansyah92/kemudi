"""The slice of the Taiga API the Awak loop uses, acting as one bot user."""

from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

LOCAL_HOSTS = {"kemudi-back", "kemudi-gateway", "localhost", "127.0.0.1"}


class TaigaError(Exception):
    pass


def assert_local(api_url: str) -> None:
    """The loop writes to Taiga; only ever to the local dev stack."""
    host = urlparse(api_url).hostname or ""
    if host not in LOCAL_HOSTS:
        raise TaigaError(
            f"refusing to run the Awak loop against {host!r}: "
            f"only {sorted(LOCAL_HOSTS)} are allowed"
        )


@dataclass
class Project:
    id: int
    slug: str
    statuses: dict[str, int]  # status slug -> id
    status_names: dict[int, str] = field(default_factory=dict)

    def status(self, slug: str) -> int:
        try:
            return self.statuses[slug]
        except KeyError as e:
            raise TaigaError(
                f"project {self.slug} has no user story status {slug!r}; "
                f"has {sorted(self.statuses)}"
            ) from e


def tag_names(story: dict) -> list[str]:
    out = []
    for t in story.get("tags") or []:
        out.append(t[0] if isinstance(t, (list, tuple)) else str(t))
    return out


class Taiga:
    def __init__(
        self,
        api_url: str,
        username: str,
        password: str,
        transport: httpx.BaseTransport | None = None,
    ):
        assert_local(api_url)
        self.username = username
        self._password = password
        self.c = httpx.Client(
            base_url=api_url.rstrip("/"),
            timeout=30,
            transport=transport,
            headers={"x-disable-pagination": "True"},
        )
        self.me: dict = {}

    # --- auth -----------------------------------------------------------
    def login(self) -> str:
        r = self.c.post(
            "/auth",
            json={"type": "normal", "username": self.username, "password": self._password},
        )
        if r.status_code != 200:
            raise TaigaError(f"login as {self.username} failed: HTTP {r.status_code}")
        data = r.json()
        self.c.headers["Authorization"] = f"Bearer {data['auth_token']}"
        self.me = data
        return data["auth_token"]

    def _req(self, method: str, url: str, **kw) -> httpx.Response:
        if "Authorization" not in self.c.headers:
            self.login()
        r = self.c.request(method, url, **kw)
        if r.status_code == 401:
            self.login()
            r = self.c.request(method, url, **kw)
        if r.status_code >= 400:
            raise TaigaError(f"{method} {url}: HTTP {r.status_code} {r.text[:300]}")
        return r

    # --- reads ----------------------------------------------------------
    def project(self, slug: str) -> Project:
        p = self._req("GET", "/projects/by_slug", params={"slug": slug}).json()
        statuses = {s["slug"]: s["id"] for s in p.get("us_statuses", [])}
        names = {s["id"]: s["name"] for s in p.get("us_statuses", [])}
        return Project(id=p["id"], slug=slug, statuses=statuses, status_names=names)

    def stories(self, project_id: int, status_id: int, tag: str) -> list[dict]:
        r = self._req(
            "GET",
            "/userstories",
            params={"project": project_id, "status": status_id, "tags": tag},
        )
        return [s for s in r.json() if tag in tag_names(s)]

    def story(self, story_id: int) -> dict:
        return self._req("GET", f"/userstories/{story_id}").json()

    def comments(self, story_id: int) -> list[dict]:
        r = self._req("GET", f"/history/userstory/{story_id}", params={"type": "comment"})
        return [h for h in r.json() if (h.get("comment") or "").strip()]

    # --- writes ---------------------------------------------------------
    def create_story(self, project_id: int, **fields) -> dict:
        return self._req("POST", "/userstories", json={"project": project_id, **fields}).json()

    def update_story(self, story_id: int, **fields) -> dict:
        """PATCH with optimistic locking; refetches the version once on conflict."""
        version = fields.pop("version", None)
        if version is None:
            version = self.story(story_id)["version"]
        try:
            return self._req(
                "PATCH", f"/userstories/{story_id}", json={**fields, "version": version}
            ).json()
        except TaigaError as e:
            if "HTTP 400" not in str(e) or "version" not in str(e).lower():
                raise
            fresh = self.story(story_id)["version"]
            return self._req(
                "PATCH", f"/userstories/{story_id}", json={**fields, "version": fresh}
            ).json()

    def comment(self, story_id: int, text: str) -> dict:
        return self.update_story(story_id, comment=text)

    def attach(self, project_id: int, story_id: int, path: str, name: str) -> dict:
        with open(path, "rb") as fh:
            return self._req(
                "POST",
                "/userstories/attachments",
                data={"project": str(project_id), "object_id": str(story_id)},
                files={"attached_file": (name, fh, "image/png")},
            ).json()
