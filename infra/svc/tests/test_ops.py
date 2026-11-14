"""svc.py's ops with `docker` faked: what each op runs, writes and returns."""

import json
import secrets
import threading

import pytest

from conftest import FIXTURES

JOB = "demo/us-1/web"


@pytest.fixture
def checkout(svc):
    root = svc.WORKSPACE / "demo" / "us-1" / "web"
    for sub in ("backend", "frontend", "sales-inbox/backend", "sales-inbox/frontend"):
        (root / sub).mkdir(parents=True, exist_ok=True)
        (root / sub / "Dockerfile").write_text("FROM scratch\n")
    (root / "docker-compose.yml").write_text("services: {}\n")
    return root


class FakeDocker:
    """Answers like docker would; records every call."""

    def __init__(self, svc, checkout):
        self.svc, self.calls, self.fail = svc, [], {}
        self.noint = (FIXTURES / "playfast.json").read_text(encoding="utf-8").replace(
            "@CHECKOUT@", checkout.as_posix())
        self.logs = ""
        self.env_file_seen = None
        self.interpolate = None  # changes what the second `config` gives back
        self.images = None  # `image ls -q` answer (None: like any `ls`)
        self.now = 0.0  # svc.clock; each call advances it by cost[verb]
        self.cost: dict = {}
        self.hook = None  # called with the verb before answering

    def __call__(self, args, timeout, *, env=None, as_child=False, daemon=True):
        self.calls.append({"args": args, "timeout": timeout, "env": env,
                           "as_child": as_child, "daemon": daemon})
        verb = next((a for a in args if a in {
            "config", "build", "up", "port", "logs", "run", "down", "ls", "rm", "ps",
            "stats", "inspect", "prune"}), "")
        self.now += self.cost.get(verb, 0)
        if self.hook:
            self.hook(verb)
        if args[:2] == ["image", "ls"] and self.images is not None:
            return 0, self.images, ""
        if verb in self.fail:
            return self.fail[verb]
        if verb == "config" and "--no-interpolate" in args:
            return 0, self.noint, "warning: something"
        if verb == "config":
            env_file = args[args.index("--env-file") + 1]
            with open(env_file, encoding="utf-8") as f:
                self.env_file_seen = f.read()
            with open(args[args.index("-f") + 1], encoding="utf-8") as f:
                doc = json.load(f)  # interpolation is compose's job
            if self.interpolate:
                self.interpolate(doc)
            return 0, json.dumps(doc), ""
        if verb == "port":
            return 0, "0.0.0.0:32768\n", ""
        if verb == "logs":
            return 0, self.logs, ""
        return 0, "", ""

    def verbs(self):
        return [next((a for a in c["args"] if a in {"config", "build", "up", "port", "logs",
                                                    "run", "down"}), c["args"][0])
                for c in self.calls]


@pytest.fixture
def fake(svc, checkout, monkeypatch):
    f = FakeDocker(svc, checkout)
    monkeypatch.setattr(svc, "docker", f)
    monkeypatch.setattr(svc, "clock", lambda: f.now)
    return f


def up(svc, **kw):
    body = {"path": JOB, "project": "demo-us1", "services": ["backend"],
            "expose": "backend:5000", **kw}
    return svc.op_svc_up(body)


def test_svc_up(svc, fake):
    secret = secrets.token_hex(8)
    fake.logs = f"backend | started with {secret}\n"
    res = up(svc, env={"JWT_SECRET_KEY": secret})
    assert res == {"ok": True, "project": "demo-us1", "services": ["backend", "postgres", "redis"],
                   "built": ["backend"], "url": f"http://{svc.DIND_HOST}:32768",
                   "logs_tail": "backend | started with [redacted]\n"}
    assert fake.verbs() == ["config", "config", "build", "up", "port", "logs"]

    first, second, build, start = fake.calls[:4]
    # 1: no interpolation, unprivileged, no daemon, no .env
    assert first["as_child"] and not first["daemon"]
    assert first["args"][first["args"].index("--env-file") + 1] == svc.os.devnull
    # 3: only the vault file, deleted afterwards
    assert fake.env_file_seen == f'JWT_SECRET_KEY="{secret}"\n'
    pd = svc.RUN_DIR / "demo-us1"
    assert sorted(p.name for p in pd.iterdir()) == ["compose.json"]
    # 5: build the built services, start everything with --wait
    assert build["args"][-1] == "backend" and build["timeout"] == svc.BUILD_TIMEOUT
    assert "--wait" in start["args"] and start["args"][-3:] == ["backend", "postgres", "redis"]
    assert all(c["args"][c["args"].index("-f") + 1] == str(pd / "compose.json")
               for c in (build, start))
    final = json.loads((pd / "compose.json").read_text())
    assert final["services"]["backend"]["image"] == "kemudi-demo-us1-backend"
    assert final["services"]["backend"]["ports"] == ["0.0.0.0::5000"]


def test_svc_up_subset_and_no_wait(svc, fake):
    res = up(svc, expose=None, up=["postgres"], wait=False)
    assert res["ok"] and res["url"] is None
    start = next(c for c in fake.calls if "up" in c["args"])
    assert "--wait" not in start["args"] and start["args"][-1] == "postgres"


def test_svc_up_with_empty_up_builds_only(svc, fake):
    # run_in gates whose service has no dependency: the image, nothing started
    res = up(svc, expose=None, up=[])
    assert res == {"ok": True, "project": "demo-us1",
                   "services": ["backend", "postgres", "redis"], "built": ["backend"],
                   "url": None, "logs_tail": ""}
    assert fake.verbs() == ["config", "config", "build"]


@pytest.mark.parametrize("body,match", [
    ({"path": "../x"}, "bad workspace path"),
    ({"project": "Bad"}, "bad project"),
    ({"file": "../x.yml"}, "bad compose file"),
    ({"services": []}, "services"),
    ({"expose": "frontend:3000"}, "expose"),
    ({"up": ["frontend"]}, "up: no service"),
    ({"env": {"DOCKER_HOST": "tcp://x"}}, "reserved"),
])
def test_svc_up_refusals(svc, fake, body, match):
    with pytest.raises(ValueError, match=match):
        up(svc, **body)


def test_svc_up_refuses_a_file_that_reads_other_files(svc, fake, checkout):
    (checkout / "docker-compose.yml").write_text("include:\n  - ../../x.yml\n")
    with pytest.raises(svc.Refused, match="'include'"):
        up(svc)
    assert fake.calls == []


def test_svc_up_config_errors_are_refusals_and_redacted(svc, fake):
    secret = secrets.token_hex(8)
    fake.fail["config"] = (1, "", f"required variable X is missing a value {secret}")
    with pytest.raises(svc.Refused) as e:
        up(svc, env={"A": secret})
    assert secret not in str(e.value) and "[redacted]" in str(e.value)


def test_svc_up_build_and_start_failures(svc, fake):
    secret = secrets.token_hex(8)
    fake.fail["build"] = (1, f"step 3 failed {secret}", "")
    res = up(svc, redact=[secret])
    assert res["ok"] is False and res["stage"] == "build"
    assert secret not in res["logs_tail"]

    del fake.fail["build"]
    fake.fail["up"] = (1, "", "dependency failed to start: postgres is unhealthy")
    fake.logs = f"postgres | FATAL {secret}"
    res = up(svc, env={"PGPASS": secret})
    assert res["ok"] is False and res["stage"] == "up" and "unhealthy" in res["error"]
    assert res["logs_tail"] == "postgres | FATAL [redacted]"


def test_svc_exec(svc, fake):
    up(svc)
    fake.calls.clear()
    secret = secrets.token_hex(8)
    fake.fail["run"] = (0, f"created admin {secret}\n", "")
    res = svc.op_svc_exec({"project": "demo-us1", "service": "backend",
                           "argv": ["python", "-m", "init"], "env": {"ADMIN_PW": secret},
                           "timeout": 99999})
    assert res == {"ok": True, "exit": 0, "output": "created admin [redacted]\n"}
    call = fake.calls[0]
    args = call["args"]
    assert args[args.index("run"):args.index("run") + 4] == ["run", "--rm", "--no-deps", "-T"]
    assert args[-4:] == ["backend", "python", "-m", "init"]
    assert "ADMIN_PW" in args and secret not in " ".join(args)
    assert call["env"] == {"ADMIN_PW": secret} and call["timeout"] == svc.EXEC_MAX_TIMEOUT

    # a timeout removes the container by name
    fake.calls.clear()
    fake.fail["run"] = (124, "", "[timed out]")
    res = svc.op_svc_exec({"project": "demo-us1", "service": "backend", "argv": ["sleep", "9"],
                           "timeout": 1})
    assert res["exit"] == 124 and not res["ok"]
    name = fake.calls[0]["args"][fake.calls[0]["args"].index("--name") + 1]
    assert fake.calls[1]["args"] == ["rm", "-f", name]

    with pytest.raises(svc.Refused, match="no service"):
        svc.op_svc_exec({"project": "demo-us1", "service": "frontend", "argv": ["x"]})
    with pytest.raises(svc.Refused, match="argv"):
        svc.op_svc_exec({"project": "demo-us1", "service": "backend", "argv": []})
    with pytest.raises(svc.Refused, match="not up"):
        svc.op_svc_exec({"project": "other-us2", "service": "backend", "argv": ["x"]})


def test_svc_logs(svc, fake):
    up(svc)
    secret = secrets.token_hex(8)
    fake.logs = f"redis | ready {secret}"
    res = svc.op_svc_logs({"project": "demo-us1", "service": "redis", "tail": 50,
                           "redact": [secret]})
    assert res == {"ok": True, "logs": "redis | ready [redacted]"}
    assert fake.calls[-1]["args"][-3:] == ["--tail", "50", "redis"]


def test_svc_stats(svc, fake):
    fake.fail["ps"] = (0, "demo-us1-redis-1\tredis\n", "")
    fake.fail["stats"] = (0, json.dumps({
        "Name": "demo-us1-redis-1", "CPUPerc": "1.50%", "MemUsage": "12.5MiB / 2GiB",
        "MemPerc": "0.61%", "PIDs": "5"}) + "\n", "")
    res = svc.op_svc_stats({"project": "demo-us1"})
    assert res == {"ok": True, "stats": [{
        "name": "demo-us1-redis-1", "service": "redis", "cpu_pct": 1.5,
        "mem_bytes": int(12.5 * 1024 ** 2), "mem_limit_bytes": 2 * 1024 ** 3,
        "mem_pct": 0.61, "pids": 5}]}
    assert "label=kemudi.project=demo-us1" in fake.calls[0]["args"]


def test_svc_down(svc, fake):
    up(svc)
    fake.calls.clear()
    fake.fail["ls"] = (0, "vol1\n", "")
    res = svc.op_svc_down({"project": "demo-us1"})
    assert res["ok"]
    down = fake.calls[0]["args"]
    assert down[-5:] == ["down", "-v", "--remove-orphans", "-t", "10"] and "-f" in down
    assert ["volume", "rm", "-f", "vol1"] in [c["args"] for c in fake.calls]
    assert not (svc.RUN_DIR / "demo-us1").exists()
    # without svc's file (svc restarted): by project name only
    fake.calls.clear()
    svc.op_svc_down({"project": "demo-us1"})
    assert "-f" not in fake.calls[0]["args"]


def test_svc_sweep(svc, fake):
    (svc.RUN_DIR / "stale-us9").mkdir()
    fake.fail["ps"] = (0, "demo-us1\nold-us2\n", "")
    fake.fail["ls"] = (0, "old-us3\n", "")  # volume ls; image ls -q too
    fake.fail["inspect"] = (0, "sha256:aaa demo-us1\nsha256:bbb old-us2\n", "")
    res = svc.op_svc_sweep({"keep": ["demo-us1"]})
    assert res["ok"] and res["removed"] == ["old-us2", "old-us3", "stale-us9"]
    downs = [c["args"] for c in fake.calls if "down" in c["args"]]
    assert [a[a.index("-p") + 1] for a in downs] == ["old-us2", "old-us3", "stale-us9"]
    # svc_down of each removed project removes its images by label...
    image_ls = [c["args"] for c in fake.calls if c["args"][:2] == ["image", "ls"]]
    assert ["image", "ls", "-q", "--filter", "label=kemudi.project=old-us2"] in image_ls
    # ...and the sweep removes what is left of projects not kept
    rms = [c["args"] for c in fake.calls if c["args"][:2] == ["image", "rm"]
           and "-f" not in c["args"]]
    assert rms == [["image", "rm", "sha256:bbb"]]
    assert res["images_removed"] == 1
    assert any(c["args"][:2] == ["builder", "prune"] for c in fake.calls)
    with pytest.raises(svc.Refused):
        svc.op_svc_sweep({"keep": ["../x"]})


def test_svc_up_retries_a_build_once_on_network_trouble(svc, fake, monkeypatch):
    monkeypatch.setattr(svc.time, "sleep", lambda s: None)
    fake.fail["build"] = (1, "", "lookup auth.docker.io on 127.0.0.11:53: server misbehaving")
    res = up(svc)
    assert res["ok"] is False and fake.verbs().count("build") == 2
    fake.calls.clear()
    fake.fail["build"] = (1, "", "step 3: pip failed")
    up(svc)
    assert fake.verbs().count("build") == 1


# --- checks after interpolation ------------------------------------------------------


def test_svc_up_refuses_a_reserved_image_that_only_interpolation_shows(svc, fake):
    def other_projects_image(doc):
        doc["services"]["redis"]["image"] = "kemudi-other-us3-backend"
    fake.interpolate = other_projects_image
    with pytest.raises(svc.Refused, match="reserved"):
        up(svc)
    assert "build" not in fake.verbs() and "up" not in fake.verbs()


def test_svc_up_refuses_a_build_context_interpolated_outside(svc, fake):
    def escape(doc):
        doc["services"]["backend"]["build"]["context"] = str(svc.RUN_DIR)
    fake.interpolate = escape
    with pytest.raises(svc.Refused, match="outside the checkout"):
        up(svc)
    assert "build" not in fake.verbs()


def test_svc_up_refuses_a_dockerfile_from_another_projects_image(svc, fake, checkout):
    (checkout / "backend" / "Dockerfile").write_text(
        "FROM python:3.12\nCOPY --from=kemudi-other-us3-backend /app /app\n")
    with pytest.raises(svc.Refused, match="Dockerfile uses image"):
        up(svc)
    assert "build" not in fake.verbs()


def test_svc_up_refuses_file_keys_in_composes_output(svc, fake):
    noint = json.loads(fake.noint)
    noint["services"]["redis"]["env_file"] = [{"path": "/run/svc/x", "required": True}]
    fake.noint = json.dumps(noint)
    with pytest.raises(svc.Refused, match="'env_file'"):
        up(svc)
    assert fake.verbs() == ["config"]


def test_svc_up_bad_limit_is_a_refusal(svc, fake):
    def bad(doc):
        doc["services"]["redis"]["pids_limit"] = "abc"
    fake.interpolate = bad
    with pytest.raises(svc.Refused, match="'redis': pids_limit"):
        up(svc)


# --- time budget ---------------------------------------------------------------------


def test_svc_up_steps_share_one_budget(svc, fake, monkeypatch):
    def nap(s):
        fake.now += s
    monkeypatch.setattr(svc.time, "sleep", nap)
    fake.cost = {"config": 10, "up": 100, "port": 60}
    builds = []

    def build_flaky_then_quick(verb):
        if verb == "build":
            builds.append(1)
            fake.now += 900 if len(builds) == 1 else 300
            fake.fail["build"] = (1, "", "i/o timeout") if len(builds) == 1 else (0, "", "")
    fake.hook = build_flaky_then_quick
    res = up(svc)
    assert res["ok"], res
    t = {v: [c["timeout"] for c, vv in zip(fake.calls, fake.verbs()) if vv == v]
         for v in ("config", "build", "up", "port", "logs")}
    assert t["config"] == [60, 60]
    # 1400 - 20 for the configs: the first build gets its 900 s, the retry what is left
    assert t["build"] == [900, 1400 - 20 - 900 - 5]
    left_for_up = 1400 - 20 - 900 - 5 - 300
    up_call = next(c for c, v in zip(fake.calls, fake.verbs()) if v == "up")
    assert t["up"] == [left_for_up]
    wait = int(up_call["args"][up_call["args"].index("--wait-timeout") + 1])
    assert wait == left_for_up - svc.MIN_STEP
    assert t["port"] == [60] and t["logs"] == [left_for_up - 100 - 60]


def test_svc_up_out_of_budget_stops_before_the_next_step(svc, fake, monkeypatch):
    monkeypatch.setattr(svc.time, "sleep", lambda s: None)
    fake.cost = {"config": 10, "build": 1380}
    res = up(svc)
    assert res["ok"] is False and res["stage"] == "up" and "budget" in res["error"]
    assert "up" not in fake.verbs()


def test_budget_is_below_the_clients_wait(svc):
    """kemudi_ai/awak/svc.py (the orchestrator's client) waits longer than svc
    can take: svc_up's budget plus its last logs, svc_down after a lock wait."""
    import re
    from pathlib import Path
    client = (Path(__file__).resolve().parents[3] / "apps" / "orchestrator" / "kemudi_ai"
              / "awak" / "svc.py").read_text(encoding="utf-8")
    default = int(re.search(r"TIMEOUT_S = (\d+)", client).group(1))
    up_s = int(re.search(r'"svc_up": (\d+)', client).group(1))
    down_s = int(re.search(r'"svc_down": (\d+)', client).group(1))
    assert svc.UP_BUDGET < 1600 and svc.UP_BUDGET + 60 < up_s
    assert svc.LOCK_WAIT > svc.UP_BUDGET + 60  # outlasts an svc_up
    assert svc.LOCK_WAIT + 600 <= down_s
    assert svc.EXEC_WINDOW + 60 < default


# --- one lock per project ------------------------------------------------------------


def _up_in_background(svc, fake):
    """svc_up stuck in its build until `release` is set."""
    started, release = threading.Event(), threading.Event()

    def hold(verb):
        if verb == "build":
            started.set()
            release.wait(10)
    fake.hook = hold
    t = threading.Thread(target=up, args=(svc,), daemon=True)
    t.start()
    assert started.wait(10)
    return t, release


def test_svc_down_waits_for_an_svc_up_of_the_same_project(svc, fake):
    t, release = _up_in_background(svc, fake)
    done = []
    d = threading.Thread(target=lambda: done.append(svc.op_svc_down({"project": "demo-us1"})),
                         daemon=True)
    d.start()
    d.join(0.3)
    assert not done and "down" not in fake.verbs()
    release.set()
    t.join(10)
    d.join(10)
    assert done and done[0]["ok"]
    verbs = fake.verbs()
    assert verbs.index("down") > verbs.index("up")


def test_waiting_is_bounded_and_other_projects_do_not_wait(svc, fake, monkeypatch):
    monkeypatch.setattr(svc, "LOCK_WAIT", 0.2)
    t, release = _up_in_background(svc, fake)
    try:
        with pytest.raises(svc.Busy):
            svc.op_svc_down({"project": "demo-us1"})
        with pytest.raises(svc.Busy):
            svc.op_svc_exec({"project": "demo-us1", "service": "backend", "argv": ["true"]})
        assert svc.op_svc_down({"project": "other-us2"})["ok"]
        # the sweep leaves a busy project for next time
        fake.fail["ps"] = (0, "demo-us1\n", "")
        res = svc.op_svc_sweep({"keep": []})
        assert "demo-us1" not in res["removed"]
    finally:
        release.set()
        t.join(10)


def test_svc_down_removes_the_projects_images(svc, fake):
    up(svc)
    fake.calls.clear()
    fake.images = "sha256:aaa\nsha256:bbb\nsha256:aaa\n"
    assert svc.op_svc_down({"project": "demo-us1"})["ok"]
    args = [c["args"] for c in fake.calls]
    assert ["image", "ls", "-q", "--filter", "label=kemudi.project=demo-us1"] in args
    assert ["image", "rm", "-f", "sha256:aaa", "sha256:bbb"] in args
    # nothing built: nothing removed
    fake.calls.clear()
    fake.images = ""
    svc.op_svc_down({"project": "demo-us1"})
    assert not [c for c in fake.calls if c["args"][:2] == ["image", "rm"]]


def test_exec_and_logs_bad_numbers_are_refusals(svc, fake):
    up(svc)
    with pytest.raises(svc.Refused, match="timeout"):
        svc.op_svc_exec({"project": "demo-us1", "service": "backend", "argv": ["x"],
                         "timeout": "abc"})
    with pytest.raises(svc.Refused, match="tail"):
        svc.op_svc_logs({"project": "demo-us1", "tail": "abc"})
