"""Tests for kemudi-runner's command handling (stdlib + pytest only).

Run: python -m pytest infra/runner -q
"""

import importlib.util
import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent
JOB = "demo/us-1/web"


@pytest.fixture
def runner(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNNER_WORKSPACE", str(tmp_path))
    spec = importlib.util.spec_from_file_location("kemudi_runner_under_test", HERE / "runner.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    (tmp_path / "demo" / "us-1" / "web" / "apps" / "web").mkdir(parents=True)
    (tmp_path / "demo" / "us-1" / "web" / "svc").mkdir()
    yield mod
    sys.modules.pop(spec.name, None)


def test_commands_allowlist_and_subdir(runner, monkeypatch):
    calls = []
    monkeypatch.setattr(runner, "run", lambda cmd, cwd, timeout, env=None:
                        calls.append((cmd, cwd, timeout)) or (0, "ok"))
    job = {"path": JOB}

    # explicit commands run in the subdir, without a shell
    res = runner.op_gates({**job, "subdir": "svc", "commands": [
        {"name": "test", "argv": ["uv", "run", "pytest"], "timeout": 60}]})
    assert res["ok"] and res["gates"][0]["name"] == "test"
    assert calls[-1][0] == ["uv", "run", "pytest"]
    assert calls[-1][1] == runner.WORKSPACE / "demo" / "us-1" / "web" / "svc"

    # argv[0] outside the allowlist
    with pytest.raises(ValueError, match="not allowed"):
        runner.op_gates({**job, "commands": [{"name": "x", "argv": ["rm", "-rf", "/"]}]})
    with pytest.raises(ValueError, match="not allowed"):
        runner.op_install({**job, "commands": [{"name": "x", "argv": ["/bin/pnpm"]}]})
    # a subdir outside the job, or missing
    for bad in ("../x", "svc/../../x", "/etc", "C:\\x", "missing"):
        with pytest.raises(ValueError):
            runner.op_gates({**job, "subdir": bad, "commands": []})

    # empty list: nothing to run, still ok
    assert runner.op_gates({**job, "subdir": "", "commands": []}) == {"ok": True, "gates": []}

    # omitted: iteration 1's apps/web behaviour
    calls.clear()
    runner.op_gates(job)
    assert [c[0][:3] for c in calls][0] == ["pnpm", "exec", "tsc"]
    assert calls[0][1] == runner.WORKSPACE / "demo" / "us-1" / "web" / "apps" / "web"
    calls.clear()
    assert runner.op_install({**job, "subdir": "svc",
                              "commands": [{"name": "i", "argv": ["uv", "sync"]}]})["ok"]
    assert calls == [(["uv", "sync"], runner.WORKSPACE / "demo" / "us-1" / "web" / "svc", 900)]


def test_workspace_path_validation(runner, tmp_path):
    (tmp_path / "demo" / "setup" / "pf-web").mkdir(parents=True)
    (tmp_path / "demo" / "us-1" / "file.txt").write_text("x")
    assert runner.job_dir({"path": JOB}) == tmp_path / "demo" / "us-1" / "web"
    assert runner.job_dir({"path": "demo/setup/pf-web"}) == tmp_path / "demo" / "setup" / "pf-web"
    bad = ["", "demo", "demo/us-1", "awak-us-1", "../demo/us-1/web", "demo/../us-1/web",
           "demo/us-1/..", "demo/us-1/.git", "Demo/us-1/web", "demo/us-x/web",
           "demo/other/web", "/demo/us-1/web", "demo/us-1/web/", "demo\\us-1\\web",
           "demo/us-1/web\n", "demo/us-1/missing", "demo/us-1/file.txt"]
    for path in bad:
        with pytest.raises(ValueError):
            runner.job_dir({"path": path})
    # the old `job` name is gone
    with pytest.raises(ValueError):
        runner.job_dir({"job": "awak-us-1"})


def test_workspace_path_refuses_symlinks(runner, tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    try:
        (tmp_path / "demo" / "us-3").mkdir(parents=True)
        (tmp_path / "demo" / "us-3" / "web").symlink_to(outside, target_is_directory=True)
        (tmp_path / "evil").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks not available")
    (outside / "us-1" / "web").mkdir(parents=True)
    for path in ("demo/us-3/web", "evil/us-1/web"):
        with pytest.raises(ValueError):
            runner.job_dir({"path": path})


def test_children_get_a_clean_env_without_the_runner_key(runner, monkeypatch):
    key_name = "KEMUDI_" + "RUNNER_KEY"
    monkeypatch.setenv(key_name, "k" * 24)  # built at runtime: not a literal secret
    monkeypatch.setenv("KEMUDI_DEV_GATEWAY", "http://gw")
    monkeypatch.setenv("SOME_HOST_SETTING", "x")
    env = runner.child_env({"FOO": "1"})
    assert not any(k.upper().startswith("KEMUDI_") for k in env)
    assert "SOME_HOST_SETTING" not in env
    assert env["FOO"] == "1" and env["npm_config_store_dir"] == "/pnpm-store"
    assert env["PATH"] == os.environ["PATH"]
    # a real child: the key is not in its environment, the request's env is
    code, out = runner.run([sys.executable, "-c",
                            "import os; print(sorted(k for k in os.environ "
                            "if k.upper().startswith('KEMUDI_')), os.environ['APP_MODE'])"],
                           runner.WORKSPACE, 60, {"APP_MODE": "test"})
    assert code == 0 and out.strip() == "[] test"


def test_install_and_gates_take_a_validated_env(runner, monkeypatch):
    calls = []
    monkeypatch.setattr(runner, "run", lambda cmd, cwd, timeout, env=None:
                        calls.append(env) or (0, "ok"))
    cmds = [{"name": "i", "argv": ["npm", "ci", "--ignore-scripts", "--legacy-peer-deps"]}]
    assert runner.op_install({"path": JOB, "commands": cmds, "env": {"NEXT_X": "1"}})["ok"]
    assert runner.op_gates({"path": JOB, "commands": [
        {"name": "t", "argv": ["npx", "--no-install", "tsc", "--noEmit"]}],
        "env": {"A": "b"}})["ok"]
    assert calls == [{"NEXT_X": "1"}, {"A": "b"}]
    for bad in ({"KEMUDI_RUNNER_KEY": "x"}, {"PATH": "/x"}, {"node_options": "x"},
                {"GIT_DIR": "/"}, {"bad-name": "x"}, {"A": 1}, ["A"]):
        with pytest.raises(ValueError):
            runner.op_gates({"path": JOB, "commands": cmds, "env": bad})


def _service(name="web", **kw):
    return {"name": name, "subdir": "svc", "health": "/",
            "argv": ["python", "-m", "http.server", "{port}", "--bind", "127.0.0.1"],
            "env": {}, "ready_timeout": 30, **kw}


def _spec(tmp_path):
    spec = tmp_path / "demo" / "us-1" / "web" / ".qa" / "spec"
    spec.mkdir(parents=True)
    (spec / "story.spec.ts").write_text("test('AC1: x', () => {})")
    return spec


def test_qa_starts_process_services_and_stops_them(runner, tmp_path, monkeypatch):
    import urllib.request

    _spec(tmp_path)
    d = tmp_path / "demo" / "us-1" / "web"
    (d / "svc" / "index.html").write_text("hello")
    (d / ".qa" / "routes.txt").write_text("/index.html\nnot-a-path\n/\n")
    seen = {}

    def fake_specs(job, spec_dir, base, state, extra, deadline):
        seen.update(base=base, state=state, extra=extra)
        with urllib.request.urlopen(base + "/index.html", timeout=5) as r:
            seen["body"] = r.read().decode()
        return {"ok": True, "runs": []}

    monkeypatch.setattr(runner, "_run_specs", fake_specs)
    procs = []
    real_spawn = runner._spawn
    monkeypatch.setattr(runner, "_spawn", lambda *a: procs.append(real_spawn(*a)) or procs[-1])
    warmed = []
    monkeypatch.setattr(runner, "_warm", lambda base, paths, deadline: warmed.extend(paths))
    api = _service("api", env={"FROM": "x"})
    web = _service("web", env={"API_URL": "{services.api.url}/v1"})
    res = runner.op_qa({"path": JOB, "services": [api, web], "base_service": "web",
                        "warm": ["/"]})
    assert res == {"ok": True, "runs": []}, res
    assert seen["body"] == "hello" and seen["state"] is None and seen["extra"] == {}
    assert seen["base"].startswith("http://localhost:52")
    assert warmed == ["/", "/index.html"]
    assert (d / ".qa" / "logs" / "web.log").exists() and (d / ".qa" / "logs" / "api.log").exists()
    assert len(procs) == 2 and all(p.poll() is not None for p in procs)


def test_qa_service_env_gets_port_and_resolved_urls(runner, tmp_path, monkeypatch):
    _spec(tmp_path)
    envs = []

    class Proc:
        pid, returncode = 0, None

        def poll(self):
            return None

    monkeypatch.setattr(runner, "_spawn", lambda argv, cwd, env, log: envs.append(
        (argv, env)) or Proc())
    monkeypatch.setattr(runner, "_stop", lambda p: None)
    monkeypatch.setattr(runner, "_wait_http", lambda *a, **k: True)
    monkeypatch.setattr(runner, "_warm", lambda *a: None)
    monkeypatch.setattr(runner, "_run_specs", lambda *a: {"ok": True, "runs": []})
    api = _service("api")
    web = _service("web", argv=["pnpm", "exec", "next", "dev", "--port", "{port}"],
                   env={"INTERNAL_API_URL": "{services.api.url}"})
    runner.op_qa({"path": JOB, "services": [api, web], "base_service": "web"})
    (_, api_env), (web_argv, web_env) = envs
    port = web_env["PORT"]
    assert web_argv == ["pnpm", "exec", "next", "dev", "--port", port]
    assert web_env["INTERNAL_API_URL"] == f"http://localhost:{api_env['PORT']}"
    assert web_env["NEXT_TELEMETRY_DISABLED"] == "1"
    assert web_env["NODE_OPTIONS"] == "--max-old-space-size=2048"
    assert web_env["npm_config_store_dir"] == "/pnpm-store"
    assert "HOSTNAME" not in web_env
    assert not any(k.upper().startswith("KEMUDI_") for k in web_env)


def test_qa_service_that_dies_is_an_infra_error_with_its_log(runner, tmp_path):
    _spec(tmp_path)
    svc = _service(argv=["python", "-c", "import sys; print('boom: no config'); sys.exit(3)"])
    res = runner.op_qa({"path": JOB, "services": [svc], "base_service": "web"})
    assert "did not start" in res["infra_error"] and "exited with 3" in res["infra_error"]
    assert "boom: no config" in res["infra_error"]


def test_qa_services_are_validated(runner, tmp_path):
    _spec(tmp_path)
    for services, base in (
        ([_service(argv=["bash", "-c", "x"])], "web"),
        ([_service(subdir="../x")], "web"),
        ([_service(env={"KEMUDI_X": "1"})], "web"),
        ([_service(health="nope")], "web"),
        ([_service(), _service()], "web"),
        ([_service(name="Web")], "Web"),
        ([_service(repo="../../x")], "web"),
        ([_service()], "other"),
        ([], "web"),
    ):
        with pytest.raises(ValueError):
            runner.op_qa({"path": JOB, "services": services, "base_service": base})


def test_failing_install_command_is_an_infra_error(runner, monkeypatch):
    monkeypatch.setattr(runner, "run", lambda cmd, cwd, timeout, env=None: (1, "boom"))
    res = runner.op_install({"path": JOB, "commands": [{"name": "i", "argv": ["npm", "ci"]}]})
    assert "infra_error" in res and "boom" in res["infra_error"]


def test_deploy_runs_command_in_job_dir(runner, monkeypatch):
    calls = []
    monkeypatch.setattr(runner, "run", lambda cmd, cwd, timeout, env=None:
                        calls.append((cmd, cwd, timeout)) or (3, "deploy log"))
    res = runner.op_deploy({"path": JOB, "command": "make deploy"})
    assert res == {"ok": False, "exit": 3, "output": "deploy log"}
    assert calls == [(["sh", "-c", "make deploy"], runner.WORKSPACE / "demo" / "us-1" / "web", 900)]
    with pytest.raises(ValueError):
        runner.op_deploy({"path": JOB, "command": " "})
    with pytest.raises(ValueError):
        runner.op_deploy({"path": "../x", "command": "make deploy"})


def _git(cwd, *args):
    import subprocess
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_clean_check_reports_head_and_every_stray_path(runner, tmp_path):
    d = tmp_path / "demo" / "us-2" / "web"
    d.mkdir(parents=True)
    _git(d, "init", "-q", "-b", "main")
    _git(d, "config", "user.email", "t@t")
    _git(d, "config", "user.name", "t")
    _git(d, "config", "core.autocrlf", "false")
    (d / ".gitignore").write_text("secret.local\n")
    (d / "app.ts").write_text("export const a = 1\n")
    _git(d, "add", "-A")
    _git(d, "commit", "-q", "-m", "init")
    head = (d / ".git" / "refs" / "heads" / "main").read_text().strip()

    res = runner.op_clean_check({"path": "demo/us-2/web"})
    assert res == {"ok": True, "head": head, "entries": [], "truncated": False}

    (d / "secret.local").write_text("x")       # gitignored
    (d / "extra.ts").write_text("x")            # untracked
    (d / "app.ts").write_text("export const a = 2\n")
    _git(d, "update-index", "--assume-unchanged", "app.ts")  # hidden from a plain status
    (d / "node_modules" / "pkg").mkdir(parents=True)
    (d / "node_modules" / "pkg" / "i.js").write_text("x")
    res = runner.op_clean_check({"path": "demo/us-2/web"})
    got = {(e["status"], e["path"]) for e in res["entries"]}
    assert got == {("!!", "secret.local"), ("??", "extra.ts"), (" M", "app.ts"),
                   ("??", "node_modules/")}
    assert res["head"] == head
