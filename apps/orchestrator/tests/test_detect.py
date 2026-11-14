"""Detection in subfolders (stage 1a): a repo shaped like playfast."""

import json
import subprocess
from pathlib import Path

from kemudi_ai.awak import gitops
from kemudi_ai.awak.detect import detect_apps, detect_commands

from .awak_fakes import git
from .conftest import ADMIN, MEMBER

NEXT_PKG = json.dumps({
    "scripts": {"dev": "next dev", "build": "next build", "lint": "next lint"},
    "dependencies": {"next": "15.0.0", "react": "19.0.0"},
    "devDependencies": {"eslint": "9.0.0", "typescript": "5.6.0"},
})
PLAYFAST = {
    "README.md": "playfast",
    "docker-compose.yml": "services: {}\n",
    "frontend/package.json": NEXT_PKG,
    "frontend/pnpm-lock.yaml": "lockfileVersion: 9",
    "frontend/tsconfig.json": "{}",
    "backend/requirements.txt": "flask\n",
    "backend/app.py": "",
    "docs/package.json": "{}",
    "node_modules/x/package.json": "{}",
    ".github/workflows/ci.yml": "",
    ".devcontainer/package.json": "{}",
}


def fake_tree(files: dict[str, str]):
    def tree(path: str) -> str | None:
        return files.get(path)

    def list_dir(path: str) -> list[str]:
        prefix = f"{path}/" if path else ""
        return sorted({p[len(prefix):].split("/")[0] for p in files
                       if p.startswith(prefix) and "/" in p[len(prefix):]})

    return tree, list_dir


def test_detect_apps_in_subfolders():
    found = detect_apps(*fake_tree(PLAYFAST))
    assert found["compose_files"] == ["docker-compose.yml"]
    by_dir = {a["dir"]: a for a in found["apps"]}
    assert set(by_dir) == {"backend", "frontend"}  # no root app; docs, dot dirs skipped
    web = by_dir["frontend"]
    assert web["kind"] == "node"
    cmds = web["commands"]
    assert cmds["install_cmd"] == ("pnpm install --frozen-lockfile --ignore-scripts "
                                   "--store-dir /pnpm-store")
    assert cmds["check_cmd"].splitlines() == ["pnpm exec tsc --noEmit", "pnpm lint"]
    assert cmds["build_cmd"] == "pnpm build" and cmds["run_cmd"] == "pnpm dev"
    assert by_dir["backend"]["kind"] == "python"


def test_detect_apps_root_app_and_nested_compose():
    pkg = json.dumps({"devDependencies": {"eslint": "9"}, "scripts": {"test": "vitest"}})
    files = {"package.json": pkg, "tsconfig.json": "{}", "package-lock.json": "{}",
             "deploy/compose.yaml": "services: {}", "api/pyproject.toml": "[project]"}
    found = detect_apps(*fake_tree(files))
    assert [(a["dir"], a["kind"]) for a in found["apps"]] == [("", "node"), ("api", "python")]
    root = found["apps"][0]["commands"]
    # not Next.js: the build-mode type check; no lint script: eslint directly
    assert root["check_cmd"].splitlines() == ["npx --no-install tsc -b",
                                              "npx --no-install eslint .", "npm test"]
    assert found["apps"][1]["commands"]["install_cmd"] == "uv sync"
    assert found["compose_files"] == ["deploy/compose.yaml"]


def test_detect_commands_root_still_works():
    files = {"package.json": NEXT_PKG, "pnpm-lock.yaml": "", "tsconfig.json": "{}"}
    d = detect_commands(files.get)
    assert "pnpm exec tsc --noEmit" in d["check_cmd"]
    assert detect_commands({}.get)["install_cmd"] == ""


def make_remote(tmp_path: Path, files: dict[str, str]) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    git(src, "init", "-b", "main")
    git(src, "config", "user.email", "t@t")
    git(src, "config", "user.name", "t")
    for name, content in files.items():
        p = src / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, newline="\n")
    git(src, "add", "-A")
    git(src, "commit", "-m", "init")
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(src), str(remote)], check=True)
    return remote


def test_list_dir_reads_the_bare_repo(tmp_path):
    remote = make_remote(tmp_path, {k: v for k, v in PLAYFAST.items()
                                    if not k.startswith("node_modules")})
    assert gitops.list_dirs(str(remote), "main") == [".devcontainer", ".github", "backend",
                                                     "docs", "frontend"]
    assert gitops.list_dirs(str(remote), "main", "frontend") == []
    assert gitops.list_dirs(str(remote), "main", "missing") == []


def _add(client, url, **over):
    r = client.post("/projects/demo/agent/repos", headers=ADMIN,
                    json={"name": "pf-web", "role": "web", "url": url, **over})
    assert r.status_code == 200, r.text
    return r.json()


def test_check_fills_subdir_and_commands_from_first_app(agent_client, tmp_path):
    remote = make_remote(tmp_path, {k: v for k, v in PLAYFAST.items()
                                    if not k.startswith("node_modules")})
    agent_client.settings.host_git = str(remote)
    repo = _add(agent_client, str(remote))
    body = agent_client.post(f"/projects/demo/agent/repos/{repo['id']}/check",
                             headers=ADMIN).json()
    assert body["ok"]
    assert [(a["dir"], a["kind"]) for a in body["apps"]] == [("backend", "python"),
                                                             ("frontend", "node")]
    assert body["compose_files"] == ["docker-compose.yml"]
    saved = agent_client.get("/projects/demo/agent/repos", headers=MEMBER).json()["repos"][0]
    # backend has no command the runner can run here; frontend is the first app with some
    assert saved["subdir"] == "frontend"
    assert saved["check_cmd"].splitlines() == ["pnpm exec tsc --noEmit", "pnpm lint"]
    assert "--store-dir /pnpm-store" in saved["install_cmd"]


def test_check_keeps_admin_commands_for_the_root(agent_client, tmp_path):
    remote = make_remote(tmp_path, {k: v for k, v in PLAYFAST.items()
                                    if not k.startswith("node_modules")})
    agent_client.settings.host_git = str(remote)
    repo = _add(agent_client, str(remote), check_cmd="make test")
    body = agent_client.post(f"/projects/demo/agent/repos/{repo['id']}/check",
                             headers=ADMIN).json()
    assert body["ok"] and body["apps"]
    saved = agent_client.get("/projects/demo/agent/repos", headers=MEMBER).json()["repos"][0]
    # commands typed for the root are not mixed with another folder's
    assert saved["subdir"] == "" and saved["install_cmd"] == ""
    assert saved["check_cmd"] == "make test"
