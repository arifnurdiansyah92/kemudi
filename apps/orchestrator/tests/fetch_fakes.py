"""A stand-in for kemudi-runner's `fetch_repo` / `fetch_cleanup` ops: repos
are dicts of files, written into `skills_fetch_dir/<hex>/` with a
{path: sha256} manifest like the runner's fetch child would."""

from __future__ import annotations

import hashlib
import os
import secrets
import shutil
from pathlib import Path

from kemudi_ai.awak.runner import RunnerError


class FakeFetchRunner:
    def __init__(self, base: str | Path):
        self.base = Path(base)
        # "owner/repo" -> {ref: sha} ("" = the default branch) and sha -> files
        self.refs: dict[str, dict[str, str]] = {}
        self.trees: dict[str, dict[str, bytes]] = {}
        self.skipped: dict[str, list[dict]] = {}
        self.truncated: set[str] = set()
        self.calls: list[tuple[str, dict]] = []
        self.fail: str | None = None  # an {ok: False, error} answer
        self.down = False  # RunnerError
        # sha asked for -> sha answered (a runner that fetched another commit)
        self.answer_sha: dict[str, str] = {}

    def publish(self, repo: str, sha: str, files: dict[str, bytes | str], ref: str = "",
                skipped: list[dict] | None = None, truncated: bool = False) -> None:
        self.refs.setdefault(repo, {})[ref] = sha
        self.trees[sha] = {p: d.encode() if isinstance(d, str) else d for p, d in files.items()}
        if skipped:
            self.skipped[sha] = skipped
        if truncated:
            self.truncated.add(sha)

    def live_dirs(self) -> list[str]:
        return sorted(p.name for p in self.base.iterdir()) if self.base.exists() else []

    def call(self, op: str, **payload) -> dict:
        self.calls.append((op, payload))
        if self.down:
            raise RunnerError(f"runner {op} failed: ConnectError")
        if op == "fetch_cleanup":
            shutil.rmtree(self.base / payload["dir"], ignore_errors=True)
            return {"ok": True, "removed": True}
        assert op == "fetch_repo", op
        if self.fail:
            return {"ok": False, "error": self.fail}
        repo = f"{payload['owner']}/{payload['repo']}"
        ref = payload.get("ref") or ""
        sha = ref if ref in self.trees else self.refs.get(repo, {}).get(ref)
        if sha is None:
            return {"ok": False, "error": f"{repo}@{ref or 'default branch'} not found: the "
                    "repository is missing or private, or the ref does not exist"}
        files = self.trees[sha]
        sha = self.answer_sha.get(sha, sha)
        name = secrets.token_hex(16)
        self.base.mkdir(parents=True, exist_ok=True)
        root = self.base / name
        root.mkdir(0o755)
        os.chmod(root, 0o755)
        for path, data in files.items():
            p = root / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        return {"ok": True, "sha": sha, "dir": name, "files": len(files), "bytes": 0,
                "skipped": self.skipped.get(sha, []),
                "skipped_truncated": sha in self.truncated,
                "manifest": {p: hashlib.sha256(d).hexdigest() for p, d in files.items()}}
