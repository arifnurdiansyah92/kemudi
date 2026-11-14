"""Awak skills: validation, scan, skill sets and the Hermes profiles that serve them.

docs/superpowers/specs/2026-11-14-awak-skills-design.md ("Panel review" wins).

A skill is an Agent Skills folder (`<slug>/SKILL.md` + support files), stored
in the DB as immutable versions ({path: base64}). A run gets its role's skills
as a *set*: the pinned versions written to `<skills_dir>/sets/<setid>/<slug>/`
(content-addressed, setid = sha12 of the sorted (slug, sha) pairs) and a
Hermes profile `sk-<setid>` whose `skills.external_dirs` is that folder only.
Every Awak run goes through a profile, an empty set included, so the bundled
Hermes skills never reach a run.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import secrets as pysecrets
import shutil
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath

import yaml
from sqlalchemy.orm import Session

from ..config import Settings
from ..store import AwakLlmAlias, AwakRole, AwakSkill, AwakSkillSet, AwakSkillVersion

log = logging.getLogger(__name__)

# --- Limits (agentskills.io rules + Kemudi's) ---------------------------------
NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9]|-(?=[a-z0-9])){0,63}$")
DESCRIPTION_MAX = 1024
# What reaches the agent (the materialised SKILL.md): a long description is a
# prompt-injection surface in every run's skills index.
DESCRIPTION_AGENT_MAX = 300
COMPATIBILITY_MAX = 500
MAX_TOTAL_BYTES = 2 * 1024 * 1024
MAX_FILES = 200
MAX_DEPTH = 8
BODY_WARN_LINES = 500
SKILL_FILE = "SKILL.md"
SOURCES = ("builtin", "local", "marketplace")

# Where kemudi-awak sees the skill volume (read-only there).
HERMES_SKILLS_DIR = "/opt/skills"
PROFILE_PREFIX = "sk-"
PROFILE_RE = re.compile(r"^sk-[0-9a-f]{12}$")
SETID_RE = re.compile(r"^[0-9a-f]{12}$")
# Hermes creates this in a profile's home once it serves the profile.
SERVED_MARKER = "gateway.lock"
SET_IDLE = timedelta(hours=24)
TMP_IDLE = timedelta(hours=1)

BUILTIN_DIR = Path(__file__).parent / "builtin_skills"


class SkillError(ValueError):
    """A skill that breaks the rules; `problems` lists every reason."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


# --- Files --------------------------------------------------------------------

def _is_text(data: bytes) -> bool:
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _path_problem(path: str) -> str | None:
    if not path or path.startswith("/") or "\\" in path or ":" in path:
        return f"{path!r}: not a plain relative path"
    if any(ord(c) < 32 for c in path):
        return f"{path!r}: control characters in the path"
    parts = PurePosixPath(path).parts
    if path.endswith("/") or any(p in ("", ".", "..") for p in path.split("/")):
        return f"{path!r}: empty, '.' or '..' segment"
    if len(parts) > MAX_DEPTH:
        return f"{path!r}: nested deeper than {MAX_DEPTH} folders"
    if any(len(p) > 255 for p in parts):
        return f"{path!r}: a path segment is too long"
    return None


def read_dir(root: Path) -> dict[str, bytes]:
    """A skill folder from disk as {posix path: bytes}. Symlinks are refused."""
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise SkillError([f"{root}: not a plain folder"])
    files: dict[str, bytes] = {}
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for name in sorted(dirnames + filenames):
            p = Path(dirpath) / name
            if p.is_symlink():
                raise SkillError([f"{p.relative_to(root).as_posix()}: symlinks are not allowed"])
        for name in filenames:
            p = Path(dirpath) / name
            files[p.relative_to(root).as_posix()] = p.read_bytes()
    return files


def encode_files(files: dict[str, bytes]) -> dict[str, str]:
    return {p: base64.b64encode(files[p]).decode("ascii") for p in sorted(files)}


def decode_files(stored: dict[str, str]) -> dict[str, bytes]:
    return {p: base64.b64decode(v) for p, v in stored.items()}


def canonical_sha(files: dict[str, bytes]) -> str:
    """sha256 over the sorted tree: path, length and bytes of every file."""
    h = hashlib.sha256()
    for path in sorted(files):
        data = files[path]
        h.update(f"{path}\0{len(data)}\0".encode())
        h.update(data)
        h.update(b"\0")
    return h.hexdigest()


# --- SKILL.md -----------------------------------------------------------------

_FRONT_RE = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", re.S)


def split_frontmatter(text: str) -> tuple[dict, str, str]:
    """(metadata, frontmatter text, body). Raises SkillError without one."""
    m = _FRONT_RE.match(text)
    if not m:
        raise SkillError(["SKILL.md: no YAML frontmatter (--- ... ---) at the top"])
    try:
        meta = yaml.safe_load(m.group(1))
    except yaml.YAMLError as e:
        raise SkillError([f"SKILL.md: frontmatter is not valid YAML ({e.__class__.__name__})"]) from e
    if not isinstance(meta, dict):
        raise SkillError(["SKILL.md: frontmatter is not a mapping"])
    return meta, m.group(1), text[m.end():]


@dataclass(frozen=True)
class SkillMeta:
    name: str
    description: str
    license: str = ""
    body_lines: int = 0
    size: int = 0
    warnings: tuple[str, ...] = ()


def validate(slug: str, files: dict[str, bytes]) -> SkillMeta:
    """The Agent Skills rules plus Kemudi's limits; every problem at once."""
    problems: list[str] = []
    warnings: list[str] = []
    if not NAME_RE.match(slug or ""):
        problems.append(f"folder name {slug!r}: use 1-64 of a-z, 0-9 and single hyphens "
                        "inside, no leading or trailing hyphen")
    if len(files) > MAX_FILES:
        problems.append(f"{len(files)} files; at most {MAX_FILES}")
    size = sum(len(d) for d in files.values())
    if size > MAX_TOTAL_BYTES:
        problems.append(f"{size} bytes in total; at most {MAX_TOTAL_BYTES}")
    seen: dict[str, str] = {}
    for path, data in sorted(files.items()):
        bad = _path_problem(path)
        if bad:
            problems.append(bad)
            continue
        folded = path.casefold()
        if folded in seen:
            problems.append(f"{path!r} and {seen[folded]!r} differ only in case")
        seen[folded] = path
        if not _is_text(data) and not path.startswith("assets/"):
            problems.append(f"{path!r}: not UTF-8 text (binary files go under assets/)")
    meta: dict = {}
    body = ""
    raw = files.get(SKILL_FILE)
    if raw is None:
        problems.append("no SKILL.md at the top of the folder")
    elif not _is_text(raw):
        problems.append("SKILL.md is not UTF-8 text")
    else:
        try:
            meta, _, body = split_frontmatter(raw.decode("utf-8"))
        except SkillError as e:
            problems.extend(e.problems)
    name = meta.get("name")
    description = meta.get("description")
    lic = meta.get("license")
    if raw is not None and meta:
        if not isinstance(name, str) or not NAME_RE.match(name):
            problems.append("frontmatter name: use 1-64 of a-z, 0-9 and single hyphens inside")
        elif name != slug:
            problems.append(f"frontmatter name {name!r} must equal the folder name {slug!r}")
        if not isinstance(description, str) or not description.strip():
            problems.append("frontmatter description is missing")
        elif len(description) > DESCRIPTION_MAX:
            problems.append(f"frontmatter description is longer than {DESCRIPTION_MAX} characters")
        if lic is not None and not isinstance(lic, str):
            problems.append("frontmatter license must be text")
        comp = meta.get("compatibility")
        if comp is not None and (not isinstance(comp, str) or len(comp) > COMPATIBILITY_MAX):
            problems.append(f"frontmatter compatibility must be text of at most "
                            f"{COMPATIBILITY_MAX} characters")
        if meta.get("metadata") is not None and not isinstance(meta.get("metadata"), dict):
            problems.append("frontmatter metadata must be a mapping")
    lines = body.count("\n") + (1 if body and not body.endswith("\n") else 0)
    if lines > BODY_WARN_LINES:
        warnings.append(f"SKILL.md body has {lines} lines; keep it under {BODY_WARN_LINES} "
                        "and move detail into reference files")
    if problems:
        raise SkillError(problems)
    return SkillMeta(name=name, description=description.strip(), license=(lic or "").strip(),
                     body_lines=lines, size=size, warnings=tuple(warnings))


# --- Scan ---------------------------------------------------------------------

@dataclass(frozen=True)
class _Rule:
    rule: str
    severity: str  # high | medium | low
    pattern: re.Pattern


_RULES = (
    _Rule("instruction_override", "high", re.compile(
        r"\b(ignore|disregard|forget)\s+(all\s+|any\s+|the\s+|your\s+)?"
        r"(previous|prior|above|earlier|system|original)\s+(instructions|rules|prompts?|guidelines)"
        r"|\boverride\s+(the\s+)?(system|kemudi|safety)\s+(prompt|rules|instructions)", re.I)),
    _Rule("exfiltration", "high", re.compile(
        r"\bexfiltrat\w*"
        r"|\b(send|post|upload|leak)\s+(the\s+|all\s+|any\s+)?(secrets?|credentials|api\s+keys?"
        r"|tokens?|passwords?|env(ironment)?(\s+variables)?)\s+to\b", re.I)),
    _Rule("pipe_to_shell", "high", re.compile(
        r"\b(curl|wget)\b[^\n|]*\|\s*(sudo\s+)?(ba|z|da)?sh\b", re.I)),
    _Rule("git_push", "high", re.compile(r"\bgit\s+push\b", re.I)),
    _Rule("env_dump", "high", re.compile(
        r"\bprintenv\b|\benv\s*(\||>)|\bcat\s+\S*\.env\b|/proc/\S*/environ|\bset\s*\|\s*grep\b",
        re.I)),
    _Rule("inline_shell", "high", re.compile(r"!`[^`\n]+`")),
    _Rule("secret_reference", "medium", re.compile(
        r"\b[A-Z][A-Z0-9_]*(API_KEY|SECRET|TOKEN|PASSWORD|PRIVATE_KEY)[A-Z0-9_]*\b"
        r"|\bKEMUDI_[A-Z0-9_]+\b|\bid_(rsa|ed25519)\b")),
    _Rule("network_url", "low", re.compile(r"\b(https?|ftp|wss?)://[^\s)>\]\"'`]+", re.I)),
)
_SEVERITY_ORDER = {"high": 3, "medium": 2, "low": 1}
MAX_FINDINGS_PER_RULE = 20


def scan(files: dict[str, bytes]) -> list[dict]:
    """Findings (rule, severity, path, line, excerpt) over every text file."""
    findings: list[dict] = []
    counts: dict[str, int] = {}
    for path in sorted(files):
        if path.startswith("scripts/"):
            findings.append({"rule": "script", "severity": "medium", "path": path,
                             "line": 0, "excerpt": "a script the agent can run"})
        data = files[path]
        if not _is_text(data):
            continue
        for n, line in enumerate(data.decode("utf-8").splitlines(), 1):
            for r in _RULES:
                m = r.pattern.search(line)
                if not m or counts.get(r.rule, 0) >= MAX_FINDINGS_PER_RULE:
                    continue
                counts[r.rule] = counts.get(r.rule, 0) + 1
                start = max(0, m.start() - 40)
                findings.append({"rule": r.rule, "severity": r.severity, "path": path,
                                 "line": n, "excerpt": line[start:start + 120].strip()})
    return findings


def worst(findings: Iterable[dict]) -> str:
    """The highest severity among `findings`, '' for none."""
    best = ""
    for f in findings:
        if _SEVERITY_ORDER.get(f.get("severity", ""), 0) > _SEVERITY_ORDER.get(best, 0):
            best = f["severity"]
    return best


# --- Skill sets -----------------------------------------------------------------

@dataclass(frozen=True)
class SetEntry:
    slug: str
    version: int
    sha256: str
    source: str


def set_id(entries: Iterable[SetEntry]) -> str:
    lines = sorted(f"{e.slug}:{e.sha256}" for e in entries)
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()[:12]


EMPTY_SETID = set_id(())


def profile_name(setid: str) -> str:
    return PROFILE_PREFIX + setid


@dataclass(frozen=True)
class Resolved:
    """A role's skills as a run gets them: enabled skills at their current
    active version; the others dropped (with the reason)."""

    entries: tuple[SetEntry, ...] = ()
    dropped: tuple[dict, ...] = ()

    @property
    def setid(self) -> str:
        return set_id(self.entries)

    @property
    def profile(self) -> str:
        return profile_name(self.setid)

    @property
    def slugs(self) -> list[str]:
        return [e.slug for e in self.entries]

    @property
    def has_marketplace(self) -> bool:
        return any(e.source == "marketplace" for e in self.entries)

    def event(self) -> dict:
        """What a run event records about the skills it got."""
        return {"profile": self.profile,
                "skills": [{"slug": e.slug, "version": e.version, "sha": e.sha256[:12],
                            "source": e.source} for e in self.entries],
                "dropped": list(self.dropped)}


def resolve(db: Session, slugs: Iterable[str] | None) -> Resolved:
    entries: list[SetEntry] = []
    dropped: list[dict] = []
    for slug in dict.fromkeys(slugs or []):
        sk = db.get(AwakSkill, slug)
        if sk is None:
            dropped.append({"slug": slug, "reason": "missing"})
            continue
        if not sk.enabled:
            dropped.append({"slug": slug, "reason": "disabled"})
            continue
        v = (db.query(AwakSkillVersion)
             .filter_by(slug=slug, version=sk.current_version, status="active").one_or_none())
        if v is None:
            dropped.append({"slug": slug, "reason": "no active version"})
            continue
        entries.append(SetEntry(slug, v.version, v.sha256, sk.source))
    return Resolved(tuple(entries), tuple(dropped))


# --- Role assignment ---------------------------------------------------------------

# Skills a new role of a template gets (only those installed and enabled).
TEMPLATE_DEFAULTS: dict[str, tuple[str, ...]] = {
    "frontend": ("impeccable",),
    "fullstack": ("impeccable",),
}
ROLE_TEMPLATES = ("frontend", "backend", "fullstack", "qa")
MAX_ROLE_SKILLS = 20
PICKER_DESCRIPTION_MAX = 200


def _current(db: Session, sk: AwakSkill) -> AwakSkillVersion | None:
    return (db.query(AwakSkillVersion)
            .filter_by(slug=sk.slug, version=sk.current_version, status="active").one_or_none())


def _usable(db: Session, sk: AwakSkill | None) -> bool:
    return sk is not None and sk.enabled and _current(db, sk) is not None


def template_defaults(db: Session, template: str) -> list[str]:
    """The template's default skills that a role can get now."""
    return [s for s in TEMPLATE_DEFAULTS.get(template, ()) if _usable(db, db.get(AwakSkill, s))]


def check_assignable(db: Session, slugs: list[str], keep: Iterable[str] = ()) -> list[str]:
    """`slugs` as a role's skills: unique, at most MAX_ROLE_SKILLS, each
    installed and enabled. Slugs in `keep` (already on the role) may stay
    even when disabled or missing since (the role shows a warning, runs drop
    them). Raises SkillError naming the refused slugs."""
    if len(set(slugs)) != len(slugs):
        raise SkillError(["each skill can be assigned once"])
    if len(slugs) > MAX_ROLE_SKILLS:
        raise SkillError([f"at most {MAX_ROLE_SKILLS} skills per role"])
    keep = set(keep)
    bad = [s for s in slugs if s not in keep and not _usable(db, db.get(AwakSkill, s))]
    if bad:
        raise SkillError([f"skills not installed or not enabled: {', '.join(bad)}"])
    return list(slugs)


def _summary(db: Session, sk: AwakSkill) -> dict:
    v = _current(db, sk)
    return {"slug": sk.slug, "title": sk.title or sk.slug, "source": sk.source,
            "license": sk.license, "enabled": sk.enabled,
            "version": v.version if v is not None else None,
            # "" (clean) | low | medium | high
            "scan_level": (v.scan or {}).get("worst", "") if v is not None else ""}


def describe(db: Session, slugs: Iterable[str] | None) -> list[dict]:
    """A role's skills for display, in order; `status` ok | disabled |
    missing | no_version (the last three are dropped at run time)."""
    out = []
    for slug in slugs or []:
        sk = db.get(AwakSkill, slug)
        if sk is None:
            out.append({"slug": slug, "title": slug, "source": "", "license": "",
                        "enabled": False, "version": None, "scan_level": "",
                        "status": "missing"})
            continue
        d = _summary(db, sk)
        d["status"] = ("disabled" if not sk.enabled
                       else "no_version" if d["version"] is None else "ok")
        out.append(d)
    return out


def _short(text: str, limit: int = PICKER_DESCRIPTION_MAX) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def picker(db: Session) -> list[dict]:
    """Enabled skills with an active version, for the role editor's picker."""
    rows = db.query(AwakSkill).filter_by(enabled=True).order_by(AwakSkill.slug).all()
    out = []
    for sk in rows:
        d = _summary(db, sk)
        if d["version"] is None:
            continue
        d["description"] = _short(sk.description)
        out.append(d)
    return out


def agent_skill_md(raw: bytes) -> bytes:
    """SKILL.md as the agent sees it: the description cut to
    DESCRIPTION_AGENT_MAX characters (the rest of the file as stored)."""
    text = raw.decode("utf-8")
    meta, _, body = split_frontmatter(text)
    desc = str(meta.get("description") or "")
    if len(desc) <= DESCRIPTION_AGENT_MAX:
        return raw
    meta["description"] = desc[:DESCRIPTION_AGENT_MAX - 3].rstrip() + "..."
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, width=1_000_000)
    return f"---\n{front}---\n{body}".encode()


def agent_files(files: dict[str, bytes]) -> dict[str, bytes]:
    out = dict(files)
    if SKILL_FILE in out:
        out[SKILL_FILE] = agent_skill_md(out[SKILL_FILE])
    return out


def _tree(root: Path) -> dict[str, bytes] | None:
    try:
        return read_dir(root)
    except (SkillError, OSError):
        return None


def _chown(path: Path, uid: int | None) -> None:
    if uid is None or not hasattr(os, "chown"):
        return
    try:
        os.chown(path, uid, uid)
    except PermissionError:  # not root (tests): the files stay the caller's
        pass


def _write_tree(root: Path, files: dict[str, bytes], uid: int | None = None) -> None:
    root.mkdir(mode=0o755)
    os.chmod(root, 0o755)
    _chown(root, uid)
    for rel in sorted(files):
        p = root / rel
        for parent in reversed(p.relative_to(root).parents[:-1]):
            d = root / parent
            if not d.exists():
                d.mkdir(mode=0o755)
                os.chmod(d, 0o755)
                _chown(d, uid)
        p.write_bytes(files[rel])
        os.chmod(p, 0o644)
        _chown(p, uid)


def _swap_in(tmp: Path, final: Path) -> None:
    """Moves `tmp` to `final`, replacing an existing `final`."""
    if final.exists():
        old = final.parent / f".old-{final.name}-{pysecrets.token_hex(4)}"
        os.rename(final, old)
        os.rename(tmp, final)
        shutil.rmtree(old, ignore_errors=True)
    else:
        os.rename(tmp, final)


def materialise(sets_dir: Path, entries: list[tuple[str, dict[str, bytes]]]) -> tuple[str, bool]:
    """Writes the set (`[(slug, files)]`) to `<sets_dir>/<setid>/<slug>/...`,
    built under a `.tmp-` name and renamed into place. An existing set with
    the same bytes is kept; any difference is rewritten. Returns (setid,
    written)."""
    sets_dir = Path(sets_dir)
    sets_dir.mkdir(parents=True, exist_ok=True)
    setid = set_id(SetEntry(slug, 0, canonical_sha(files), "") for slug, files in entries)
    want = {f"{slug}/{p}": data for slug, files in entries
            for p, data in agent_files(files).items()}
    final = sets_dir / setid
    if final.is_dir() and not final.is_symlink() and _tree(final) == want:
        return setid, False
    tmp = sets_dir / f".tmp-{setid}-{pysecrets.token_hex(4)}"
    try:
        _write_tree(tmp, want)
        _swap_in(tmp, final)
    finally:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
    return setid, True


# --- Profiles -------------------------------------------------------------------

def _env_value(name: str, value: str) -> str:
    if any(c in value for c in "\r\n\0"):
        raise ValueError(f"{name} contains a line break")
    return value


def profile_files(settings: Settings, setid: str) -> dict[str, bytes]:
    """config.yaml and .env of profile sk-<setid>. The managed overlay
    (/etc/hermes/config.yaml) wins over everything but skills.external_dirs;
    the overlay's ${...} expand from this .env (container env vars do not
    reach a profile scope), and the gateway checks API_SERVER_KEY per
    profile."""
    if not SETID_RE.match(setid):
        raise ValueError(f"bad set id {setid!r}")
    config = ("# Written by Kemudi (kemudi_ai/awak/skills.py); rewritten when it changes.\n"
              "skills:\n"
              "  external_dirs:\n"
              f"    - {HERMES_SKILLS_DIR}/sets/{setid}\n")
    env = (f"API_SERVER_KEY={_env_value('API_SERVER_KEY', settings.awak_api_key)}\n"
           "KEMUDI_LLM_PROXY_TOKEN="
           f"{_env_value('KEMUDI_LLM_PROXY_TOKEN', settings.llm_proxy_token or 'unset')}\n"
           f"KEMUDI_AWAK_MODEL={_env_value('KEMUDI_AWAK_MODEL', settings.awak_model)}\n")
    return {"config.yaml": config.encode(), ".env": env.encode()}


_FILE_MODES = {"config.yaml": 0o644, ".env": 0o600}


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_profile(settings: Settings, setid: str) -> tuple[str, list[str]]:
    """Creates profile sk-<setid> (built as `.tmp-…`, owned by the agent's uid
    because Hermes writes its runtime state there, then renamed in), or
    re-checks an existing one's config files by hash and rewrites those that
    differ. Returns (profile, rewritten file names)."""
    name = profile_name(setid)
    root = Path(settings.awak_profiles_dir)
    root.mkdir(parents=True, exist_ok=True)
    want = profile_files(settings, setid)
    home = root / name
    uid = settings.awak_uid
    if home.is_dir() and not home.is_symlink():
        rewritten = []
        for fn, data in want.items():
            p = home / fn
            try:
                ok = not p.is_symlink() and _digest(p.read_bytes()) == _digest(data)
            except OSError:
                ok = False
            if ok:
                continue
            tmp = home / f".tmp-{fn}-{pysecrets.token_hex(4)}"
            tmp.write_bytes(data)
            os.chmod(tmp, _FILE_MODES[fn])
            _chown(tmp, uid)
            if p.is_symlink() or p.is_dir():
                p.unlink() if p.is_symlink() else shutil.rmtree(p)
            os.replace(tmp, p)
            rewritten.append(fn)
        return name, rewritten
    if home.is_symlink():
        home.unlink()
    tmp = root / f".tmp-{name}-{pysecrets.token_hex(4)}"
    try:
        tmp.mkdir(mode=0o755)
        os.chmod(tmp, 0o755)
        _chown(tmp, uid)
        for fn, data in want.items():
            (tmp / fn).write_bytes(data)
            os.chmod(tmp / fn, _FILE_MODES[fn])
            _chown(tmp / fn, uid)
        os.rename(tmp, home)
    finally:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
    return name, list(want)


def is_served(settings: Settings, profile: str) -> bool:
    return (Path(settings.awak_profiles_dir) / profile / SERVED_MARKER).exists()


def wait_served(settings: Settings, profile: str, timeout_s: float,
                sleep: Callable[[float], None] = time.sleep,
                clock: Callable[[], float] = time.monotonic) -> bool:
    """Hermes serves a new profile at its next watcher pass (every 30 s)."""
    deadline = clock() + timeout_s
    while not is_served(settings, profile):
        if clock() >= deadline:
            return False
        sleep(2.0)
    return True


# --- Prepare (per run) -----------------------------------------------------------

def _naive_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass(frozen=True)
class Prepared(Resolved):
    rewritten: tuple[str, ...] = field(default=())

    def event(self) -> dict:
        out = super().event()
        if self.rewritten:
            out["rewritten"] = list(self.rewritten)
        return out


def prepare_set(settings: Settings, db: Session, slugs: Iterable[str] | None) -> Prepared:
    """Before every run: the role's skills (disabled or missing ones dropped)
    written as a set and its profile; existing ones re-verified. The run then
    calls /p/<profile>/."""
    r = resolve(db, slugs)
    loaded: list[tuple[str, dict[str, bytes]]] = []
    for e in r.entries:
        v = db.query(AwakSkillVersion).filter_by(slug=e.slug, version=e.version).one()
        files = decode_files(v.files)
        if canonical_sha(files) != e.sha256:
            raise SkillError([f"skill {e.slug} v{e.version}: stored files do not match their sha"])
        loaded.append((e.slug, files))
    setid, set_written = materialise(Path(settings.awak_skills_dir) / "sets", loaded)
    assert setid == r.setid
    profile, rewritten = write_profile(settings, setid)
    now = _naive_now()
    row = db.get(AwakSkillSet, setid)
    if row is None:
        db.add(AwakSkillSet(setid=setid, created_at=now, last_used_at=now,
                            skills=[asdict(e) for e in r.entries]))
    else:
        row.last_used_at = now
    db.commit()
    changed = (["set"] if set_written else []) + rewritten
    return Prepared(r.entries, r.dropped, tuple(changed))


# --- Sweep -----------------------------------------------------------------------

def _mtime(p: Path) -> datetime:
    try:
        return datetime.fromtimestamp(p.stat().st_mtime, UTC).replace(tzinfo=None)
    except OSError:
        return datetime.min


def referenced_setids(db: Session) -> set[str]:
    """Sets some role would run with now (the empty set always)."""
    ids = {EMPTY_SETID}
    for role in db.query(AwakRole).all():
        ids.add(resolve(db, role.skills or []).setid)
    return ids


def sweep(settings: Settings, db: Session, now: datetime | None = None,
          idle: timedelta = SET_IDLE) -> list[str]:
    """Deletes sets no role references and no run used for `idle`, never one a
    live alias (a running run) names: the profile first, then the files.
    Leftover `.tmp-`/`.old-` folders older than an hour go too. Returns the
    removed set ids."""
    now = now or _naive_now()
    sets_dir = Path(settings.awak_skills_dir) / "sets"
    prof_dir = Path(settings.awak_profiles_dir)
    keep = referenced_setids(db)
    for a in db.query(AwakLlmAlias).all():
        if a.profile and a.expires_at > now and a.profile.startswith(PROFILE_PREFIX):
            keep.add(a.profile[len(PROFILE_PREFIX):])
    rows = {r.setid: r for r in db.query(AwakSkillSet).all()}
    found: set[str] = set(rows)
    if sets_dir.is_dir():
        found |= {p.name for p in sets_dir.iterdir() if SETID_RE.match(p.name)}
    if prof_dir.is_dir():
        found |= {p.name[len(PROFILE_PREFIX):] for p in prof_dir.iterdir()
                  if PROFILE_RE.match(p.name)}
    removed = []
    for setid in sorted(found - keep):
        row = rows.get(setid)
        last = row.last_used_at if row else max(_mtime(sets_dir / setid),
                                                 _mtime(prof_dir / profile_name(setid)))
        if now - last < idle:
            continue
        shutil.rmtree(prof_dir / profile_name(setid), ignore_errors=True)
        shutil.rmtree(sets_dir / setid, ignore_errors=True)
        if row is not None:
            db.delete(row)
        removed.append(setid)
    db.commit()
    for d in (sets_dir, prof_dir):
        if not d.is_dir():
            continue
        for p in d.iterdir():
            if (p.name.startswith((".tmp-", ".old-")) and p.is_dir()
                    and now - _mtime(p) > TMP_IDLE):
                shutil.rmtree(p, ignore_errors=True)
    if removed:
        log.info("skill sets swept: %s", ", ".join(removed))
    return removed


# --- Built-in skills -------------------------------------------------------------

def _store_version(db: Session, slug: str, version: int, files: dict[str, bytes], sha: str,
                   findings: list[dict], warnings: tuple[str, ...], by: str) -> AwakSkillVersion:
    v = AwakSkillVersion(slug=slug, version=version, sha256=sha, files=encode_files(files),
                         size=sum(len(d) for d in files.values()),
                         scan={"findings": findings, "warnings": list(warnings),
                               "worst": worst(findings)},
                         status="active", created_by=by)
    db.add(v)
    return v


def seed_builtin(db: Session, root: Path = BUILTIN_DIR) -> list[str]:
    """The skills vendored with Kemudi (builtin_skills/<slug>/, origin in
    sources.json) as `builtin` library entries. Idempotent: a vendored tree
    with a new sha becomes the next active version. A builtin with a high
    scan finding is stored disabled. Returns what changed ("slug vN")."""
    root = Path(root)
    sources_file = root / "sources.json"
    sources = json.loads(sources_file.read_text(encoding="utf-8")) if sources_file.exists() else {}
    changed: list[str] = []
    for d in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(("_", "."))):
        slug = d.name
        try:
            files = read_dir(d)
            meta = validate(slug, files)
        except SkillError as e:
            log.error("builtin skill %s is invalid: %s", slug, e)
            continue
        sha = canonical_sha(files)
        findings = scan(files)
        src = sources.get(slug) or {}
        origin = {k: v for k, v in src.items() if k not in ("title", "license")}
        sk = db.get(AwakSkill, slug)
        if sk is None:
            sk = AwakSkill(slug=slug, source="builtin", title=src.get("title") or slug,
                           description=meta.description,
                           license=src.get("license") or meta.license or "",
                           enabled=worst(findings) != "high", current_version=1,
                           origin=origin, created_by="builtin")
            db.add(sk)
            _store_version(db, slug, 1, files, sha, findings, meta.warnings, "builtin")
            changed.append(f"{slug} v1")
        else:
            cur = (db.query(AwakSkillVersion)
                   .filter_by(slug=slug, version=sk.current_version).one_or_none())
            if cur is not None and cur.sha256 == sha:
                continue
            if sk.source != "builtin":
                log.warning("skill %s exists as %s; the builtin copy is not seeded",
                            slug, sk.source)
                continue
            last = max([v.version for v in db.query(AwakSkillVersion).filter_by(slug=slug)],
                       default=0)
            _store_version(db, slug, last + 1, files, sha, findings, meta.warnings, "builtin")
            sk.current_version = last + 1
            sk.description = meta.description
            sk.license = src.get("license") or meta.license or sk.license
            sk.title = src.get("title") or sk.title
            sk.origin = origin
            if worst(findings) == "high":
                sk.enabled = False
            sk.updated_at = datetime.now(UTC)
            changed.append(f"{slug} v{last + 1}")
        if worst(findings) == "high":
            log.error("builtin skill %s has a high scan finding; stored disabled", slug)
    db.commit()
    return changed
