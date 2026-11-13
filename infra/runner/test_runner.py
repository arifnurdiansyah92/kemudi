"""Tests for kemudi-runner's command handling (stdlib + pytest only).

Run: python -m pytest infra/runner -q
"""

import importlib.util
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).parent


@pytest.fixture
def runner(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNNER_WORKSPACE", str(tmp_path))
    spec = importlib.util.spec_from_file_location("kemudi_runner_under_test", HERE / "runner.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    (tmp_path / "awak-us-1" / "apps" / "web").mkdir(parents=True)
    (tmp_path / "awak-us-1" / "svc").mkdir()
    yield mod
    sys.modules.pop(spec.name, None)


def test_commands_allowlist_and_subdir(runner, monkeypatch):
    calls = []
    monkeypatch.setattr(runner, "run", lambda cmd, cwd, timeout, env=None:
                        calls.append((cmd, cwd, timeout)) or (0, "ok"))
    job = {"job": "awak-us-1"}

    # explicit commands run in the subdir, without a shell
    res = runner.op_gates({**job, "subdir": "svc", "commands": [
        {"name": "test", "argv": ["uv", "run", "pytest"], "timeout": 60}]})
    assert res["ok"] and res["gates"][0]["name"] == "test"
    assert calls[-1][0] == ["uv", "run", "pytest"]
    assert calls[-1][1] == runner.WORKSPACE / "awak-us-1" / "svc"

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
    assert calls[0][1] == runner.WORKSPACE / "awak-us-1" / "apps" / "web"
    calls.clear()
    assert runner.op_install({**job, "subdir": "svc",
                              "commands": [{"name": "i", "argv": ["uv", "sync"]}]})["ok"]
    assert calls == [(["uv", "sync"], runner.WORKSPACE / "awak-us-1" / "svc", 900)]


def test_failing_install_command_is_an_infra_error(runner, monkeypatch):
    monkeypatch.setattr(runner, "run", lambda cmd, cwd, timeout, env=None: (1, "boom"))
    res = runner.op_install({"job": "awak-us-1", "commands": [{"name": "i", "argv": ["npm", "ci"]}]})
    assert "infra_error" in res and "boom" in res["infra_error"]


def test_deploy_runs_command_in_job_dir(runner, monkeypatch):
    calls = []
    monkeypatch.setattr(runner, "run", lambda cmd, cwd, timeout, env=None:
                        calls.append((cmd, cwd, timeout)) or (3, "deploy log"))
    res = runner.op_deploy({"job": "awak-us-1", "command": "make deploy"})
    assert res == {"ok": False, "exit": 3, "output": "deploy log"}
    assert calls == [(["sh", "-c", "make deploy"], runner.WORKSPACE / "awak-us-1", 900)]
    with pytest.raises(ValueError):
        runner.op_deploy({"job": "awak-us-1", "command": " "})
    with pytest.raises(ValueError):
        runner.op_deploy({"job": "../x", "command": "make deploy"})
