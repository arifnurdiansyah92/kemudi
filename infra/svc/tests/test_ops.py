"""svc.py's ops with `docker` faked: what each op runs, writes and returns."""

import json
import secrets

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

    def __call__(self, args, timeout, *, env=None, as_child=False, daemon=True):
        self.calls.append({"args": args, "timeout": timeout, "env": env,
                           "as_child": as_child, "daemon": daemon})
        verb = next((a for a in args if a in {
            "config", "build", "up", "port", "logs", "run", "down", "ls", "rm", "ps",
            "stats", "inspect", "prune"}), "")
        if verb in self.fail:
            return self.fail[verb]
        if verb == "config" and "--no-interpolate" in args:
            return 0, self.noint, "warning: something"
        if verb == "config":
            env_file = args[args.index("--env-file") + 1]
            with open(env_file, encoding="utf-8") as f:
                self.env_file_seen = f.read()
            with open(args[args.index("-f") + 1], encoding="utf-8") as f:
                return 0, f.read(), ""  # interpolation is compose's job
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
    rms = [c["args"] for c in fake.calls if c["args"][:2] == ["image", "rm"]]
    assert rms == [["image", "rm", "sha256:bbb"]]
    assert res["images_removed"] == 1
    assert any(c["args"][:2] == ["builder", "prune"] for c in fake.calls)
    with pytest.raises(svc.Refused):
        svc.op_svc_sweep({"keep": ["../x"]})
