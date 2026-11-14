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


# --- uid split: the server is root, every child runs as CHILD_UID -------------


class _Done:
    def __init__(self, text):
        self.returncode = 0
        self.stdout = self.stderr = "" if text else b""


def test_children_drop_to_the_child_uid_when_the_server_is_root(runner, monkeypatch, tmp_path):
    import subprocess

    monkeypatch.setattr(runner, "dropping", lambda: True)
    monkeypatch.setattr(runner, "_child_home", lambda: "/opt/data")
    calls = []

    def fake_run(argv, **kw):
        calls.append((argv, kw))
        return _Done(kw.get("text"))

    monkeypatch.setattr(subprocess, "run", fake_run)
    runner.run(["node", "x.js"], tmp_path, 60, {"A": "1"})
    argv, kw = calls[-1]
    assert kw["user"] == 10000 and kw["group"] == 10000 and kw["extra_groups"] == []
    assert kw["env"]["HOME"] == "/opt/data" and kw["env"]["A"] == "1"
    assert not any(k.upper().startswith("KEMUDI_") for k in kw["env"])

    popens = []
    monkeypatch.setattr(subprocess, "Popen", lambda argv, **kw: popens.append((argv, kw)))
    runner._spawn(["pnpm", "dev"], tmp_path, runner.child_env(), tmp_path / "web.log")
    argv, kw = popens[-1]
    # the log is opened by the child's shell, not by the root server
    assert argv[:2] == ["sh", "-c"] and argv[-2:] == ["pnpm", "dev"]
    assert str(tmp_path / "web.log") in argv and kw["stdout"] == subprocess.DEVNULL
    assert kw["user"] == 10000 and kw["extra_groups"] == []

    # files the agent can write are read with the child's rights
    runner.read_as_child(tmp_path / "report.json")
    argv, kw = calls[-1]
    assert argv[0] == "head" and kw["user"] == 10000

    # git for the clean check runs as the child too
    runner._git_out(["status"], {"PATH": "/usr/bin"})
    argv, kw = calls[-1]
    assert argv[0] == "git" and kw["user"] == 10000


def test_qa_reset_and_logs_dir_are_made_by_the_child(runner, monkeypatch):
    monkeypatch.setattr(runner, "dropping", lambda: True)
    calls = []
    monkeypatch.setattr(runner, "run", lambda cmd, cwd, timeout, env=None:
                        calls.append(cmd) or (0, ""))
    assert runner.op_qa_reset({"path": JOB}) == {"ok": True}
    assert calls == [["rm", "-rf", "--", ".qa"], ["mkdir", "-p", "--", ".qa/spec"]]


def test_without_root_children_keep_the_server_uid(runner):
    assert runner.child_kw() == {} or runner.dropping()

ROOT_ONLY = pytest.mark.skipif(
    os.name != "posix" or not hasattr(os, "geteuid") or os.geteuid() != 0,
    reason="needs root to drop to the child uid")


@ROOT_ONLY
def test_a_child_cannot_read_the_server_environment(runner):
    for pid in (1, os.getpid()):
        code, out = runner.run(["cat", f"/proc/{pid}/environ"], Path("/"), 30)
        assert code != 0, out
        assert runner.read_as_child(Path(f"/proc/{pid}/environ")) is None
    code, out = runner.run(["id", "-u"], Path("/"), 30)
    assert out.strip() == str(runner.CHILD_UID)


@ROOT_ONLY
def test_the_server_never_writes_through_a_workspace_symlink(runner, monkeypatch):
    import tempfile

    ws = runner.child_tmpdir("ws-")
    # like a real checkout (0755): Python enters cwd before it switches uid
    assert runner.run(["chmod", "755", str(ws)], Path("/"), 30)[0] == 0
    victim = Path(tempfile.mkdtemp(prefix="victim-"))  # root's, 0700
    try:
        monkeypatch.setattr(runner, "WORKSPACE", ws)
        job = "demo/us-9/web"
        assert runner.run(["mkdir", "-p", f"{job}/svc"], ws, 30)[0] == 0
        assert runner.op_qa_reset({"path": job}) == {"ok": True}
        d = ws / "demo" / "us-9" / "web"
        assert (d / ".qa" / "spec").stat().st_uid == runner.CHILD_UID
        assert runner.run(["ln", "-s", str(victim), ".qa/logs"], d, 30)[0] == 0
        assert runner.run(["touch", ".qa/spec/a.spec.ts"], d, 30)[0] == 0
        res = runner.op_qa({"path": job, "services": [_service(ready_timeout=5)],
                            "base_service": "web"})
        assert "did not start" in res.get("infra_error", ""), res
        assert not (victim / "web.log").exists()
        # the clean check runs git as the child
        res = runner.op_clean_check({"path": job})
        assert res["entries"] == [{"status": "!?", "path": ".git"}]
    finally:
        runner.remove_child_tmpdir(ws)
        import shutil
        shutil.rmtree(victim, ignore_errors=True)
    assert not ws.exists()


@ROOT_ONLY
def test_the_server_stops_a_child_process_group(runner):
    proc = runner._spawn(["sh", "-c", "sleep 60 & sleep 60"], Path("/"), runner.child_env(),
                         None)
    runner._stop(proc)
    assert proc.poll() is not None
    code, out = runner.run(["sh", "-c", "pgrep -u %d -x sleep || true" % runner.CHILD_UID],
                           Path("/"), 30)
    assert out.strip() == ""
