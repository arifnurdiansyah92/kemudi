import importlib.util
import secrets
import sys
from pathlib import Path

import pytest

SVC_DIR = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def load(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, SVC_DIR / file)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def svc(tmp_path, monkeypatch):
    """svc.py loaded fresh against a temp workspace and a temp /run/svc, with a
    key built at run time."""
    ws = tmp_path / "ws"
    (ws / "demo" / "us-1" / "web").mkdir(parents=True)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    monkeypatch.setenv("SVC_WORKSPACE", str(ws))
    monkeypatch.setenv("SVC_RUN_DIR", str(run_dir))
    monkeypatch.setenv("KEMUDI_SVC_KEY", secrets.token_hex(16))
    mod = load("kemudi_svc_under_test", "svc.py")
    yield mod
    sys.modules.pop("kemudi_svc_under_test", None)
