"""SSH plumbing: the system `ssh` binary, a per-project known_hosts, and
decrypted keys that live on disk only for the duration of one command.

No paramiko or asyncssh: git gets the same `ssh` command line through
GIT_SSH_COMMAND, and everything that runs a command goes through a
`CommandRunner` that tests replace.
"""

import base64
import hashlib
import hmac
import os
import re
import shlex
import subprocess
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator
from urllib.parse import urlparse

from ..config import Settings
from . import crypto

# argv, env, timeout (s) -> (exit code, stdout + stderr)
CommandRunner = Callable[[list[str], dict[str, str], int], tuple[int, str]]

_WINDOWS_PATH = re.compile(r"^[A-Za-z]:[\\/]")
# user@host:path (scp-like). The host never starts with "-" (no option injection).
_SCP = re.compile(r"^(?P<user>[A-Za-z0-9._-]+)@(?P<host>[A-Za-z0-9][A-Za-z0-9.-]*|\[[0-9A-Fa-f:.]+\])"
                  r":(?P<path>[^\s]+)$")
_SLUG = re.compile(r"^[A-Za-z0-9._-]+$")


def subprocess_runner(argv: list[str], env: dict[str, str], timeout: int) -> tuple[int, str]:
    try:
        p = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"
    except OSError as e:
        return 127, f"{type(e).__name__}: {e}"


def is_local_url(url: str) -> bool:
    """A path on the orchestrator's filesystem ("/x", "file://", "C:\\x")."""
    return url.startswith(("/", "file://")) or bool(_WINDOWS_PATH.match(url))


def is_ssh_url(url: str) -> bool:
    if url.startswith("ssh://"):
        p = urlparse(url)
        host = p.hostname or ""
        return bool(host) and not host.startswith("-") and bool(p.path.strip("/"))
    return bool(_SCP.match(url))


def url_host(url: str) -> str:
    """The SSH host of a git URL; "" for a local path."""
    if is_local_url(url):
        return ""
    if url.startswith("ssh://"):
        return urlparse(url).hostname or ""
    m = _SCP.match(url)
    return m.group("host").strip("[]") if m else ""


def _key_dir(settings: Settings) -> Path:
    return Path(settings.ssh_dir) / "tmp"


@contextmanager
def key_file(settings: Settings, key_row) -> Iterator[Path]:
    """Decrypt the key to a 0600 file under {ssh_dir}/tmp; always deleted after."""
    private = crypto.decrypt(settings, key_row.private_key_enc)
    d = _key_dir(settings)
    d.mkdir(parents=True, exist_ok=True)
    path = d / uuid.uuid4().hex
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", newline="\n") as fh:
            fh.write(private if private.endswith("\n") else private + "\n")
        yield path
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def ssh_base(key_path: Path, known_hosts: Path, port: int | None = 22) -> list[str]:
    argv = [
        "ssh", "-i", str(key_path),
        "-o", "IdentitiesOnly=yes",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=accept-new",
        "-o", f"UserKnownHostsFile={known_hosts}",
        # Debian's ssh_config hashes known_hosts; keep it readable so the UI can
        # show the fingerprint and a host change can forget the old key.
        "-o", "HashKnownHosts=no",
        "-o", "ConnectTimeout=10",
    ]
    if port is not None:
        argv += ["-p", str(port)]
    return argv


def git_ssh_env(key_path: Path, known_hosts: Path) -> dict[str, str]:
    # No -p: git passes the URL's port itself.
    return {"GIT_SSH_COMMAND": shlex.join(ssh_base(key_path, known_hosts, port=None))}


def known_hosts_path(settings: Settings, slug: str) -> Path:
    if not _SLUG.match(slug):
        raise ValueError(f"bad project slug {slug!r}")
    return Path(settings.ssh_dir) / slug / "known_hosts"


def _host_matches(field: str, host: str) -> bool:
    for name in field.split(","):
        if name.startswith("|1|"):
            try:
                _, _, salt, digest = name.split("|", 3)
                salt_b = base64.b64decode(salt)
                for candidate in (host, f"[{host}]"):
                    mac = hmac.new(salt_b, candidate.encode(), hashlib.sha1).digest()
                    if hmac.compare_digest(base64.b64encode(mac).decode(), digest):
                        return True
            except ValueError:
                continue
        elif name == host or (name.startswith(f"[{host}]:")):
            return True
    return False


def forget_host(settings: Settings, slug: str, host: str) -> None:
    """Drop every known_hosts line for `host` (any port)."""
    if not host:
        return
    path = known_hosts_path(settings, slug)
    if not path.exists():
        return
    kept = [line for line in path.read_text().splitlines()
            if not (line.split() and _host_matches(line.split()[0], host))]
    path.write_text("".join(f"{line}\n" for line in kept))


def host_key_fingerprint(known_hosts: Path, host: str) -> str | None:
    """SHA256 fingerprint of the first stored key for `host`, if any."""
    if not host or not known_hosts.exists():
        return None
    for line in known_hosts.read_text().splitlines():
        parts = line.split()
        if len(parts) >= 3 and not line.startswith("#") and _host_matches(parts[0], host):
            try:
                return crypto.fingerprint(f"{parts[1]} {parts[2]}")
            except ValueError:
                continue
    return None
