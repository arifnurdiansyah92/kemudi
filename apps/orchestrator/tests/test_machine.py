from pathlib import Path

from kemudi_ai.api import app
from kemudi_ai.awak import agent_api, config_store, machine, ssh
from kemudi_ai.store import AwakKey, AwakProject, Decision

from .conftest import ADMIN, MEMBER

SSH_SETTINGS = {"enabled": False, "merge_mode": "approve", "deploy_command": "",
                "executor": "ssh", "ssh_host": "vps.example.com", "ssh_port": 2222,
                "ssh_user": "deploy"}
GOOD = "cpu=8\nram_kb=16000000\ndisk_kb=100000000\ndocker=27.1.1\narch=x86_64\n"
KH_LINE = ("[vps.example.com]:2222 ssh-ed25519 "
           "AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl\n")


def test_parse_probe_and_slots():
    p = machine.evaluate(machine.parse_probe(GOOD))
    assert p.ok and p.slots == 2 and p.problems == []
    assert p.cpu == 8 and p.ram_gb == 16.0 and p.disk_gb == 100.0 and p.docker == "27.1.1"
    assert p.arch == "x86_64"

    p = machine.evaluate(machine.parse_probe(GOOD.replace("docker=27.1.1", "docker=none")))
    assert not p.ok and p.docker is None
    assert any("Docker" in x for x in p.problems)

    p = machine.evaluate(machine.parse_probe(GOOD.replace("cpu=8", "cpu=2")))
    assert p.slots == 0 and not p.ok
    assert any("CPU" in x for x in p.problems)


def test_parse_probe_tolerates_banner_lines():
    text = ("Welcome to Ubuntu 24.04 LTS\n * Documentation: https://help.ubuntu.com\n"
            "Last login: x=y from 10.0.0.1\nfoo=bar\n" + GOOD + "nonsense\n")
    facts = machine.parse_probe(text)
    assert set(facts) == {"cpu", "ram_kb", "disk_kb", "docker", "arch"}  # unknown keys dropped
    p = machine.evaluate(facts)
    assert p.ok and p.slots == 2
    # junk values do not crash, they become unknown
    p = machine.evaluate({"cpu": "lots", "ram_kb": "?", "disk_kb": "", "docker": "27"})
    assert p.cpu is None and p.ram_gb is None and p.disk_gb is None and not p.ok


def _ssh_project(client):
    r = client.put("/projects/demo/agent/settings", headers=ADMIN, json=SSH_SETTINGS)
    assert r.status_code == 200, r.text
    r = client.post("/projects/demo/agent/machine/key", headers=ADMIN)
    assert r.status_code == 200, r.text
    return r.json()


def test_machine_key_endpoint(agent_client):
    assert agent_client.post("/projects/demo/agent/machine/key",
                             headers=MEMBER).status_code == 403
    first = _ssh_project(agent_client)
    assert set(first) == {"public_key", "fingerprint"}
    assert first["public_key"].startswith("ssh-ed25519 ")
    assert "PRIVATE" not in str(first)
    body = agent_client.get("/projects/demo/agent/settings", headers=MEMBER).json()
    assert body["ssh_public_key"] == first["public_key"]
    assert body["ssh_fingerprint"] == first["fingerprint"]
    with agent_client.S() as db:
        p = db.get(AwakProject, "demo")
        key = config_store.key_row(db, p.ssh_key_id)
        assert key.owner_kind == "machine" and key.public_key == first["public_key"]
        d = db.query(Decision).filter_by(action="awak_machine_key").one()
        assert "PRIVATE" not in str(d.detail)
    # regenerate replaces the old key row
    second = agent_client.post("/projects/demo/agent/machine/key", headers=ADMIN).json()
    assert second["fingerprint"] != first["fingerprint"]
    with agent_client.S() as db:
        assert db.query(AwakKey).filter_by(owner_kind="machine").count() == 1


def test_machine_key_needs_secret_key(agent_client):
    agent_client.settings.secret_key = ""
    r = agent_client.post("/projects/demo/agent/machine/key", headers=ADMIN)
    assert r.status_code == 503 and "KEMUDI_SECRET_KEY" in r.text


def test_check_ssh_argv(agent_client):
    seen = []

    def fake(argv, env, timeout):
        key_path = Path(argv[argv.index("-i") + 1])
        seen.append((argv, key_path, key_path.exists(), timeout))
        kh = ssh.known_hosts_path(agent_client.settings, "demo")
        kh.write_text(KH_LINE)  # what accept-new would record
        return 0, "banner\n" + GOOD

    app.dependency_overrides[agent_api.get_command_runner] = lambda: fake
    _ssh_project(agent_client)
    r = agent_client.post("/projects/demo/agent/machine/check", headers=ADMIN)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] and body["slots"] == 2 and body["error"] is None
    assert body["host_key"].startswith("SHA256:") and body["executor"] == "ssh"
    argv, key_path, existed, timeout = seen[0]
    joined = " ".join(argv)
    assert "BatchMode=yes" in joined and "StrictHostKeyChecking=accept-new" in joined
    assert "HashKnownHosts=no" in joined
    kh = ssh.known_hosts_path(agent_client.settings, "demo")
    assert f"UserKnownHostsFile={kh}" in argv
    assert argv[argv.index("-p") + 1] == "2222"
    assert argv[-2] == "deploy@vps.example.com" and argv[-1] == machine.PROBE
    assert existed and not key_path.exists() and timeout == 20
    # saved on the project and shown by GET settings
    pre = agent_client.get("/projects/demo/agent/settings", headers=MEMBER).json()["preflight"]
    assert pre["ok"] and pre["slots"] == 2 and pre["checked_at"]
    with agent_client.S() as db:
        assert db.query(Decision).filter_by(action="awak_machine_check").count() == 1


def test_check_ssh_unreachable(agent_client):
    paths = []

    def fake(argv, env, timeout):
        key_path = argv[argv.index("-i") + 1]
        paths.append(key_path)
        return 255, f"Warning: Identity file {key_path} ...\nssh: connect to host " \
                    "vps.example.com port 2222: Connection refused\n"

    app.dependency_overrides[agent_api.get_command_runner] = lambda: fake
    _ssh_project(agent_client)
    body = agent_client.post("/projects/demo/agent/machine/check", headers=ADMIN).json()
    assert body["ok"] is False and body["error"]
    assert "cannot connect" in body["error"]
    assert paths[0] not in body["error"] and "PRIVATE" not in str(body)
    assert body["slots"] == 0


def test_host_key_mismatch_message(agent_client):
    def fake(argv, env, timeout):
        return 255, ("@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@\n"
                     "@    WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!     @\n"
                     "Host key verification failed.\n")

    app.dependency_overrides[agent_api.get_command_runner] = lambda: fake
    _ssh_project(agent_client)
    body = agent_client.post("/projects/demo/agent/machine/check", headers=ADMIN).json()
    assert not body["ok"]
    assert "host key" in body["error"].lower() and "forget" in body["error"].lower()


def test_check_ssh_without_key_is_409(agent_client):
    agent_client.put("/projects/demo/agent/settings", headers=ADMIN, json=SSH_SETTINGS)
    r = agent_client.post("/projects/demo/agent/machine/check", headers=ADMIN)
    assert r.status_code == 409


def test_changing_host_forgets_host_key(agent_client):
    _ssh_project(agent_client)
    kh = ssh.known_hosts_path(agent_client.settings, "demo")
    kh.parent.mkdir(parents=True, exist_ok=True)
    kh.write_text(KH_LINE + "github.com ssh-ed25519 "
                  "AAAAC3NzaC1lZDI1NTE5AAAAIOMqqnkVzrm0SdG6UOoqKLsabgH5C9okWi0dh2l9GKJl\n")
    with agent_client.S() as db:
        db.get(AwakProject, "demo").preflight = {"ok": True, "slots": 2}
        db.commit()
    r = agent_client.put("/projects/demo/agent/settings", headers=ADMIN,
                         json={**SSH_SETTINGS, "ssh_host": "vps2.example.com"})
    assert r.status_code == 200
    assert "vps.example.com" not in kh.read_text() and "github.com" in kh.read_text()
    assert r.json()["preflight"] == {}  # an old machine's check says nothing about the new one


def test_forget_host_key_endpoint(agent_client):
    _ssh_project(agent_client)
    kh = ssh.known_hosts_path(agent_client.settings, "demo")
    kh.parent.mkdir(parents=True, exist_ok=True)
    kh.write_text(KH_LINE)
    url = "/projects/demo/agent/machine/host-key"
    assert agent_client.delete(url, headers=MEMBER).status_code == 403
    assert agent_client.delete(url, headers=ADMIN).status_code == 204
    assert ssh.host_key_fingerprint(kh, "vps.example.com") is None
    with agent_client.S() as db:
        assert db.query(Decision).filter_by(action="awak_machine_forget_host").count() == 1


def test_check_local_runs_on_windows(agent_settings, tmp_path):
    p = machine.check_local(agent_settings, lambda: True,
                            meminfo=tmp_path / "no-proc" / "meminfo",
                            cgroup_memory=tmp_path / "no-cgroup")
    assert p.ram_gb is None and p.cpu and p.disk_gb is not None
    assert p.docker == "runner" and not p.ok
    assert any("unknown" in x for x in p.problems)
    p = machine.check_local(agent_settings, lambda: False,
                            meminfo=tmp_path / "no-proc" / "meminfo",
                            cgroup_memory=tmp_path / "no-cgroup")
    assert p.docker is None and any("runner" in x for x in p.problems)


def test_check_local_reads_meminfo_and_cgroup(agent_settings, tmp_path):
    mi = tmp_path / "meminfo"
    mi.write_text("MemTotal:       32000000 kB\nMemFree: 1 kB\n")
    cg = tmp_path / "memory.max"
    cg.write_text("8000000000\n")
    p = machine.check_local(agent_settings, lambda: True, meminfo=mi, cgroup_memory=cg)
    assert p.ram_gb == 8.0  # the container limit wins
    cg.write_text("max\n")
    p = machine.check_local(agent_settings, lambda: True, meminfo=mi, cgroup_memory=cg)
    assert p.ram_gb == 32.0


def test_check_local_endpoint(agent_client):
    app.dependency_overrides[agent_api.get_runner_health] = lambda: (lambda: True)
    r = agent_client.post("/projects/demo/agent/machine/check", headers=ADMIN)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["executor"] == "local" and body["docker"] == "runner"
    assert agent_client.post("/projects/demo/agent/machine/check",
                             headers=MEMBER).status_code == 403
