"""Execution machine preflight: CPU, RAM, disk and Docker against the
per-job minimum (4 vCPU, 8 GB RAM, 40 GB free disk, measured in iteration 1).

Over SSH it runs one fixed probe script (nothing the admin types reaches the
remote shell) with the system `ssh`, the machine key and the project's
known_hosts. Jobs still run on `local` until remote execution ships; the
machine is only checked and used for the deploy command.
"""

import os
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from ..config import Settings
from . import secrets, ssh
from .ssh import CommandRunner

MIN_PER_JOB = {"cpu": 4, "ram_gb": 8, "disk_gb": 40}
PROBE = ("echo cpu=$(nproc); awk '/MemTotal/{print \"ram_kb=\"$2}' /proc/meminfo; "
         "echo disk_kb=$(df -Pk . | awk 'NR==2{print $4}'); "
         "echo docker=$(docker version --format '{{.Server.Version}}' 2>/dev/null || echo none); "
         "echo arch=$(uname -m)")
PROBE_KEYS = ("cpu", "ram_kb", "disk_kb", "docker", "arch")
SSH_TIMEOUT = 20
_LINE = re.compile(r"^(cpu|ram_kb|disk_kb|docker|arch)=(.*)$")


@dataclass
class Preflight:
    ok: bool
    cpu: int | None
    ram_gb: float | None
    disk_gb: float | None
    docker: str | None
    arch: str | None
    slots: int
    problems: list[str] = field(default_factory=list)
    host_key: str | None = None
    checked_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    error: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["checked_at"] = self.checked_at.isoformat()
        d["minimum"] = dict(MIN_PER_JOB)
        return d


def parse_probe(text: str) -> dict:
    """key=value lines of the probe; banners, MOTD and unknown keys are ignored."""
    facts = {}
    for line in text.splitlines():
        m = _LINE.match(line.strip())
        if m:
            facts[m.group(1)] = m.group(2).strip()
    return facts


def _int(v) -> int | None:
    try:
        n = int(str(v).strip())
    except (TypeError, ValueError):
        return None
    return n if n >= 0 else None


def _gb(kb) -> float | None:
    n = _int(kb)
    return None if n is None else round(n / 1_000_000, 1)


def evaluate(facts: dict) -> Preflight:
    """Facts (cpu, ram_kb, disk_kb, docker, arch) -> verdict and job slots.

    slots = min(cpu // 4, ram_gb // 8, disk_gb // 40) over the known values;
    a value that could not be read is a problem, so the check is not ok.
    """
    cpu = _int(facts.get("cpu"))
    cpu = cpu if cpu else None
    ram_gb = _gb(facts.get("ram_kb"))
    disk_gb = _gb(facts.get("disk_kb"))
    docker = (facts.get("docker") or "").strip() or None
    if docker in ("none", "None"):
        docker = None
    arch = (facts.get("arch") or "").strip() or None

    problems: list[str] = []
    per: list[int] = []
    for label, value, minimum, unit in (
        ("CPU", cpu, MIN_PER_JOB["cpu"], "vCPU"),
        ("RAM", ram_gb, MIN_PER_JOB["ram_gb"], "GB"),
        ("Disk", disk_gb, MIN_PER_JOB["disk_gb"], "GB free"),
    ):
        if value is None:
            problems.append(f"{label}: unknown (could not be read)")
            continue
        per.append(int(value // minimum))
        if value < minimum:
            problems.append(f"{label}: {value:g} {unit}, a job needs {minimum} {unit}")
    if docker is None and "docker" in facts:
        problems.append("Docker: not installed or not reachable by this user")
    elif docker is None:
        problems.append("Docker: unknown (could not be read)")
    slots = min(per) if per else 0
    return Preflight(ok=not problems and slots >= 1, cpu=cpu, ram_gb=ram_gb, disk_gb=disk_gb,
                     docker=docker, arch=arch, slots=slots, problems=problems)


# --- local -------------------------------------------------------------------


def _meminfo_kb(path: Path) -> int | None:
    try:
        for line in path.read_text().splitlines():
            if line.startswith("MemTotal:"):
                return _int(line.split()[1])
    except (OSError, IndexError):
        return None
    return None


def _cgroup_kb(path: Path) -> int | None:
    """The container's memory limit (cgroup v2 memory.max), "max" = none."""
    try:
        raw = path.read_text().strip()
    except OSError:
        return None
    n = _int(raw)
    return None if n is None else n // 1000


def _disk_kb(path: Path) -> int | None:
    p = path
    while not p.exists() and p.parent != p:
        p = p.parent
    try:
        return shutil.disk_usage(p).free // 1000
    except OSError:
        return None


def check_local(settings: Settings, runner_ok: Callable[[], bool],
                meminfo: Path = Path("/proc/meminfo"),
                cgroup_memory: Path = Path("/sys/fs/cgroup/memory.max")) -> Preflight:
    """The orchestrator's own host. Docker means the runner sandbox answers."""
    ram = [v for v in (_meminfo_kb(meminfo), _cgroup_kb(cgroup_memory)) if v]
    try:
        alive = bool(runner_ok())
    except Exception:  # noqa: BLE001 - a dead runner is a finding, not a crash
        alive = False
    facts = {
        "cpu": os.cpu_count(),
        "ram_kb": min(ram) if ram else None,
        "disk_kb": _disk_kb(Path(settings.workspace_dir)),
        "docker": "runner" if alive else "none",
        "arch": os.uname().machine if hasattr(os, "uname") else None,
    }
    p = evaluate(facts)
    if not alive:
        p.problems = [x for x in p.problems if not x.startswith("Docker")]
        p.problems.append("Docker: the runner sandbox (kemudi-runner) is not reachable")
        p.ok = False
    return p


# --- ssh ---------------------------------------------------------------------

_MISMATCH = ("REMOTE HOST IDENTIFICATION HAS CHANGED", "Host key verification failed")


def _scrub(text: str, scrub: list[str]) -> str:
    for s in scrub:
        text = text.replace(s, "<key>")
    return secrets.redact(text, secrets.known_values())


def check_ssh(settings: Settings, cfg, key_row, run: CommandRunner) -> Preflight:
    """Run PROBE on `cfg.ssh_user@cfg.ssh_host`; never raises for a dead host."""
    known_hosts = ssh.known_hosts_path(settings, cfg.slug)
    known_hosts.parent.mkdir(parents=True, exist_ok=True)
    target = f"{cfg.ssh_user}@{cfg.ssh_host}"
    with ssh.key_file(settings, key_row) as key_path:
        argv = ssh.ssh_base(key_path, known_hosts, cfg.ssh_port) + [target, PROBE]
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
        code, out = run(argv, env, SSH_TIMEOUT)
        out = _scrub(out, [str(key_path)])
    facts = parse_probe(out)
    host_key = ssh.host_key_fingerprint(known_hosts, cfg.ssh_host)
    if code == 255 or not facts:
        if any(m in out for m in _MISMATCH):
            error = (f"the host key of {cfg.ssh_host} changed since it was first seen; if the "
                     "machine was rebuilt on purpose, forget the host key and check again")
        else:
            last = next((ln.strip() for ln in reversed(out.splitlines()) if ln.strip()), "")
            error = f"cannot connect to {target} port {cfg.ssh_port}"
            if code != 255:
                error = f"the probe on {target} printed nothing usable (exit {code})"
            if last:
                error += f": {last[:200]}"
        return Preflight(ok=False, cpu=None, ram_gb=None, disk_gb=None, docker=None, arch=None,
                         slots=0, problems=[], host_key=host_key, error=error)
    p = evaluate(facts)
    p.host_key = host_key
    return p
