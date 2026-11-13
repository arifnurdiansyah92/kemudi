"""Git plumbing the orchestrator owns.

The agent controls the workspace repo, so the orchestrator never runs git
*inside* it except a hardened `fetch` (no hooks, no fsmonitor, a fixed
upload-pack). Everything else happens in an orchestrator-owned bare repo,
and only `awak/us-<n>` branches are ever pushed to the remote.

The remote is a local path (the Kemudi repo at /host-git) or an SSH URL; for
SSH, `git_env` supplies GIT_SSH_COMMAND with a deploy key that exists on disk
only while one remote command runs.
"""

import os
import re
import shutil
import subprocess
import uuid
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from typing import Callable, Iterator

BRANCH_RE = re.compile(r"^awak/us-\d+$")
# Passed as GIT_CONFIG_* environment ("command line" scope), so every git
# process inherits it, including the upload-pack a local fetch spawns. The
# workspace belongs to another uid (Awak), hence safe.directory.
SAFE_CONFIG = {
    "core.hooksPath": "/dev/null",
    "core.fsmonitor": "false",
    "protocol.file.allow": "always",
    "safe.directory": "*",
}
UPLOAD_PACK = ("git -c core.hooksPath=/dev/null -c core.fsmonitor=false "
               "-c 'safe.directory=*' upload-pack")

# A fixed environment for remote commands, or a factory that yields one for the
# duration of a single command (so a decrypted key file is deleted right after).
GitEnv = dict[str, str] | Callable[[], AbstractContextManager[dict[str, str]]] | None


class GitError(Exception):
    pass


class MergeConflict(GitError):
    """The branch does not merge cleanly onto the default branch."""


class PushRejected(GitError):
    """The remote refused a (non-forced) push: its branch moved."""


def branch_for(ref: int) -> str:
    return f"awak/us-{ref}"


def git_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """The hardened environment every orchestrator git process runs with."""
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": "/tmp",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_COUNT": str(len(SAFE_CONFIG)),
    }
    for i, (k, v) in enumerate(SAFE_CONFIG.items()):
        env[f"GIT_CONFIG_KEY_{i}"] = k
        env[f"GIT_CONFIG_VALUE_{i}"] = v
    env.update(extra or {})
    return env


def _git(*args: str, git_dir: str | None = None, cwd: str | None = None, timeout=300,
         env_extra: dict[str, str] | None = None) -> str:
    cmd = ["git"]
    if git_dir:
        cmd += ["--git-dir", git_dir]
    cmd += list(args)
    p = subprocess.run(cmd, cwd=cwd, env=git_env(env_extra), capture_output=True, text=True,
                       timeout=timeout)
    if p.returncode != 0:
        raise GitError(f"git {' '.join(args[:2])} failed: {p.stderr.strip()[:500]}")
    return p.stdout.strip()


class Repo:
    def __init__(self, bare: str, remote: str, workspace: str, uid: int,
                 default_branch: str = "main", subdir: str = "", git_env: GitEnv = None,
                 scratch_dir: str | None = None):
        self.scratch_dir = scratch_dir
        self.bare = bare
        self.remote = remote
        self.workspace = workspace
        self.uid = uid
        self.default_branch = default_branch
        self.subdir = subdir
        self.git_env = git_env

    @property
    def host_git(self) -> str:  # iteration 1 name
        return self.remote

    @contextmanager
    def _remote_env(self) -> Iterator[dict[str, str]]:
        if callable(self.git_env):
            with self.git_env() as env:
                yield env
        else:
            yield dict(self.git_env or {})

    def ensure_bare(self) -> None:
        if not Path(self.bare, "HEAD").exists():
            Path(self.bare).parent.mkdir(parents=True, exist_ok=True)
            _git("init", "--bare", self.bare)

    def sync_default(self) -> str:
        """Bring the remote's default branch into the bare repo; returns its sha."""
        self.ensure_bare()
        d = self.default_branch
        with self._remote_env() as env:
            _git("fetch", "--no-tags", self.remote, f"+refs/heads/{d}:refs/heads/{d}",
                 git_dir=self.bare, env_extra=env)
        return _git("rev-parse", f"refs/heads/{d}", git_dir=self.bare)

    sync_main = sync_default  # iteration 1 name

    def has_branch(self, branch: str) -> bool:
        try:
            _git("rev-parse", "--verify", f"refs/heads/{branch}", git_dir=self.bare)
            return True
        except GitError:
            return False

    def sha(self, branch: str) -> str:
        return _git("rev-parse", f"refs/heads/{branch}", git_dir=self.bare)

    def job_dir(self, branch: str) -> Path:
        return Path(self.workspace) / branch.replace("/", "-")

    def prepare(self, branch: str) -> Path:
        """A fresh clone for the attempt, on the branch (new from the default
        branch, or the previous attempt's tip for rework)."""
        if not BRANCH_RE.match(branch):
            raise GitError(f"refusing branch {branch!r}")
        d = self.job_dir(branch)
        if d.exists():
            shutil.rmtree(d, onerror=_force_remove)
        start = branch if self.has_branch(branch) else self.default_branch
        _git("clone", "--no-tags", "--branch", start, self.bare, str(d))
        if start != branch:
            _git("checkout", "-b", branch, cwd=str(d))
        # The clone points at the bare repo; drop the remote so nothing in the
        # workspace knows where it came from or can push back.
        _git("remote", "remove", "origin", cwd=str(d))
        _git("config", "user.name", "Awak", cwd=str(d))
        _git("config", "user.email", "awak@kemudi.local", cwd=str(d))
        exclude = d / ".git" / "info" / "exclude"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        with exclude.open("a") as fh:
            fh.write("\n.qa/\nnode_modules/\n")
        _chown(d, self.uid)
        return d

    def collect(self, branch: str) -> str:
        """Fetch the branch from the workspace into the bare repo (hardened)."""
        if not BRANCH_RE.match(branch):
            raise GitError(f"refusing branch {branch!r}")
        d = self.job_dir(branch)
        _git("fetch", "--no-tags", "--upload-pack", UPLOAD_PACK, str(d),
             f"+refs/heads/{branch}:refs/heads/{branch}", git_dir=self.bare)
        return self.sha(branch)

    def diff_from_main(self, branch: str) -> str:
        return _git("diff", f"refs/heads/{self.default_branch}...refs/heads/{branch}",
                    git_dir=self.bare, timeout=120)

    def changed_files(self, branch: str) -> list[str]:
        """Every path the branch touches. `--no-renames`: a rename lists both its
        old (deleted) and new path, so a move out of a denied path is caught."""
        out = _git("diff", "--name-only", "--no-renames",
                   f"refs/heads/{self.default_branch}...refs/heads/{branch}", git_dir=self.bare)
        return [line for line in out.splitlines() if line]

    def push_branch(self, branch: str) -> None:
        """Push an `awak/us-<n>` branch; `--force` is only ever used for those."""
        if not BRANCH_RE.match(branch):
            raise GitError(f"refusing to push {branch!r}")
        with self._remote_env() as env:
            _git("push", "--force", self.remote,
                 f"refs/heads/{branch}:refs/heads/{branch}", git_dir=self.bare, env_extra=env)

    push_host = push_branch  # iteration 1 name

    # ------------------------------------------------------------- merging
    def is_ancestor(self, a: str, b: str) -> bool:
        """Whether commit `a` is an ancestor of (or equal to) `b`."""
        p = subprocess.run(["git", "--git-dir", self.bare, "merge-base", "--is-ancestor", a, b],
                           env=git_env(), capture_output=True, text=True, timeout=60)
        if p.returncode not in (0, 1):
            raise GitError(f"git merge-base failed: {p.stderr.strip()[:500]}")
        return p.returncode == 0

    def _scratch_root(self) -> Path:
        return Path(self.scratch_dir) if self.scratch_dir else Path(self.bare).parent / "scratch"

    def merge_commit(self, onto: str, branch_sha: str, message: str, ref: str) -> str:
        """`merge --no-ff` of `branch_sha` onto `onto` in an orchestrator-owned
        scratch clone; the result is stored in the bare repo as `ref`
        (refs/kemudi/merge/...) and its sha returned. Conflict -> MergeConflict."""
        if not ref.startswith("refs/kemudi/merge/"):
            raise GitError(f"refusing merge ref {ref!r}")
        root = self._scratch_root()
        root.mkdir(parents=True, exist_ok=True)
        d = root / uuid.uuid4().hex
        try:
            _git("clone", "--no-tags", "--quiet", "--no-checkout", self.bare, str(d))
            _git("checkout", "--quiet", "--detach", onto, cwd=str(d))
            ident = ["-c", "user.name=Kemudi", "-c", "user.email=kemudi@kemudi.local"]
            try:
                _git(*ident, "merge", "--no-ff", "--no-edit", "-m", message, branch_sha,
                     cwd=str(d))
            except GitError as e:
                raise MergeConflict(str(e)) from e
            sha = _git("rev-parse", "HEAD", cwd=str(d))
            _git("update-ref", "-d", ref, git_dir=self.bare)
            _git("push", "--quiet", self.bare, f"{sha}:{ref}", cwd=str(d))
            return sha
        finally:
            if d.exists():
                shutil.rmtree(d, onerror=_force_remove)

    def prepare_at(self, branch: str, ref: str, sha: str) -> Path:
        """The job workspace as a detached checkout of `ref` (expected at `sha`),
        for re-running the gates on a merge result. No remote, like prepare()."""
        if not BRANCH_RE.match(branch):
            raise GitError(f"refusing branch {branch!r}")
        d = self.job_dir(branch)
        if d.exists():
            shutil.rmtree(d, onerror=_force_remove)
        _git("clone", "--no-tags", "--quiet", "--no-checkout", self.bare, str(d))
        _git("fetch", "--quiet", "--no-tags", "origin", f"+{ref}:refs/kemudi/target", cwd=str(d))
        _git("checkout", "--quiet", "--detach", "refs/kemudi/target", cwd=str(d))
        if _git("rev-parse", "HEAD", cwd=str(d)) != sha:
            raise GitError(f"{ref} is not at {sha[:8]}")
        _git("remote", "remove", "origin", cwd=str(d))
        _git("update-ref", "-d", "refs/kemudi/target", cwd=str(d))
        exclude = d / ".git" / "info" / "exclude"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        with exclude.open("a") as fh:
            fh.write("\n.qa/\nnode_modules/\n")
        _chown(d, self.uid)
        return d

    def push_default(self, sha: str) -> None:
        """Push `sha` to the remote's default branch. Never forced: if the
        remote moved, git refuses and PushRejected is raised."""
        with self._remote_env() as env:
            try:
                _git("push", self.remote, f"{sha}:refs/heads/{self.default_branch}",
                     git_dir=self.bare, env_extra=env)
            except GitError as e:
                text = str(e).lower()
                if any(w in text for w in ("rejected", "non-fast-forward", "fetch first")):
                    raise PushRejected(str(e)) from e
                raise


def _force_remove(func, path, _exc) -> None:
    # git object files are read-only; Windows refuses to delete those.
    os.chmod(path, 0o700)
    func(path)


def _chown(path: Path, uid: int) -> None:
    if getattr(os, "geteuid", lambda: -1)() != 0:
        return
    for root, dirs, files in os.walk(path):
        os.chown(root, uid, uid)
        for name in files:
            os.lchown(os.path.join(root, name), uid, uid)
