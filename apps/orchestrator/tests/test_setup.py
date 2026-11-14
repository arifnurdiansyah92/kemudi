"""Stage 1c: the Setup Assistant (Configure automatically): the setup run's
state machine with a fake agent, runner and kemudi-svc, and its API."""

import copy
import json
import os
from pathlib import Path

import pytest

from kemudi_ai.awak import runbook, setup, vault
from kemudi_ai.awak.runner import RunnerError
from kemudi_ai.store import AwakProject, AwakRepo, AwakSetupRun, Decision

from .awak_fakes import PNG, git
from .conftest import ADMIN, MEMBER
from .test_awak import host, repo  # noqa: F401 (fixtures)
from .test_compose_qa import RB, FakeSvc, Runner, creds
from .test_vault import _worker, made_value


class SetupAgent:
    """Writes `runbook.json` from `replies` (a dict, raw text, or None to write
    nothing), one per setup turn; the last reply repeats."""

    def __init__(self, replies, cost=7.0):
        self.replies = list(replies)
        self.cost = cost
        self.tasks: list[str] = []
        self.runs: list[dict] = []

    def run(self, purpose, model, system, task, slug="", role_id=None):
        assert purpose == "awak.setup"
        self.tasks.append(task)
        self.runs.append({"model": model, "system": system, "slug": slug, "role_id": role_id})
        root = Path(task.splitlines()[0].removeprefix("Workspace: ").strip())
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        if reply is not None:
            text = reply if isinstance(reply, str) else json.dumps(reply)
            (root / "runbook.json").write_text(text, encoding="utf-8")
        return "runbook written", self.cost


class SetupRunner(Runner):
    """The runner with the `screenshot` op: writes a PNG where the real one
    would, unless `shots` holds replies."""

    def __init__(self, workspace, order, shots=None, on_shot=None, **kw):
        super().__init__(workspace, order, **kw)
        self.shots = list(shots or [])
        self.on_shot = on_shot

    def call(self, op, **payload):
        if op == "screenshot":
            self.order.append(op)
            self.calls.append(op)
            self.payloads.append((op, payload))
            if self.on_shot:
                self.on_shot()
            if self.shots:
                return self.shots.pop(0)
            f = self.workspace / payload["path"] / ".qa" / payload["out"]
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(PNG)
            return {"ok": True, "screenshot": f".qa/{payload['out']}", "peak_mb": 900.0,
                    "processes": [{"name": s["name"], "rss_mb": 310.5, "log": "ready in 3s"}
                                  for s in payload["services"]]}
        return super().call(op, **payload)


class StatsSvc(FakeSvc):
    def call(self, op, **payload):
        res = super().call(op, **payload)
        if op == "svc_stats":
            return {"ok": True, "stats": [
                {"name": "x-backend-1", "service": "backend", "cpu_pct": 3.5,
                 "mem_bytes": 200 * 1024 * 1024},
                {"name": "x-postgres-1", "service": "postgres", "cpu_pct": 1.0,
                 "mem_bytes": 50 * 1024 * 1024}]}
        return res


@pytest.fixture
def project_host(host):
    """The test repo with an app at its root and a compose file."""
    (host / "package.json").write_text(json.dumps(
        {"scripts": {"dev": "next dev", "lint": "next lint"},
         "dependencies": {"next": "15"}}))
    (host / "package-lock.json").write_text("{}")
    (host / "docker-compose.yml").write_text("services: {}\n")
    git(host, "add", "-A")
    git(host, "commit", "-m", "app")
    return host


def make(tmp_path, repo, replies=(RB,), fill=True, shots=None, on_shot=None, confirmed=True,
         **kw):
    """`confirmed`: the saved values count as confirmed for the run (as if an
    admin had confirmed them); False to see the run ask."""
    order: list[str] = []
    runner = SetupRunner(tmp_path / "ws", order, shots=shots, on_shot=on_shot,
                         health=kw.pop("health", None), gates=kw.pop("gates", None))
    agent = SetupAgent(list(replies))
    w, taiga, sessions, settings = _worker(tmp_path, repo, agent, runner)
    w.svc = StatsSvc(order, **kw)
    w._seed()
    values = creds() if fill else {}
    with sessions() as db:
        for k, v in values.items():
            vault.put(db, settings, "kemudi", k, v, True, "pm")
        run = setup.start(db, "kemudi", "pm")
        if confirmed:
            run.confirmed_env = sorted(values)
            db.commit()
    return w, sessions, settings, runner, agent, run.id, values


def run_of(sessions, run_id) -> AwakSetupRun:
    with sessions() as db:
        return db.get(AwakSetupRun, run_id)


def drive(w, sessions, run_id, until=("ready", "failed", "needs_input", "cancelled"), n=20):
    """Worker ticks until the run reaches one of `until`; the states seen."""
    seen = [run_of(sessions, run_id).state]
    for _ in range(n):
        w.tick()
        state = run_of(sessions, run_id).state
        seen.append(state)
        if state in until:
            return seen
    raise AssertionError(f"stuck: {seen}")


def steps(run) -> dict[str, dict]:
    return {s["name"]: s for s in run.steps}


# --- the state machine ---------------------------------------------------------------


def test_happy_path_reads_proposes_proves_and_is_ready(tmp_path, repo, project_host):
    w, sessions, settings, runner, agent, run_id, values = make(tmp_path, repo)
    seen = drive(w, sessions, run_id)
    assert seen == ["queued", "reading", "proving", "ready"]
    run = run_of(sessions, run_id)
    # one step per tick, the draft from detection
    draft = run.proposal["draft"]["kemudi"]
    assert draft["apps"][0]["dir"] == "" and draft["compose_files"] == ["docker-compose.yml"]
    assert run.proposal["runbook"]["services"][0]["name"] == "api"
    assert run.round == 1 and run.error == "" and run.cost_idr == 7.0
    # the agent: setup template, the schema, the draft, the vault names (never values)
    [task] = agent.tasks
    assert "Write the project's runbook to" in task and '"compose_services"' in task
    assert "docker-compose.yml" in task and "JWT_SECRET_KEY" in task
    assert not any(v in task for v in values.values())
    assert "devops engineer" in agent.runs[0]["system"] and agent.runs[0]["slug"] == "kemudi"
    # the proof: install, checks, compose up (init first), health, the screenshot
    by = steps(run)
    for name in ("install web", "checks web", "start api", "init python scripts/init_qa.py",
                 "health api", "seed python scripts/seed_campaigns.py", "service web",
                 "login", "screenshot", "logs api"):
        assert name in by and by[name]["ok"], (name, list(by))
    assert run.screenshot == "kemudi/.qa/setup/home.png"
    assert (setup.setup_root(settings, "kemudi") / run.screenshot).read_bytes() == PNG
    shot = next(p for op, p in runner.payloads if op == "screenshot")
    assert shot["path"] == "kemudi/setup/kemudi" and shot["base_service"] == "web"
    assert shot["external"] == {"api": "http://kemudi-dind:32768"}
    assert shot["login"]["fields"][1]["value"] == values["QA_ADMIN_PASSWORD"]
    assert run.resources["processes"] == [{"name": "web", "rss_mb": 310.5}]
    assert run.resources["compose"][0] == {"service": "api", "container": "backend",
                                           "mem_mb": 200.0, "cpu_pct": 3.5}
    assert run.resources["total_mb"] == 560.5 and run.resources["runner_peak_mb"] == 900.0
    # compose project `<slug>-setup`, always down at the end
    ups = w.svc.ops("svc_up")
    assert {u["project"] for u in ups} == {"kemudi-setup"}
    assert ups[0]["path"] == "kemudi/setup/kemudi"
    assert w.svc.ops("svc_down") == [{"project": "kemudi-setup"}]
    assert runner.order.index("screenshot") < w.svc.order.index("svc_down")
    # nothing else to do
    assert setup.SetupRunner(w).next_run() is None


def test_invalid_runbook_goes_back_to_the_agent_then_fails(tmp_path, repo, project_host):
    bad = copy.deepcopy(RB)
    bad["qa"]["service"] = "api"
    w, sessions, _, _, agent, run_id, _ = make(tmp_path, repo, replies=["{not json", bad])
    seen = drive(w, sessions, run_id)
    assert seen[-1] == "failed" and seen.count("reading") == 3  # first turn + 2 retries
    assert len(agent.tasks) == 3
    assert "not valid JSON" in agent.tasks[1] and "must be a process service" in agent.tasks[2]
    assert "Your previous runbook" in agent.tasks[2]
    run = run_of(sessions, run_id)
    assert "still invalid after 3 turns" in run.error and run.cost_idr == 21.0


def test_invalid_twice_then_valid_goes_on(tmp_path, repo, project_host):
    w, sessions, _, _, agent, run_id, _ = make(tmp_path, repo, replies=[None, "[]", RB])
    assert drive(w, sessions, run_id)[-1] == "ready"
    assert "was not written" in agent.tasks[1] and "one JSON object" in agent.tasks[2]


def test_a_secret_value_in_the_runbook_is_refused(tmp_path, repo, project_host):
    value = made_value()
    leaky = copy.deepcopy(RB)
    leaky["apps"][0]["env"]["API_TOKEN"] = value
    w, sessions, settings, _, agent, run_id, _ = make(tmp_path, repo, replies=[leaky, RB])
    with sessions() as db:
        vault.put(db, settings, "kemudi", "API_TOKEN", value, True, "pm")
    assert drive(w, sessions, run_id)[-1] == "ready"
    assert "secret value" in agent.tasks[1] and value not in agent.tasks[1]
    assert value not in json.dumps(run_of(sessions, run_id).proposal)


def test_missing_env_waits_for_input_holding_nothing(tmp_path, repo, project_host):
    w, sessions, settings, runner, _, run_id, _ = make(tmp_path, repo, fill=False)
    assert drive(w, sessions, run_id)[-1] == "needs_input"
    run = run_of(sessions, run_id)
    by = {m["name"]: m for m in run.missing_env}
    # every referenced or required name; the optional MIDTRANS key is not asked for
    assert set(by) == {"JWT_SECRET_KEY", "QA_ADMIN_EMAIL", "QA_ADMIN_PASSWORD"}
    assert by["QA_ADMIN_EMAIL"]["secret"] is False and by["QA_ADMIN_PASSWORD"]["secret"] is True
    assert by["JWT_SECRET_KEY"]["secret"] is True
    # needs_input is not stepped and holds no services or processes
    assert not w.tick() or run_of(sessions, run_id).state == "needs_input"
    assert setup.SetupRunner(w).next_run() is None
    assert "svc_up" not in w.svc.order and "screenshot" not in runner.order


def test_env_help_describes_missing_names(tmp_path, repo, project_host):
    spec = {**copy.deepcopy(RB), "env_help": {"JWT_SECRET_KEY": "any 64-char hex string"}}
    w, sessions, _, _, _, run_id, _ = make(tmp_path, repo, replies=[spec], fill=False)
    drive(w, sessions, run_id)
    run = run_of(sessions, run_id)
    by = {m["name"]: m for m in run.missing_env}
    assert by["JWT_SECRET_KEY"]["description"] == "any 64-char hex string"
    assert run.proposal["env_help"] == {"JWT_SECRET_KEY": "any 64-char hex string"}
    assert "env_help" not in run.proposal["runbook"]


def test_failed_health_goes_back_to_the_agent_then_ready(tmp_path, repo, project_host):
    health = [{"ok": False, "error": "no 2xx/3xx answer at /api/health within 90s"}]
    w, sessions, _, runner, agent, run_id, values = make(tmp_path, repo, health=health)
    seen = drive(w, sessions, run_id)
    assert seen == ["queued", "reading", "proving", "reading", "proving", "ready"]
    run = run_of(sessions, run_id)
    assert run.round == 2 and run.error == ""
    fix = agent.tasks[1]
    assert "Running the runbook in the sandbox failed" in fix
    assert "/api/health" in fix and "no table users" in fix  # the redacted service log
    assert "Your previous runbook" in fix
    # every proof brought its services down
    assert w.svc.order.count("svc_down") == 2


def test_three_failed_rounds_fail_with_the_last_logs(tmp_path, repo, project_host):
    health = [{"ok": False, "error": "down"}] * 3
    w, sessions, _, _, agent, run_id, _ = make(tmp_path, repo, health=health)
    seen = drive(w, sessions, run_id)
    assert seen[-1] == "failed" and seen.count("proving") == 3
    run = run_of(sessions, run_id)
    assert run.round == setup.MAX_ROUNDS == 3 and len(agent.tasks) == 3
    assert "Round 3/3" in run.error and "no table users" in run.error
    assert not steps(run)["services"]["ok"]
    assert w.svc.order.count("svc_down") == 3


def test_a_red_check_is_reported_but_does_not_fail(tmp_path, repo, project_host):
    gates = [{"ok": False, "gates": [{"name": "tsc", "ok": False, "output": "error TS2322"}]}]
    w, sessions, _, _, _, run_id, _ = make(tmp_path, repo, gates=gates)
    assert drive(w, sessions, run_id)[-1] == "ready"
    check = steps(run_of(sessions, run_id))["checks web"]
    assert check["ok"] is False and check["red"] is True and "error TS2322" in check["output"]


def test_a_check_that_cannot_run_fails_the_round(tmp_path, repo, project_host):
    gates = [{"infra_error": "FileNotFoundError: [Errno 2] No such file: 'pytest'"}]
    w, sessions, _, _, agent, run_id, _ = make(tmp_path, repo, gates=gates)
    seen = drive(w, sessions, run_id)
    assert seen[:5] == ["queued", "reading", "proving", "reading", "proving"]
    assert seen[-1] == "ready" and "could not run" in agent.tasks[1]
    # it failed before any service was started
    assert w.svc.order.count("svc_up") == 2


def test_a_failed_login_is_a_fix_round(tmp_path, repo, project_host):
    shots = [{"login_error": "login failed: still at /login", "processes": []}]
    w, sessions, _, runner, agent, run_id, _ = make(tmp_path, repo, shots=shots)
    assert drive(w, sessions, run_id)[-1] == "ready"
    assert "qa.login" in agent.tasks[1] and "still at /login" in agent.tasks[1]


def test_a_failed_install_is_a_fix_round(tmp_path, repo, project_host):
    class FailingInstall(SetupRunner):
        def call(self, op, **payload):
            if op == "install" and not self.order.count("install-failed"):
                self.order.append("install-failed")
                return {"ok": False, "infra_error": "npm ci failed: missing lockfile"}
            return super().call(op, **payload)

    w, sessions, _, runner, agent, run_id, _ = make(tmp_path, repo)
    w.runner = FailingInstall(tmp_path / "ws", runner.order)
    assert drive(w, sessions, run_id)[-1] == "ready"
    assert "install of app web failed" in agent.tasks[1] and "missing lockfile" in agent.tasks[1]
    assert "svc_up" in w.svc.order  # the second round got that far


def test_step_outputs_and_errors_are_redacted(tmp_path, repo, project_host):
    value = made_value()
    shots = [{"infra_error": f"service web did not start: token={value}",
              "processes": [{"name": "web", "rss_mb": 1, "log": f"boot with {value}"}]}] * 3
    w, sessions, settings, _, agent, run_id, _ = make(tmp_path, repo, shots=shots)
    with sessions() as db:
        vault.put(db, settings, "kemudi", "API_TOKEN", value, True, "pm")
    assert drive(w, sessions, run_id)[-1] == "failed"
    run = run_of(sessions, run_id)
    stored = json.dumps({"steps": run.steps, "error": run.error, "proposal": run.proposal})
    assert value not in stored and "[disembunyikan]" in stored
    assert not any(value in t for t in agent.tasks)


def test_transport_errors_retry_then_fail(tmp_path, repo, project_host):
    w, sessions, _, runner, _, run_id, _ = make(tmp_path, repo)
    drive(w, sessions, run_id, until=("proving",))

    class Down:
        def call(self, op, **payload):
            raise RunnerError("runner install failed: ConnectError")

    w.runner = Down()
    w.tick()
    run = run_of(sessions, run_id)
    assert run.state == "proving" and run.round == 1 and "retrying" in run.error
    # no sleep in the tick: the run waits until `not_before`, the worker goes on
    assert run.not_before is not None
    assert not w.tick() and setup.SetupRunner(w).next_run() is None
    assert run_of(sessions, run_id).proposal["infra_errors"] == 1

    def due():
        with sessions() as db:
            db.get(AwakSetupRun, run_id).not_before = None
            db.commit()

    due()
    w.tick()
    due()
    w.tick()
    run = run_of(sessions, run_id)
    assert run.state == "failed" and "3 times in a row" in run.error


def test_cancel_during_the_proof_is_not_overwritten(tmp_path, repo, project_host):
    holder = {}

    def cancel():
        with holder["sessions"]() as db:
            setup.transition(db, holder["id"], setup.ACTIVE, state="cancelled")

    w, sessions, _, _, _, run_id, _ = make(tmp_path, repo, on_shot=cancel)
    holder.update(sessions=sessions, id=run_id)
    drive(w, sessions, run_id, until=("cancelled",))
    assert run_of(sessions, run_id).state == "cancelled"
    assert w.svc.order.count("svc_down") == 1  # the proof's services still came down


def test_setup_steps_and_stories_take_turns_and_it_recovers(tmp_path, repo, project_host):
    w, sessions, settings, runner, _, run_id, _ = make(tmp_path, repo)
    w.taiga.add(1, 12, "Badge", "## Acceptance criteria\n- shows a badge")
    stories: list[int] = []
    w._process = lambda project, job_id, story: stories.append(story["ref"])
    w.tick()
    assert run_of(sessions, run_id).state == "reading" and stories == []
    # the next tick serves the ready story, not the setup run
    w.tick()
    assert stories == [12] and run_of(sessions, run_id).state == "reading"
    w.tick()
    assert run_of(sessions, run_id).state == "proving" and stories == [12]
    w.tick()
    assert stories == [12, 12] and run_of(sessions, run_id).state == "proving"
    w.tick()
    assert run_of(sessions, run_id).state == "ready" and stories == [12, 12]
    assert w.tick() and stories == [12, 12, 12]
    with sessions() as db:
        setup.transition(db, run_id, "ready", state="proving")
    with sessions() as db:
        db.get(AwakSetupRun, run_id).steps = [{"name": "half", "ok": True, "output": ""}]
        db.commit()
    # a new worker: the proof starts over, its compose project is kept by the sweep
    w._services_swept = False
    w.recover()
    run = run_of(sessions, run_id)
    assert run.state == "proving" and run.steps == []
    assert w.svc.ops("svc_sweep")[-1]["keep"] == ["kemudi-setup"]


def test_missing_env_list_rules():
    rb = runbook.Runbook.model_validate(RB)
    names = [m["name"] for m in setup.missing_env(rb, {"JWT_SECRET_KEY"}, {})]
    assert names == ["QA_ADMIN_EMAIL", "QA_ADMIN_PASSWORD"]
    assert setup.plain_name("QA_ADMIN_EMAIL") and setup.plain_name("API_URL")
    assert not setup.plain_name("DATABASE_URL") and not setup.plain_name("JWT_SECRET_KEY")
    assert not setup.plain_name("SOMETHING")


# --- API -------------------------------------------------------------------------------

BASE = "/projects/demo/agent/setup"


@pytest.fixture
def api(agent_client):
    with agent_client.S() as db:
        db.add(AwakRepo(project_slug="demo", name="kemudi", url="git@example.com:x/y.git"))
        db.commit()
    agent_client.svc = FakeSvc()
    agent_client.settings.svc_key = "svc-" + made_value()  # kemudi-svc configured
    from kemudi_ai.api import app
    from kemudi_ai.awak import agent_api

    app.dependency_overrides[agent_api.get_svc] = lambda: agent_client.svc
    return agent_client


def put_run(client, state, **fields) -> int:
    with client.S() as db:
        run = AwakSetupRun(project_slug="demo", state=state, created_by="pm",
                           proposal={"runbook": copy.deepcopy(RB)}, **fields)
        db.add(run)
        db.commit()
        return run.id


def decisions(client, action="awak_setup"):
    with client.S() as db:
        return [d.detail for d in db.query(Decision).filter_by(action=action).order_by(Decision.id)]


def test_start_needs_admin_and_one_active_run(api):
    assert api.post(BASE, headers=MEMBER).status_code == 403
    r = api.post(BASE, headers=ADMIN)
    assert r.status_code == 202, r.text
    run = r.json()["run"]
    assert run["state"] == "queued" and run["active"] and run["round"] == 1
    assert run["max_rounds"] == 3 and run["created_by"].startswith("pm")
    assert api.started == [True]
    r = api.post(BASE, headers=ADMIN)
    assert r.status_code == 409 and "still queued" in r.text
    assert decisions(api) == [{"op": "start", "run_id": run["id"]}]


def test_start_needs_a_repo(agent_client):
    assert agent_client.post(BASE, headers=ADMIN).status_code == 422


def test_latest_for_members_masks_env_values(api):
    assert api.get(f"{BASE}/latest", headers=MEMBER).json() == {"run": None}
    spec = copy.deepcopy(RB)
    spec["apps"][0]["env"]["FEATURE_FLAG_TOKEN"] = "plain-but-hidden"
    with api.S() as db:
        db.add(AwakSetupRun(project_slug="demo", state="ready", proposal={"runbook": spec}))
        db.commit()
    member = api.get(f"{BASE}/latest", headers=MEMBER).json()["run"]
    assert member["state"] == "ready" and "plain-but-hidden" not in json.dumps(member)
    admin = api.get(f"{BASE}/latest", headers=ADMIN).json()["run"]
    assert admin["proposal"]["runbook"]["apps"][0]["env"]["FEATURE_FLAG_TOKEN"] == \
        "plain-but-hidden"
    assert set(admin) >= {"id", "state", "active", "round", "max_rounds", "proposal", "steps",
                          "missing_env", "screenshot", "resources", "error", "cost_idr",
                          "created_by", "created_at", "updated_at"}


def test_env_fills_the_vault_and_resumes_the_proof(api):
    run_id = put_run(api, "needs_input", missing_env=[
        {"name": "JWT_SECRET_KEY", "description": "", "secret": True}])
    values = creds()
    url = f"{BASE}/{run_id}/env"
    body = {"values": {"JWT_SECRET_KEY": {"value": values["JWT_SECRET_KEY"], "secret": True}}}
    assert api.post(url, headers=MEMBER, json=body).status_code == 403
    r = api.post(url, headers=ADMIN, json=body)
    assert r.status_code == 200, r.text
    run = r.json()["run"]
    # QA_ADMIN_* are still missing: the run keeps waiting, with the shorter list
    assert run["state"] == "needs_input"
    assert [m["name"] for m in run["missing_env"]] == ["QA_ADMIN_EMAIL", "QA_ADMIN_PASSWORD"]
    r = api.post(url, headers=ADMIN, json={"values": {
        "QA_ADMIN_EMAIL": {"value": values["QA_ADMIN_EMAIL"], "secret": False},
        "QA_ADMIN_PASSWORD": {"value": values["QA_ADMIN_PASSWORD"]}}})
    run = r.json()["run"]
    assert run["state"] == "proving" and run["missing_env"] == []
    with api.S() as db:
        assert vault.values(db, api.settings, "demo") == values
    detail = decisions(api)
    assert detail[-1]["names"] == ["QA_ADMIN_EMAIL", "QA_ADMIN_PASSWORD"]
    assert detail[-1]["secret"] == ["QA_ADMIN_PASSWORD"]
    assert not any(v in json.dumps(detail) for v in values.values())
    # not waiting any more; a bad name
    assert api.post(url, headers=ADMIN, json=body).status_code == 409
    # an empty body is refused; one active run per project
    with api.S() as db:
        setup.transition(db, run_id, "proving", state="failed")
    other = put_run(api, "needs_input")
    r = api.post(f"{BASE}/{other}/env", headers=ADMIN, json={"values": {}})
    assert r.status_code == 422
    r = api.post(f"{BASE}/{other}/env", headers=ADMIN,
                 json={"values": {"PATH": {"value": "x"}}})
    assert r.status_code == 422


def test_approve_only_from_ready_bumps_the_version_and_sets_qa_mode(api):
    with api.S() as db:
        runbook.save(db, "demo", runbook.Runbook.model_validate({"apps": []}), "old-admin")
        db.add(AwakProject(slug="demo", merge_mode="approve", qa_mode="gates"))
        db.commit()
    proving = put_run(api, "proving")
    assert api.post(f"{BASE}/{proving}/approve", headers=ADMIN).status_code == 409
    ready = put_run(api, "ready")
    assert api.post(f"{BASE}/{ready}/approve", headers=MEMBER).status_code == 403
    r = api.post(f"{BASE}/{ready}/approve", headers=ADMIN, json={"qa_mode": "browser"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["run"]["state"] == "approved" and body["qa_mode"] == "browser"
    assert body["runbook"]["version"] == 2 and body["runbook"]["approved_by"].startswith("pm")
    assert body["runbook"]["runbook"]["qa"]["service"] == "web"
    with api.S() as db:
        assert db.get(AwakProject, "demo").qa_mode == "browser"
    assert decisions(api)[-1] == {"op": "approve", "run_id": ready, "version": 2,
                                  "qa_mode": "browser"}
    assert api.post(f"{BASE}/{ready}/approve", headers=ADMIN).status_code == 409
    # without qa_mode the mode stays; a run of another project is not found
    again = put_run(api, "ready")
    body = api.post(f"{BASE}/{again}/approve", headers=ADMIN).json()
    assert body["runbook"]["version"] == 3 and body["qa_mode"] == "browser"
    assert api.post(f"/projects/other/agent/setup/{again}/approve",
                    headers=ADMIN).status_code in (403, 404)


def test_approve_refuses_a_qa_mode_the_runbook_cannot_run(api):
    spec = copy.deepcopy(RB)
    spec.pop("qa")
    with api.S() as db:
        run = AwakSetupRun(project_slug="demo", state="ready", proposal={"runbook": spec})
        db.add(run)
        db.commit()
        run_id = run.id
    r = api.post(f"{BASE}/{run_id}/approve", headers=ADMIN, json={"qa_mode": "browser"})
    assert r.status_code == 422 and "qa section" in r.text
    assert api.get(f"{BASE}/latest", headers=ADMIN).json()["run"]["state"] == "ready"


def test_cancel_brings_services_down_first(api):
    run_id = put_run(api, "proving")
    assert api.post(f"{BASE}/{run_id}/cancel", headers=MEMBER).status_code == 403
    r = api.post(f"{BASE}/{run_id}/cancel", headers=ADMIN)
    assert r.status_code == 200 and r.json()["run"]["state"] == "cancelled"
    assert api.svc.ops("svc_down") == [{"project": "demo-setup"}]
    assert api.post(f"{BASE}/{run_id}/cancel", headers=ADMIN).status_code == 409
    assert decisions(api)[-1] == {"op": "cancel", "run_id": run_id}
    # a new run may start now
    assert api.post(BASE, headers=ADMIN).status_code == 202


def test_screenshot_is_served_only_from_the_setup_folder(api, tmp_path):
    root = setup.setup_root(api.settings, "demo")
    (root / "kemudi" / ".qa" / "setup").mkdir(parents=True)
    (root / "kemudi" / ".qa" / "setup" / "home.png").write_bytes(PNG)
    good = put_run(api, "ready", screenshot="kemudi/.qa/setup/home.png")
    r = api.get(f"{BASE}/{good}/screenshot", headers=MEMBER)
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.content == PNG
    outside = Path(api.settings.workspace_dir) / "demo" / "secret.png"
    outside.write_bytes(PNG)
    (root / "kemudi" / "notpng.png").write_bytes(b"hello")
    for path in ("../secret.png", "kemudi/../../secret.png", "kemudi/notpng.png",
                 "kemudi/.qa/setup/missing.png", ""):
        bad = put_run(api, "ready", screenshot=path)
        assert api.get(f"{BASE}/{bad}/screenshot", headers=MEMBER).status_code == 404, path
    if hasattr(os, "symlink"):
        link = root / "kemudi" / "link.png"
        try:
            link.symlink_to(outside)
        except OSError:
            return  # no symlink rights (Windows)
        bad = put_run(api, "ready", screenshot="kemudi/link.png")
        assert api.get(f"{BASE}/{bad}/screenshot", headers=MEMBER).status_code == 404


# --- review fixes: confirmation, scans, fairness, supersede, failures, cost ---------


def as_admin():
    from kemudi_ai.auth import TaigaUser

    return TaigaUser(id=1, username="pm", token=made_value())


def fill(sessions, settings, run_id, values=None, confirm=False):
    """POST /setup/{id}/env, through the API function, on the worker's database."""
    from kemudi_ai.awak import agent_api

    body = agent_api.SetupEnvIn(values={k: agent_api.SetupEnvValue(value=v)
                                        for k, v in (values or {}).items()},
                                confirm=confirm)
    with sessions() as db:
        return agent_api.fill_setup_env("kemudi", run_id, body, user=as_admin(), db=db,
                                        settings=settings)["run"]


def test_saved_values_wait_for_an_admins_confirmation(tmp_path, repo, project_host):
    w, sessions, settings, runner, _, run_id, _ = make(tmp_path, repo, confirmed=False)
    assert drive(w, sessions, run_id) == ["queued", "reading", "needs_input"]
    run = run_of(sessions, run_id)
    assert run.missing_env == []
    by = {c["name"]: c for c in run.confirm_env}
    assert set(by) == {"JWT_SECRET_KEY", "QA_ADMIN_EMAIL", "QA_ADMIN_PASSWORD"}
    assert by["JWT_SECRET_KEY"] == {"name": "JWT_SECRET_KEY", "secret": True,
                                    "used_in": ["services.api.env"]}
    assert by["QA_ADMIN_PASSWORD"]["used_in"] == ["init[0]", "qa.env", "qa.login"]
    # nothing ran with them
    assert "svc_up" not in w.svc.order and "screenshot" not in runner.order
    assert setup.SetupRunner(w).next_run() is None
    out = fill(sessions, settings, run_id, confirm=True)
    assert out["state"] == "proving" and out["confirm_env"] == []
    assert out["confirmed_env"] == ["JWT_SECRET_KEY", "QA_ADMIN_EMAIL", "QA_ADMIN_PASSWORD"]
    assert drive(w, sessions, run_id)[-1] == "ready"
    with sessions() as db:
        last = (db.query(Decision).filter_by(action="awak_setup")
                .order_by(Decision.id.desc()).first())
    assert last.detail["confirmed"] == ["JWT_SECRET_KEY", "QA_ADMIN_EMAIL", "QA_ADMIN_PASSWORD"]


def test_a_later_proposal_wiring_another_saved_value_asks_again(tmp_path, repo, project_host):
    more = copy.deepcopy(RB)
    more["services"][0]["env"] = [*RB["services"][0]["env"], "SENTRY_DSN"]
    more["env"] = [*RB["env"], {"name": "SENTRY_DSN", "secret": True}]
    health = [{"ok": False, "error": "down"}]
    w, sessions, settings, _, agent, run_id, _ = make(tmp_path, repo, replies=[RB, more],
                                                      health=health)
    with sessions() as db:
        vault.put(db, settings, "kemudi", "SENTRY_DSN", made_value(), True, "pm")
    seen = drive(w, sessions, run_id)
    assert seen == ["queued", "reading", "proving", "reading", "needs_input"]
    run = run_of(sessions, run_id)
    assert run.confirm_env == [{"name": "SENTRY_DSN", "secret": True,
                                "used_in": ["services.api.env"]}]
    assert fill(sessions, settings, run_id, confirm=True)["state"] == "proving"
    assert drive(w, sessions, run_id)[-1] == "ready"


def test_values_typed_in_the_run_count_as_confirmed(tmp_path, repo, project_host):
    w, sessions, settings, _, _, run_id, _ = make(tmp_path, repo, fill=False, confirmed=False)
    drive(w, sessions, run_id)
    run = run_of(sessions, run_id)
    assert len(run.missing_env) == 3 and run.confirm_env == []
    out = fill(sessions, settings, run_id, creds())
    assert out["state"] == "proving" and out["confirm_env"] == []
    # a value saved elsewhere meanwhile (not typed here) is asked about before the proof
    with sessions() as db:
        vault.put(db, settings, "kemudi", "JWT_SECRET_KEY", made_value(), True, "pm")
        run = db.get(AwakSetupRun, run_id)
        run.confirmed_env = ["QA_ADMIN_EMAIL", "QA_ADMIN_PASSWORD"]
        db.commit()
    w.tick()
    run = run_of(sessions, run_id)
    assert run.state == "needs_input"
    assert [c["name"] for c in run.confirm_env] == ["JWT_SECRET_KEY"]


def test_the_proof_gets_only_the_wired_values(tmp_path, repo, project_host):
    w, sessions, settings, _, _, run_id, _ = make(tmp_path, repo)
    other = made_value()
    with sessions() as db:
        vault.put(db, settings, "kemudi", "UNRELATED_TOKEN", other, True, "pm")
    seen_values = []
    real = setup.checks.Compose

    def spy(rb, svc, run, projects, path, values, *a, **k):
        seen_values.append(dict(values))
        return real(rb, svc, run, projects, path, values, *a, **k)

    setup.checks.Compose = spy
    try:
        assert drive(w, sessions, run_id)[-1] == "ready"
    finally:
        setup.checks.Compose = real
    assert set(seen_values[0]) == {"JWT_SECRET_KEY", "QA_ADMIN_EMAIL", "QA_ADMIN_PASSWORD"}


def test_the_secret_scan_sees_values_json_would_escape(tmp_path, repo, project_host):
    value = 'q"' + made_value() + '\\é'
    leaky = copy.deepcopy(RB)
    leaky["apps"][0]["env"]["API_TOKEN"] = value
    w, sessions, settings, _, agent, run_id, _ = make(tmp_path, repo, replies=[leaky, RB])
    with sessions() as db:
        vault.put(db, settings, "kemudi", "API_TOKEN", value, True, "pm")
    assert drive(w, sessions, run_id)[-1] == "ready"
    assert "secret value" in agent.tasks[1] and value not in agent.tasks[1]
    # the previous runbook shown to the agent and stored is redacted string by string
    assert json.dumps(value)[1:-1] not in agent.tasks[1]
    assert not any(value in x for x in setup._strings(run_of(sessions, run_id).proposal))


def test_a_secret_value_in_a_key_is_refused(tmp_path, repo, project_host):
    value = made_value()
    leaky = copy.deepcopy(RB)
    leaky["apps"][0]["env"][value] = "x"
    w, sessions, settings, _, agent, run_id, _ = make(tmp_path, repo, replies=[leaky, RB])
    with sessions() as db:
        vault.put(db, settings, "kemudi", "API_TOKEN", value, True, "pm")
    assert drive(w, sessions, run_id)[-1] == "ready"
    assert "secret value" in agent.tasks[1] and value not in agent.tasks[1]


def test_a_plain_vault_value_is_neither_refused_nor_redacted(tmp_path, repo, project_host):
    spec = copy.deepcopy(RB)
    spec["apps"][0]["env"]["APP_ENV"] = "development-mode"
    shots = [{"infra_error": "web: APP_ENV is development-mode", "processes": []}]
    w, sessions, settings, _, agent, run_id, _ = make(tmp_path, repo, replies=[spec],
                                                      shots=shots)
    with sessions() as db:
        vault.put(db, settings, "kemudi", "APP_ENV", "development-mode", False, "pm")
    assert drive(w, sessions, run_id)[-1] == "ready"
    run = run_of(sessions, run_id)
    assert run.round == 2 and "secret value" not in agent.tasks[1]
    assert "APP_ENV is development-mode" in agent.tasks[1]
    assert run.proposal["runbook"]["apps"][0]["env"]["APP_ENV"] == "development-mode"


def test_a_runbook_json_folder_goes_back_to_the_agent(tmp_path, repo, project_host):
    class FolderAgent(SetupAgent):
        def run(self, purpose, model, system, task, slug="", role_id=None):
            if not self.tasks:
                self.tasks.append(task)
                root = Path(task.splitlines()[0].removeprefix("Workspace: ").strip())
                (root / "runbook.json" / "x").mkdir(parents=True)
                return "made a folder", 1.0
            return super().run(purpose, model, system, task, slug, role_id)

    w, sessions, _, _, _, run_id, _ = make(tmp_path, repo)
    agent = w.agent = FolderAgent([RB])
    seen = drive(w, sessions, run_id)
    assert seen[-1] == "ready" and "is a folder" in agent.tasks[1]
    assert run_of(sessions, run_id).proposal.get("infra_errors", 0) == 0


def test_a_runner_without_the_screenshot_op_fails_the_run(tmp_path, repo, project_host):
    from kemudi_ai.awak.runner import RunnerUnknownOp

    class OldRunner(SetupRunner):
        def call(self, op, **payload):
            if op == "screenshot":
                raise RunnerUnknownOp("the runner has no `screenshot` op")
            return super().call(op, **payload)

    w, sessions, _, runner, agent, run_id, _ = make(tmp_path, repo)
    w.runner = OldRunner(tmp_path / "ws", runner.order)
    assert drive(w, sessions, run_id)[-1] == "failed"
    run = run_of(sessions, run_id)
    assert "kemudi-runner image" in run.error and run.round == 1 and len(agent.tasks) == 1
    assert w.svc.order.count("svc_down") == 1  # the services still came down


def test_the_http_runner_reports_an_unknown_op():
    import httpx

    from kemudi_ai.awak.runner import HttpRunner, RunnerUnknownOp

    r = HttpRunner("http://runner", made_value(), transport=httpx.MockTransport(
        lambda req: httpx.Response(404, json={"error": "unknown op"})))
    with pytest.raises(RunnerUnknownOp):
        r.call("screenshot")


def test_a_failed_agent_turn_still_counts_its_cost(tmp_path, repo, project_host):
    from kemudi_ai.awak.agent import AgentError

    class Broken(SetupAgent):
        def run(self, *a, **k):
            if not self.tasks:
                self.tasks.append("")
                raise AgentError("provider down", cost_idr=5.0)
            return super().run(*a, **k)

    w, sessions, _, _, _, run_id, _ = make(tmp_path, repo)
    w.agent = Broken([RB])
    drive(w, sessions, run_id, until=("reading",))
    w.tick()
    run = run_of(sessions, run_id)
    assert run.state == "reading" and "retrying" in run.error and run.cost_idr == 5.0
    with sessions() as db:
        db.get(AwakSetupRun, run_id).not_before = None
        db.commit()
    assert drive(w, sessions, run_id)[-1] == "ready"
    assert run_of(sessions, run_id).cost_idr == 12.0


def test_cancel_through_the_api_during_the_proof(tmp_path, repo, project_host):
    from kemudi_ai.awak import agent_api

    holder = {}

    def cancel():
        with holder["sessions"]() as db:
            out = agent_api.cancel_setup("kemudi", holder["id"], user=as_admin(), db=db,
                                         svc=holder["svc"])
        holder["out"] = out["run"]

    w, sessions, _, _, _, run_id, _ = make(tmp_path, repo, on_shot=cancel)
    holder.update(sessions=sessions, id=run_id, svc=w.svc)
    drive(w, sessions, run_id, until=("cancelled",))
    assert holder["out"]["state"] == "cancelled"
    run = run_of(sessions, run_id)
    assert run.state == "cancelled" and run.screenshot == ""
    # the API brought the project down, and so did the proof on its way out
    assert w.svc.order.count("svc_down") == 2


def test_one_active_run_per_project_in_the_database(tmp_path):
    from kemudi_ai.store import make_session

    sessions = make_session("sqlite:///:memory:")
    with sessions() as db:
        first = setup.start(db, "demo", "pm")
        assert first is not None and setup.start(db, "demo", "pm") is None
        assert setup.start(db, "other", "pm") is not None
        db.add(AwakSetupRun(project_slug="demo", state="needs_input"))
        with pytest.raises(Exception):
            db.commit()
        db.rollback()
        setup.transition(db, first.id, "queued", state="failed")
        assert setup.start(db, "demo", "pm") is not None


def test_a_run_of_another_project_is_not_found(api):
    run_id = put_run(api, "needs_input")
    other = f"/projects/other/agent/setup/{run_id}"
    assert api.post(f"{other}/env", headers=ADMIN,
                    json={"values": {}, "confirm": True}).status_code == 404
    assert api.post(f"{other}/approve", headers=ADMIN).status_code == 404
    assert api.post(f"{other}/cancel", headers=ADMIN).status_code == 404
    assert api.get(f"{other}/screenshot", headers=MEMBER).status_code == 404
    with api.S() as db:
        assert db.get(AwakSetupRun, run_id).state == "needs_input"
    assert api.svc.ops("svc_down") == []


def test_confirm_over_http_lets_the_proof_use_saved_values(api):
    values = creds()
    with api.S() as db:
        for k, v in values.items():
            vault.put(db, api.settings, "demo", k, v, k != "QA_ADMIN_EMAIL", "pm")
    shown = [{"name": "JWT_SECRET_KEY", "secret": True, "used_in": ["services.api.env"]}]
    run_id = put_run(api, "needs_input", confirm_env=shown)
    url = f"{BASE}/{run_id}/env"
    assert api.post(url, headers=MEMBER, json={"confirm": True}).status_code == 403
    member = api.get(f"{BASE}/latest", headers=MEMBER).json()["run"]
    assert member["confirm_env"] == shown
    # a confirmation covers what the run listed, nothing more
    r = api.post(url, headers=ADMIN, json={"confirm": True})
    run = r.json()["run"]
    assert run["state"] == "needs_input" and run["confirmed_env"] == ["JWT_SECRET_KEY"]
    assert [c["name"] for c in run["confirm_env"]] == ["QA_ADMIN_EMAIL", "QA_ADMIN_PASSWORD"]
    assert run["confirm_env"][0]["secret"] is False
    r = api.post(url, headers=ADMIN, json={"values": {}, "confirm": True})
    assert r.status_code == 200, r.text
    run = r.json()["run"]
    assert run["state"] == "proving" and run["confirm_env"] == [] and run["missing_env"] == []
    assert run["confirmed_env"] == ["JWT_SECRET_KEY", "QA_ADMIN_EMAIL", "QA_ADMIN_PASSWORD"]
    assert [d["confirmed"] for d in decisions(api)] == [
        ["JWT_SECRET_KEY"], ["QA_ADMIN_EMAIL", "QA_ADMIN_PASSWORD"]]


def test_values_without_confirm_leave_saved_ones_unconfirmed(api):
    values = creds()
    with api.S() as db:
        vault.put(db, api.settings, "demo", "JWT_SECRET_KEY", values["JWT_SECRET_KEY"], True,
                  "pm")
    run_id = put_run(api, "needs_input")
    r = api.post(f"{BASE}/{run_id}/env", headers=ADMIN, json={"values": {
        "QA_ADMIN_EMAIL": {"value": values["QA_ADMIN_EMAIL"], "secret": False},
        "QA_ADMIN_PASSWORD": {"value": values["QA_ADMIN_PASSWORD"]}}})
    run = r.json()["run"]
    assert run["state"] == "needs_input" and run["missing_env"] == []
    assert [c["name"] for c in run["confirm_env"]] == ["JWT_SECRET_KEY"]
    assert run["confirmed_env"] == ["QA_ADMIN_EMAIL", "QA_ADMIN_PASSWORD"]


def test_a_new_run_or_an_approval_supersedes_ready_runs(api):
    old = put_run(api, "ready")
    r = api.post(BASE, headers=ADMIN)
    assert r.status_code == 202
    with api.S() as db:
        assert db.get(AwakSetupRun, old).state == "superseded"
    r = api.post(f"{BASE}/{old}/approve", headers=ADMIN)
    assert r.status_code == 409 and "superseded" in r.text
    assert api.post(f"{BASE}/{old}/cancel", headers=ADMIN).status_code == 409
    # approving one ready run supersedes another
    with api.S() as db:
        for run in db.query(AwakSetupRun).filter(AwakSetupRun.state == "queued"):
            run.state = "failed"
        db.commit()
    a, b = put_run(api, "ready"), put_run(api, "ready")
    assert api.post(f"{BASE}/{b}/approve", headers=ADMIN).status_code == 200
    with api.S() as db:
        assert db.get(AwakSetupRun, a).state == "superseded"
        assert db.get(AwakSetupRun, b).state == "approved"
    out = api.get(f"{BASE}/latest", headers=ADMIN).json()["run"]
    assert out["state"] == "approved" and not out["active"]


def test_members_see_no_compose_environment_values(api):
    spec = copy.deepcopy(RB)
    spec["services"][0]["environment"] = {"backend": {"FLASK_ENV": "plain-but-hidden"}}
    with api.S() as db:
        db.add(AwakSetupRun(project_slug="demo", state="ready", proposal={"runbook": spec}))
        db.commit()
    member = api.get(f"{BASE}/latest", headers=MEMBER).json()["run"]
    assert "plain-but-hidden" not in json.dumps(member)
    assert member["proposal"]["runbook"]["services"][0]["environment"] == {
        "backend": {"FLASK_ENV": runbook.MASK}}
    admin = api.get(f"{BASE}/latest", headers=ADMIN).json()["run"]
    assert admin["proposal"]["runbook"]["services"][0]["environment"]["backend"] == {
        "FLASK_ENV": "plain-but-hidden"}


def test_the_setup_folder_belongs_to_the_agent_uid(tmp_path, monkeypatch):
    # the orchestrator runs as root; the agent (awak uid) writes runbook.json there
    calls = []
    monkeypatch.setattr(setup.os, "geteuid", lambda: 0, raising=False)
    monkeypatch.setattr(setup.os, "chown", lambda p, u, g: calls.append((Path(p), u, g)),
                        raising=False)
    d = tmp_path / "setup"
    d.mkdir()
    setup._own(d, 10000)
    assert calls == [(d, 10000, 10000)]
