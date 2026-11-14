"""Awak skills at run time: profiles, prepare_set, the agent call, prompt
version, the sweep, the worker wiring and the merge-mode guard."""

import os
import secrets as pysecrets
import sys
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, inspect, text

from kemudi_ai.awak import config_store, llm_conn, prompts, skills
from kemudi_ai.awak.agent import AgentError, HermesAgent
from kemudi_ai.config import Settings
from kemudi_ai.store import (
    AwakEvent,
    AwakLlmAlias,
    AwakProject,
    AwakRole,
    AwakSkill,
    AwakSkillSet,
    AwakSkillVersion,
    init_db,
    make_session,
)

from .awak_fakes import FakeAgent, FakeRunner
from .test_awak import DESC, job_of, make_worker, repo, host  # noqa: F401 (fixtures)
from .test_skills import skill_md


GW_KEY = pysecrets.token_hex(16)
PROXY_TOKEN = pysecrets.token_hex(16)


def _settings(**kw) -> Settings:
    base = {"ai_db_url": "sqlite:///:memory:", "awak_api_key": GW_KEY,
            "llm_proxy_token": PROXY_TOKEN, "awak_model": "m1"}
    return Settings(**{**base, **kw})


def _add_skill(db, slug="demo", source="local", enabled=True, body="# Demo\n", version=1):
    files = {"SKILL.md": skill_md(name=slug, body=body)}
    sk = db.get(AwakSkill, slug)
    if sk is None:
        sk = AwakSkill(slug=slug, source=source)
        db.add(sk)
    sk.current_version, sk.enabled = version, enabled
    db.add(AwakSkillVersion(slug=slug, version=version, sha256=skills.canonical_sha(files),
                            files=skills.encode_files(files), size=1, scan={}))
    db.commit()
    return skills.canonical_sha(files)


# --- profiles -------------------------------------------------------------------

def test_write_profile_builds_in_tmp_then_verifies_by_hash():
    s = _settings()
    setid = "0123456789ab"
    name, written = skills.write_profile(s, setid)
    assert name == "sk-0123456789ab" and sorted(written) == [".env", "config.yaml"]
    root = Path(s.awak_profiles_dir)
    assert sorted(p.name for p in root.iterdir()) == [name]  # no .tmp- left behind
    home = root / name
    cfg = (home / "config.yaml").read_text()
    assert "external_dirs:\n    - /opt/skills/sets/0123456789ab\n" in cfg
    env = (home / ".env").read_text()
    assert f"API_SERVER_KEY={GW_KEY}\n" in env
    assert f"KEMUDI_LLM_PROXY_TOKEN={PROXY_TOKEN}\n" in env
    assert "KEMUDI_AWAK_MODEL=m1\n" in env
    if sys.platform != "win32":
        assert (home / ".env").stat().st_mode & 0o777 == 0o600
    # unchanged: nothing rewritten; Hermes' runtime files are left alone
    (home / "state.db").write_bytes(b"hermes")
    assert skills.write_profile(s, setid) == (name, [])
    # tampered (the agent's uid can write here): rewritten from the expected bytes
    (home / "config.yaml").write_text("skills:\n  external_dirs: [/opt/data/skills]\n")
    assert skills.write_profile(s, setid) == (name, ["config.yaml"])
    assert (home / "config.yaml").read_text() == cfg
    assert (home / "state.db").read_bytes() == b"hermes"
    assert sorted(p.name for p in home.iterdir()) == [".env", "config.yaml", "state.db"]
    with pytest.raises(ValueError):
        skills.write_profile(s, "../../etc")


def test_profile_env_refuses_line_breaks():
    with pytest.raises(ValueError, match="line break"):
        skills.profile_files(_settings(awak_model="m\nAPI_SERVER_KEY=x"), "0123456789ab")


# --- prepare_set ----------------------------------------------------------------

def test_prepare_set_drops_disabled_and_missing_skills():
    s = _settings()
    S = make_session(s.ai_db_url)
    with S() as db:
        sha = _add_skill(db, "demo")
        _add_skill(db, "off", enabled=False)
        kit = skills.prepare_set(s, db, ["demo", "off", "gone", "demo"])
        assert kit.slugs == ["demo"]
        assert kit.dropped == ({"slug": "off", "reason": "disabled"},
                               {"slug": "gone", "reason": "missing"})
        assert kit.setid == skills.set_id([skills.SetEntry("demo", 1, sha, "local")])
        ev = kit.event()
        assert ev["profile"] == kit.profile == f"sk-{kit.setid}"
        assert ev["skills"] == [{"slug": "demo", "version": 1, "sha": sha[:12],
                                 "source": "local"}]
        assert sorted(ev["rewritten"]) == [".env", "config.yaml", "set"]
        assert db.get(AwakSkillSet, kit.setid).skills[0]["slug"] == "demo"
        # second time: everything verified, nothing written
        again = skills.prepare_set(s, db, ["demo"])
        assert again.setid == kit.setid and again.rewritten == ()
    set_dir = Path(s.awak_skills_dir) / "sets" / kit.setid
    assert (set_dir / "demo" / "SKILL.md").exists()
    assert not (set_dir / "off").exists()


def test_prepare_empty_set_and_marketplace_flag():
    s = _settings()
    S = make_session(s.ai_db_url)
    with S() as db:
        empty = skills.prepare_set(s, db, None)
        assert empty.setid == skills.EMPTY_SETID and empty.entries == ()
        assert list((Path(s.awak_skills_dir) / "sets" / empty.setid).iterdir()) == []
        assert not empty.has_marketplace
        _add_skill(db, "mk", source="marketplace")
        assert skills.prepare_set(s, db, ["mk"]).has_marketplace


def test_prepare_refuses_files_that_do_not_match_their_sha():
    s = _settings()
    S = make_session(s.ai_db_url)
    with S() as db:
        _add_skill(db, "demo")
        v = db.query(AwakSkillVersion).one()
        v.files = skills.encode_files({"SKILL.md": skill_md(body="# swapped\n")})
        db.commit()
        with pytest.raises(skills.SkillError, match="do not match"):
            skills.prepare_set(s, db, ["demo"])


def test_new_version_is_a_new_set_and_prompt_version():
    s = _settings()
    S = make_session(s.ai_db_url)
    with S() as db:
        _add_skill(db, "demo")
        first = skills.resolve(db, ["demo"]).setid
        _add_skill(db, "demo", body="# Better\n", version=2)
        second = skills.resolve(db, ["demo"]).setid
    assert first != second
    role = config_store.RoleConfig(id=3, template="frontend", name="F", area="web", model="m")
    plain = prompts.prompt_version(role)
    assert plain.startswith("3.v1.") and ".s" not in plain
    a = prompts.prompt_version(role, (), first)
    assert a.endswith(f".s{first}") and a != plain
    assert prompts.prompt_version(role, (), second) != a
    # the skills section is in the prompt only with skills
    assert prompts.SKILLS_SECTION not in prompts.render_role(role)
    assert prompts.SKILLS_SECTION in prompts.render_role(role, (), True)


# --- the agent call -------------------------------------------------------------

def _hermes(seen, status=None):
    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        if status:
            code, body = status.pop(0)
            if code != 200:
                return httpx.Response(code, json=body)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}],
                                         "usage": {"prompt_tokens": 1, "completion_tokens": 1}})
    return handler


def test_agent_calls_the_profile_url_and_records_the_profile_on_the_alias():
    s = _settings(awak_url="http://kemudi-awak:8642/v1")
    S = make_session(s.ai_db_url)
    seen: list = []
    profiles: list[str] = []
    inner = _hermes(seen)

    def handler(req):
        with S() as db:
            profiles.append(llm_conn.active_alias(db).profile)
        return inner(req)

    agent = HermesAgent(s, S, transport=httpx.MockTransport(handler))
    assert agent.run("awak.code", "m", "sys", "task", profile="sk-0123456789ab")[0] == "ok"
    assert str(seen[0].url) == "http://kemudi-awak:8642/p/sk-0123456789ab/v1/chat/completions"
    assert profiles == ["sk-0123456789ab"]
    with pytest.raises(AgentError, match="not a skill-set profile"):
        agent.run("awak.code", "m", "sys", "task", profile="default")
    with pytest.raises(TypeError):
        agent.run("awak.code", "m", "sys", "task")  # a profile is required


def test_agent_waits_for_hermes_to_serve_a_new_profile():
    s = _settings(awak_profile_wait_s=30)
    S = make_session(s.ai_db_url)
    home = Path(s.awak_profiles_dir) / "sk-0123456789ab"
    home.mkdir(parents=True)
    seen: list = []
    slept: list[float] = []

    def sleep(t):  # the watcher picks the profile up while we wait
        slept.append(t)
        if len(slept) == 2:
            (home / skills.SERVED_MARKER).write_text("pid")

    status = [(409, {"error": {"code": "profile_mismatch"}}), (200, None)]
    agent = HermesAgent(s, S, transport=httpx.MockTransport(_hermes(seen, status)))
    agent.sleep = sleep
    assert agent.run("awak.qa", "m", "sys", "task", profile="sk-0123456789ab")[0] == "ok"
    assert len(slept) == 3 and len(seen) == 2  # 2 waits for the marker, 1 retry of the 409


def test_agent_gives_up_on_a_profile_hermes_never_serves():
    s = _settings(awak_profile_wait_s=0)
    S = make_session(s.ai_db_url)
    status = [(409, {"error": {"code": "profile_mismatch"}})]
    agent = HermesAgent(s, S, transport=httpx.MockTransport(_hermes([], status)))
    with pytest.raises(AgentError, match="409"):
        agent.run("awak.code", "m", "sys", "task", profile="sk-0123456789ab")


# --- sweep ----------------------------------------------------------------------

def test_sweep_removes_only_unreferenced_idle_sets():
    s = _settings()
    S = make_session(s.ai_db_url)
    with S() as db:
        for slug in ("kept", "old", "busy", "fresh"):
            _add_skill(db, slug)
        db.add(AwakRole(project_slug="p", template="frontend", name="F", area="web", model="",
                        skills=["kept"]))
        db.commit()
        kits = {slug: skills.prepare_set(s, db, [slug])
                for slug in ("kept", "old", "busy", "fresh")}
        empty = skills.prepare_set(s, db, [])
        later = skills._naive_now() + timedelta(hours=25)
        for k in (kits["kept"], kits["old"], kits["busy"], empty):
            db.get(AwakSkillSet, k.setid).last_used_at = later - timedelta(hours=30)
        db.get(AwakSkillSet, kits["fresh"].setid).last_used_at = later - timedelta(hours=1)
        db.add(AwakLlmAlias(alias="awak-run-x", project_slug="p",
                            expires_at=later + timedelta(hours=1), profile=kits["busy"].profile))
        db.commit()
        tmp = Path(s.awak_skills_dir) / "sets" / ".tmp-stale-1"
        tmp.mkdir()
        os.utime(tmp, (0, 0))
        assert skills.sweep(s, db, now=later) == [kits["old"].setid]
        assert db.get(AwakSkillSet, kits["old"].setid) is None
    sets = Path(s.awak_skills_dir) / "sets"
    profiles = Path(s.awak_profiles_dir)
    assert not (sets / kits["old"].setid).exists()
    assert not (profiles / kits["old"].profile).exists()
    for slug in ("kept", "busy", "fresh"):
        assert (sets / kits[slug].setid).is_dir() and (profiles / kits[slug].profile).is_dir()
    assert (sets / empty.setid).is_dir()  # the empty set always stays
    assert not tmp.exists()


def test_worker_idle_sweep_runs_the_skill_sweep(tmp_path, repo):
    w, _, sessions = make_worker(tmp_path, repo, FakeAgent(), FakeRunner(tmp_path / "ws"))
    calls = []
    w.sweep_skill_sets = lambda: calls.append(1)
    w.idle_sweep()
    assert calls == [1]


# --- migration ------------------------------------------------------------------

def test_migration_adds_skills_and_profile_columns(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'old.db'}"
    engine = create_engine(db_url)
    init_db(engine)
    with engine.begin() as c:
        c.execute(text("ALTER TABLE awak_roles DROP COLUMN skills"))
        c.execute(text("ALTER TABLE awak_llm_aliases DROP COLUMN profile"))
        c.execute(text("INSERT INTO awak_roles (project_slug, template, name, area, model, "
                       "repo_ids, allowed_paths, denied_paths, prompt_overlay, enabled, version, "
                       "llm_base_url, llm_model, llm_api_key_enc, llm_key_last4, updated_by, "
                       "updated_at) VALUES ('demo', 'frontend', 'F', 'web', '', '[]', '[]', '[]',"
                       " '', 1, 1, '', '', '', '', 'pm', '2026-11-14 10:00:00')"))
    init_db(engine)
    assert "skills" in {c["name"] for c in inspect(engine).get_columns("awak_roles")}
    assert "profile" in {c["name"] for c in inspect(engine).get_columns("awak_llm_aliases")}
    S = make_session(db_url)
    with S() as db:
        assert config_store.load(db, "demo").roles[0].skills == []


# --- the worker -----------------------------------------------------------------

def test_worker_runs_code_and_qa_through_the_roles_skill_sets(tmp_path, repo):
    agent = FakeAgent()
    w, taiga, sessions = make_worker(tmp_path, repo, agent, FakeRunner(tmp_path / "ws",
                                                                       qa=["pass"]))
    w._seed()
    with sessions() as db:
        skills.seed_builtin(db)
        db.query(AwakRole).filter_by(template="frontend").one().skills = ["impeccable", "gone"]
        db.commit()
        kit = skills.resolve(db, ["impeccable"])
    taiga.add(1, 12, "Badge", DESC)
    assert w.tick()
    assert taiga.status_of(1) == "done"
    code = next(r for r in agent.runs if r["purpose"] == "awak.code")
    qa = next(r for r in agent.runs if r["purpose"] == "awak.qa")
    assert code["profile"] == kit.profile != skills.profile_name(skills.EMPTY_SETID)
    assert prompts.SKILLS_SECTION in code["system"]
    assert qa["profile"] == skills.profile_name(skills.EMPTY_SETID)  # QA has no skills
    assert prompts.SKILLS_SECTION not in qa["system"]
    job = job_of(sessions)
    assert job.prompt_version.endswith(f".s{kit.setid}")
    with sessions() as db:
        routed = db.query(AwakEvent).filter_by(job_id=job.id, kind="routed").one().detail
        runs = [e.detail for e in db.query(AwakEvent).filter_by(job_id=job.id, kind="skills")]
    assert routed["skills"] == ["impeccable"]
    assert [r["phase"] for r in runs] == ["code", "qa"]
    assert runs[0]["profile"] == kit.profile
    assert [x["slug"] for x in runs[0]["skills"]] == ["impeccable"]
    assert runs[0]["dropped"] == [{"slug": "gone", "reason": "missing"}]
    assert runs[1]["skills"] == [] and runs[1]["dropped"] == []
    md = Path(w.s.awak_skills_dir) / "sets" / kit.setid / "impeccable" / "SKILL.md"
    assert md.exists()


def test_role_without_skills_keeps_its_prompt_version(tmp_path, repo):
    agent = FakeAgent()
    w, taiga, sessions = make_worker(tmp_path, repo, agent, FakeRunner(tmp_path / "ws",
                                                                       qa=["pass"]))
    taiga.add(1, 12, "Badge", DESC)
    w.tick()
    with sessions() as db:
        cfg = config_store.load(db, "kemudi")
    role = next(r for r in cfg.roles if r.template == "frontend")
    assert job_of(sessions).prompt_version == prompts.prompt_version(role, cfg.repos)
    code = next(r for r in agent.runs if r["purpose"] == "awak.code")
    assert code["profile"] == skills.profile_name(skills.EMPTY_SETID)
    assert code["system"] == prompts.render_role(role, cfg.repos)


def test_marketplace_skill_forces_approve_merge(tmp_path, repo):
    agent = FakeAgent()
    w, taiga, sessions = make_worker(tmp_path, repo, agent, FakeRunner(tmp_path / "ws",
                                                                       qa=["pass"]))
    w._seed()
    with sessions() as db:
        db.get(AwakProject, "kemudi").merge_mode = "auto"
        _add_skill(db, "mk", source="marketplace")
        db.query(AwakRole).filter_by(template="frontend").one().skills = ["mk"]
        db.commit()
    taiga.add(1, 12, "Badge", DESC)
    w.tick()
    job = job_of(sessions)
    assert job.merge_mode == "approve"
    with sessions() as db:
        ev = [e.detail for e in db.query(AwakEvent).filter_by(job_id=job.id, kind="merge_mode")]
    assert {"merge_mode": "approve", "reason": "a marketplace skill was used"} in ev
