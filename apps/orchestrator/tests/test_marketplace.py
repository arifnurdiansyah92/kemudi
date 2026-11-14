"""Skill marketplaces: marketplace.json parsing (fixtures), the API (register,
refresh, plugins, install pinned), updates (pending -> approve / reject),
authz and fetch failures. The runner is faked (fetch_fakes.py)."""

import json

import pytest

from kemudi_ai.api import app
from kemudi_ai.awak import marketplace, skills
from kemudi_ai.awak.fetched import open_tree
from kemudi_ai.awak.skills_api import get_fetch_runner
from kemudi_ai.store import AwakSkill, AwakSkillMarketplace, AwakSkillVersion, Decision

from .conftest import ADMIN, MEMBER
from .fetch_fakes import FakeFetchRunner
from .test_roles import ROLE
from .test_skills import skill_md

MP = "/skill-marketplaces"
LIB = "/skills"
SHA1, SHA2, SHA3 = "1" * 40, "2" * 40, "3" * 40
EXT_SHA = "e" * 40
APACHE = "\n    Apache License\n    Version 2.0, January 2004\n"


def manifest(plugins, **extra) -> str:
    return json.dumps({"name": "acme-skills", "owner": {"name": "Acme"},
                       "metadata": {"description": "Acme's skills"}, "plugins": plugins,
                       **extra})


def anthropic_like(notes_body="# Notes\n") -> dict:
    """Like anthropics/skills: plugins with source "./" and explicit skills lists."""
    return {
        ".claude-plugin/marketplace.json": manifest([
            {"name": "writing", "description": "Writing skills", "source": "./",
             "strict": False, "skills": ["./skills/notes", "./skills/broken"]},
            {"name": "local-plugin", "source": "./plugin", "version": "4.9.1",
             "category": "design"},
            {"name": "external", "source": {"source": "github", "repo": "ext/plug"}},
            {"name": "by-url", "source": {"source": "url", "url": "https://gitlab.com/x/y.git"}},
            {"name": "by-npm", "source": {"source": "npm", "package": "x"}},
            {"name": "escape", "source": "../outside"},
        ]),
        "LICENSE": APACHE,
        "NOTICE": "Acme NOTICE\n",
        "skills/notes/SKILL.md": skill_md(name="notes", description="Use when writing notes.",
                                          body=notes_body),
        "skills/notes/reference/style.md": "Short sentences.\n",
        "skills/broken/SKILL.md": skill_md(name="other-name"),
        "plugin/skills/design/SKILL.md": skill_md(name="design", extra="license: MIT\n"),
        "plugin/LICENSE": "MIT License\n\nPermission is hereby granted, free of charge\n",
    }


EXTERNAL = {"skills/ext-skill/SKILL.md": skill_md(name="ext-skill"),
            "LICENSE": "MIT License\n"}


@pytest.fixture
def fake(agent_settings):
    r = FakeFetchRunner(agent_settings.skills_fetch_dir)
    r.publish("acme/skills", SHA1, anthropic_like())
    r.publish("ext/plug", EXT_SHA, EXTERNAL)
    return r


@pytest.fixture
def client(agent_client, fake):
    agent_client.settings.admin_user_ids = "1"
    app.dependency_overrides[get_fetch_runner] = lambda: fake
    agent_client.fake = fake
    return agent_client


def listing_of(fake, settings, sha=SHA1, repo="skills"):
    with fake_tree(fake, settings, sha) as t:
        return marketplace.read_listing(t, repo)


class fake_tree:
    def __init__(self, fake, settings, sha):
        self.fake, self.settings, self.sha = fake, settings, sha

    def __enter__(self):
        res = self.fake.call("fetch_repo", owner="x", repo="y", ref=self.sha)
        self.dir = res["dir"]
        return open_tree(self.settings, res)

    def __exit__(self, *a):
        self.fake.call("fetch_cleanup", dir=self.dir)


def plugin(listing, name):
    return next(p for p in listing["plugins"] if p["name"] == name)


# --- parse_repo -------------------------------------------------------------------------

def test_parse_repo():
    ok = {"anthropics/skills": ("anthropics", "skills", ""),
          "pbakaus/impeccable@v2": ("pbakaus", "impeccable", "v2"),
          "https://github.com/anthropics/skills": ("anthropics", "skills", ""),
          "https://github.com/anthropics/skills.git": ("anthropics", "skills", ""),
          "github.com/a/b/": ("a", "b", ""),
          "https://github.com/a/b/tree/feature/x": ("a", "b", "feature/x"),
          " a/b ": ("a", "b", "")}
    for text, want in ok.items():
        assert marketplace.parse_repo(text) == want, text
    for bad in ("", "https://gitlab.com/a/b", "http://evil.example/a/b", "git@github.com:a/b",
                "https://github.com/a", "a/b/c", "a", "a/..", "-a/b", "a/b@../x",
                "https://github.com/a/b/blob/main/x", "https://user:pw@github.com/a/b",
                "https://github.com:8443/a/b", "https://github.com/a/b?x=1", "file:///a/b",
                "https://raw.githubusercontent.com/a/b/main/x"):
        with pytest.raises(marketplace.MarketplaceError):
            marketplace.parse_repo(bad)


# --- marketplace.json fixtures ---------------------------------------------------------------

def test_listing_relative_github_and_unsupported(fake, agent_settings):
    listing, pending = listing_of(fake, agent_settings)
    assert listing["name"] == "acme-skills" and listing["owner"] == "Acme"
    assert listing["description"] == "Acme's skills" and listing["kind"] == "marketplace"
    w = plugin(listing, "writing")
    assert w["supported"] and w["source"] == {"type": "relative", "path": ""}
    notes, broken = w["skills"]
    assert notes["name"] == "notes" and notes["valid"] and notes["path"] == "skills/notes"
    assert notes["description"] == "Use when writing notes."
    assert notes["license"] == "Apache-2.0"  # from the repo LICENSE
    assert notes["files"] == 4  # SKILL.md, reference, LICENSE and NOTICE
    assert broken["valid"] is False and "must equal the folder name" in broken["problems"][0]
    lp = plugin(listing, "local-plugin")
    assert lp["source"]["path"] == "plugin" and lp["category"] == "design"
    (design,) = lp["skills"]
    assert design["license"] == "MIT" and design["version"] == "4.9.1" and design["valid"]
    assert [p["name"] for p in pending] == ["external"]
    assert "not supported yet" in plugin(listing, "by-url")["reason"]
    assert "npm sources are not supported" in plugin(listing, "by-npm")["reason"]
    assert "'..'" in plugin(listing, "escape")["reason"]
    for name in ("by-url", "by-npm", "escape"):
        assert plugin(listing, name)["supported"] is False


def test_build_listing_fetches_github_sources_one_level(fake, agent_settings):
    listing = marketplace.build_listing(fake, agent_settings, "acme", "skills", "")
    ext = plugin(listing, "external")
    assert ext["supported"] and ext["source"]["resolved_sha"] == EXT_SHA
    assert [s["name"] for s in ext["skills"]] == ["ext-skill"]
    assert listing["sha"] == SHA1
    assert fake.live_dirs() == []  # every fetch cleaned up
    fake.refs["ext/plug"] = {}
    listing = marketplace.build_listing(fake, agent_settings, "acme", "skills", "")
    assert "not found" in plugin(listing, "external")["reason"]
    assert plugin(listing, "external")["supported"] is False


def test_listing_without_marketplace_json(fake, agent_settings):
    fake.publish("x/a", SHA2, {"skills/one/SKILL.md": skill_md(name="one"),
                               "skills/two/SKILL.md": skill_md(name="two"),
                               "skills/not-a-skill/README.md": "x"})
    listing, pending = listing_of(fake, agent_settings, SHA2, repo="a")
    assert listing["kind"] == "skills" and not pending
    (p,) = listing["plugins"]
    assert p["name"] == "a" and [s["name"] for s in p["skills"]] == ["one", "two"]
    # <name>/SKILL.md folders at the root
    fake.publish("x/b", SHA3, {"alpha/SKILL.md": skill_md(name="alpha"), "docs/x.md": "x"})
    listing, _ = listing_of(fake, agent_settings, SHA3, repo="b")
    assert [s["name"] for s in listing["plugins"][0]["skills"]] == ["alpha"]
    # a skill at the root of the repo
    fake.publish("x/c", "4" * 40, {"SKILL.md": skill_md(name="solo")})
    listing, _ = listing_of(fake, agent_settings, "4" * 40, repo="c")
    (s,) = listing["plugins"][0]["skills"]
    assert s["name"] == "solo" and s["path"] == "" and s["valid"]
    # nothing at all
    fake.publish("x/d", "5" * 40, {"README.md": "x"})
    with pytest.raises(marketplace.MarketplaceError, match="no skills"):
        listing_of(fake, agent_settings, "5" * 40, repo="d")


def test_listing_bad_manifests(fake, agent_settings):
    fake.publish("x/a", SHA2, {".claude-plugin/marketplace.json": "{not json"})
    with pytest.raises(marketplace.MarketplaceError, match="not valid JSON"):
        listing_of(fake, agent_settings, SHA2)
    fake.publish("x/b", SHA3, {".claude-plugin/marketplace.json": '{"name": "x"}'})
    with pytest.raises(marketplace.MarketplaceError, match="no plugins list"):
        listing_of(fake, agent_settings, SHA3)
    fake.publish("x/c", "4" * 40, {".claude-plugin/marketplace.json": manifest([
        {"name": "p", "source": "./", "skills": [1, 2]},
        {"name": "q", "source": "./missing"},
        {"name": "r", "source": {"source": "github", "repo": "not a repo"}},
        "junk"])})
    listing, pending = listing_of(fake, agent_settings, "4" * 40)
    assert "not a list of paths" in plugin(listing, "p")["reason"]
    assert "no such folder" in plugin(listing, "q")["reason"]
    assert "not a valid GitHub owner" in plugin(listing, "r")["reason"]
    assert not pending and len(listing["plugins"]) == 3


def test_plugin_json_skills_and_plugin_root(fake, agent_settings):
    fake.publish("x/a", SHA2, {
        ".claude-plugin/marketplace.json": manifest([{"name": "p", "source": "p"}],
                                                    metadata={"pluginRoot": "./plugins"}),
        "plugins/p/.claude-plugin/plugin.json": json.dumps({"skills": "./custom"}),
        "plugins/p/custom/s1/SKILL.md": skill_md(name="s1")})
    listing, _ = listing_of(fake, agent_settings, SHA2)
    p = plugin(listing, "p")
    assert p["source"]["path"] == "plugins/p"
    assert [s["path"] for s in p["skills"]] == ["plugins/p/custom/s1"]


# --- API: marketplaces ----------

def test_builtins_registered_on_start(client):
    r = client.get(MP, headers=ADMIN)
    assert r.status_code == 200
    rows = r.json()["marketplaces"]
    assert [(m["repo"], m["builtin"]) for m in rows] == [("anthropics/skills", True),
                                                         ("pbakaus/impeccable", True)]
    assert rows[0]["last_sha"] == "" and rows[0]["plugin_count"] == 0  # not fetched
    assert client.fake.calls == []
    with client.S() as db:  # idempotent
        assert marketplace.seed_builtin_marketplaces(db) == []


def test_marketplace_endpoints_are_admin_only(client):
    mid = client.get(MP, headers=ADMIN).json()["marketplaces"][0]["id"]
    for method, url, body in [("get", MP, None), ("post", MP, {"repo": "a/b"}),
                              ("delete", f"{MP}/{mid}", None),
                              ("post", f"{MP}/{mid}/refresh", None),
                              ("get", f"{MP}/{mid}/plugins", None),
                              ("post", f"{MP}/{mid}/install", {"plugin": "p", "skill": "s"}),
                              ("post", f"{LIB}/impeccable/check-update", None),
                              ("post", f"{LIB}/impeccable/versions/1/approve", None),
                              ("post", f"{LIB}/impeccable/versions/1/reject", None)]:
        kw = {"json": body} if body is not None else {}
        r = getattr(client, method)(url, headers=MEMBER, **kw)
        assert r.status_code == 403, (method, url, r.status_code)
    assert client.fake.calls == []


def test_add_and_delete_marketplace(client):
    r = client.post(MP, headers=ADMIN, json={"repo": "https://github.com/acme/skills"})
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["repo"] == "acme/skills" and m["builtin"] is False and m["ref"] == ""
    assert client.post(MP, headers=ADMIN, json={"repo": "ACME/skills"}).status_code == 409
    r = client.post(MP, headers=ADMIN, json={"repo": "https://gitlab.com/acme/skills"})
    assert r.status_code == 422 and "only GitHub" in r.json()["detail"]["message"]
    assert client.fake.calls == []  # a refused URL never reaches the runner
    r = client.post(MP, headers=ADMIN, json={"repo": "acme/skills@v1"})
    assert r.status_code == 201 and r.json()["ref"] == "v1"
    builtin = client.get(MP, headers=ADMIN).json()["marketplaces"][0]
    r = client.delete(f"{MP}/{builtin['id']}", headers=ADMIN)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "builtin"
    assert client.delete(f"{MP}/{m['id']}", headers=ADMIN).status_code == 200
    assert client.delete(f"{MP}/{m['id']}", headers=ADMIN).status_code == 404
    with client.S() as db:
        ops = [d.detail["op"] for d in
               db.query(Decision).filter_by(action="awak_skill_marketplace")]
    assert ops == ["add", "add", "delete"]


def _add(client, repo="acme/skills") -> int:
    r = client.post(MP, headers=ADMIN, json={"repo": repo})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _refresh(client, mid):
    r = client.post(f"{MP}/{mid}/refresh", headers=ADMIN)
    assert r.status_code == 200, r.text
    return r.json()


def test_refresh_and_plugins(client):
    mid = _add(client)
    r = client.get(f"{MP}/{mid}/plugins", headers=ADMIN)
    assert r.json()["refreshed"] is False and r.json()["plugins"] == []
    m = _refresh(client, mid)
    assert m["last_sha"] == SHA1 and m["name"] == "acme-skills" and m["error"] == ""
    assert m["plugin_count"] == 6 and m["skill_count"] == 4
    r = client.get(f"{MP}/{mid}/plugins", headers=ADMIN).json()
    assert r["refreshed"] and r["owner"] == "Acme"
    notes = plugin(r, "writing")["skills"][0]
    assert notes["name"] == "notes" and notes["installed"] is None
    assert client.fake.live_dirs() == []


def test_refresh_failure_is_kept(client):
    mid = _add(client)
    _refresh(client, mid)
    client.fake.fail = "GitHub's API rate limit was reached; try again after 10:00 UTC"
    r = client.post(f"{MP}/{mid}/refresh", headers=ADMIN)
    assert r.status_code == 502
    d = r.json()["detail"]
    assert d["code"] == "fetch_failed" and "rate limit" in d["problems"][0]
    assert "rate limit" in d["marketplace"]["error"]
    m = client.get(MP, headers=ADMIN).json()["marketplaces"][-1]
    assert "rate limit" in m["error"] and m["last_sha"] == SHA1  # old listing kept
    assert m["skill_count"] == 4
    client.fake.fail, client.fake.down = None, True
    assert client.post(f"{MP}/{mid}/refresh", headers=ADMIN).status_code == 502
    client.fake.down = False
    mid2 = _add(client, "acme/nothing")
    r = client.post(f"{MP}/{mid2}/refresh", headers=ADMIN)
    assert r.status_code == 502 and "not found" in r.json()["detail"]["problems"][0]


# --- API: install ----------

def _install(client, mid, plugin_name="writing", skill="notes"):
    return client.post(f"{MP}/{mid}/install", headers=ADMIN,
                       json={"plugin": plugin_name, "skill": skill})


def test_install_pins_the_sha(client):
    mid = _add(client)
    _refresh(client, mid)
    # the default branch moves after the refresh: install still takes the listed commit
    client.fake.publish("acme/skills", SHA2, anthropic_like(notes_body="# Changed\n"))
    r = _install(client, mid)
    assert r.status_code == 200, r.text
    sk = r.json()
    assert sk["slug"] == "notes" and sk["source"] == "marketplace" and sk["enabled"] is False
    assert sk["license"] == "Apache-2.0" and sk["version"] == 1
    o = sk["origin"]
    assert (o["repo"], o["sha"], o["plugin"], o["path"], o["ref"]) == (
        "acme/skills", SHA1, "writing", "skills/notes", "")
    assert sk["origin_url"] == f"https://github.com/acme/skills/tree/{SHA1}/skills/notes"
    assert sorted(f["path"] for f in sk["current"]["files"]) == [
        "LICENSE", "NOTICE", "SKILL.md", "reference/style.md"]
    assert "# Notes" in sk["current"]["skill_md"]
    assert [lf["path"] for lf in sk["current"]["license_files"]] == ["LICENSE", "NOTICE"]
    fetches = [c[1] for c in client.fake.calls if c[0] == "fetch_repo"]
    assert fetches[-1] == {"owner": "acme", "repo": "skills", "ref": SHA1}
    with client.S() as db:
        v = db.query(AwakSkillVersion).filter_by(slug="notes").one()
        assert v.status == "active" and v.origin["sha"] == SHA1
        d = db.query(Decision).filter_by(action="awak_skill", subject="notes").one()
        assert d.detail["op"] == "install" and d.detail["upstream_sha"] == SHA1
    # listed as installed now
    r = client.get(f"{MP}/{mid}/plugins", headers=ADMIN).json()
    inst = plugin(r, "writing")["skills"][0]["installed"]
    assert inst["same_origin"] and inst["version"] == 1 and inst["sha"] == SHA1
    # enable works like any skill (scan clean)
    assert client.post(f"{LIB}/notes/enable", headers=ADMIN).json()["enabled"] is True
    assert client.fake.live_dirs() == []


def test_install_from_plugin_folder_and_github_source(client):
    mid = _add(client)
    _refresh(client, mid)
    r = _install(client, mid, "local-plugin", "design")
    assert r.status_code == 200, r.text
    assert r.json()["license"] == "MIT"
    files = sorted(f["path"] for f in r.json()["current"]["files"])
    assert files == ["LICENSE", "NOTICE", "SKILL.md"]  # plugin LICENSE, repo NOTICE
    r = _install(client, mid, "external", "ext-skill")
    assert r.status_code == 200, r.text
    o = r.json()["origin"]
    assert o["repo"] == "ext/plug" and o["sha"] == EXT_SHA and o["path"] == "skills/ext-skill"


def test_install_refusals(client):
    mid = _add(client)
    assert _install(client, mid).status_code == 422  # not refreshed yet
    _refresh(client, mid)
    r = _install(client, mid, "writing", "nope")
    assert r.status_code == 422 and "refresh the marketplace" in r.json()["detail"]["message"]
    r = _install(client, mid, "by-url", "x")
    assert r.status_code == 422
    r = _install(client, mid, "writing", "broken")  # invalid: name != folder
    assert r.status_code == 422 and "must equal the folder name" in str(r.json()["detail"])
    # clash with an existing local skill
    with client.S() as db:
        db.add(AwakSkill(slug="notes", source="local", title="notes", enabled=False,
                         current_version=1, origin={}))
        db.commit()
    r = _install(client, mid)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "exists"
    assert r.json()["detail"]["source"] == "local"
    # clash with the builtin impeccable
    client.fake.publish("acme/skills", SHA2, {"skills/impeccable/SKILL.md":
                                              skill_md(name="impeccable")})
    _refresh(client, mid)
    r = _install(client, mid, "skills", "impeccable")
    assert r.status_code == 409 and r.json()["detail"]["source"] == "builtin"
    # the runner fails
    client.fake.publish("acme/skills", SHA3, anthropic_like())
    _refresh(client, mid)
    client.fake.down = True
    r = _install(client, mid, "local-plugin", "design")
    assert r.status_code == 502 and r.json()["detail"]["code"] == "fetch_failed"


# --- updates ----------

def _installed(client):
    mid = _add(client)
    _refresh(client, mid)
    assert _install(client, mid).status_code == 200
    return mid


def _check(client, slug="notes"):
    r = client.post(f"{LIB}/{slug}/check-update", headers=ADMIN)
    assert r.status_code == 200, r.text
    return r.json()


def test_check_update_up_to_date(client):
    _installed(client)
    out = _check(client)
    assert out["result"] == {"status": "up_to_date", "sha": SHA1}
    assert out["skill"]["origin"]["check_status"] == "up_to_date"
    # a new commit that does not touch the skill: still up to date
    files = anthropic_like()
    files["README.md"] = "new readme"
    client.fake.publish("acme/skills", SHA2, files)
    assert _check(client)["result"] == {"status": "up_to_date", "sha": SHA2}
    assert client.fake.live_dirs() == []


def _pending_sha(client, slug="notes", version=None) -> str:
    sk = client.get(f"{LIB}/{slug}", headers=ADMIN).json()
    return next(p["sha256"] for p in sk["pending"] if version in (None, p["version"]))


def _decide(client, version, op="approve", slug="notes", sha=None, **params):
    """approve / reject with the reviewed version's sha256 (the pending one's
    unless `sha` is given)."""
    params["sha256"] = sha or _pending_sha(client, slug, version)
    return client.post(f"{LIB}/{slug}/versions/{version}/{op}", headers=ADMIN, params=params)


def test_update_pending_then_approve(client):
    _installed(client)
    assert client.post(f"{LIB}/notes/enable", headers=ADMIN).status_code == 200
    client.fake.publish("acme/skills", SHA2, anthropic_like(notes_body="# Notes v2\n"))
    out = _check(client)
    assert out["result"]["status"] == "pending" and out["result"]["version"] == 2
    sk = out["skill"]
    assert sk["version"] == 1  # the pending version is not current
    (p,) = sk["pending"]
    assert p["version"] == 2 and p["origin"]["sha"] == SHA2
    assert p["diff"] == {"added": [], "removed": [], "changed": ["SKILL.md"]}
    assert [v["status"] for v in sk["versions"]] == ["pending", "active"]
    # runs never get a pending version
    with client.S() as db:
        res = skills.resolve(db, ["notes"])
        assert [(e.slug, e.version) for e in res.entries] == [("notes", 1)]
    # checking again finds the same pending version
    assert _check(client)["result"] == {"status": "pending", "sha": SHA2, "version": 2,
                                        "new": False}
    # the reviewed tree's sha256 is required, and must match
    assert client.post(f"{LIB}/notes/versions/2/approve", headers=ADMIN).status_code == 422
    r = _decide(client, 2, sha="0" * 64)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "stale"
    r = _decide(client, 2)
    assert r.status_code == 200, r.text
    sk = r.json()
    assert sk["version"] == 2 and sk["pending"] == [] and sk["origin"]["sha"] == SHA2
    assert sk["enabled"] is True and "# Notes v2" in sk["current"]["skill_md"]
    with client.S() as db:
        res = skills.resolve(db, ["notes"])
        assert [(e.slug, e.version) for e in res.entries] == [("notes", 2)]
        ops = [d.detail["op"] for d in db.query(Decision).filter_by(subject="notes")]
    assert ops == ["install", "enable", "update_pending", "approve_version"]
    assert _decide(client, 2, sha=p["sha256"]).status_code == 409  # not pending now
    assert _decide(client, 9, sha=p["sha256"]).status_code == 404


def test_update_reject_is_not_proposed_again(client):
    _installed(client)
    client.fake.publish("acme/skills", SHA2, anthropic_like(notes_body="# Other\n"))
    assert _check(client)["result"]["status"] == "pending"
    r = _decide(client, 2, "reject", sha="0" * 64)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "stale"
    r = _decide(client, 2, "reject")
    assert r.status_code == 200, r.text
    assert r.json()["pending"] == [] and r.json()["version"] == 1
    with client.S() as db:
        assert db.query(AwakSkillVersion).filter_by(slug="notes").count() == 1
    assert _check(client)["result"]["status"] == "rejected"
    # a newer upstream change is proposed again
    client.fake.publish("acme/skills", SHA3, anthropic_like(notes_body="# Third\n"))
    assert _check(client)["result"]["status"] == "pending"


def test_rejected_trees_are_all_remembered(client):
    """Rejecting B after A: upstream flipping back to A is still refused."""
    _installed(client)
    client.fake.publish("acme/skills", SHA2, anthropic_like(notes_body="# A\n"))
    assert _check(client)["result"]["status"] == "pending"
    assert _decide(client, 2, "reject").status_code == 200
    client.fake.publish("acme/skills", SHA3, anthropic_like(notes_body="# B\n"))
    v = _check(client)["result"]["version"]
    assert _decide(client, v, "reject").status_code == 200
    client.fake.publish("acme/skills", "4" * 40, anthropic_like(notes_body="# A\n"))
    assert _check(client)["result"]["status"] == "rejected"
    with client.S() as db:
        assert len(db.get(AwakSkill, "notes").origin["rejected_shas"]) == 2


def test_rejected_memory_is_bounded_and_reads_the_old_form():
    origin = {"rejected": "old"}
    assert marketplace.rejected_shas(origin) == ["old"]
    for i in range(marketplace.REJECTED_KEPT + 5):
        marketplace.remember_rejected(origin, f"s{i}")
    shas = origin["rejected_shas"]
    assert "rejected" not in origin and len(shas) == marketplace.REJECTED_KEPT
    assert shas[-1] == f"s{marketplace.REJECTED_KEPT + 4}" and "old" not in shas
    marketplace.remember_rejected(origin, shas[0])  # again: moves to the end
    assert origin["rejected_shas"][-1] == shas[0] and len(origin["rejected_shas"]) == 20


def test_update_replaces_an_older_pending_version(client):
    """A replaced pending version's number is never given again, so an
    approve of the number the admin reviewed cannot apply other content."""
    _installed(client)
    client.fake.publish("acme/skills", SHA2, anthropic_like(notes_body="# Two\n"))
    assert _check(client)["result"]["version"] == 2
    reviewed = _pending_sha(client, version=2)
    client.fake.publish("acme/skills", SHA3, anthropic_like(notes_body="# Three\n"))
    out = _check(client)
    assert out["result"]["version"] == 3 and out["result"]["sha"] == SHA3
    assert [(p["version"], p["origin"]["sha"]) for p in out["skill"]["pending"]] == [
        (3, SHA3)]
    # the admin approves what they reviewed as version 2: gone, not replaced
    assert _decide(client, 2, sha=reviewed).status_code == 404
    # and version 3 with version 2's tree: stale
    r = _decide(client, 3, sha=reviewed)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "stale"
    # upstream back to the installed tree: the stale pending version goes
    client.fake.publish("acme/skills", "4" * 40, anthropic_like())
    out = _check(client)
    assert out["result"]["status"] == "up_to_date" and out["skill"]["pending"] == []
    # the next change gets a new number again (3 was given once)
    client.fake.publish("acme/skills", "5" * 40, anthropic_like(notes_body="# Five\n"))
    assert _check(client)["result"]["version"] == 4
    with client.S() as db:
        assert db.get(AwakSkill, "notes").last_version == 4


def test_update_findings_rise_on_approve(client):
    _installed(client)
    assert client.post(f"{LIB}/notes/enable", headers=ADMIN).status_code == 200
    role = client.post("/projects/demo/agent/roles", headers=ADMIN,
                       json={**ROLE, "skills": ["notes"]}).json()
    client.fake.publish("acme/skills", SHA2,
                        anthropic_like(notes_body="Then run git push.\n"))
    assert _check(client)["result"]["status"] == "pending"
    r = _decide(client, 2)
    assert r.status_code == 409
    d = r.json()["detail"]
    assert d["code"] == "findings_rise" and d["worst"] == "high"
    assert d["used_by"][0]["role_id"] == role["id"]
    r = _decide(client, 2, accept_findings="true")
    assert r.status_code == 200 and r.json()["disabled_now"] is True
    assert r.json()["enabled"] is False


def test_root_path_skill_checks_updates(client):
    """A skill at the root of its repo (`path` "") can be checked."""
    client.fake.publish("x/solo", SHA2, {"SKILL.md": skill_md(name="solo")})
    mid = _add(client, "x/solo")
    _refresh(client, mid)
    r = _install(client, mid, "solo", "solo")
    assert r.status_code == 200, r.text
    assert r.json()["origin"]["path"] == ""
    assert _check(client, "solo")["result"] == {"status": "up_to_date", "sha": SHA2}
    client.fake.publish("x/solo", SHA3, {"SKILL.md": skill_md(name="solo", body="# New\n")})
    out = _check(client, "solo")["result"]
    assert out["status"] == "pending" and out["sha"] == SHA3 and out["version"] == 2


EXT_SHA2 = "f" * 40


def _pinned_marketplace(ext_sha, extra_plugins=()) -> dict:
    files = anthropic_like()
    files[".claude-plugin/marketplace.json"] = manifest([
        {"name": "external",
         "source": {"source": "github", "repo": "ext/plug", "sha": ext_sha}},
        *extra_plugins])
    return files


def test_github_plugin_pinned_to_a_sha_follows_the_marketplace(client):
    """The update check re-reads the marketplace entry: a new pin is followed;
    without the entry (or the marketplace) the stored source is checked and
    the answer says so."""
    client.fake.publish("acme/skills", SHA1, _pinned_marketplace(EXT_SHA))
    mid = _installed_ext(client)
    assert _check(client, "ext-skill")["result"] == {"status": "up_to_date", "sha": EXT_SHA}
    # the plugin repo moves on (not its default branch: a commit only), and
    # the marketplace pins the new commit
    changed = {**EXTERNAL, "skills/ext-skill/SKILL.md": skill_md(name="ext-skill",
                                                               body="# v2\n")}
    client.fake.publish("ext/plug", EXT_SHA2, changed, ref="some-branch")
    client.fake.publish("acme/skills", SHA2, _pinned_marketplace(EXT_SHA2))
    out = _check(client, "ext-skill")
    res = out["result"]
    assert res["status"] == "pending" and res["sha"] == EXT_SHA2 and "note" not in res
    fetches = [c[1] for c in client.fake.calls if c[0] == "fetch_repo"]
    assert fetches[-2:] == [{"owner": "acme", "repo": "skills", "ref": ""},
                            {"owner": "ext", "repo": "plug", "ref": EXT_SHA2}]
    assert _decide(client, 2, slug="ext-skill").status_code == 200
    with client.S() as db:
        o = db.get(AwakSkill, "ext-skill").origin
        assert (o["sha"], o["ref"], o["repo"]) == (EXT_SHA2, EXT_SHA2, "ext/plug")
    # the entry is gone: the stored source (now EXT_SHA2), with a note
    client.fake.publish("acme/skills", SHA3, _pinned_marketplace(EXT_SHA2)
                        | {".claude-plugin/marketplace.json": manifest([])})
    res = _check(client, "ext-skill")["result"]
    assert res["status"] == "up_to_date" and "no longer lists the plugin" in res["note"]
    # the marketplace is gone
    assert client.delete(f"{MP}/{mid}", headers=ADMIN).status_code == 200
    res = _check(client, "ext-skill")["result"]
    assert res["status"] == "up_to_date" and "no longer registered" in res["note"]
    assert client.fake.live_dirs() == []


def _installed_ext(client) -> int:
    mid = _add(client)
    _refresh(client, mid)
    r = _install(client, mid, "external", "ext-skill")
    assert r.status_code == 200, r.text
    o = r.json()["origin"]
    assert (o["sha"], o["ref"], o["source_type"]) == (EXT_SHA, EXT_SHA, "github")
    return mid


def test_install_refuses_another_commit_than_the_pinned_one(client):
    mid = _add(client)
    _refresh(client, mid)
    client.fake.answer_sha[SHA1] = SHA2  # the runner answers with another commit
    r = _install(client, mid)
    assert r.status_code == 502 and "another commit" in r.json()["detail"]["problems"][0]
    with client.S() as db:
        assert db.get(AwakSkill, "notes") is None


def test_refresh_unexpected_error_is_kept(client, monkeypatch):
    mid = _add(client)

    def boom(*a, **k):
        raise KeyError("plugins")
    monkeypatch.setattr(marketplace, "build_listing", boom)
    r = client.post(f"{MP}/{mid}/refresh", headers=ADMIN)
    assert r.status_code == 502 and r.json()["detail"]["code"] == "fetch_failed"
    m = client.get(MP, headers=ADMIN).json()["marketplaces"][-1]
    assert "internal error: KeyError" in m["error"]


def test_refresh_unreadable_tree_is_kept(client, monkeypatch):
    """An OSError reading the fetched tree is a FetchError (502, kept)."""
    mid = _add(client)
    # the runner extracts somewhere the orchestrator does not see
    monkeypatch.setattr(client.fake, "base", client.fake.base.parent / "elsewhere")
    r = client.post(f"{MP}/{mid}/refresh", headers=ADMIN)
    assert r.status_code == 502, r.text
    m = client.get(MP, headers=ADMIN).json()["marketplaces"][-1]
    assert "cannot be read" in m["error"]


def test_update_invalid_missing_and_failures(client):
    _installed(client)
    files = anthropic_like()
    files["skills/notes/SKILL.md"] = skill_md(name="renamed")
    client.fake.publish("acme/skills", SHA2, files)
    out = _check(client)["result"]
    assert out["status"] == "invalid" and "must equal the folder name" in out["problems"][0]
    files = anthropic_like()
    del files["skills/notes/SKILL.md"], files["skills/notes/reference/style.md"]
    client.fake.publish("acme/skills", SHA3, files)
    out = _check(client)["result"]
    assert out["status"] == "missing" and "skills/notes" in out["message"]
    client.fake.fail = "GitHub's API rate limit was reached"
    r = client.post(f"{LIB}/notes/check-update", headers=ADMIN)
    assert r.status_code == 502 and "rate limit" in r.json()["detail"]["problems"][0]
    # not a marketplace skill
    r = client.post(f"{LIB}/impeccable/check-update", headers=ADMIN)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_marketplace"
    with client.S() as db:
        assert db.query(AwakSkillVersion).filter_by(slug="notes").count() == 1


def test_marketplace_skill_still_forces_approve(client):
    _installed(client)
    client.post(f"{LIB}/notes/enable", headers=ADMIN)
    with client.S() as db:
        assert skills.resolve(db, ["notes"]).has_marketplace


def test_store_migrates_version_origin(tmp_path):
    """Version rows from before the `origin` column read as NULL (handled)."""
    import sqlite3

    from kemudi_ai.store import make_session

    db_file = tmp_path / "old.db"
    con = sqlite3.connect(db_file)
    con.execute("CREATE TABLE awak_skill_versions (id INTEGER PRIMARY KEY, slug VARCHAR(64), "
                "version INTEGER, sha256 VARCHAR(64), files JSON, size INTEGER, scan JSON, "
                "status VARCHAR(10), created_by VARCHAR(200), created_at DATETIME)")
    con.execute("INSERT INTO awak_skill_versions (slug, version, sha256, files, size, scan, "
                "status, created_by, created_at) VALUES ('x', 1, 'h', '{}', 0, '{}', "
                "'active', 'me', '2026-01-01 00:00:00')")
    con.commit()
    con.close()
    S = make_session(f"sqlite:///{db_file}")
    with S() as db:
        v = db.query(AwakSkillVersion).one()
        assert v.origin is None
        assert db.query(AwakSkillMarketplace).count() == 0


def test_store_migrates_skill_last_version(tmp_path):
    """Skill rows from before `last_version` get 0; numbering still goes past
    every stored version."""
    import sqlite3

    from kemudi_ai.store import make_session

    db_file = tmp_path / "old.db"
    con = sqlite3.connect(db_file)
    con.execute("CREATE TABLE awak_skills (slug VARCHAR(64) PRIMARY KEY, source VARCHAR(20), "
                "title VARCHAR(200), description TEXT, license VARCHAR(100), enabled BOOLEAN, "
                "current_version INTEGER, origin JSON, created_by VARCHAR(200), "
                "created_at DATETIME, updated_at DATETIME)")
    con.execute("INSERT INTO awak_skills VALUES ('x', 'local', 'x', '', '', 1, 3, '{}', 'me', "
                "'2026-01-01 00:00:00', '2026-01-01 00:00:00')")
    con.commit()
    con.close()
    S = make_session(f"sqlite:///{db_file}")
    with S() as db:
        assert db.get(AwakSkill, "x").last_version == 0
        db.add(AwakSkillVersion(slug="x", version=3, sha256="h", files={}))
        db.commit()
        assert skills.next_version(db, "x") == 4
        assert db.get(AwakSkill, "x").last_version == 4


def test_license_pointing_at_a_file_and_oversized_skills(fake, agent_settings, monkeypatch):
    lic = "license: Complete terms in LICENSE.txt\n"
    fake.publish("x/a", SHA2, {
        "skills/a/SKILL.md": skill_md(name="a", extra=lic),
        "skills/a/LICENSE.txt": APACHE,
        "skills/b/SKILL.md": skill_md(name="b", extra=lic),
        "skills/b/LICENSE.txt": "Proprietary. All rights reserved.\n",
        "skills/big/SKILL.md": skill_md(name="big", description="A big one.",
                                        extra="license: MIT\n"),
        "skills/big/assets/blob.bin": b"x" * 5000,
    })
    monkeypatch.setattr(skills, "MAX_TOTAL_BYTES", 1000)
    listing, _ = listing_of(fake, agent_settings, SHA2, repo="a")
    a, b, big = listing["plugins"][0]["skills"]
    assert a["license"] == "Apache-2.0"
    assert b["license"] == "Complete terms in LICENSE.txt"  # nothing better known
    assert big["valid"] is False and "of files" in big["problems"][0]
    assert big["description"] == "A big one." and big["license"] == "MIT"
