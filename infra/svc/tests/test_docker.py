"""svc_up -> svc_exec -> svc_logs/svc_stats -> svc_down against a real Docker
daemon (kemudi-dind). Skipped unless KEMUDI_SVC_DOCKER_TEST=1.

Run it in the svc image, beside a dind, sharing its network so published
ports answer on 127.0.0.1:

    docker run --rm --network container:<dind> -v <dind socket volume>:/run/dind \
      -e DOCKER_HOST=unix:///run/dind/docker.sock -e KEMUDI_SVC_DOCKER_TEST=1 \
      -e SVC_DIND_HOST=127.0.0.1 -v $PWD/infra/svc:/src:ro --entrypoint sh \
      kemudi/kemudi-svc:dev -c "apk add -q py3-pytest && cd /tmp && \
      python3 -m pytest -q -p no:cacheprovider /src/tests/test_docker.py"
"""

import json
import os
import secrets
import shutil
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import pytest

from conftest import load

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(os.environ.get("KEMUDI_SVC_DOCKER_TEST") != "1" or not shutil.which("docker"),
                       reason="needs Docker (KEMUDI_SVC_DOCKER_TEST=1)"),
]

COMPOSE = """
services:
  web:
    build:
      context: .
      dockerfile: web/Dockerfile
    depends_on:
      cache: {condition: service_healthy}
    environment:
      GREETING: ${GREETING:?set GREETING}
    ports: ["127.0.0.1:8080:8080"]
    networks: [inner]
    logging: {driver: json-file}
  cache:
    image: redis:7-alpine
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 2s
      retries: 15
    volumes: [cachedata:/data]
    networks: [inner]
  unselected:
    image: alpine:3.20
    privileged: true
    environment:
      X: ${NOT_SET:?never interpolated}
volumes:
  cachedata: {}
networks:
  inner: {}
"""

DOCKERFILE = """FROM busybox:1.36
RUN mkdir /www && echo hello-from-web > /www/index.html
CMD ["httpd", "-f", "-p", "8080", "-h", "/www"]
"""


@pytest.fixture
def real_svc(monkeypatch):
    # world-readable: the compose file is first read as uid 10000
    base = Path(tempfile.mkdtemp(prefix="svc-it-"))
    os.chmod(base, 0o755)
    ws = base / "ws"
    root = ws / "itest" / "us-1" / "app"
    (root / "web").mkdir(parents=True)
    (root / "docker-compose.yml").write_text(COMPOSE)
    (root / "web" / "Dockerfile").write_text(DOCKERFILE)
    for dirpath, dirs, files in os.walk(base):
        for name in dirs:
            os.chmod(os.path.join(dirpath, name), 0o755)
        for name in files:
            os.chmod(os.path.join(dirpath, name), 0o644)
    run = base / "run"
    run.mkdir(mode=0o700)
    monkeypatch.setenv("SVC_WORKSPACE", str(ws))
    monkeypatch.setenv("SVC_RUN_DIR", str(run))
    monkeypatch.setenv("KEMUDI_SVC_KEY", secrets.token_hex(16))
    mod = load("kemudi_svc_docker_test", "svc.py")
    yield mod
    try:
        mod.op_svc_down({"project": "itest-us1"})
        mod.docker(["image", "rm", "kemudi-itest-us1-web"], 60)
    finally:
        sys.modules.pop("kemudi_svc_docker_test", None)
        shutil.rmtree(base, ignore_errors=True)


def get(url: str, seconds: float = 30) -> str:
    deadline = time.time() + seconds
    while True:
        try:
            with urllib.request.urlopen(url, timeout=5) as r:
                return r.read().decode()
        except OSError:
            if time.time() > deadline:
                raise
            time.sleep(1)


def test_up_exec_logs_stats_down(real_svc):
    svc = real_svc
    greeting = "hi-" + secrets.token_hex(6)
    res = svc.op_svc_up({"path": "itest/us-1/app", "project": "itest-us1", "services": ["web"],
                         "expose": "web:8080", "env": {"GREETING": greeting}})
    assert res["ok"], res
    assert res["services"] == ["web", "cache"] and res["built"] == ["web"]
    assert get(res["url"]).strip() == "hello-from-web"

    final = json.loads((svc.RUN_DIR / "itest-us1" / "compose.json").read_text())
    assert final["services"]["web"]["environment"]["GREETING"] == greeting
    assert not (svc.RUN_DIR / "itest-us1" / "vault.env").exists()

    out = svc.op_svc_exec({"project": "itest-us1", "service": "web",
                           "argv": ["sh", "-c", "echo got $GREETING $EXTRA; exit 3"],
                           "env": {"EXTRA": "extra-value"}, "timeout": 120,
                           "redact": [greeting]})
    assert out["exit"] == 3 and not out["ok"]
    assert "got [redacted] [redacted]" in out["output"]

    code, ps, _ = svc.docker(["ps", "--filter", "label=kemudi.project=itest-us1",
                              "--format", "{{.Names}}"], 60)
    assert code == 0 and len(ps.split()) == 2  # the run container is gone

    stats = svc.op_svc_stats({"project": "itest-us1"})["stats"]
    assert {s["service"] for s in stats} == {"web", "cache"}
    assert all(s["mem_limit_bytes"] <= 2 * 1024 ** 3 for s in stats)

    logs = svc.op_svc_logs({"project": "itest-us1", "service": "cache"})["logs"]
    assert "Ready to accept connections" in logs

    assert svc.op_svc_down({"project": "itest-us1"})["ok"]
    _, left, _ = svc.docker(["ps", "-a", "-q", "--filter", "label=kemudi.project=itest-us1"], 60)
    _, vols, _ = svc.docker(["volume", "ls", "-q", "--filter",
                             "label=com.docker.compose.project=itest-us1"], 60)
    assert left.split() == [] and vols.split() == []

    # a refused key in a started service never reaches Docker
    with pytest.raises(svc.Refused, match="'privileged'"):
        svc.op_svc_up({"path": "itest/us-1/app", "project": "itest-us1",
                       "services": ["unselected"]})
