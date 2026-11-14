"""Tests for kemudi-runner's command handling (stdlib + pytest only).

Run: python -m pytest infra/runner -q
"""

import importlib.util
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
