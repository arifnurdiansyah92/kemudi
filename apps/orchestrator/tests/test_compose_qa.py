"""Stage 1b: compose services, init/seed, run_in gates, qa.login and qa.env
(runbook schema, the worker's and the merge's QA and gates with kemudi-svc)."""

import copy
import secrets as pysecrets

import pytest

from kemudi_ai.awak import checks, runbook, vault
from kemudi_ai.awak.svc import SvcError
from kemudi_ai.store import AwakEvent, AwakJob, AwakProject

from .awak_fakes import FakeAgent, FakeRunner
from .conftest import SECRET_KEY
from .test_awak import DESC, host, repo  # noqa: F401 (fixtures)
from .test_vault import _worker, made_value

URL = "http://kemudi-dind:32768"

# playfast's shape (frontend/ Next.js, backend/ Flask in compose with
# postgres and redis), on the test repo "kemudi".
ENV = [{"name": "JWT_SECRET_KEY", "secret": True, "required": True},
       {"name": "QA_ADMIN_EMAIL", "required": True},
       {"name": "QA_ADMIN_PASSWORD", "secret": True, "required": True},
       {"name": "MIDTRANS_SERVER_KEY", "secret": True}]
RB = {
    "apps": [
        {"name": "web", "repo": "kemudi", "dir": "",
         "install": ["npm ci --ignore-scripts"],
         "checks": ["npx --no-install tsc --noEmit"],
         "env": {"INTERNAL_API_URL": "{services.api.url}"}},
    ],
    "services": [
        {"name": "api", "kind": "compose", "repo": "kemudi", "file": "docker-compose.yml",
         "compose_services": ["postgres", "redis", "backend"], "expose": "backend:5000",
         "health": "/api/health", "env": ["JWT_SECRET_KEY", "MIDTRANS_SERVER_KEY"],
         "ready_timeout": 90},
        {"name": "web", "kind": "process", "app": "web",
         "command": "npx --no-install next dev --port {port}", "health": "/"},
    ],
    "env": ENV,
    "init": [{"service": "api:backend", "command": "python scripts/init_qa.py",
              "env": ["QA_ADMIN_EMAIL", "QA_ADMIN_PASSWORD"]}],
    "seed": {"service": "api", "command": "python scripts/seed_campaigns.py"},
    "qa": {"service": "web", "env": ["QA_ADMIN_EMAIL", "QA_ADMIN_PASSWORD"],
           "login": {"path": "/login",
                     "fields": {"input[type=email]": "{env.QA_ADMIN_EMAIL}",
                                "input[type=password]": "{env.QA_ADMIN_PASSWORD}"},
                     "submit": "button[type=submit]", "success_url": "/store"}},
}
RUN_IN_APP = {"name": "api", "repo": "kemudi", "dir": "", "run_in": "api:backend",
              "checks": ["python -m pytest -q tests", "python -m flake8 app"]}


def problems(data, repos=("kemudi",)):
    rb, errs = runbook.validate(data, set(repos))
    assert (rb is None) == bool(errs)
    return "\n".join(errs)


def parsed(data=RB) -> runbook.Runbook:
    rb, errs = runbook.validate(data, {"kemudi"})
    assert errs == [], errs
    return rb


class FakeSvc:
    """kemudi-svc: `up`/`exec` entries are replies, else a healthy default.
    Every op goes to the shared `order` (svc_exec with its argv)."""

    def __init__(self, order=None, up=None, exec=None, fail=None):
        self.order = order if order is not None else []
        self.up, self.exec = list(up or []), list(exec or [])
        self.fail = fail
        self.calls: list[tuple[str, dict]] = []

    def call(self, op, **payload):
        if self.fail:
            raise self.fail
        self.calls.append((op, payload))
        self.order.append(f"svc_exec:{' '.join(payload['argv'])}" if op == "svc_exec" else op)
        if op == "svc_up":
            if self.up:
                return self.up.pop(0)
            return {"ok": True, "project": payload["project"], "services": payload["services"],
                    "built": ["backend"], "url": URL if "expose" in payload else None,
                    "logs_tail": "backend | listening"}
        if op == "svc_exec":
            return self.exec.pop(0) if self.exec else {"ok": True, "exit": 0, "output": "ok"}
        if op == "svc_logs":
            return {"ok": True, "logs": "backend | Traceback: no table users"}
        return {"ok": True}

    def ops(self, op):
        return [p for o, p in self.calls if o == op]


class Runner(FakeRunner):
    def __init__(self, workspace, order, health=None, **kw):
        super().__init__(workspace, **kw)
        self.order, self.health = order, list(health or [])

    def call(self, op, **payload):
        self.order.append(op)
        if op == "health":
            self.calls.append(op)
            self.payloads.append((op, payload))
            return self.health.pop(0) if self.health else {"ok": True, "waited": 1}
        return super().call(op, **payload)


def creds():
    return {"JWT_SECRET_KEY": made_value(), "QA_ADMIN_EMAIL": f"qa-{pysecrets.token_hex(4)}@x.test",
            "QA_ADMIN_PASSWORD": made_value()}


def setup(tmp_path, repo, spec=RB, qa=("pass",), qa_mode="browser", health=None, **svc_kw):
    order: list[str] = []
    runner = Runner(tmp_path / "ws", order, qa=list(qa), health=health)
    agent = FakeAgent()
    w, taiga, sessions, settings = _worker(tmp_path, repo, agent, runner)
    w.svc = FakeSvc(order, **svc_kw)
    w._seed()
    values = creds()
    with sessions() as db:
        runbook.save(db, "kemudi", parsed(spec), "pm")
        for k, v in values.items():
            vault.put(db, settings, "kemudi", k, v, True, "pm")
        p = db.get(AwakProject, "kemudi")
        p.qa_mode, p.merge_mode = qa_mode, "approve"
        db.commit()
    taiga.add(1, 12, "Badge jumlah", DESC)
    return w, taiga, sessions, runner, agent, order, values


def events(sessions, kind):
    with sessions() as db:
        return [e.detail for e in db.query(AwakEvent).filter_by(kind=kind).order_by(AwakEvent.id)]


# --- schema ---------------------------------------------------------------------------


def test_playfast_compose_runbook_is_valid():
    rb = parsed({**RB, "apps": [*RB["apps"], RUN_IN_APP]})
    assert rb.browser_qa_ready()
    assert [s.name for s in rb.qa_compose()] == ["api"]
    assert rb.target("api") == (rb.service("api"), "backend")
    assert rb.target("api:postgres")[1] == "postgres"
    assert rb.target("web") is None


@pytest.mark.parametrize("change, needle", [
    (lambda r: r["apps"][0]["env"].update(TOKEN="{env.JWT_SECRET_KEY}"), "only allowed in qa.login"),
    (lambda r: r["init"][0].update(command="python x.py {env.QA_ADMIN_EMAIL}"), "only allowed"),
    (lambda r: r["services"][0].update(compose_services=[]), "compose_services"),
    (lambda r: r["services"][0].update(compose_services=["a b"]), "not a compose service name"),
    (lambda r: r["services"][0].update(expose="frontend:3000"), "not in compose_services"),
    (lambda r: r["services"][0].update(expose="backend"), "expose must be"),
    (lambda r: r["services"][0].update(expose="backend:70000"), "expose must be"),
    (lambda r: r["services"][0].update(expose=""), "has no expose"),
    (lambda r: r["services"][0].update(env=["NOT_DECLARED"]), "not declared"),
    (lambda r: r["services"][0].update(env={"X": "1"}), "lists env names"),
    (lambda r: r["services"][0].update(command="python x"), "only for a process service"),
    (lambda r: r["services"][1].update(expose="web:3000"), "only for a compose service"),
    (lambda r: r["services"].reverse(), "must come before"),
    (lambda r: r["init"][0].update(service="web:backend"), "not a compose service"),
    (lambda r: r["init"][0].update(service="api:frontend"), "not one of api's"),
    (lambda r: r["init"][0].update(env=["NOPE"]), "not declared"),
    (lambda r: r["init"][0].update(command="python 'x"), "cannot parse"),
    (lambda r: r.update(seed={"service": "web", "command": "x"}), "compose service"),
    (lambda r: r["qa"].update(service="api"), "must be a process service"),
    (lambda r: r["qa"].update(env=["NOPE"]), "not declared"),
    (lambda r: r["qa"]["login"]["fields"].update({"#otp": "{env.NOPE}"}), "not declared"),
    (lambda r: r["qa"]["login"].update(path="login"), "qa.login.path"),
    (lambda r: r["qa"]["login"].update(success_url="store"), "success_url"),
    (lambda r: r["qa"]["login"].update(fields={}), "fields"),
    (lambda r: r["qa"]["login"].update(submit=""), "CSS selector"),
    (lambda r: r["apps"].append({**RUN_IN_APP, "run_in": "api"}), "run_in must be"),
    (lambda r: r["apps"].append({**RUN_IN_APP, "run_in": "web:backend"}), "not a compose"),
    (lambda r: r["apps"].append({**RUN_IN_APP, "run_in": "api:nginx"}), "not one of api's"),
    (lambda r: r["apps"].append({**RUN_IN_APP, "install": ["pip install -r x"]}),
     "has no install"),
    (lambda r: r["services"][1].update(app="api") or r["apps"].append(RUN_IN_APP),
     "process service needs an app the runner can start"),
])
def test_compose_runbook_rejects(change, needle):
    rb = copy.deepcopy(RB)
    change(rb)
    assert needle in problems(rb)


def test_qa_env_cannot_shadow_the_runners_own_names():
    rb = copy.deepcopy(RB)
    rb["env"].append({"name": "QA_BASE_URL"})
    rb["qa"]["env"].append("QA_BASE_URL")
    assert "set by the runner itself" in problems(rb)


def test_run_in_app_must_share_the_compose_service_repo():
    rb = copy.deepcopy(RB)
    rb["apps"].append({**RUN_IN_APP, "repo": "other"})
    assert "builds from repo kemudi, not the app's repo other" in problems(rb, ("kemudi", "other"))


def test_existing_process_only_runbooks_stay_valid():
    from .test_runbook import KEMUDI_RB, PLAYFAST, REPOS

    assert runbook.validate(PLAYFAST, REPOS)[1] == []
    assert runbook.validate(KEMUDI_RB, {"kemudi"})[1] == []


# --- placeholders, plan, masking ------------------------------------------------------


def test_login_placeholders_resolve_from_the_vault_only():
    rb = parsed()
    v = creds()
    body = checks.login_payload(rb, v)
    assert body == {"path": "/login", "submit": "button[type=submit]", "success_url": "/store",
                    "fields": [{"selector": "input[type=email]", "value": v["QA_ADMIN_EMAIL"]},
                               {"selector": "input[type=password]",
                                "value": v["QA_ADMIN_PASSWORD"]}]}
    with pytest.raises(checks.ServiceFailed, match="QA_ADMIN_PASSWORD") as e:
        checks.login_payload(rb, {"QA_ADMIN_EMAIL": v["QA_ADMIN_EMAIL"]})
    assert not e.value.infra
    # optional names without a value are left out; required ones stop the run
    assert checks.vault_env(rb, ["JWT_SECRET_KEY", "MIDTRANS_SERVER_KEY"], v, "x") == {
        "JWT_SECRET_KEY": v["JWT_SECRET_KEY"]}
    with pytest.raises(checks.ServiceFailed, match="JWT_SECRET_KEY"):
        checks.vault_env(rb, ["JWT_SECRET_KEY"], {}, "services.api")


def test_qa_plan_with_compose_services():
    plan = checks.qa_plan(parsed())
    assert [s["name"] for s in plan["services"]] == ["web"]  # compose is not the runner's
    assert plan["services"][0]["env"] == {"INTERNAL_API_URL": "{services.api.url}"}
    assert plan["compose"] == ["api"]
    [init] = plan["init"]
    assert (init["service"], init["compose_service"], init["argv"]) == (
        "api", "backend", ["python", "scripts/init_qa.py"])
    assert plan["seed"]["compose_service"] == "backend"  # the exposed service by default
    assert plan["qa_env"] == ["QA_ADMIN_EMAIL", "QA_ADMIN_PASSWORD"]
    assert plan["login"]["path"] == "/login"
    assert checks.qa_repos(parsed()) == ["kemudi"]


def test_literal_login_values_are_masked_and_redacted():
    rb = copy.deepcopy(RB)
    literal = "qa-" + pysecrets.token_hex(6)
    rb["qa"]["login"]["fields"]["input[name=user]"] = literal
    spec = parsed(rb).model_dump(mode="json")
    fields = runbook.masked(spec)["qa"]["login"]["fields"]
    assert fields["input[name=user]"] == runbook.MASK
    assert fields["input[type=email]"] == "{env.QA_ADMIN_EMAIL}"
    assert literal in runbook.env_values(parsed(rb))


def test_compose_project_names():
    rb = parsed()
    assert checks.compose_projects(rb, "playfast", "us12") == {"api": "playfast-us12"}
    two = copy.deepcopy(RB)
    two["services"].insert(0, {**RB["services"][0], "name": "mail", "expose": "",
                               "compose_services": ["mailpit"], "env": []})
    assert checks.compose_projects(parsed(two), "pf", "us3") == {"mail": "pf-us3-mail",
                                                                  "api": "pf-us3-api"}
    long = checks.compose_projects(rb, "a" * 70, "us1")["api"]
    assert len(long) <= 63 and long != checks.compose_projects(rb, "a" * 71, "us1")["api"]
    assert checks.compose_projects(None, "pf", "us1") == {}


def test_compose_for_qa_downs_what_it_started_when_the_body_fails():
    svc = FakeSvc()
    compose = checks.Compose(parsed(), svc.call, lambda op, **b: {"ok": True},
                             {"api": "pf-us1"}, lambda repo: f"pf/us-1/{repo}", creds(), [])
    with pytest.raises(RuntimeError):
        with compose.for_qa(checks.qa_plan(parsed())) as urls:
            assert urls == {"api": URL}
            raise RuntimeError("qa crashed")
    assert svc.order[-1] == "svc_down" and svc.ops("svc_down") == [{"project": "pf-us1"}]


# --- worker: browser QA ---------------------------------------------------------------


def test_browser_qa_runs_up_init_seed_health_qa_down_in_order(tmp_path, repo):
    w, taiga, sessions, runner, agent, order, v = setup(tmp_path, repo)
    w.tick()
    assert taiga.status_of(1) == "done", taiga.texts(1)
    start = order.index("svc_up")
    assert order[start:start + 6] == [
        "svc_up", "svc_exec:python scripts/init_qa.py",
        "svc_exec:python scripts/seed_campaigns.py", "health", "qa", "svc_down"]

    [up] = w.svc.ops("svc_up")
    assert up["project"] == "kemudi-us12" and up["path"] == "kemudi/us-12/kemudi"
    assert up["services"] == ["postgres", "redis", "backend"] and up["expose"] == "backend:5000"
    assert up["env"] == {"JWT_SECRET_KEY": v["JWT_SECRET_KEY"]}  # MIDTRANS_* not set: left out
    assert v["JWT_SECRET_KEY"] in up["redact"] and v["QA_ADMIN_PASSWORD"] in up["redact"]
    init, seed = w.svc.ops("svc_exec")
    assert (init["project"], init["service"]) == ("kemudi-us12", "backend")
    assert init["env"] == {"QA_ADMIN_EMAIL": v["QA_ADMIN_EMAIL"],
                           "QA_ADMIN_PASSWORD": v["QA_ADMIN_PASSWORD"]}
    assert seed["env"] == {} and seed["timeout"] == 600
    health = next(b for op, b in runner.payloads if op == "health")
    assert health == {"url": URL, "path": "/api/health", "timeout": 90}

    qa = next(b for op, b in runner.payloads if op == "qa")
    assert qa["external"] == {"api": URL}
    assert [s["name"] for s in qa["services"]] == ["web"]
    assert qa["services"][0]["env"]["INTERNAL_API_URL"] == "{services.api.url}"
    assert qa["login"]["fields"][1] == {"selector": "input[type=password]",
                                        "value": v["QA_ADMIN_PASSWORD"]}
    assert qa["spec_env"] == {"QA_ADMIN_EMAIL": v["QA_ADMIN_EMAIL"],
                              "QA_ADMIN_PASSWORD": v["QA_ADMIN_PASSWORD"]}
    # the services' and processes' env never carry the spec's values
    assert v["QA_ADMIN_PASSWORD"] not in str(qa["services"])

    task = next(t for p, t in agent.calls if p == "awak.qa")
    assert "process.env.QA_ADMIN_EMAIL" in task and "process.env.QA_ADMIN_PASSWORD" in task
    assert "starts logged in" in task and "/login" in task and "Backing services (api)" in task
    for value in v.values():
        assert value not in task
    up_event = events(sessions, "compose_up")[0]
    assert up_event["project"] == "kemudi-us12" and up_event["ok"]


def test_qa_without_login_or_env_says_so(tmp_path, repo):
    spec = copy.deepcopy(RB)
    spec["qa"] = {"service": "web"}
    w, taiga, sessions, runner, agent, order, _ = setup(tmp_path, repo, spec)
    w.tick()
    qa = next(b for op, b in runner.payloads if op == "qa")
    assert "login" not in qa and "spec_env" not in qa
    task = next(t for p, t in agent.calls if p == "awak.qa")
    assert "starts logged out" in task and "no project environment variables" in task


def test_unhealthy_compose_service_is_infra_with_logs_and_still_goes_down(tmp_path, repo):
    w, taiga, sessions, runner, agent, order, _ = setup(
        tmp_path, repo, health=[{"ok": False, "error": "no 2xx/3xx answer"}])
    w.tick()
    first = order.index("health")
    assert order[first + 1:first + 3] == ["svc_logs", "svc_down"]
    assert "qa" in order[first:]  # retried (not an attempt) and passed
    assert taiga.status_of(1) == "done"
    [failed] = events(sessions, "service_failed")
    assert failed["infra"] and "Traceback: no table users" in failed["logs"]
    note = next(t for t in taiga.texts(1) if "Gangguan lingkungan" in t)
    assert "tidak sehat di /api/health" in note and "no table users" in note


def test_failed_start_logs_reach_the_card_redacted(tmp_path, repo):
    w, taiga, sessions, runner, agent, order, v = setup(tmp_path, repo)
    w.svc.up = [{"ok": False, "stage": "up", "error": "backend exited (1)",
                 "logs_tail": f"backend | KeyError with key {v['JWT_SECRET_KEY']}"}]
    w.tick()
    assert w.svc.order.count("svc_down") == w.svc.order.count("svc_up") == 2
    text = "\n".join(taiga.texts(1))
    assert "gagal start (up)" in text and "KeyError with key" in text
    assert v["JWT_SECRET_KEY"] not in text
    assert v["JWT_SECRET_KEY"] not in str(events(sessions, "service_failed"))
    assert v["JWT_SECRET_KEY"] not in str(events(sessions, "compose_up"))


def test_failing_init_blocks_with_redacted_output(tmp_path, repo):
    w, taiga, sessions, runner, agent, order, v = setup(tmp_path, repo)
    w.svc.exec = [{"ok": False, "exit": 1,
                   "output": f"psql: password authentication failed ({v['QA_ADMIN_PASSWORD']})"}]
    w.tick()
    with sessions() as db:
        assert db.query(AwakJob).one().state == "failed"
    assert taiga.story(1)["is_blocked"]
    assert "qa" not in runner.calls and order[-1] == "svc_down"
    text = taiga.texts(1)[-1]
    assert "init `python scripts/init_qa.py`" in text and "authentication failed" in text
    assert v["QA_ADMIN_PASSWORD"] not in text
    assert v["QA_ADMIN_PASSWORD"] not in str(events(sessions, "service_failed"))


def test_login_failure_blocks_the_story(tmp_path, repo):
    w, taiga, sessions, runner, agent, order, _ = setup(
        tmp_path, repo, qa=[{"login_error": "login failed: still at /login 30 s after"}])
    w.tick()
    assert taiga.story(1)["is_blocked"] and order[-1] == "svc_down"
    assert "qa.login" in taiga.texts(1)[-1] and "still at /login" in taiga.texts(1)[-1]


def test_missing_required_vault_value_blocks_before_anything_starts(tmp_path, repo):
    w, taiga, sessions, runner, agent, order, _ = setup(tmp_path, repo)
    with sessions() as db:
        vault.delete(db, "kemudi", "QA_ADMIN_PASSWORD")
    w.tick()
    assert taiga.story(1)["is_blocked"] and "svc_up" not in order
    assert "QA_ADMIN_PASSWORD" in taiga.texts(1)[-1]


def test_svc_unreachable_is_infra(tmp_path, repo):
    w, taiga, sessions, runner, agent, order, _ = setup(tmp_path, repo)
    w.svc.fail = SvcError("svc svc_up failed: ConnectError")
    w.s.max_infra_errors = 1
    w.tick()
    assert "Gangguan lingkungan berulang" in taiga.texts(1)[-1]
    assert events(sessions, "service_failed")[0]["infra"]


def test_svc_refusal_needs_a_human(tmp_path, repo):
    from kemudi_ai.awak.svc import SvcRejected

    w, taiga, sessions, runner, agent, order, _ = setup(tmp_path, repo)
    w.svc.fail = SvcRejected("svc svc_up refused: service 'backend' uses key 'privileged'")
    w.tick()
    assert taiga.story(1)["is_blocked"] and "privileged" in taiga.texts(1)[-1]


# --- worker: run_in gates -------------------------------------------------------------


def _run_in_spec():
    spec = copy.deepcopy(RB)
    spec["apps"].append(copy.deepcopy(RUN_IN_APP))
    return spec


def test_run_in_gates_build_up_deps_exec_and_down(tmp_path, repo):
    w, taiga, sessions, runner, agent, order, v = setup(tmp_path, repo, _run_in_spec(),
                                                        qa_mode="gates")
    w.tick()
    assert taiga.status_of(1) == "done", taiga.texts(1)
    assert [o for o in order if o.startswith("svc")] == [
        "svc_up", "svc_exec:python -m pytest -q tests", "svc_exec:python -m flake8 app",
        "svc_down"]
    [up] = w.svc.ops("svc_up")
    assert up["up"] == ["postgres", "redis"] and "expose" not in up
    assert up["path"] == "kemudi/us-12/kemudi" and up["env"] == {
        "JWT_SECRET_KEY": v["JWT_SECRET_KEY"]}
    ex = w.svc.ops("svc_exec")[0]
    assert ex["service"] == "backend" and ex["timeout"] == checks.TIMEOUTS["checks"]
    assert "api: python -m pytest -q tests" in taiga.texts(1)[-1]
    # install never ran for the run_in app
    installs = [b for op, b in runner.payloads if op == "install"]
    assert all(c["argv"][0] == "npm" for b in installs for c in b["commands"])


def test_run_in_gate_failure_reworks_and_still_goes_down(tmp_path, repo):
    w, taiga, sessions, runner, agent, order, v = setup(tmp_path, repo, _run_in_spec(),
                                                        qa_mode="gates")
    w.svc.exec = [{"ok": False, "exit": 1,
                   "output": f"FAILED tests/test_x.py {v['JWT_SECRET_KEY']}"}]
    w.tick()
    assert order.index("svc_down") > order.index("svc_exec:python -m pytest -q tests")
    assert "svc_exec:python -m flake8 app" not in order[:order.index("svc_down")]
    fail = next(t for t in taiga.texts(1) if "gagal di pemeriksaan" in t)
    assert "FAILED tests/test_x.py" in fail and v["JWT_SECRET_KEY"] not in fail
    with sessions() as db:
        assert v["JWT_SECRET_KEY"] not in db.query(AwakJob).one().feedback


def test_run_in_build_failure_is_a_failed_gate(tmp_path, repo):
    w, taiga, sessions, runner, agent, order, _ = setup(
        tmp_path, repo, _run_in_spec(), qa_mode="gates",
        up=[{"ok": False, "stage": "build", "error": "build failed (exit 1)",
             "logs_tail": "ERROR: No matching distribution found for flask==9"}])
    w.tick()
    fail = next(t for t in taiga.texts(1) if "gagal di pemeriksaan" in t)
    assert "build api:backend" in fail and "flask==9" in fail
    assert "svc_down" in order


# --- worker start -----------------------------------------------------------------------


def _start_worker(tmp_path, running: bool, svc=None):
    from kemudi_ai.awak.worker import Worker
    from kemudi_ai.config import Settings
    from kemudi_ai.store import make_session

    from .awak_fakes import FakeTaiga

    settings = Settings(awak_projects="", ai_db_url="sqlite:///:memory:",
                        workspace_dir=str(tmp_path / "ws"), secret_key=SECRET_KEY)
    sessions = make_session(settings.ai_db_url)
    with sessions() as db:
        runbook.save(db, "kemudi", parsed(), "pm")
        db.add(AwakJob(project_slug="kemudi", story_id=1, story_ref=12, branch="awak/us-12",
                       state="running" if running else "passed"))
        db.add(AwakJob(project_slug="kemudi", story_id=2, story_ref=13, branch="awak/us-13",
                       state="passed"))
        db.commit()
    runner = FakeRunner(tmp_path / "ws")
    w = Worker(settings, sessions, FakeTaiga(), FakeTaiga("awak-qa"), FakeAgent(), runner,
               None, secret_values=[], sleep=lambda s: None, svc=svc or FakeSvc())
    return w, runner


def test_worker_start_sweeps_compose_keeping_the_running_job(tmp_path):
    w, runner = _start_worker(tmp_path, running=True)
    w.recover()
    assert w.svc.calls == [("svc_sweep", {"keep": ["kemudi-us12"]})]
    assert "reap" not in runner.calls  # a job's processes may still be in use
    w.recover()  # once per worker
    assert len(w.svc.calls) == 1


def test_worker_start_without_jobs_sweeps_all_and_reaps_the_runner(tmp_path):
    w, runner = _start_worker(tmp_path, running=False)
    w.recover()
    assert w.svc.calls == [("svc_sweep", {"keep": []})]
    assert runner.calls == ["reap"]


def test_worker_start_survives_an_unreachable_svc(tmp_path):
    w, runner = _start_worker(tmp_path, running=False, svc=FakeSvc(fail=SvcError("down")))
    w.recover()
    assert runner.calls == ["reap"]


def test_browser_mode_with_compose_qa_needs_kemudi_svc(agent_client):
    from .conftest import ADMIN
    from .test_runbook import SETTINGS, _repo

    _repo(agent_client, name="kemudi")
    r = agent_client.put("/projects/demo/agent/runbook", headers=ADMIN, json={"runbook": RB})
    assert r.status_code == 200, r.text
    url = "/projects/demo/agent/settings"
    agent_client.settings.svc_key = ""
    r = agent_client.put(url, headers=ADMIN, json={**SETTINGS, "qa_mode": "browser"})
    assert r.status_code == 422 and "kemudi-svc" in r.text
    agent_client.settings.svc_key = "configured"
    r = agent_client.put(url, headers=ADMIN, json={**SETTINGS, "qa_mode": "browser"})
    assert r.status_code == 200 and r.json()["qa_mode"] == "browser"
