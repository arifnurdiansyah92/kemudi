"""Guess a repo's install/check/build/run commands from its files.

`tree(path)` returns a file's text from the default branch, or None. The
result is a suggestion: it only fills command fields the admin left empty,
and every line must still pass the runner's program allowlist.

`detect_apps` also looks one level down (`frontend/`, `backend/`...), for
repos whose apps do not sit at the root.
"""

import json
from typing import Callable

FIELDS = ("install_cmd", "check_cmd", "build_cmd", "run_cmd")
ESLINT_CONFIGS = ("eslint.config.js", "eslint.config.mjs", "eslint.config.cjs",
                  "eslint.config.ts", ".eslintrc", ".eslintrc.js", ".eslintrc.cjs",
                  ".eslintrc.json", ".eslintrc.yml")
COMPOSE_FILES = ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")
# First-level directories that never hold an app of their own.
SKIP_DIRS = {"node_modules", "docs", ".github"}

Tree = Callable[[str], str | None]


def _empty() -> dict[str, str]:
    return {f: "" for f in FIELDS}


def _node(tree: Tree, package_json: str) -> dict[str, str]:
    try:
        pkg = json.loads(package_json)
    except ValueError:
        pkg = {}
    if not isinstance(pkg, dict):
        pkg = {}
    scripts = pkg.get("scripts") if isinstance(pkg.get("scripts"), dict) else {}
    deps = {}
    for key in ("dependencies", "devDependencies"):
        if isinstance(pkg.get(key), dict):
            deps.update(pkg[key])
    if tree("pnpm-lock.yaml") is not None:
        # The runner keeps one pnpm store (a volume), shared by every job.
        pm, exec_ = "pnpm", "pnpm exec"
        install = "pnpm install --frozen-lockfile --ignore-scripts --store-dir /pnpm-store"
    elif tree("yarn.lock") is not None:
        pm, install, exec_ = "yarn", "yarn install --frozen-lockfile --ignore-scripts", "yarn"
    else:
        lock = tree("package-lock.json") is not None
        pm = "npm"
        install = "npm ci --ignore-scripts" if lock else "npm install --ignore-scripts"
        exec_ = "npx --no-install"
    run_script = (lambda s: f"npm run {s}") if pm == "npm" else (lambda s: f"{pm} {s}")
    check = []
    if tree("tsconfig.json") is not None:
        # Next.js projects are not set up for project references; `-b` would
        # emit or fail on them.
        check.append(f"{exec_} tsc --noEmit" if "next" in deps else f"{exec_} tsc -b")
    if "lint" in scripts:
        check.append(run_script("lint"))  # the project's own lint setup (e.g. next lint)
    elif "eslint" in deps or any(tree(f) is not None for f in ESLINT_CONFIGS):
        check.append(f"{exec_} eslint .")
    if "test" in scripts:
        check.append(f"{pm} test")
    run = "dev" if "dev" in scripts else "start" if "start" in scripts else ""
    return {
        "install_cmd": install,
        "check_cmd": "\n".join(check),
        "build_cmd": f"{pm} build" if "build" in scripts else "",
        "run_cmd": f"{pm} {run}" if run else "",
    }


def _make_targets(makefile: str) -> set[str]:
    return {line.split(":", 1)[0].strip() for line in makefile.splitlines()
            if ":" in line and not line.startswith(("\t", " ", "#"))}


def _app(tree: Tree) -> tuple[str, dict[str, str]] | None:
    """(kind, commands) of the app in one directory, or None."""
    package_json = tree("package.json")
    if package_json is not None:
        return "node", _node(tree, package_json)
    if tree("pyproject.toml") is not None:
        return "python", {**_empty(), "install_cmd": "uv sync", "check_cmd": "uv run pytest"}
    if tree("requirements.txt") is not None:
        # No isolated env for it in the runner (pip into its Python is not ours
        # to do); its commands come from a runbook (`run_in`, stage 1b).
        return "python", _empty()
    if tree("go.mod") is not None:
        return "go", {**_empty(), "install_cmd": "go mod download",
                      "check_cmd": "go vet ./...\ngo test ./...", "build_cmd": "go build ./..."}
    if tree("Cargo.toml") is not None:
        return "rust", {**_empty(), "install_cmd": "cargo fetch", "check_cmd": "cargo test",
                        "build_cmd": "cargo build --release"}
    makefile = tree("Makefile")
    if makefile is not None:
        t = _make_targets(makefile)
        return "make", {
            "install_cmd": "make install" if "install" in t else "",
            "check_cmd": "make test" if "test" in t else "",
            "build_cmd": "make build" if "build" in t else "",
            "run_cmd": "make run" if "run" in t else "",
        }
    return None


def detect_commands(tree: Tree) -> dict[str, str]:
    """Commands for the app at the root of `tree` (empty fields if none)."""
    found = _app(tree)
    return found[1] if found else _empty()


def detect_apps(tree: Tree, list_dir: Callable[[str], list[str]]) -> dict:
    """Apps at the repo root and in its first-level directories, plus compose
    files there. `list_dir(path)` lists the directory names under `path`
    ("" = the root). Returns {"apps": [{dir, kind, commands}], "compose_files"}."""
    dirs = [""] + [d for d in sorted(list_dir(""))
                   if d and not d.startswith(".") and d not in SKIP_DIRS]
    apps, compose = [], []
    for d in dirs:
        def sub(path: str, d: str = d) -> str | None:
            return tree(f"{d}/{path}" if d else path)

        found = _app(sub)
        if found:
            apps.append({"dir": d, "kind": found[0], "commands": found[1]})
        compose += [f"{d}/{f}" if d else f for f in COMPOSE_FILES if sub(f) is not None]
    return {"apps": apps, "compose_files": compose}


def suggestion(found: dict) -> dict[str, str]:
    """Command fields (and `subdir`) for a repo row from `detect_apps`: the
    root app when it has commands, else the first subfolder app that has."""
    for app in found["apps"]:
        if any(app["commands"].values()):
            return {**app["commands"], "subdir": app["dir"]}
    return {**_empty(), "subdir": ""}
