"""A GitHub repo fetched by kemudi-runner (`fetch_repo`), read from the
kemudi-skills-fetch volume.

docs/superpowers/plans/2026-11-14-awak-skills-pr3-marketplace.md, Task 1.
The runner's fetch child (its own uid, `skills_fetch_uid`, no Kemudi
secrets) downloads and extracts the repo into `<skills_fetch_dir>/<hex>/`;
the orchestrator only reads files there (the volume is read-only here),
never runs anything. The volume is mounted only in kemudi-runner and here,
never in the workspace that project code and Hermes write.

Every read is checked three ways:
- the base folder belongs to root (or the fetch uid) and the fetch folder
  and every folder on the way belong to the fetch uid, none writable by
  others (POSIX);
- each path component is lstat-checked (plain folders, a regular file at
  the end, opened with O_NOFOLLOW): a symlink is refused, never followed;
- the bytes read must match the sha256 the fetch child reported for that
  path in its manifest, and a folder read must hold exactly the manifest's
  files under it.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from ..config import Settings
from .runner import Runner, RunnerError

log = logging.getLogger(__name__)

FETCH_DIR_RE = re.compile(r"[0-9a-f]{32}")
SHA_RE = re.compile(r"[0-9a-f]{40}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_BINARY = getattr(os, "O_BINARY", 0)
_POSIX = os.name == "posix"


class FetchError(Exception):
    """The repo could not be fetched or read; the message is for the admin."""


class TreeError(FetchError):
    """A path in the fetched tree is not a plain file or folder."""


def _size(n: int) -> str:
    return f"{n // 2**20} MB" if n >= 2**20 and n % 2**20 == 0 else f"{n} bytes"


def _parts(path: str) -> list[str]:
    """`path` (posix, relative; '' = the root) as parts; refuses tricks."""
    if path in ("", "."):
        return []
    if path.startswith("/") or "\\" in path or "\x00" in path:
        raise TreeError(f"{path!r}: not a relative path")
    parts = [p for p in PurePosixPath(path).parts if p != "."]
    if any(p == ".." for p in parts):
        raise TreeError(f"{path!r}: '..' is not allowed")
    return parts


@dataclass
class Tree:
    """Read-only access to one fetched repo."""

    root: Path
    sha: str
    skipped: list[dict] = field(default_factory=list)
    # {path: sha256} of every file the fetch child extracted
    manifest: dict[str, str] = field(default_factory=dict)
    # the fetch listed only the first skipped entries
    skipped_truncated: bool = False
    # owner every folder must have (None: not checked)
    uid: int | None = None

    def _check_owner(self, st: os.stat_result, rel: str) -> None:
        if self.uid is not None and st.st_uid != self.uid:
            raise TreeError(f"{rel or '/'}: not written by the fetch")

    def _lstat(self, parts: list[str]) -> os.stat_result | None:
        """lstat of root/parts, every folder on the way checked; None if missing."""
        p = self.root
        for i, part in enumerate(parts):
            p = p / part
            try:
                st = os.lstat(p)
            except (FileNotFoundError, NotADirectoryError):
                return None
            except OSError as e:
                raise TreeError(f"{'/'.join(parts[:i + 1])}: {e.strerror or e}") from e
            if stat.S_ISLNK(st.st_mode):
                raise TreeError(f"{'/'.join(parts[:i + 1])}: a symlink")
            if i < len(parts) - 1:
                if not stat.S_ISDIR(st.st_mode):
                    return None
                self._check_owner(st, "/".join(parts[:i + 1]))
        if not parts:
            try:
                st = os.lstat(self.root)
            except OSError as e:
                raise TreeError(f"the fetched tree is gone: {e.strerror or e}") from e
        if stat.S_ISDIR(st.st_mode):
            self._check_owner(st, "/".join(parts))
        return st

    def is_file(self, path: str) -> bool:
        st = self._lstat(_parts(path))
        return st is not None and stat.S_ISREG(st.st_mode)

    def is_dir(self, path: str) -> bool:
        st = self._lstat(_parts(path))
        return st is not None and stat.S_ISDIR(st.st_mode)

    def listdir(self, path: str = "") -> list[tuple[str, str]]:
        """[(name, 'file' | 'dir')] sorted; links and special files left out."""
        parts = _parts(path)
        st = self._lstat(parts)
        if st is None or not stat.S_ISDIR(st.st_mode):
            return []
        out = []
        d = self.root.joinpath(*parts)
        try:
            for name in sorted(os.listdir(d)):
                m = os.lstat(d / name).st_mode
                if stat.S_ISDIR(m):
                    out.append((name, "dir"))
                elif stat.S_ISREG(m):
                    out.append((name, "file"))
        except OSError as e:
            raise TreeError(f"{path or '/'}: cannot be listed ({e.strerror or e})") from e
        return out

    def read(self, path: str, limit: int) -> bytes | None:
        """A regular file's bytes (None if missing); more than `limit` bytes,
        or bytes other than the fetch's manifest says, raise TreeError."""
        parts = _parts(path)
        if not parts:
            return None
        st = self._lstat(parts)
        if st is None or not stat.S_ISREG(st.st_mode):
            return None
        rel = "/".join(parts)
        want = self.manifest.get(rel)
        if want is None:
            raise TreeError(f"{rel}: not in the fetch's manifest")
        if st.st_size > limit:
            raise TreeError(f"{path}: larger than {limit} bytes")
        try:
            fd = os.open(self.root.joinpath(*parts), os.O_RDONLY | _O_NOFOLLOW | _O_BINARY)
            with os.fdopen(fd, "rb") as f:
                fst = os.fstat(f.fileno())
                if not stat.S_ISREG(fst.st_mode) or \
                        (fst.st_ino, fst.st_dev) != (st.st_ino, st.st_dev):
                    raise TreeError(f"{path}: changed while being read")
                data = f.read(limit + 1)
        except OSError as e:
            raise TreeError(f"{rel}: cannot be read ({e.strerror or e})") from e
        if len(data) > limit:
            raise TreeError(f"{path}: larger than {limit} bytes")
        if hashlib.sha256(data).hexdigest() != want:
            raise TreeError(f"{rel}: changed after the fetch (sha256 differs from the manifest)")
        return data

    def read_folder(self, path: str, max_files: int, max_bytes: int) -> dict[str, bytes]:
        """Every regular file under `path` as {relative posix path: bytes}.
        A symlink, a special file or an entry the fetch skipped (a link)
        under `path` is a TreeError, as is a skipped list the fetch cut short
        (an unlisted entry may be under `path`), more than `max_files` files
        or `max_bytes` bytes, or files other than the manifest lists."""
        base = _parts(path)
        prefix = "/".join(base) + "/" if base else ""
        for s in self.skipped:
            if prefix == "" or str(s.get("path", "")).startswith(prefix):
                raise TreeError(f"{s.get('path')}: {s.get('reason', 'skipped')} "
                                "(not fetched)")
        if self.skipped_truncated:
            raise TreeError(f"{path or '/'}: the repository has too many links or special "
                            "files to list; it cannot be imported safely")
        if not self.is_dir(path):
            raise TreeError(f"{path or '/'}: not a folder")
        files: dict[str, bytes] = {}
        total = 0

        def walk(rel: list[str]) -> None:
            nonlocal total
            d = self.root.joinpath(*base, *rel)
            for name in sorted(os.listdir(d)):
                st = os.lstat(d / name)
                sub = [*rel, name]
                if stat.S_ISDIR(st.st_mode):
                    self._check_owner(st, "/".join([*base, *sub]))
                    walk(sub)
                elif stat.S_ISREG(st.st_mode):
                    if len(files) >= max_files:
                        raise TreeError(f"{path or '/'}: more than {max_files} files")
                    if total + st.st_size > max_bytes:
                        raise TreeError(f"{path or '/'}: more than {_size(max_bytes)} of "
                                        "files")
                    data = self.read("/".join([*base, *sub]), max_bytes - total)
                    if data is None:
                        raise TreeError(f"{'/'.join(sub)}: changed while being read")
                    total += len(data)
                    files["/".join(sub)] = data
                else:
                    kind = "a symlink" if stat.S_ISLNK(st.st_mode) else "a special file"
                    raise TreeError(f"{'/'.join(sub)}: {kind}")

        try:
            walk([])
        except OSError as e:
            raise TreeError(f"{path or '/'}: cannot be read ({e.strerror or e})") from e
        listed = {p[len(prefix):] for p in self.manifest if p.startswith(prefix)}
        gone = sorted(listed - set(files))
        if gone:
            raise TreeError(f"{prefix}{gone[0]}: missing (changed after the fetch)")
        return files


def _check_dir(p: Path, owners: set[int], what: str, group_ok: bool) -> None:
    st = os.lstat(p)
    if not stat.S_ISDIR(st.st_mode):
        raise FetchError(f"{what} is not a plain folder")
    if _POSIX:
        if st.st_uid not in owners:
            raise FetchError(f"{what} belongs to uid {st.st_uid}, not the fetch")
        if st.st_mode & 0o002 or (st.st_mode & 0o020 and not group_ok):
            raise FetchError(f"{what} is writable by others")


def open_tree(settings: Settings, res: dict) -> Tree:
    """The tree a `fetch_repo` answer names: `dir` (32 hex) under
    `skills_fetch_dir`, with its sha, skipped list and manifest. A missing
    or foreign folder is a FetchError."""
    name = str(res.get("dir") or "")
    sha = str(res.get("sha") or "")
    manifest = res.get("manifest")
    if not FETCH_DIR_RE.fullmatch(name) or not SHA_RE.fullmatch(sha):
        raise FetchError("the runner answered with a bad fetch folder or sha")
    if not isinstance(manifest, dict) or not all(
            isinstance(k, str) and isinstance(v, str) and SHA256_RE.fullmatch(v)
            for k, v in manifest.items()):
        raise FetchError("the runner answered without a valid file manifest")
    uid = settings.skills_fetch_uid
    base = Path(settings.skills_fetch_dir)
    try:
        # the base: root's (the image's folder) with group write for the fetch gid
        _check_dir(base, {0, uid}, "the fetch volume", group_ok=True)
        _check_dir(base / name, {uid}, "the fetch folder", group_ok=False)
    except OSError as e:
        raise FetchError(f"the fetched tree cannot be read: {e.strerror or e}") from e
    skipped = [s for s in (res.get("skipped") or []) if isinstance(s, dict)]
    return Tree(base / name, sha, skipped, manifest, bool(res.get("skipped_truncated")),
                uid if _POSIX else None)


@contextmanager
def fetched(runner: Runner, settings: Settings, owner: str, repo: str,
            ref: str = "") -> Iterator[Tree]:
    """Fetch `owner/repo@ref` through the runner; the tree is removed after."""
    try:
        res = runner.call("fetch_repo", owner=owner, repo=repo, ref=ref)
    except RunnerError as e:
        raise FetchError(f"the runner could not fetch {owner}/{repo}: {e}") from e
    if not res.get("ok"):
        raise FetchError(str(res.get("error") or res.get("infra_error")
                             or f"the fetch of {owner}/{repo} failed"))
    name = str(res.get("dir") or "")
    try:
        yield open_tree(settings, res)
    finally:
        if FETCH_DIR_RE.fullmatch(name):
            try:
                runner.call("fetch_cleanup", dir=name)
            except RunnerError as e:
                log.warning("fetch_cleanup %s failed: %s", name, e)
