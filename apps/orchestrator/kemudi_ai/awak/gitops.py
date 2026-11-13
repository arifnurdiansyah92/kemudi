"""Git plumbing the orchestrator owns.

The agent controls the workspace repo, so the orchestrator never runs git
*inside* it except a hardened `fetch` (no hooks, no fsmonitor, a fixed
upload-pack). Everything else happens in an orchestrator-owned bare repo,
and only `awak/us-<n>` branches are ever pushed to the host repo.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

BRANCH_RE = re.compile(r"^awak/us-\d+$")
SAFE = [
    "-c", "core.hooksPath=/dev/null",
    "-c", "core.fsmonitor=false",
    "-c", "protocol.file.allow=always",
    "-c", "safe.directory=*",
]
UPLOAD_PACK = "git -c core.hooksPath=/dev/null -c core.fsmonitor=false upload-pack"


class GitError(Exception):
    pass


def branch_for(ref: int) -> str:
    return f"awak/us-{ref}"


def _git(*args: str, git_dir: str | None = None, cwd: str | None = None, timeout=300) -> str:
    cmd = ["git", *SAFE]
    if git_dir:
        cmd += ["--git-dir", git_dir]
    cmd += list(args)
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": "/tmp",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_TERMINAL_PROMPT": "0",
    }
    p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise GitError(f"git {' '.join(args[:2])} failed: {p.stderr.strip()[:500]}")
    return p.stdout.strip()


class Repo:
    def __init__(self, bare: str, host_git: str, workspace: str, uid: int):
        self.bare = bare
        self.host_git = host_git
        self.workspace = workspace
        self.uid = uid

    def ensure_bare(self) -> None:
        if not Path(self.bare, "HEAD").exists():
            Path(self.bare).parent.mkdir(parents=True, exist_ok=True)
            _git("init", "--bare", self.bare)

    def sync_main(self) -> str:
        """Bring the host's main into the bare repo; returns its sha."""
        self.ensure_bare()
        _git("fetch", "--no-tags", self.host_git, "+refs/heads/main:refs/heads/main",
             git_dir=self.bare)
        return _git("rev-parse", "refs/heads/main", git_dir=self.bare)

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
        """A fresh clone for the attempt, on the branch (new from main, or the
        previous attempt's tip for rework)."""
        if not BRANCH_RE.match(branch):
            raise GitError(f"refusing branch {branch!r}")
        d = self.job_dir(branch)
        if d.exists():
            shutil.rmtree(d, onerror=_force_remove)
        start = branch if self.has_branch(branch) else "main"
        _git("clone", "--no-tags", "--branch", start, self.bare, str(d))
        if start == "main":
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
        return _git("diff", f"refs/heads/main...refs/heads/{branch}", git_dir=self.bare,
                    timeout=120)

    def changed_files(self, branch: str) -> list[str]:
        out = _git("diff", "--name-only", f"refs/heads/main...refs/heads/{branch}",
                   git_dir=self.bare)
        return [line for line in out.splitlines() if line]

    def push_host(self, branch: str) -> None:
        if not BRANCH_RE.match(branch):
            raise GitError(f"refusing to push {branch!r}")
        _git("push", "--force", self.host_git,
             f"refs/heads/{branch}:refs/heads/{branch}", git_dir=self.bare)


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
