"""Role skills: assignment API, template defaults, reset, and the picker list."""

from kemudi_ai.awak import skills
from kemudi_ai.store import AwakSkill, Decision

from .conftest import ADMIN, MEMBER
from .test_roles import ROLE

ROLES = "/projects/demo/agent/roles"


def _role(client, **over):
    r = client.post(ROLES, headers=ADMIN, json={**ROLE, **over})
    assert r.status_code == 200, r.text
    return r.json()


def _body(role, **over):
    return {**{k: role[k] for k in ROLE}, "skills": role["skills"], **over}


def _set_enabled(client, slug, enabled):
    with client.S() as db:
        db.get(AwakSkill, slug).enabled = enabled
        db.commit()


def _decisions(client):
    with client.S() as db:
        return [x.detail for x in db.query(Decision).filter_by(action="awak_role")]


def test_create_applies_template_defaults(agent_client):
    fe = _role(agent_client)
    assert fe["skills"] == ["impeccable"]
    assert fe["skill_defaults"] == ["impeccable"]
    (d,) = fe["skill_details"]
    assert d["slug"] == "impeccable" and d["status"] == "ok"
    assert d["source"] == "builtin" and d["license"] == "Apache-2.0"
    assert d["version"] == 1 and d["scan_level"] in ("", "low")
    assert _role(agent_client, template="fullstack", area="both")["skills"] == ["impeccable"]
    be = _role(agent_client, template="backend", area="backend")
    assert be["skills"] == [] and be["skill_defaults"] == []
    # An explicit list wins over the defaults.
    assert _role(agent_client, skills=[])["skills"] == []
    assert _decisions(agent_client)[0]["skills"] == ["impeccable"]


def test_defaults_skip_disabled_skills(agent_client):
    _set_enabled(agent_client, "impeccable", False)
    fe = _role(agent_client)
    assert fe["skills"] == [] and fe["skill_defaults"] == []


def test_put_validates_skills(agent_client):
    role = _role(agent_client, skills=[])
    url = f"{ROLES}/{role['id']}"
    r = agent_client.put(url, headers=ADMIN, json=_body(role, skills=["nope", "impeccable"]))
    assert r.status_code == 422 and "nope" in r.text and "impeccable" not in r.json()["detail"]
    r = agent_client.put(url, headers=ADMIN, json=_body(role, skills=["impeccable"] * 2))
    assert r.status_code == 422
    r = agent_client.put(url, headers=ADMIN,
                         json=_body(role, skills=[f"s{i}" for i in range(21)]))
    assert r.status_code == 422
    r = agent_client.put(url, headers=MEMBER, json=_body(role, skills=["impeccable"]))
    assert r.status_code == 403
    _set_enabled(agent_client, "impeccable", False)
    r = agent_client.put(url, headers=ADMIN, json=_body(role, skills=["impeccable"]))
    assert r.status_code == 422 and "impeccable" in r.text


def test_put_skills_bumps_version_and_records(agent_client):
    role = _role(agent_client, skills=[])
    url = f"{ROLES}/{role['id']}"
    r = agent_client.put(url, headers=ADMIN, json=_body(role, skills=["impeccable"])).json()
    assert r["skills"] == ["impeccable"] and r["version"] == 2
    assert r["prompt_version"] != role["prompt_version"]
    d = _decisions(agent_client)[-1]
    assert d["changed"] == ["skills"]
    assert (d["old_skills"], d["new_skills"]) == ([], ["impeccable"])
    # Omitted skills: unchanged, no new version.
    body = _body(r)
    del body["skills"]
    r2 = agent_client.put(url, headers=ADMIN, json=body).json()
    assert r2["skills"] == ["impeccable"] and r2["version"] == 2


def test_disabled_assigned_skill_warns_and_can_stay(agent_client):
    role = _role(agent_client)
    _set_enabled(agent_client, "impeccable", False)
    (row,) = agent_client.get(ROLES, headers=MEMBER).json()["roles"]
    assert row["skills"] == ["impeccable"]
    assert row["skill_details"][0]["status"] == "disabled"
    # Saving other fields keeps the (now disabled) skill without a 422.
    url = f"{ROLES}/{role['id']}"
    r = agent_client.put(url, headers=ADMIN, json=_body(row, prompt_overlay="Use tabs."))
    assert r.status_code == 200 and r.json()["skills"] == ["impeccable"]
    r = agent_client.put(url, headers=ADMIN, json=_body(row, skills=[]))
    assert r.status_code == 200 and r.json()["skills"] == []


def test_missing_skill_shows_as_missing(agent_client):
    role = _role(agent_client)
    with agent_client.S() as db:
        from kemudi_ai.store import AwakRole
        db.get(AwakRole, role["id"]).skills = ["gone", "impeccable"]
        db.commit()
    (row,) = agent_client.get(ROLES, headers=MEMBER).json()["roles"]
    assert [(d["slug"], d["status"]) for d in row["skill_details"]] == [
        ("gone", "missing"), ("impeccable", "ok")]


def test_reset_to_template_defaults(agent_client):
    role = _role(agent_client, skills=[])
    url = f"{ROLES}/{role['id']}/skills/reset"
    assert agent_client.post(url, headers=MEMBER).status_code == 403
    r = agent_client.post(url, headers=ADMIN).json()
    assert r["skills"] == ["impeccable"] and r["version"] == 2
    d = _decisions(agent_client)[-1]
    assert d["op"] == "skills_reset" and d["new_skills"] == ["impeccable"]
    n = len(_decisions(agent_client))
    r = agent_client.post(url, headers=ADMIN).json()  # already the defaults: no-op
    assert r["version"] == 2 and len(_decisions(agent_client)) == n
    be = _role(agent_client, template="backend", area="backend", skills=["impeccable"])
    r = agent_client.post(f"{ROLES}/{be['id']}/skills/reset", headers=ADMIN).json()
    assert r["skills"] == []
    assert agent_client.post(f"{ROLES}/999/skills/reset", headers=ADMIN).status_code == 404


def test_picker_lists_enabled_skills(agent_client):
    assert agent_client.get("/skills").status_code == 401
    (sk,) = agent_client.get("/skills", headers=MEMBER).json()["skills"]
    assert sk["slug"] == "impeccable" and sk["source"] == "builtin"
    assert sk["title"] and sk["license"] == "Apache-2.0" and sk["version"] == 1
    assert sk["scan_level"] in ("", "low") and sk["enabled"] is True
    assert 0 < len(sk["description"]) <= skills.PICKER_DESCRIPTION_MAX
    assert agent_client.get("/skills", headers=MEMBER).json()["template_defaults"] == {
        "frontend": ["impeccable"], "backend": [], "fullstack": ["impeccable"], "qa": []}
    _set_enabled(agent_client, "impeccable", False)
    assert agent_client.get("/skills", headers=MEMBER).json()["skills"] == []
