"""kemudi-runner's marketplace fetch: one GitHub repo at a full commit sha.

Run by the runner as a child (uid 10000, clean environment, no Kemudi
secrets), never by the server itself:

    python -I fetch.py '{"owner": ..., "repo": ..., "ref": ..., "dest": ...}'

prints one JSON line: {"sha", "files", "bytes", "skipped"} or {"error"}.

- GitHub only: `ref` (default branch when empty) is resolved to a full sha
  with `https://api.github.com/repos/<o>/<r>/commits/<ref>` (no token), then
  `https://codeload.github.com/<o>/<r>/tar.gz/<sha>` is streamed with a
  byte cap. Connections go only to those two hosts, over HTTPS, to public
  addresses; a redirect anywhere else is refused; no proxy is used.
- Extraction into `dest` (a new folder) takes regular files and folders
  only, each path checked (no absolute paths, no `..`), every folder on the
  way lstat-checked, every file created with O_EXCL | O_NOFOLLOW. Symlinks,
  hardlinks and special files are skipped and listed; files over
  MAX_FILE_BYTES are skipped; more than MAX_ENTRIES entries or
  MAX_EXTRACT_BYTES bytes fails the fetch.

Python stdlib only.
"""

from __future__ import annotations

import http.client
import ipaddress
import json
import os
import re
import shutil
import socket
import ssl
import stat
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
import zlib
from pathlib import Path
from urllib.parse import quote, urlsplit

API_HOST = "api.github.com"
CODELOAD_HOST = "codeload.github.com"
ALLOWED_HOSTS = frozenset({API_HOST, CODELOAD_HOST})

OWNER_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")
REPO_RE = re.compile(r"[A-Za-z0-9._-]{1,100}")
REF_RE = re.compile(r"[A-Za-z0-9._/-]{1,200}")
SHA_RE = re.compile(r"[0-9a-f]{40}")

MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024
MAX_EXTRACT_BYTES = 200 * 1024 * 1024
MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_ENTRIES = 20_000
MAX_DEPTH = 24
MAX_SKIPPED_LISTED = 200
SOCKET_TIMEOUT = 30
DEADLINE = 240  # seconds for the whole fetch
CHUNK = 64 * 1024
USER_AGENT = "kemudi-runner-skills-fetch"


class FetchError(Exception):
    """The fetch failed; the message is shown to the admin."""


# --- arguments ---------------------------------------------------------------

def check_args(owner: str, repo: str, ref: str) -> None:
    """Raises ValueError for a name GitHub would not have (or a path trick)."""
    if not isinstance(owner, str) or not OWNER_RE.fullmatch(owner):
        raise ValueError(f"bad GitHub owner {owner!r}")
    if (not isinstance(repo, str) or not REPO_RE.fullmatch(repo) or repo in (".", "..")
            or repo.endswith(".git")):
        raise ValueError(f"bad GitHub repository name {repo!r}")
    if not isinstance(ref, str):
        raise ValueError("ref must be text")
    if ref and (not REF_RE.fullmatch(ref) or ref.startswith(("-", "/", "."))
                or ref.endswith(("/", ".lock")) or ".." in ref or "//" in ref):
        raise ValueError(f"bad git ref {ref!r}")


# --- HTTPS to GitHub only ------------------------------------------------------

def _public_addr(host: str, port: int) -> tuple[int, tuple]:
    """The first public address of `host` (no private, loopback, link-local
    or reserved ones: DNS must not point the fetch inside)."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError as e:
        raise FetchError(f"cannot resolve {host}: {e}") from e
    for family, _, _, _, addr in infos:
        try:
            ip = ipaddress.ip_address(addr[0])
        except ValueError:
            continue
        if ip.is_global:
            return family, addr
    raise FetchError(f"{host} resolves to no public address")


class _GuardedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS to an allowed host only, at a public address it resolved itself."""

    def connect(self):  # noqa: D401 - http.client API
        if self.host not in ALLOWED_HOSTS or self.port != 443:
            raise FetchError(f"connection to {self.host}:{self.port} refused")
        family, addr = _public_addr(self.host, self.port)
        sock = socket.socket(family, socket.SOCK_STREAM)
        sock.settimeout(self.timeout if isinstance(self.timeout, (int, float)) else SOCKET_TIMEOUT)
        try:
            sock.connect(addr)
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


class _HTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self):
        super().__init__(context=ssl.create_default_context())

    def https_open(self, req):
        return self.do_open(_GuardedHTTPSConnection, req, context=self._context)


class _Redirects(urllib.request.HTTPRedirectHandler):
    """Redirects stay on the allowed hosts, over HTTPS (GitHub redirects a
    renamed repo's API calls to api.github.com/repositories/<id>/...)."""

    max_redirections = 3

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def check_url(url: str) -> None:
    u = urlsplit(url)
    if u.scheme != "https" or u.hostname not in ALLOWED_HOSTS or u.port not in (None, 443) \
            or u.username or u.password:
        raise FetchError(f"refused to follow {u.scheme}://{u.hostname}: only "
                         f"{' and '.join(sorted(ALLOWED_HOSTS))} over HTTPS")


def _refuse_http(*_a, **_k):
    raise FetchError("plain HTTP is refused")


class _NoHTTP(urllib.request.HTTPHandler):
    http_open = _refuse_http


class _NoFile(urllib.request.FileHandler):
    file_open = _refuse_http


class _NoFTP(urllib.request.FTPHandler):
    ftp_open = _refuse_http


class _NoData(urllib.request.DataHandler):
    data_open = _refuse_http


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), _HTTPSHandler(),
                                      _Redirects(), _NoHTTP(), _NoFile(), _NoFTP(), _NoData())


def default_urlopen(url: str, headers: dict, timeout: float):
    check_url(url)
    return _OPENER.open(urllib.request.Request(url, headers=headers), timeout=timeout)


# --- GitHub ----------------------------------------------------------------------

def _http_error(e: urllib.error.HTTPError, what: str) -> FetchError:
    h = e.headers or {}
    if e.code == 429 or (e.code == 403 and h.get("X-RateLimit-Remaining") == "0"):
        reset = h.get("X-RateLimit-Reset")
        when = ""
        if reset and reset.isdigit():
            when = " after " + time.strftime("%H:%M UTC", time.gmtime(int(reset)))
        return FetchError(f"GitHub's API rate limit was reached (60 requests an hour per "
                          f"address without a token); try again{when}")
    if e.code in (404, 422):
        return FetchError(f"{what} not found: the repository is missing or private, or the "
                          "ref does not exist")
    if e.code == 451:
        return FetchError(f"{what} is unavailable (blocked for legal reasons)")
    return FetchError(f"GitHub answered {e.code} for {what}")


def resolve_sha(owner: str, repo: str, ref: str, urlopen=default_urlopen) -> str:
    """`ref` (branch, tag, sha; empty = the default branch) as a full commit sha."""
    if SHA_RE.fullmatch(ref or ""):
        return ref
    url = (f"https://{API_HOST}/repos/{owner}/{repo}/commits/"
           f"{quote(ref or 'HEAD', safe='/')}")
    headers = {"Accept": "application/vnd.github.sha", "User-Agent": USER_AGENT,
               "X-GitHub-Api-Version": "2022-11-28"}
    try:
        with urlopen(url, headers, SOCKET_TIMEOUT) as r:
            body = r.read(200).decode("ascii", errors="replace").strip()
    except urllib.error.HTTPError as e:
        raise _http_error(e, f"{owner}/{repo}@{ref or 'default branch'}") from e
    except FetchError:
        raise
    except (urllib.error.URLError, OSError) as e:
        raise FetchError(f"cannot reach GitHub: {getattr(e, 'reason', e)}") from e
    if not SHA_RE.fullmatch(body):
        raise FetchError("GitHub did not answer with a commit sha")
    return body


def download(owner: str, repo: str, sha: str, out, urlopen=default_urlopen,
             cap: int = MAX_DOWNLOAD_BYTES, deadline: float | None = None) -> int:
    """Stream the tarball of `sha` into the file `out`; returns its size."""
    url = f"https://{CODELOAD_HOST}/{owner}/{repo}/tar.gz/{sha}"
    deadline = deadline or time.monotonic() + DEADLINE
    try:
        with urlopen(url, {"User-Agent": USER_AGENT}, SOCKET_TIMEOUT) as r:
            length = (r.headers.get("Content-Length") or "") if r.headers else ""
            if length.isdigit() and int(length) > cap:
                raise FetchError(f"the repository archive is larger than {cap // 2**20} MB")
            total = 0
            while chunk := r.read(CHUNK):
                total += len(chunk)
                if total > cap:
                    raise FetchError(f"the repository archive is larger than {cap // 2**20} MB")
                if time.monotonic() > deadline:
                    raise FetchError("the download took too long")
                out.write(chunk)
    except urllib.error.HTTPError as e:
        raise _http_error(e, f"{owner}/{repo}@{sha[:12]}") from e
    except FetchError:
        raise
    except (urllib.error.URLError, OSError) as e:
        raise FetchError(f"the download failed: {getattr(e, 'reason', e)}") from e
    return total


# --- extraction ----------------------------------------------------------------------

_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_BINARY = getattr(os, "O_BINARY", 0)
_BAD_CHARS = re.compile(r"[\x00-\x1f\x7f\\]")


def _ensure_dirs(root: Path, parts: list[str]) -> Path:
    """root/parts..., every folder created if missing and lstat-checked (a
    symlink planted on the way stops the fetch)."""
    p = root
    for part in parts:
        p = p / part
        try:
            os.mkdir(p, 0o755)
        except FileExistsError:
            pass
        if not stat.S_ISDIR(os.lstat(p).st_mode):
            raise FetchError(f"{p.relative_to(root).as_posix()}: not a plain folder")
    return p


def _kind(m: tarfile.TarInfo) -> str:
    if m.issym():
        return "symlink"
    if m.islnk():
        return "hardlink"
    return "special file"


def extract(fileobj, dest: Path, expect_sha: str | None = None) -> dict:
    """The gzip tarball in `fileobj` into `dest` (an existing, empty folder),
    without its single top folder. Returns {files, bytes, skipped}."""
    files = total = entries = 0
    skipped: list[dict] = []
    top: str | None = None
    checked_sha = False

    def skip(path: str, reason: str) -> None:
        if len(skipped) < MAX_SKIPPED_LISTED:
            skipped.append({"path": path, "reason": reason})

    try:
        tf = tarfile.open(fileobj=fileobj, mode="r|gz")
    except (tarfile.TarError, OSError, EOFError) as e:
        raise FetchError(f"the archive is not a gzip tarball: {e}") from e
    with tf:
        try:
            for m in tf:
                entries += 1
                if entries > MAX_ENTRIES:
                    raise FetchError(f"the repository has more than {MAX_ENTRIES} entries")
                if expect_sha and not checked_sha:
                    checked_sha = True
                    comment = tf.pax_headers.get("comment")
                    if comment and comment != expect_sha:
                        raise FetchError("the archive is not the commit asked for")
                name = m.name
                if name.startswith("/") or ".." in name.split("/"):
                    raise FetchError(f"unsafe path in the archive: {name[:200]!r}")
                parts = [p for p in name.split("/") if p not in ("", ".")]
                if not parts:
                    continue
                if top is None:
                    top = parts[0]
                if parts[0] != top:
                    raise FetchError("the archive has more than one top folder")
                parts = parts[1:]
                if not parts:
                    continue
                rel = "/".join(parts)
                if _BAD_CHARS.search(rel) or any(len(p) > 255 for p in parts):
                    skip(rel[:300], "unusual name")
                    continue
                if len(parts) > MAX_DEPTH:
                    skip(rel[:300], "nested too deep")
                    continue
                if m.isdir():
                    _ensure_dirs(dest, parts)
                elif m.isreg():
                    if m.size > MAX_FILE_BYTES:
                        skip(rel, f"larger than {MAX_FILE_BYTES // 2**20} MB")
                        continue
                    total += m.size
                    if total > MAX_EXTRACT_BYTES:
                        raise FetchError(f"the repository holds more than "
                                         f"{MAX_EXTRACT_BYTES // 2**20} MB of files")
                    parent = _ensure_dirs(dest, parts[:-1])
                    src = tf.extractfile(m)
                    fd = os.open(parent / parts[-1],
                                 os.O_WRONLY | os.O_CREAT | os.O_EXCL | _O_NOFOLLOW | _O_BINARY,
                                 0o644)
                    with os.fdopen(fd, "wb") as out:
                        left = m.size
                        while left > 0:
                            chunk = src.read(min(CHUNK, left))
                            if not chunk:
                                raise FetchError(f"{rel}: the archive ends early")
                            out.write(chunk)
                            left -= len(chunk)
                    files += 1
                else:
                    skip(rel, _kind(m))
        except FileExistsError as e:
            raise FetchError(f"a path appears twice in the archive: {e.filename}") from e
        except (tarfile.TarError, EOFError, zlib.error) as e:
            raise FetchError(f"the archive is damaged: {e}") from e
    return {"files": files, "bytes": total, "skipped": skipped}


# --- one fetch ---------------------------------------------------------------------------

STALE_SECONDS = 3600
DIR_RE = re.compile(r"[0-9a-f]{32}")


def sweep(base: Path, keep: str = "", now: float | None = None) -> list[str]:
    """Remove fetch folders older than an hour (left by a crash)."""
    now = time.time() if now is None else now
    removed = []
    try:
        names = os.listdir(base)
    except OSError:
        return removed
    for name in names:
        if name == keep or not DIR_RE.fullmatch(name):
            continue
        p = base / name
        try:
            st = os.lstat(p)
        except OSError:
            continue
        if now - st.st_mtime < STALE_SECONDS:
            continue
        if stat.S_ISDIR(st.st_mode):
            shutil.rmtree(p, ignore_errors=True)
        else:
            try:
                os.unlink(p)
            except OSError:
                continue
        removed.append(name)
    return removed


def fetch(owner: str, repo: str, ref: str, dest: Path, urlopen=default_urlopen) -> dict:
    """Resolve, download and extract into `dest` (created here; its parent
    must exist and be a plain folder). On failure `dest` is removed."""
    check_args(owner, repo, ref)
    deadline = time.monotonic() + DEADLINE
    base = dest.parent
    _ensure_dirs(base.parent, [base.name])
    sweep(base, keep=dest.name)
    os.mkdir(dest, 0o755)
    try:
        sha = resolve_sha(owner, repo, ref, urlopen)
        with tempfile.TemporaryFile() as tmp:
            download(owner, repo, sha, tmp, urlopen, deadline=deadline)
            tmp.seek(0)
            res = extract(tmp, dest, expect_sha=sha)
        return {"sha": sha, **res}
    except BaseException:
        shutil.rmtree(dest, ignore_errors=True)
        raise


def main(argv: list[str]) -> int:
    try:
        args = json.loads(argv[1])
        res = fetch(str(args["owner"]), str(args["repo"]), str(args.get("ref") or ""),
                    Path(args["dest"]))
    except (FetchError, ValueError) as e:
        res = {"error": str(e)}
    except Exception as e:  # noqa: BLE001 - reported to the admin
        res = {"error": f"{type(e).__name__}: {e}"}
    print(json.dumps(res), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
