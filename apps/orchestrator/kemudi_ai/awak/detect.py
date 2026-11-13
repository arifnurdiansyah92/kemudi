"""Guess a repo's install/check/build/run commands from its files.

`tree(path)` returns a file's text from the default branch, or None. The
result is a suggestion: it only fills command fields the admin left empty,
and every line must still pass the runner's program allowlist.
"""

import json
from typing import Callable

FIELDS = ("install_cmd", "check_cmd", "build_cmd", "run_cmd")
ESLINT_CONFIGS = ("eslint.config.js", "eslint.config.mjs", "eslint.config.cjs",
                  "eslint.config.ts", ".eslintrc", ".eslintrc.js", ".eslintrc.cjs",
                  ".eslintrc.json", ".eslintrc.yml")


def _empty() -> dict[str, str]:
    return {f: "" for f in FIELDS}


def _node(tree: Callable[[str], str | None], package_json: str) -> dict[str, str]:
    try:
        pkg = json.loads(package_json)
    except ValueError:
        pkg = {}
    scripts = pkg.get("scripts") if isinstance(pkg.get("scripts"), dict) else {}
    deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
    if tree("pnpm-lock.yaml") is not None:
        pm, install, exec_ = "pnpm", "pnpm install --frozen-lockfile --ignore-scripts", "pnpm exec"
    elif tree("yarn.lock") is not None:
        pm, install, exec_ = "yarn", "yarn install --frozen-lockfile --ignore-scripts", "yarn"
    else:
        lock = tree("package-lock.json") is not None
        pm = "npm"
        install = "npm ci --ignore-scripts" if lock else "npm install --ignore-scripts"
        exec_ = "npx --no-install"
    check = []
    if tree("tsconfig.json") is not None:
        check.append(f"{exec_} tsc -b")
    if "eslint" in deps or any(tree(f) is not None for f in ESLINT_CONFIGS):
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


def detect_commands(tree: Callable[[str], str | None]) -> dict[str, str]:
    package_json = tree("package.json")
    if package_json is not None:
        return _node(tree, package_json)
    if tree("pyproject.toml") is not None:
        return {**_empty(), "install_cmd": "uv sync", "check_cmd": "uv run pytest"}
    if tree("go.mod") is not None:
        return {**_empty(), "install_cmd": "go mod download",
                "check_cmd": "go vet ./...\ngo test ./...", "build_cmd": "go build ./..."}
    if tree("Cargo.toml") is not None:
        return {**_empty(), "install_cmd": "cargo fetch", "check_cmd": "cargo test",
                "build_cmd": "cargo build --release"}
    makefile = tree("Makefile")
    if makefile is not None:
        t = _make_targets(makefile)
        return {
            "install_cmd": "make install" if "install" in t else "",
            "check_cmd": "make test" if "test" in t else "",
            "build_cmd": "make build" if "build" in t else "",
            "run_cmd": "make run" if "run" in t else "",
        }
    return _empty()
