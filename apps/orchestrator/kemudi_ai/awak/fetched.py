"""A GitHub repo fetched by kemudi-runner (`fetch_repo`), read from the shared
workspace volume.

docs/superpowers/plans/2026-11-14-awak-skills-pr3-marketplace.md, Task 1.
The runner (uid 10000, no Kemudi secrets) downloads and extracts the repo
into `<workspace>/.skills-fetch/<hex>/`; the orchestrator only reads files
there, never runs anything. The folder belongs to the child uid, so every
read re-checks each path component with lstat (plain folders, a regular
file at the end, opened with O_NOFOLLOW): a symlink planted after the
extraction is refused, never followed.
"""

from __future__ import annotations

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

FETCH_DIR_RE = re.compile(r"\.skills-fetch/[0-9a-f]{32}")
SHA_RE = re.compile(r"[0-9a-f]{40}")
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_O_BINARY = getattr(os, "O_BINARY", 0)


class FetchError(Exception):
    """The repo could not be fetched or read; the message is for the admin."""


class TreeError(FetchError):
    """A path in the fetched tree is not a plain file or folder."""


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

    def _lstat(self, parts: list[str]) -> os.stat_result | None:
        """lstat of root/parts, every folder on the way checked; None if missing."""
        p = self.root
        for i, part in enumerate(parts):
            p = p / part
            try:
                st = os.lstat(p)
            except FileNotFoundError:
                return None
            if stat.S_ISLNK(st.st_mode):
                raise TreeError(f"{'/'.join(parts[:i + 1])}: a symlink")
            if i < len(parts) - 1 and not stat.S_ISDIR(st.st_mode):
                return None
        return os.lstat(p) if parts else os.lstat(self.root)

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
        for name in sorted(os.listdir(d)):
            m = os.lstat(d / name).st_mode
            if stat.S_ISDIR(m):
                out.append((name, "dir"))
            elif stat.S_ISREG(m):
                out.append((name, "file"))
        return out

    def read(self, path: str, limit: int) -> bytes | None:
        """A regular file's bytes (None if missing); more than `limit` bytes
        raises TreeError."""
        parts = _parts(path)
        if not parts:
            return None
        st = self._lstat(parts)
        if st is None or not stat.S_ISREG(st.st_mode):
            return None
        if st.st_size > limit:
            raise TreeError(f"{path}: larger than {limit} bytes")
        fd = os.open(self.root.joinpath(*parts), os.O_RDONLY | _O_NOFOLLOW | _O_BINARY)
        with os.fdopen(fd, "rb") as f:
            fst = os.fstat(f.fileno())
            if not stat.S_ISREG(fst.st_mode) or (fst.st_ino, fst.st_dev) != (st.st_ino, st.st_dev):
                raise TreeError(f"{path}: changed while being read")
            data = f.read(limit + 1)
        if len(data) > limit:
            raise TreeError(f"{path}: larger than {limit} bytes")
        return data

    def read_folder(self, path: str, max_files: int, max_bytes: int) -> dict[str, bytes]:
        """Every regular file under `path` as {relative posix path: bytes}.
        A symlink, a special file or an entry the fetch skipped (a link) is
        a TreeError, as are more than `max_files` files or `max_bytes` bytes."""
        base = _parts(path)
        prefix = "/".join(base) + "/" if base else ""
        for s in self.skipped:
            if prefix == "" or str(s.get("path", "")).startswith(prefix):
                raise TreeError(f"{s.get('path')}: {s.get('reason', 'skipped')} "
                                "(not fetched)")
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
                    walk(sub)
                elif stat.S_ISREG(st.st_mode):
                    if len(files) >= max_files:
                        raise TreeError(f"{path or '/'}: more than {max_files} files")
                    if total + st.st_size > max_bytes:
                        raise TreeError(f"{path or '/'}: more than {max_bytes} bytes")
                    data = self.read("/".join([*base, *sub]), max_bytes - total)
                    if data is None:
                        raise TreeError(f"{'/'.join(sub)}: changed while being read")
                    total += len(data)
                    files["/".join(sub)] = data
                else:
                    kind = "a symlink" if stat.S_ISLNK(st.st_mode) else "a special file"
                    raise TreeError(f"{'/'.join(sub)}: {kind}")

        walk([])
        return files


def open_tree(settings: Settings, rel: str, sha: str, skipped=None) -> Tree:
    """The fetch folder `rel` (`.skills-fetch/<hex>`) under the workspace."""
    if not FETCH_DIR_RE.fullmatch(rel or "") or not SHA_RE.fullmatch(sha or ""):
        raise FetchError("the runner answered with a bad fetch folder or sha")
    ws = Path(settings.workspace_dir)
    base, name = rel.split("/")
    for p in (ws / base, ws / base / name):
        st = os.lstat(p)
        if not stat.S_ISDIR(st.st_mode):
            raise FetchError(f"{p}: not a plain folder")
    return Tree(ws / base / name, sha, [s for s in (skipped or []) if isinstance(s, dict)])


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
    rel = str(res.get("dir") or "")
    try:
        yield open_tree(settings, rel, str(res.get("sha") or ""), res.get("skipped"))
    finally:
        if FETCH_DIR_RE.fullmatch(rel):
            try:
                runner.call("fetch_cleanup", dir=rel)
            except RunnerError as e:
                log.warning("fetch_cleanup %s failed: %s", rel, e)
