"""What the project's code already contains, as read-only context for intake.

Intake turns a requirement into stories. Without the code it guesses page
names, endpoints and what already exists, so the stories drift from the
project. This reads the project's repos straight from the bare repos Awak
keeps (default branch, `git ls-tree` / `git show`, no checkout):

1. `overview()`: per repo its README, manifest and a file map (collapsed to
   folders when the repo is large);
2. the model picks the files it needs (`pick_prompt`), `read()` returns them
   within a size budget.

Nothing here writes to a repo. A repo that cannot be fetched is left out
and named, so intake still works without it.
"""

import json
import logging
import posixpath
from dataclasses import dataclass, field
from typing import Callable

from . import gitops

log = logging.getLogger(__name__)

SKIP_DIRS = {".git", "node_modules", "dist", "build", "out", ".next", ".nuxt", ".svelte-kit",
             "vendor", "__pycache__", ".venv", "venv", "env", "coverage", ".turbo", "target",
             ".cache", ".idea", ".vscode", ".pytest_cache", ".mypy_cache", "bower_components",
             "storybook-static", ".vite"}
SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svg", ".bmp", ".avif",
            ".woff", ".woff2", ".ttf", ".otf", ".eot", ".mp4", ".mp3", ".wav", ".webm",
            ".pdf", ".zip", ".gz", ".tar", ".jar", ".war", ".class", ".so", ".dll", ".exe",
            ".pyc", ".map", ".lock", ".min.js", ".min.css", ".snap", ".db", ".sqlite"}
SKIP_FILES = {"package-lock.json", "pnpm-lock.yaml", "yarn.lock", "poetry.lock",
              "composer.lock", "Gemfile.lock", "go.sum", "Cargo.lock", ".DS_Store"}
README_NAMES = ("README.md", "readme.md", "README.MD", "Readme.md", "README.rst", "README.txt",
                "README")
MANIFESTS = ("package.json", "pyproject.toml", "requirements.txt", "composer.json", "go.mod",
             "Gemfile", "pom.xml", "build.gradle", "build.gradle.kts", "Cargo.toml")

# Budgets (characters): the overview goes into two model calls, the files
# into one. Opus/DeepSeek take 128K+ tokens; this stays far below.
MAP_CHARS = 24_000       # file map, shared by all repos
README_CHARS = 3_000
MANIFEST_CHARS = 2_000
MAX_PICK = 20
FILE_CHARS = 12_000
FILES_CHARS = 120_000


@dataclass
class Source:
    """One repo's default branch, read from its bare repo."""

    name: str
    role: str
    branch: str
    subdir: str = ""
    # (git args...) -> stdout; raises gitops.GitError. Injected in tests.
    git: Callable[..., str] | None = None
    bare: str = ""
    _paths: list[str] | None = field(default=None, repr=False)

    def _run(self, *args: str) -> str:
        if self.git is not None:
            return self.git(*args)
        return gitops._git(*args, git_dir=self.bare, timeout=60)

    def paths(self) -> list[str]:
        if self._paths is None:
            try:
                out = self._run("ls-tree", "-r", "-z", "--name-only", f"refs/heads/{self.branch}")
            except (gitops.GitError, OSError) as e:
                log.warning("intake context: cannot list %s: %s", self.name, e)
                out = ""
            self._paths = sorted(p for p in out.split("\0") if p and keep(p))
        return self._paths

    def read(self, path: str, limit: int = FILE_CHARS) -> str | None:
        try:
            text = self._run("show", f"refs/heads/{self.branch}:{path}")
        except (gitops.GitError, OSError):
            return None
        if "\0" in text[:2000]:
            return None  # binary
        if len(text) > limit:
            text = text[:limit] + f"\n… (dipotong, {len(text)} karakter)"
        return text


def keep(path: str) -> bool:
    parts = path.split("/")
    if any(p in SKIP_DIRS for p in parts[:-1]):
        return False
    name = parts[-1]
    low = name.lower()
    if name in SKIP_FILES or any(low.endswith(e) for e in SKIP_EXT):
        return False
    return True


def file_map(paths: list[str], budget: int) -> str:
    """The paths, one per line; when they do not fit, folders deeper than
    some depth collapse into `folder/… (N file)` lines, the deepest first."""
    if not paths:
        return "(kosong)"
    full = "\n".join(paths)
    if len(full) <= budget:
        return full
    for depth in range(6, 0, -1):
        lines, folded = [], {}
        for p in paths:
            parts = p.split("/")
            if len(parts) <= depth:
                lines.append(p)
            else:
                key = "/".join(parts[:depth])
                if key not in folded:
                    folded[key] = 0
                    lines.append(key)
                folded[key] += 1
        text = "\n".join(f"{ln}/… ({folded[ln]} file)" if ln in folded else ln for ln in lines)
        if len(text) <= budget:
            return text
    return text[:budget] + "\n… (daftar dipotong)"


def _manifest(name: str, text: str) -> str:
    """package.json reduced to what tells the stack: name, scripts, deps."""
    if name == "package.json":
        try:
            pkg = json.loads(text)
        except ValueError:
            pkg = None
        if isinstance(pkg, dict):
            keep_keys = {k: pkg[k] for k in ("name", "description") if k in pkg}
            if isinstance(pkg.get("scripts"), dict):
                keep_keys["scripts"] = sorted(pkg["scripts"])
            for k in ("dependencies", "devDependencies"):
                if isinstance(pkg.get(k), dict):
                    keep_keys[k] = sorted(pkg[k])
            text = json.dumps(keep_keys, ensure_ascii=False)
    return text[:MANIFEST_CHARS]


@dataclass
class RepoContext:
    sources: list[Source]
    unavailable: list[str] = field(default_factory=list)
    # "repo:path" of the files `read` returned, for the response and the audit.
    read_files: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.sources)

    def roles(self) -> str:
        return ", ".join(f"`{s.name}` ({s.role or 'web'})" for s in self.sources)

    def overview(self) -> str:
        per_repo = MAP_CHARS // max(1, len(self.sources))
        out = []
        for s in self.sources:
            paths = s.paths()
            head = f"### Repo `{s.name}` (peran: {s.role or 'web'}, branch {s.branch}"
            head += f", folder aplikasi `{s.subdir}`)" if s.subdir else ")"
            out.append(head)
            present = set(paths)
            roots = [""] + ([s.subdir.strip("/")] if s.subdir else [])
            for root in roots:
                for names, limit in ((README_NAMES, README_CHARS), (MANIFESTS, MANIFEST_CHARS)):
                    for n in names:
                        p = posixpath.join(root, n) if root else n
                        if p not in present:
                            continue
                        text = s.read(p, limit)
                        if text:
                            body = _manifest(n, text) if names is MANIFESTS else text
                            out += [f"`{p}`:", "```", body.strip(), "```"]
                        if names is README_NAMES:
                            break
            out += [f"Peta file ({len(paths)} file):", "```",
                    file_map(paths, per_repo), "```", ""]
        if self.unavailable:
            out.append("Repo yang tidak bisa dibaca (tidak ada di konteks): "
                       + ", ".join(self.unavailable))
        return "\n".join(out).strip()

    def read(self, picks: list) -> str:
        """The picked files' contents, within FILES_CHARS. `picks` is the
        model's list of {"repo", "path"}; unknown repos/paths are skipped."""
        by_name = {s.name: s for s in self.sources}
        seen, out, total = set(), [], 0
        for item in picks[:MAX_PICK * 2]:
            if not isinstance(item, dict):
                continue
            src = by_name.get(str(item.get("repo") or "")) or (
                self.sources[0] if len(self.sources) == 1 else None)
            path = str(item.get("path") or "").strip().lstrip("/")
            if src is None or not path or (src.name, path) in seen:
                continue
            if path not in set(src.paths()):
                continue
            seen.add((src.name, path))
            text = src.read(path)
            if text is None:
                continue
            block = f"#### {src.name}: `{path}`\n```\n{text}\n```"
            if total + len(block) > FILES_CHARS:
                break
            out.append(block)
            total += len(block)
            self.read_files.append(f"{src.name}:{path}")
            if len(self.read_files) >= MAX_PICK:
                break
        return "\n\n".join(out)

    def summary(self) -> dict:
        return {"repos": [s.name for s in self.sources], "files": list(self.read_files),
                "unavailable": list(self.unavailable)}


def load(db, settings, slug: str, sync: bool = True) -> RepoContext:
    """The project's configured repos at their default branch. `sync` fetches
    the remote first; a repo whose fetch fails is still used when its bare
    repo already has the branch (an older state beats no context)."""
    from . import config_store
    from .worker import repo_for

    cfg = config_store.load(db, slug)
    ctx = RepoContext(sources=[])
    for rc in cfg.repos:
        try:
            repo = repo_for(cfg, rc, settings, config_store.key_row(db, rc.key_id))
            if sync:
                try:
                    repo.sync_default()
                except Exception as e:  # noqa: BLE001 - stale beats nothing
                    log.warning("intake context: fetch of %s failed: %s", rc.name, e)
            if not repo.has_branch(rc.default_branch):
                ctx.unavailable.append(rc.name)
                continue
        except Exception as e:  # noqa: BLE001 - one broken repo never blocks intake
            log.warning("intake context: repo %s unavailable: %s", rc.name, e)
            ctx.unavailable.append(rc.name)
            continue
        ctx.sources.append(Source(name=rc.name, role=rc.role, branch=rc.default_branch,
                                  subdir=rc.subdir, bare=repo.bare))
    return ctx
