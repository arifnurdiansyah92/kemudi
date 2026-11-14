"""Runbook model, API, and gates from the runbook (stage 1a, task 4)."""

import copy

import pytest

from kemudi_ai.awak import checks, runbook
from kemudi_ai.awak.config_store import RepoConfig
from kemudi_ai.store import AwakProject, AwakRepo, AwakRunbook, Decision

from .awak_fakes import FakeAgent, FakeRunner, commit_file, real_runner
from .conftest import ADMIN, MEMBER
from .test_awak import DESC, host, job_of, make_worker, repo  # noqa: F401 (fixtures)
from .test_merge import advance, remote, request, rev  # noqa: F401 (fixtures)
from .test_merge import make as make_merge

# playfast's shape: Next.js in frontend/ (npm), a Python backend in backend/.
PLAYFAST = {
    "apps": [
        {"name": "web", "repo": "pf-web", "dir": "frontend",
         "install": ["npm ci --ignore-scripts --legacy-peer-deps", "npm run build:icons"],
         "checks": ["npx --no-install tsc --noEmit",
                    "npx --no-install eslint {changed:.ts,.tsx,.js,.jsx}"],
         "env": {"NEXT_PUBLIC_API_URL": "/api", "INTERNAL_API_URL": "{services.api.url}"}},
        {"name": "api", "repo": "pf-web", "dir": "backend",
         "checks": ["python -m pytest -q tests"]},
    ],
    "services": [
        {"name": "api", "kind": "process", "app": "api",
         "command": "python -m flask run --port {port}", "health": "/api/health"},
        {"name": "web", "kind": "process", "app": "web",
         "command": "npx --no-install next dev --port {port}", "health": "/",
         "ready_timeout": 240, "env": {"API_BASE": "{services.api.url}"}},
    ],
    "env": [{"name": "JWT_SECRET_KEY", "secret": True, "required": True}],
    "qa": {"service": "web", "routes": ["/", "/campaigns"]},
}
REPOS = {"pf-web"}
SETTINGS = {"enabled": False, "merge_mode": "approve", "deploy_command": "",
            "executor": "local", "ssh_host": "", "ssh_port": 22, "ssh_user": ""}


def problems(data, repos=REPOS):
    rb, errs = runbook.validate(data, repos)
    assert (rb is None) == bool(errs)
    return "\n".join(errs)


# --- model --------------------------------------------------------------------------

def test_playfast_runbook_is_valid():
    rb, errs = runbook.validate(PLAYFAST, REPOS)
    assert errs == [] and rb is not None
    assert [a.name for a in rb.apps_of("pf-web")] == ["web", "api"]
    assert rb.browser_qa_ready()


def test_runbook_problems_are_all_listed():
    bad = copy.deepcopy(PLAYFAST)
    bad["apps"][0]["name"] = "Web_App"
    bad["apps"][1]["repo"] = "nope"
    bad["apps"][1]["dir"] = "../backend"
    bad["apps"][0]["install"].append("rm -rf /")
    bad["apps"][0]["env"]["KEMUDI_RUNNER_KEY"] = "x"
    bad["apps"][0]["env"]["PATH"] = "/tmp"
    bad["services"][0]["env"] = {"X": "{services.nope.url}"}
    bad["qa"] = {"service": "ghost"}
    text = problems(bad)
    for needle in ("Web_App", "'nope' is not one of the project's repos", "'..'",
                   "'rm' is not an allowed program", "KEMUDI_RUNNER_KEY", "'PATH' is reserved",
                   "services.nope.url", "qa: service 'ghost'"):
        assert needle in text, needle


@pytest.mark.parametrize("change, needle", [
    (lambda r: r["apps"][0]["checks"].append("npx eslint x{changed:.ts}"), "whole argument"),
    (lambda r: r["apps"][0]["checks"].append("npx eslint {changed:ts}"), "whole argument"),
    (lambda r: r["apps"][0]["install"].append("npx eslint {changed:.ts}"), "only allowed in"),
    (lambda r: r["apps"][0]["checks"].append("npx serve --port {port}"), "{port}"),
    (lambda r: r["apps"].append(dict(r["apps"][0])), "duplicate app names: web"),
    (lambda r: r["services"].reverse(), "must come before"),
    (lambda r: r["services"][1].update(app="ghost"), "app 'ghost'"),
    (lambda r: r["services"][1].update(health="ready"), "health"),
    (lambda r: r["services"][1].update(health="/a b"), "health"),
    (lambda r: r["services"][1].update(health="/a"), "health"),
    (lambda r: r["services"][1].update(ready_timeout=900), "ready_timeout"),
    (lambda r: r.update(extra=1), "extra"),
    (lambda r: r.update(seed={"service": "web", "command": "x"}), "compose service"),
    (lambda r: r["apps"][0].update(dir="/abs"), "relative"),
])
def test_runbook_rejects(change, needle):
    rb = copy.deepcopy(PLAYFAST)
    change(rb)
    assert needle in problems(rb)


def test_changed_placeholder_syntax():
    assert runbook.changed_exts("{changed:.ts,.TSX}") == [".ts", ".tsx"]
    assert runbook.changed_exts("{changed:}") == []
    assert runbook.changed_exts("{changed:.ts,}") is None
    assert runbook.changed_exts("a{changed:.ts}") is None


def test_compose_service_is_accepted_by_the_schema():
    rb = copy.deepcopy(PLAYFAST)
    rb["services"][0] = {"name": "api", "kind": "compose", "repo": "pf-web",
                         "file": "docker-compose.yml", "compose_services": ["backend"],
                         "expose": "backend:5000", "health": "/api/health",
                         "env": ["JWT_SECRET_KEY"]}
    parsed, errs = runbook.validate(rb, REPOS)
    assert errs == [] and not parsed.browser_qa_ready()


def test_allowlist_and_blocked_env_match_the_runner():
    r = real_runner()
    assert set(r.ALLOWED_PROGRAMS) == set(runbook.ALLOWED_PROGRAMS)
    assert set(r.BLOCKED_ENV_NAMES) == set(runbook.BLOCKED_ENV_NAMES)
    assert tuple(r.BLOCKED_ENV_PREFIXES) == tuple(runbook.BLOCKED_ENV_PREFIXES)


# --- checks -------------------------------------------------------------------------

RC = RepoConfig(id=1, name="pf-web", role="web", url="git@x:pf.git", subdir="frontend",
                install_cmd="pnpm install", check_cmd="pnpm exec tsc --noEmit", build_cmd="")


def _rb():
    return runbook.validate(PLAYFAST, REPOS)[0]


def test_gate_selection_by_changed_files():
    apps = _rb().apps
    names = lambda files: [a.name for a in checks.select_apps(apps, files)]  # noqa: E731
    assert names(["frontend/app/page.tsx"]) == ["web"]
    assert names(["backend/app.py"]) == ["api"]
    assert names(["frontend/a.ts", "backend/b.py"]) == ["web", "api"]
    assert names(["README.md", "frontend/a.ts"]) == ["web", "api"]  # a root change: all
    assert names([]) == ["web", "api"]


def test_gate_payloads_expand_changed_files(tmp_path):
    (tmp_path / "frontend" / "app").mkdir(parents=True)
    (tmp_path / "frontend" / "app" / "page.tsx").write_text("x")
    (tmp_path / "frontend" / "util.js").write_text("x")
    (tmp_path / "frontend" / "styles.css").write_text("x")
    changed = ["frontend/util.js", "frontend/app/page.tsx", "frontend/styles.css",
               "frontend/gone.ts"]  # deleted by the story
    [web] = checks.gate_payloads(RC, _rb(), changed, tmp_path)
    assert web["app"] == "web" and web["subdir"] == "frontend"
    assert web["env"] == {"NEXT_PUBLIC_API_URL": "/api"}  # no service is up for gates
    assert [c["argv"] for c in web["commands"]] == [
        ["npx", "--no-install", "tsc", "--noEmit"],
        ["npx", "--no-install", "eslint", "./app/page.tsx", "./util.js"]]
    assert web["skipped"] == []
    [web] = checks.gate_payloads(RC, _rb(), ["frontend/styles.css"], tmp_path)
    assert len(web["commands"]) == 1
    assert web["skipped"] == ["npx --no-install eslint '{changed:.ts,.tsx,.js,.jsx}' "
                              "(no changed files)"]


def test_changed_files_never_read_as_options_and_are_capped(tmp_path):
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "-rf.ts").write_text("x")
    [web] = checks.gate_payloads(RC, _rb(), ["frontend/-rf.ts"], tmp_path)
    assert web["commands"][1]["argv"][-1] == "./-rf.ts"
    many = [f"frontend/f{i}.ts" for i in range(checks.MAX_CHANGED_ARGS + 1)]
    [web] = checks.gate_payloads(RC, _rb(), many)
    assert web["commands"][1]["argv"] == ["npx", "--no-install", "eslint", "."]
    few = many[:checks.MAX_CHANGED_ARGS]
    [web] = checks.gate_payloads(RC, _rb(), few)
    assert len(web["commands"][1]["argv"]) == 3 + checks.MAX_CHANGED_ARGS


def test_saved_runbook_keeps_set_defaults_and_drops_unset(agent_client):
    _repo(agent_client)
    spec = copy.deepcopy(PLAYFAST)
    spec["services"][0]["health"] = "/"  # set explicitly, though the default
    body = agent_client.put("/projects/demo/agent/runbook", headers=ADMIN,
                            json={"runbook": spec}).json()["runbook"]
    assert body["services"][0]["health"] == "/"
    assert "ready_timeout" not in body["services"][0]
    assert body["services"][1]["ready_timeout"] == 240


def test_without_a_runbook_the_repo_row_commands_are_used():
    [p] = checks.gate_payloads(RC, None, ["frontend/a.ts"])
    assert p["subdir"] == "frontend" and p["app"] == ""
    assert [c["argv"] for c in p["commands"]] == [["pnpm", "exec", "tsc", "--noEmit"]]
    [p] = checks.install_payloads(RC, None)
    assert [c["argv"] for c in p["commands"]] == [["pnpm", "install"]]
    # a runbook without an app for this repo: the repo row too
    other = RepoConfig(id=2, name="other", role="api", url="git@x:o.git", check_cmd="make test")
    assert checks.gate_payloads(other, _rb(), [])[0]["commands"][0]["argv"] == ["make", "test"]


def test_run_gates_prefixes_names_and_stops_at_the_first_failing_app():
    calls = []

    def call(op, **body):
        calls.append((op, body))
        ok = body["subdir"] != "frontend"
        return {"gates": [{"name": c["name"], "ok": ok, "output": ""}
                          for c in body["commands"]]}

    payloads = checks.gate_payloads(RC, _rb(), ["README.md"])
    gates = checks.run_gates(call, "pf/us-1/pf-web", payloads)
    assert [c[0] for c in calls] == ["gates"]  # web failed: api not run
    assert gates[0]["name"] == "web: npx --no-install tsc --noEmit" and not gates[0]["ok"]
    assert calls[0][1]["env"] == {"NEXT_PUBLIC_API_URL": "/api"}
    assert any(g["name"].endswith("(no changed files)") and g["ok"] for g in gates)


def test_run_in_is_stage_1b():
    rb = copy.deepcopy(PLAYFAST)
    rb["services"].insert(0, {"name": "db", "kind": "compose", "repo": "pf-web",
                              "file": "docker-compose.yml"})
    rb["apps"][1]["run_in"] = "db:backend"
    parsed, errs = runbook.validate(rb, REPOS)
    assert errs == []
    with pytest.raises(checks.Unsupported, match="1b"):
        checks.gate_payloads(RC, parsed, [])


def test_qa_plan_orders_needed_process_services():
    plan = checks.qa_plan(_rb())
    assert [s["name"] for s in plan["services"]] == ["api", "web"]
    web = plan["services"][1]
    assert web["repo"] == "pf-web" and web["subdir"] == "frontend"
    assert web["argv"] == ["npx", "--no-install", "next", "dev", "--port", "{port}"]
    assert web["env"]["INTERNAL_API_URL"] == "{services.api.url}"
    assert web["env"]["API_BASE"] == "{services.api.url}"
    assert plan["base_service"] == "web" and plan["warm"] == ["/", "/campaigns"]
    assert plan["app_dirs"] == ["pf-web/backend", "pf-web/frontend"]


# --- API ----------------------------------------------------------------------------

def _repo(agent_client, name="pf-web", url="git@github.com:acme/pf.git"):
    with agent_client.S() as db:
        db.add(AwakRepo(project_slug="demo", name=name, url=url))
        db.commit()


def test_runbook_api(agent_client):
    url = "/projects/demo/agent/runbook"
    assert agent_client.get(url, headers=MEMBER).json() == {
        "runbook": None, "version": 0, "approved_by": "", "approved_at": None}
    assert agent_client.put(url, headers=MEMBER, json={"runbook": PLAYFAST}).status_code == 403
    r = agent_client.put(url, headers=ADMIN, json={"runbook": PLAYFAST})
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert isinstance(detail, list) and all(isinstance(d, str) for d in detail)
    assert any("'pf-web' is not one of the project's repos" in d for d in detail)
    _repo(agent_client)
    r = agent_client.put(url, headers=ADMIN, json={"runbook": PLAYFAST})
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == 1 and body["approved_by"].startswith("pm") and body["approved_at"]
    assert body["runbook"]["apps"][0]["dir"] == "frontend"
    assert agent_client.put(url, headers=ADMIN, json={"runbook": PLAYFAST}).json()["version"] == 2
    assert agent_client.get(url, headers=MEMBER).json()["version"] == 2
    assert agent_client.put(url, headers=ADMIN, json={"runbook": []}).status_code == 422
    with agent_client.S() as db:
        assert db.get(AwakRunbook, "demo").updated_by.startswith("pm")
        d = db.query(Decision).filter_by(action="awak_runbook").all()
        assert [x.detail["version"] for x in d] == [1, 2]


def test_browser_qa_allowed_with_a_runbook_qa_process_service(agent_client):
    settings = "/projects/demo/agent/settings"
    _repo(agent_client)
    r = agent_client.put(settings, headers=ADMIN, json={**SETTINGS, "qa_mode": "browser"})
    assert r.status_code == 422 and "runbook" in r.text
    compose = copy.deepcopy(PLAYFAST)
    compose["services"][1] = {"name": "web", "kind": "compose", "repo": "pf-web",
                              "file": "docker-compose.yml", "health": "/"}
    assert agent_client.put("/projects/demo/agent/runbook", headers=ADMIN,
                            json={"runbook": compose}).status_code == 200
    r = agent_client.put(settings, headers=ADMIN, json={**SETTINGS, "qa_mode": "browser"})
    assert r.status_code == 422 and "1b" in r.text
    agent_client.put("/projects/demo/agent/runbook", headers=ADMIN, json={"runbook": PLAYFAST})
    r = agent_client.put(settings, headers=ADMIN, json={**SETTINGS, "merge_mode": "auto",
                                                        "qa_mode": "browser"})
    assert r.status_code == 200 and r.json()["qa_mode"] == "browser"


# --- worker and merge ---------------------------------------------------------------

KEMUDI_RB = {
    "apps": [{"name": "web", "repo": "kemudi", "dir": "",
              "install": ["npm ci --ignore-scripts --legacy-peer-deps"],
              "checks": ["npx --no-install tsc --noEmit", "npx --no-install eslint {changed:.txt}"],
              "env": {"MODE": "test"}}],
    "services": [{"name": "web", "kind": "process", "app": "web",
                  "command": "npx --no-install next dev --port {port}", "health": "/"}],
    "qa": {"service": "web"},
}


def _save_rb(sessions, spec, slug="kemudi"):
    rb, errs = runbook.validate(spec, {"kemudi"})
    assert not errs
    with sessions() as db:
        runbook.save(db, slug, rb, "pm")


def _set(sessions, **fields):
    with sessions() as db:
        p = db.get(AwakProject, "kemudi")
        for k, v in fields.items():
            setattr(p, k, v)
        db.commit()


def test_worker_gates_from_the_runbook(tmp_path, repo):
    runner = FakeRunner(tmp_path / "ws")
    w, taiga, sessions = make_worker(tmp_path, repo, FakeAgent(), runner)
    w._seed()
    _set(sessions, qa_mode="gates", merge_mode="approve")
    _save_rb(sessions, KEMUDI_RB)
    taiga.add(1, 12, "Badge jumlah", DESC)
    assert w.tick()
    assert taiga.status_of(1) == "done"
    install = next(b for op, b in runner.payloads if op == "install")
    assert install["commands"][0]["argv"][:2] == ["npm", "ci"] and install["env"] == {
        "MODE": "test"}
    gates = next(b for op, b in runner.payloads if op == "gates")
    assert gates["commands"][1]["argv"] == ["npx", "--no-install", "eslint", "./feature1.txt"]
    assert "web: tsc" in taiga.texts(1)[-1]


def test_worker_browser_qa_from_the_runbook(tmp_path, repo):
    runner = FakeRunner(tmp_path / "ws", qa=["pass"])
    agent = FakeAgent()
    w, taiga, sessions = make_worker(tmp_path, repo, agent, runner)
    w._seed()
    _save_rb(sessions, KEMUDI_RB)
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    assert taiga.status_of(1) == "done" and "QA lulus" in taiga.texts(1)[-1]
    qa = next(b for op, b in runner.payloads if op == "qa")
    assert "token" not in qa and qa["base_service"] == "web"
    assert qa["services"][0]["argv"][-1] == "{port}"
    assert w.qa_taiga.logins == 0
    task = next(t for p, t in agent.calls if p == "awak.qa")
    assert ".qa/routes.txt" in task and "QA project slug:" not in task
    assert "runs twice" in task


def test_worker_browser_with_compose_qa_falls_back_to_gates(tmp_path, repo):
    spec = copy.deepcopy(KEMUDI_RB)
    spec["services"] = [{"name": "web", "kind": "compose", "repo": "kemudi",
                         "file": "compose.yml", "health": "/"}]
    spec["apps"][0]["env"] = {}
    runner = FakeRunner(tmp_path / "ws")
    w, taiga, sessions = make_worker(tmp_path, repo, FakeAgent(), runner)
    w._seed()
    _save_rb(sessions, spec)
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    assert taiga.status_of(1) == "done" and "qa" not in runner.calls
    assert "tahap 1b" in taiga.texts(1)[-1]


def test_merge_recheck_uses_the_runbook_gates(tmp_path, remote):
    from kemudi_ai.awak.gitops import Repo

    merge_repo = Repo(str(tmp_path / "bare.git"), str(remote), str(tmp_path / "ws"), uid=0,
                      slug="kemudi", name="kemudi")
    w, taiga, sessions, runner = make_merge(tmp_path, merge_repo)
    _set(sessions, qa_mode="gates")
    _save_rb(sessions, KEMUDI_RB)
    w.tick()
    advance(tmp_path, remote)
    request(sessions)
    n = len(runner.payloads)
    w.tick()
    job = job_of(sessions)
    assert job.merge_state == "merged" and rev(remote) == job.merged_sha
    gates = [b for op, b in runner.payloads[n:] if op == "gates"]
    assert gates and gates[0]["commands"][1]["argv"][-1] == "./feature1.txt"


def test_unparseable_runbook_command_stops_the_story(tmp_path, repo):
    runner = FakeRunner(tmp_path / "ws")
    w, taiga, sessions = make_worker(tmp_path, repo, FakeAgent(code=lambda d, n: commit_file(
        d, "a.txt", "x")), runner)
    w._seed()
    _set(sessions, qa_mode="gates")
    spec = copy.deepcopy(KEMUDI_RB)
    _save_rb(sessions, spec)
    with sessions() as db:
        row = db.get(AwakRunbook, "kemudi")
        row.spec = {**row.spec, "apps": [{**row.spec["apps"][0], "install": ["npm 'ci"]}]}
        db.commit()
    taiga.add(1, 12, "Badge jumlah", DESC)
    w.tick()
    assert job_of(sessions).state == "stopped"
    assert any("tidak valid" in t for t in taiga.texts(1))
