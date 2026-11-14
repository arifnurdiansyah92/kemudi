"""A stand-in for kemudi-runner's `fetch_repo` / `fetch_cleanup` ops: repos
are dicts of files, written into the workspace's `.skills-fetch/<hex>/`
like the runner's child would."""

from __future__ import annotations

import secrets
import shutil
from pathlib import Path

from kemudi_ai.awak.runner import RunnerError


class FakeFetchRunner:
    def __init__(self, workspace: str | Path):
        self.workspace = Path(workspace)
        # "owner/repo" -> {ref: sha} ("" = the default branch) and sha -> files
        self.refs: dict[str, dict[str, str]] = {}
        self.trees: dict[str, dict[str, bytes]] = {}
        self.skipped: dict[str, list[dict]] = {}
        self.calls: list[tuple[str, dict]] = []
        self.fail: str | None = None  # an {ok: False, error} answer
        self.down = False  # RunnerError

    def publish(self, repo: str, sha: str, files: dict[str, bytes | str], ref: str = "",
                skipped: list[dict] | None = None) -> None:
        self.refs.setdefault(repo, {})[ref] = sha
        self.trees[sha] = {p: d.encode() if isinstance(d, str) else d for p, d in files.items()}
        if skipped:
            self.skipped[sha] = skipped

    def live_dirs(self) -> list[str]:
        base = self.workspace / ".skills-fetch"
        return sorted(p.name for p in base.iterdir()) if base.exists() else []

    def call(self, op: str, **payload) -> dict:
        self.calls.append((op, payload))
        if self.down:
            raise RunnerError(f"runner {op} failed: ConnectError")
        if op == "fetch_cleanup":
            shutil.rmtree(self.workspace / payload["dir"], ignore_errors=True)
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
        name = secrets.token_hex(16)
        root = self.workspace / ".skills-fetch" / name
        root.mkdir(parents=True)
        for path, data in self.trees[sha].items():
            p = root / path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        return {"ok": True, "sha": sha, "dir": f".skills-fetch/{name}",
                "files": len(self.trees[sha]), "bytes": 0,
                "skipped": self.skipped.get(sha, [])}
