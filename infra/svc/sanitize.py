"""kemudi-svc's compose sanitizer: pure functions, no Docker, stdlib only.

svc.py feeds it the output of `docker compose config --no-interpolate
--format json` (compose's normalized model: long-form ports, volumes and
depends_on, absolute build contexts) and writes what comes back.

1. `precheck_text` refuses, before compose reads the file, the keys that make
   compose read other files (`include`, `extends`, `env_file`, `label_file`).
2. `reduce` keeps the selected services plus their `depends_on` closure and
   checks them against an allowlist; anything else is refused with the key
   named. Services outside the closure are never looked at, so their `${X:?}`
   or odd keys do not matter. Build contexts and Dockerfiles must resolve
   inside the checkout without passing a symlink.
3. svc.py interpolates the reduced file with compose (cleared environment,
   only the vault env file from `env_file_text`).
4. `rewrite` turns the interpolated file into the one svc runs: built images
   named `kemudi-<project>-<service>`, `restart: "no"`, memory and pids
   capped, only the exposed port published (random host port), every
   service, volume and built image labelled `kemudi.project=<project>`.
"""

import os
import re
from pathlib import Path

LABEL = "kemudi.project"
MEM_CAP = 2 * 1024 ** 3
PIDS_CAP = 512

# Service keys kept as they are (some rewritten later), and keys dropped.
SERVICE_KEYS = frozenset({
    "image", "build", "command", "entrypoint", "environment", "healthcheck", "depends_on",
    "working_dir", "user", "volumes", "tmpfs", "expose", "ports", "restart",
    "stop_grace_period", "mem_limit", "pids_limit"})
DROPPED_SERVICE_KEYS = frozenset({"logging", "networks", "container_name", "labels"})
BUILD_KEYS = frozenset({"context", "dockerfile", "args", "target"})
MOUNT_KEYS = frozenset({"type", "source", "target", "read_only", "volume", "tmpfs"})
MOUNT_VOLUME_KEYS = frozenset({"nocopy", "subpath"})
MOUNT_TMPFS_KEYS = frozenset({"size", "mode"})
DEPENDS_KEYS = frozenset({"condition", "required", "restart"})

TOP_KEYS = frozenset({"services", "volumes"})
DROPPED_TOP_KEYS = frozenset({"networks", "name"})
TOP_VOLUME_KEYS = frozenset({"name", "labels"})

# Keys that make compose read another file while loading this one.
FILE_KEYS = ("include", "extends", "env_file", "label_file")
FILE_KEYS_RE = re.compile(r"""(?:^|[\s{,"'])(include|extends|env_file|label_file)["']?\s*:""",
                          re.M)

SERVICE_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
PROJECT_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,62}")

# Env names a request may not set (same lists as kemudi-runner and the
# orchestrator's runbook.py). COMPOSE_* in the env file would configure compose;
# svc_exec's env reaches the docker CLI's environment, hence BUILDX_/BUILDKIT_.
BLOCKED_ENV_PREFIXES = ("KEMUDI_", "DOCKER_", "COMPOSE_", "GIT_", "BUILDX_", "BUILDKIT_")
BLOCKED_ENV_NAMES = frozenset({"PATH", "LD_PRELOAD", "LD_LIBRARY_PATH", "NODE_OPTIONS",
                               "PYTHONPATH", "HOME"})
ENV_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,99}")


class Refused(ValueError):
    """The compose file (or request) is outside what svc runs."""


# --- request values ----------------------------------------------------------

def project_name(raw) -> str:
    p = str(raw or "")
    if not PROJECT_RE.fullmatch(p):
        raise Refused(f"bad project name {p!r}")
    return p


def service_names(raw, what: str = "services") -> list[str]:
    if not (isinstance(raw, list) and raw and all(isinstance(s, str) for s in raw)):
        raise Refused(f"{what} must be a non-empty list of service names")
    for s in raw:
        if not SERVICE_NAME_RE.fullmatch(s):
            raise Refused(f"bad service name {s!r}")
    return list(dict.fromkeys(raw))


def parse_expose(raw) -> tuple[str, int] | None:
    """`"<service>:<port>"` (the runbook's `expose`) or None."""
    if raw in (None, ""):
        return None
    m = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9._-]{0,99}):(\d{1,5})", str(raw))
    if not m or not 0 < int(m.group(2)) < 65536:
        raise Refused(f"bad expose {raw!r}; use \"<service>:<port>\"")
    return m.group(1), int(m.group(2))


def request_env(raw) -> dict[str, str]:
    """A request's `env`: string -> string, names not reserved."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise Refused("env must be an object")
    for k, v in raw.items():
        if not (isinstance(k, str) and ENV_NAME_RE.fullmatch(k) and isinstance(v, str)):
            raise Refused(f"bad env entry {k!r}")
        if k.upper() in BLOCKED_ENV_NAMES or k.upper().startswith(BLOCKED_ENV_PREFIXES):
            raise Refused(f"env name {k!r} is reserved")
        if "\x00" in v:
            raise Refused(f"env {k!r}: NUL in value")
    return dict(raw)


def env_file_text(env: dict[str, str]) -> str:
    """A dotenv file compose reads back to exactly these values: double-quoted,
    with backslash, quote, `$` and line breaks escaped (no interpolation)."""
    def q(v: str) -> str:
        v = (v.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$")
             .replace("\n", "\\n").replace("\r", "\\r"))
        return f'"{v}"'
    return "".join(f"{k}={q(v)}\n" for k, v in env.items())


def redact(text: str, values) -> str:
    """Every value of 4+ characters replaced, longest first."""
    for v in sorted({str(v) for v in values or [] if v and len(str(v)) >= 4},
                    key=len, reverse=True):
        text = text.replace(v, "[redacted]")
    return text


# --- paths -------------------------------------------------------------------

def inside(root: Path, target: str | Path, what: str, kind: str) -> Path:
    """`target` (absolute, or relative to `root`) resolved inside `root`
    without passing a symlink; `kind` is "dir" or "file"."""
    t = Path(target)
    if not t.is_absolute():
        t = root / t
    root_n = os.path.normpath(str(root))
    try:
        rel = os.path.relpath(os.path.normpath(str(t)), root_n)
    except ValueError:  # another drive (Windows)
        raise Refused(f"{what} {str(target)!r} is outside the checkout") from None
    parts = Path(rel).parts
    if rel == "." or not parts:
        parts = ()
    elif parts[0] == ".." or Path(rel).is_absolute():
        raise Refused(f"{what} {str(target)!r} is outside the checkout")
    cur = Path(root_n)
    for p in parts:
        cur = cur / p
        if cur.is_symlink():
            raise Refused(f"{what} {str(target)!r} passes a symlink")
    ok = cur.is_dir() if kind == "dir" else cur.is_file()
    if not ok:
        raise Refused(f"{what} {str(target)!r}: no such {'directory' if kind == 'dir' else 'file'}"
                      " in the checkout")
    return cur


def compose_file(checkout: Path, raw) -> Path:
    """The request's `file`: relative to the checkout, no `..`, no symlink."""
    rel = str(raw or "docker-compose.yml")
    parts = rel.replace("\\", "/").split("/")
    if (rel.startswith(("/", "\\")) or ":" in rel or ".." in parts
            or any(p in ("", ".") for p in parts)):
        raise Refused(f"bad compose file {rel!r}")
    return inside(checkout, Path(*parts), "compose file", "file")


# --- 1. text precheck --------------------------------------------------------

def precheck_text(text: str) -> None:
    """Crude on purpose (a false hit refuses a harmless file); svc also reads
    the file as an uid that cannot reach its own files."""
    body = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    m = FILE_KEYS_RE.search(body)
    if m:
        raise Refused(f"key {m.group(1)!r} is not allowed (svc reads only this compose file)")


# --- 2. reduce and check -----------------------------------------------------

def closure(services: dict, selected: list[str]) -> list[str]:
    """`selected` plus everything they depend on, in a stable order."""
    out: list[str] = []
    todo = list(selected)
    while todo:
        name = todo.pop(0)
        if name in out:
            continue
        if name not in services:
            raise Refused(f"no service {name!r} in the compose file")
        out.append(name)
        deps = services[name].get("depends_on") or {}
        todo.extend(deps if isinstance(deps, (dict, list)) else [])
    return out


def _check_build(name: str, build, checkout: Path) -> dict:
    if not isinstance(build, dict):
        raise Refused(f"service {name!r}: build must be an object")
    for k in build:
        if k not in BUILD_KEYS:
            raise Refused(f"service {name!r}: key 'build.{k}' is not allowed")
    ctx = build.get("context")
    if not isinstance(ctx, str) or not ctx or "://" in ctx or ctx.startswith("git@"):
        raise Refused(f"service {name!r}: build.context must be a folder in the checkout")
    ctx_dir = inside(checkout, ctx, f"service {name!r}: build.context", "dir")
    dockerfile = build.get("dockerfile") or "Dockerfile"
    if not isinstance(dockerfile, str):
        raise Refused(f"service {name!r}: bad build.dockerfile")
    inside(checkout, ctx_dir / dockerfile if not Path(dockerfile).is_absolute() else dockerfile,
           f"service {name!r}: build.dockerfile", "file")
    for k in ("args",):
        if k in build and not isinstance(build[k], dict):
            raise Refused(f"service {name!r}: build.{k} must be an object")
    return {k: v for k, v in build.items()}


def _check_mounts(name: str, mounts, volumes: dict) -> list:
    if not isinstance(mounts, list):
        raise Refused(f"service {name!r}: volumes must be a list")
    used = []
    for m in mounts:
        if not isinstance(m, dict):
            raise Refused(f"service {name!r}: volumes entries must be in compose's long form")
        for k in m:
            if k not in MOUNT_KEYS:
                raise Refused(f"service {name!r}: key 'volumes[].{k}' is not allowed")
        kind = m.get("type")
        if kind == "volume":
            src = m.get("source")
            if src and src not in volumes:
                raise Refused(f"service {name!r}: volume {src!r} is not a named volume of this file")
            if src:
                used.append(src)
            extra = set(m.get("volume") or {}) - MOUNT_VOLUME_KEYS
        elif kind == "tmpfs":
            extra = set(m.get("tmpfs") or {}) - MOUNT_TMPFS_KEYS
            if m.get("source"):
                extra.add("source")
        else:
            raise Refused(f"service {name!r}: only named volumes and tmpfs are allowed "
                          f"(volumes[].type {kind!r})")
        if extra:
            raise Refused(f"service {name!r}: key 'volumes[].{kind}.{sorted(extra)[0]}' "
                          "is not allowed")
    return used


def reduce(doc: dict, selected: list[str], checkout: Path) -> dict:
    """Steps 2 and 3: the selected services and their dependencies, checked
    against the allowlist, with the dropped keys removed."""
    if not isinstance(doc, dict) or not isinstance(doc.get("services"), dict):
        raise Refused("compose file has no services")
    for k in doc:
        if k not in TOP_KEYS and k not in DROPPED_TOP_KEYS and not k.startswith("x-"):
            raise Refused(f"top-level key {k!r} is not allowed")
    services = doc["services"]
    top_volumes = doc.get("volumes") or {}
    if not isinstance(top_volumes, dict):
        raise Refused("top-level volumes must be an object")
    keep = closure(services, selected)

    out_services: dict = {}
    used_volumes: list[str] = []
    for name in keep:
        svc = services[name]
        if not isinstance(svc, dict):
            raise Refused(f"service {name!r} must be an object")
        clean: dict = {}
        for k, v in svc.items():
            if k in DROPPED_SERVICE_KEYS or k.startswith("x-"):
                continue
            if k not in SERVICE_KEYS:
                raise Refused(f"service {name!r}: key {k!r} is not allowed")
            clean[k] = v
        if "build" in clean:
            clean["build"] = _check_build(name, clean["build"], checkout)
        elif not isinstance(clean.get("image"), str) or not clean["image"]:
            raise Refused(f"service {name!r} needs an image or a build")
        elif clean["image"].lower().startswith("kemudi-"):
            raise Refused(f"service {name!r}: image names starting with 'kemudi-' are reserved")
        if "volumes" in clean:
            used_volumes += _check_mounts(name, clean["volumes"], top_volumes)
        deps = clean.get("depends_on")
        if isinstance(deps, dict):
            for dep, spec in deps.items():
                for k in (spec or {}):
                    if k not in DEPENDS_KEYS:
                        raise Refused(f"service {name!r}: key 'depends_on.{dep}.{k}' "
                                      "is not allowed")
        out_services[name] = clean

    project = str(doc.get("name") or "")
    out_volumes: dict = {}
    for vol in dict.fromkeys(used_volumes):
        spec = top_volumes.get(vol) or {}
        for k in spec:
            if k not in TOP_VOLUME_KEYS:
                raise Refused(f"volume {vol!r}: key {k!r} is not allowed")
        # compose fills in `<project>_<volume>`; any other name was set by the
        # file and could reach another project's volume.
        if "name" in spec and spec["name"] != f"{project}_{vol}":
            raise Refused(f"volume {vol!r}: key 'name' is not allowed")
        out_volumes[vol] = {}
    reduced: dict = {"services": out_services}
    if out_volumes:
        reduced["volumes"] = out_volumes
    return reduced


# --- 4. rewrite --------------------------------------------------------------

_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([bkmg]?)b?", re.I)
_UNITS = {"": 1, "b": 1, "k": 1024, "m": 1024 ** 2, "g": 1024 ** 3}


def parse_bytes(v) -> int | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return int(v)
    m = _SIZE_RE.fullmatch(str(v).strip())
    if not m:
        raise Refused(f"bad memory size {v!r}")
    return int(float(m.group(1)) * _UNITS[m.group(2).lower()])


def image_name(project: str, service: str) -> str:
    return re.sub(r"[^a-z0-9._-]", "-", f"kemudi-{project}-{service}".lower())


def rewrite(doc: dict, project: str, expose: tuple[str, int] | None) -> dict:
    """Step 5, on the interpolated reduced file: the compose file svc runs."""
    services = doc.get("services") or {}
    if expose and expose[0] not in services:
        raise Refused(f"expose: no service {expose[0]!r} among the started services")
    out_services = {}
    for name, svc in services.items():
        s = {k: v for k, v in svc.items()
             if k not in DROPPED_SERVICE_KEYS and not k.startswith("x-")}
        if "build" in s:
            s["image"] = image_name(project, name)
            s["build"] = {**s["build"], "labels": {LABEL: project}}
        s["restart"] = "no"
        mem = parse_bytes(s.get("mem_limit"))
        s["mem_limit"] = min(mem, MEM_CAP) if mem else MEM_CAP
        pids = s.get("pids_limit")
        s["pids_limit"] = min(int(pids), PIDS_CAP) if pids and int(pids) > 0 else PIDS_CAP
        s.pop("ports", None)
        if expose and expose[0] == name:
            s["ports"] = [f"0.0.0.0::{expose[1]}"]
        s["labels"] = {LABEL: project}
        out_services[name] = s
    out: dict = {"name": project, "services": out_services}
    vols = doc.get("volumes") or {}
    if vols:
        out["volumes"] = {v: {"labels": {LABEL: project}} for v in vols}
    return out
