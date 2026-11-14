"""Awak skills: validation, scan, skill sets and the Hermes profiles that serve them.

docs/superpowers/specs/2026-11-14-awak-skills-design.md ("Panel review" wins).

A skill is an Agent Skills folder (`<slug>/SKILL.md` + support files), stored
in the DB as immutable versions ({path: base64}). A run gets its role's skills
as a *set*: the pinned versions written to `<skills_dir>/sets/<setid>/<slug>/`
(content-addressed, setid = the first 32 hex of a sha256 over the sorted
(slug, sha) pairs) and a
Hermes profile `sk-<setid>` whose `skills.external_dirs` is that folder only.
Every Awak run goes through a profile, an empty set included, so the bundled
Hermes skills never reach a run.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import os
import re
import secrets as pysecrets
import shutil
import time
import unicodedata
import zipfile
import zlib
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
# Words the library API uses as paths under /skills/ (skills_api.py): a skill
# with one of these names would be shadowed by, or shadow, that route.
RESERVED_SLUGS = frozenset({"library", "validate", "upload", "versions", "files",
                            "enable", "disable"})

# Where kemudi-awak sees the skill volume (read-only there).
HERMES_SKILLS_DIR = "/opt/skills"
PROFILE_PREFIX = "sk-"
SETID_LEN = 32  # "sk-" + 32 fits the 40-character alias/profile columns
PROFILE_RE = re.compile(r"^sk-[0-9a-f]{32}$")
SETID_RE = re.compile(r"^[0-9a-f]{32}$")
# Set ids the sweep removes: today's and the 12-hex ones from before.
_SWEEPABLE_RE = re.compile(r"^(?:[0-9a-f]{12}|[0-9a-f]{32})$")
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
    elif slug in RESERVED_SLUGS:
        problems.append(f"folder name {slug!r} is reserved (a path under /skills/); "
                        "pick another name")
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


_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def _scan_text(data: bytes) -> str:
    """What the scan reads of a file. Binaries (allowed under assets/) are
    read too: NUL bytes dropped (so UTF-16 text reads as ASCII) and what is
    not UTF-8 ignored; the agent can open any file it is given."""
    if _is_text(data):
        return data.decode("utf-8")
    return data.replace(b"\x00", b"").decode("utf-8", errors="ignore")


def scan(files: dict[str, bytes]) -> list[dict]:
    """Findings (rule, severity, path, line, excerpt) over every file."""
    findings: list[dict] = []
    counts: dict[str, int] = {}
    for path in sorted(files):
        if path.startswith("scripts/"):
            findings.append({"rule": "script", "severity": "medium", "path": path,
                             "line": 0, "excerpt": "a script the agent can run"})
        for n, line in enumerate(_scan_text(files[path]).splitlines(), 1):
            for r in _RULES:
                m = r.pattern.search(line)
                if not m or counts.get(r.rule, 0) >= MAX_FINDINGS_PER_RULE:
                    continue
                counts[r.rule] = counts.get(r.rule, 0) + 1
                start = max(0, m.start() - 40)
                excerpt = _CONTROL_RE.sub(" ", line[start:start + 120]).strip()
                findings.append({"rule": r.rule, "severity": r.severity, "path": path,
                                 "line": n, "excerpt": excerpt})
    return findings


def severity_rank(level: str) -> int:
    """0 for clean ("" or unknown), then low < medium < high."""
    return _SEVERITY_ORDER.get(level or "", 0)


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
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()[:SETID_LEN]


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


def _is_root() -> bool:
    """Only root can give files away; elsewhere (tests, a dev checkout) the
    files stay the caller's."""
    return hasattr(os, "geteuid") and os.geteuid() == 0


def _owner(path: Path) -> int:
    return os.lstat(path).st_uid


def _chown(path: Path, uid: int | None) -> None:
    """Gives `path` to `uid` when running as root. A failure is an error (a
    profile Hermes cannot write is parked for good), never ignored."""
    if uid is None or not _is_root():
        return
    os.chown(path, uid, uid, follow_symlinks=False)


def _safe_rel(rel: str) -> str | None:
    """Why `rel` (set-relative, `<slug>/<path>`) may not be written, or None."""
    slug, _, path = rel.partition("/")
    if not NAME_RE.match(slug):
        return f"{rel!r}: not a skill folder name"
    return _path_problem(path)


def _write_tree(root: Path, files: dict[str, bytes], uid: int | None = None,
                check: Callable[[str], str | None] = _path_problem) -> None:
    """Writes `files` under the new folder `root`. Every path is re-checked
    (`check`) and must resolve inside `root`: stored rows are not trusted."""
    problems = [bad for rel in sorted(files) if (bad := check(rel))]
    if problems:
        raise SkillError(problems)
    root.mkdir(mode=0o755)
    os.chmod(root, 0o755)
    _chown(root, uid)
    base = root.resolve()
    for rel in sorted(files):
        p = root / rel
        if not p.resolve().is_relative_to(base):
            raise SkillError([f"{rel!r}: leaves the set folder"])
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


CREATED, REWRITTEN = "created", "rewritten"


def materialise(sets_dir: Path, entries: list[tuple[str, dict[str, bytes]]]) -> tuple[str, str]:
    """Writes the set (`[(slug, files)]`) to `<sets_dir>/<setid>/<slug>/...`,
    built under a `.tmp-` name and renamed into place. An existing set with
    the same bytes is kept; any difference is rewritten. Returns (setid,
    "" | CREATED | REWRITTEN)."""
    sets_dir = Path(sets_dir)
    sets_dir.mkdir(parents=True, exist_ok=True)
    setid = set_id(SetEntry(slug, 0, canonical_sha(files), "") for slug, files in entries)
    want = {f"{slug}/{p}": data for slug, files in entries
            for p, data in agent_files(files).items()}
    final = sets_dir / setid
    existed = final.exists() or final.is_symlink()
    if final.is_dir() and not final.is_symlink() and _tree(final) == want:
        return setid, ""
    tmp = sets_dir / f".tmp-{setid}-{pysecrets.token_hex(4)}"
    try:
        _write_tree(tmp, want, check=_safe_rel)
        if final.is_symlink() or final.is_file():
            final.unlink()
        _swap_in(tmp, final)
    finally:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
    return setid, REWRITTEN if existed else CREATED


# --- Profiles -------------------------------------------------------------------

def _env_value(name: str, value: str) -> str:
    if any(c in value for c in "\r\n\0"):
        raise ValueError(f"{name} contains a line break")
    return value


# Kemudi's SOUL.md for every profile (Hermes seeds its own persona file when a
# profile has none; a run's terminal could rewrite it for later runs).
SOUL_MD = ("You are Awak, Kemudi's coding agent. Each run's system prompt sets the task "
           "and its rules; follow it. Be direct: report what changed, what is verified "
           "and what is left, without filler.\n")


def profile_files(settings: Settings, setid: str) -> dict[str, bytes]:
    """config.yaml, .env and SOUL.md of profile sk-<setid>. The managed
    overlay (/etc/hermes/config.yaml) wins over everything but
    skills.external_dirs; the overlay's ${...} expand from this .env
    (container env vars do not reach a profile scope), and the gateway checks
    API_SERVER_KEY per profile."""
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
    return {"config.yaml": config.encode(), ".env": env.encode(), "SOUL.md": SOUL_MD.encode()}


_FILE_MODES = {"config.yaml": 0o644, ".env": 0o600, "SOUL.md": 0o644}

# What a profile home may hold besides Kemudi's files (profile_files), from
# the spike (plan 2026-11-14-awak-skills-pr1-runtime.md, "Spike notes") and
# the live profiles. The agent's terminal runs as the uid that owns the
# profiles (Hermes re-chowns them at boot), so before every run everything
# else goes: a planted skill, hook, plugin, memory or cron job never reaches
# a later run.
_STATE_FILES = frozenset({"gateway.lock"})
_STATE_PREFIXES = ("state.db",)  # state.db, -shm, -wal, .fts_rebuild.lock, ...
# Hermes' runtime state, kept as it is.
_STATE_DIRS = frozenset({"sessions", "logs", "cache", "audio_cache", "image_cache",
                         "pairing", "platforms", "plugin-update-checks", "runtime", "backups"})
# Folders Hermes creates empty; what is inside goes.
_EMPTY_DIRS = frozenset({"hooks", "plugins", "memories"})
# Folder -> the entries Hermes itself keeps there.
_KEEP_INSIDE = {
    "skills": frozenset({".hub", ".usage.json", ".usage.json.lock"}),
    "cron": frozenset({"executions.db", ".jobs.lock", ".tick.lock", "ticker_heartbeat",
                       "ticker_last_success", "output"}),
}
# Caches Hermes rebuilds: removed before every run without a report (a
# planted skills-prompt snapshot would reach the next run's skills index).
_ALWAYS_DROP = frozenset({".skills_prompt_snapshot.json", "lsp"})  # lsp: language-server cache


def _remove(p: Path) -> None:
    if p.is_symlink() or not p.is_dir():
        p.unlink()
    else:
        shutil.rmtree(p)


def _expected(name: str, p: Path) -> bool:
    """Whether `name` (a profile home entry) is Hermes state left alone."""
    if p.is_symlink():
        return False
    if name in _STATE_FILES or name.startswith(_STATE_PREFIXES):
        return p.is_file()
    if name in _STATE_DIRS or name in _EMPTY_DIRS or name in _KEEP_INSIDE:
        return p.is_dir()
    return False


def reset_profile(home: Path, managed: Iterable[str]) -> list[str]:
    """Resets profile `home` to the allowlist: Kemudi's `managed` files (the
    caller re-checks them), Hermes' runtime state, and the folders Hermes
    keeps empty or holds its own entries in. Removes everything else; returns
    what it removed that was not a known cache (home-relative, sorted)."""
    managed = set(managed)
    removed: list[str] = []
    for p in sorted(home.iterdir()):
        name = p.name
        if name in managed:
            if p.is_symlink() or p.is_dir():
                _remove(p)
                removed.append(name)
            continue
        if name in _ALWAYS_DROP:
            _remove(p)
            continue
        if name.startswith(".tmp-"):  # Kemudi's own write in progress or left over
            _remove(p)
            continue
        if not _expected(name, p):
            _remove(p)
            removed.append(name)
            continue
        if name in _EMPTY_DIRS or name in _KEEP_INSIDE:
            keep = _KEEP_INSIDE.get(name, frozenset())
            for child in sorted(p.iterdir()):
                if child.name in keep and not child.is_symlink():
                    continue
                _remove(child)
                removed.append(f"{name}/{child.name}")
    return sorted(removed)


def _fix_owner(home: Path, uid: int | None) -> bool:
    """As root: everything in `home` belongs to the agent's uid (Hermes parks
    a profile it cannot write, for good). Returns whether anything changed."""
    if uid is None or not _is_root():
        return False
    changed = False
    paths = [home]
    for dirpath, dirnames, filenames in os.walk(home, followlinks=False):
        paths += [Path(dirpath) / n for n in dirnames + filenames]
    for p in paths:
        if _owner(p) != uid:
            _chown(p, uid)
            changed = True
    return changed


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class ProfileWrite:
    """What write_profile did: `created` (a new profile), `rewritten`
    (managed files that differed, "owner" when the ownership was fixed) and
    `removed` (unexpected entries; see reset_profile)."""

    name: str
    created: bool = False
    rewritten: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()


def _unknown_profiles(root: Path) -> list[str]:
    """Entries of the profiles folder that are not Kemudi's: Hermes serves
    every profile there, so a run's terminal could plant one (with its own
    cron jobs). `sk-<hex>` ones and Kemudi's `.tmp-`/`.old-` folders are left
    to the sweep."""
    removed = []
    for p in sorted(root.iterdir()):
        if re.match(r"^sk-[0-9a-f]+$", p.name) and p.is_dir() and not p.is_symlink():
            continue
        if p.name.startswith((".tmp-", ".old-")):
            continue
        _remove(p)
        removed.append(f"profiles/{p.name}")
    return removed


def write_profile(settings: Settings, setid: str) -> ProfileWrite:
    """Creates profile sk-<setid> (built as `.tmp-…`, owned by the agent's uid
    because Hermes writes its runtime state there, then renamed in), or
    resets an existing one: unexpected entries removed (reset_profile), the
    managed files re-checked by hash and rewritten when they differ, the
    ownership fixed."""
    name = profile_name(setid)
    root = Path(settings.awak_profiles_dir)
    root.mkdir(parents=True, exist_ok=True)
    want = profile_files(settings, setid)
    home = root / name
    uid = settings.awak_uid
    stray = _unknown_profiles(root)
    if home.is_dir() and not home.is_symlink():
        removed = reset_profile(home, want)
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
            os.replace(tmp, p)
            rewritten.append(fn)
        if _fix_owner(home, uid):
            log.warning("awak profile %s was not owned by uid %s; fixed", name, uid)
            rewritten.append("owner")
        return ProfileWrite(name, False, tuple(sorted(rewritten)), tuple(stray + removed))
    if home.is_symlink() or home.exists():
        _remove(home)
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
    return ProfileWrite(name, True, (), tuple(stray))


def rebuild_profile(settings: Settings, profile: str) -> ProfileWrite:
    """Deletes profile `profile` and writes it anew: Hermes parks a profile it
    could not serve (503 runtime_draining) and never retries it; a fresh
    folder is a new profile to its watcher."""
    if not PROFILE_RE.match(profile):
        raise ValueError(f"not a skill-set profile: {profile!r}")
    home = Path(settings.awak_profiles_dir) / profile
    if home.is_symlink() or home.exists():
        _remove(home)
    return write_profile(settings, profile[len(PROFILE_PREFIX):])


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


def not_served_message(profile: str) -> str:
    return (f"profile {profile} not served by kemudi-awak; is the kemudi-awak-profiles "
            "volume mounted at /opt/data/profiles?")


# --- Prepare (per run) -----------------------------------------------------------

def _naive_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass(frozen=True)
class Prepared(Resolved):
    """`created`: built for this run ("set", "profile"); `rewritten`: found
    different from what Kemudi wrote (tampering or a mismatch) and rewritten;
    `removed`: unexpected entries reset_profile removed."""

    created: tuple[str, ...] = field(default=())
    rewritten: tuple[str, ...] = field(default=())
    removed: tuple[str, ...] = field(default=())

    def event(self) -> dict:
        out = super().event()
        if self.created:
            out["created"] = list(self.created)
        if self.rewritten:
            out["rewritten"] = list(self.rewritten)
        return out


def prepare_set(settings: Settings, db: Session, slugs: Iterable[str] | None) -> Prepared:
    """Before every run: the role's skills (disabled or missing ones dropped)
    written as a set and its profile; existing ones re-verified and the
    profile reset to its allowlist. The run then calls /p/<profile>/."""
    r = resolve(db, slugs)
    loaded: list[tuple[str, dict[str, bytes]]] = []
    for e in r.entries:
        v = db.query(AwakSkillVersion).filter_by(slug=e.slug, version=e.version).one()
        files = decode_files(v.files)
        if canonical_sha(files) != e.sha256:
            raise SkillError([f"skill {e.slug} v{e.version}: stored files do not match their sha"])
        loaded.append((e.slug, files))
    setid, set_state = materialise(Path(settings.awak_skills_dir) / "sets", loaded)
    assert setid == r.setid
    prof = write_profile(settings, setid)
    now = _naive_now()
    row = db.get(AwakSkillSet, setid)
    if row is None:
        db.add(AwakSkillSet(setid=setid, created_at=now, last_used_at=now,
                            skills=[asdict(e) for e in r.entries]))
    else:
        row.last_used_at = now
    db.commit()
    created = (["set"] if set_state == CREATED else []) + (["profile"] if prof.created else [])
    rewritten = (["set"] if set_state == REWRITTEN else []) + list(prof.rewritten)
    if prof.removed:
        log.warning("awak profile %s reset; removed %s", prof.name, ", ".join(prof.removed))
    return Prepared(r.entries, r.dropped, tuple(created), tuple(rewritten), prof.removed)


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
        found |= {p.name for p in sets_dir.iterdir() if _SWEEPABLE_RE.match(p.name)}
    if prof_dir.is_dir():
        found |= {p.name[len(PROFILE_PREFIX):] for p in prof_dir.iterdir()
                  if p.name.startswith(PROFILE_PREFIX)
                  and _SWEEPABLE_RE.match(p.name[len(PROFILE_PREFIX):])}
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


# --- Upload (zip / .skill / SKILL.md) ----------------------------------------------

MAX_UPLOAD_BYTES = 4 * 1024 * 1024  # the archive itself, before decompressing
MAX_ZIP_ENTRIES = 400  # files and folder entries
MAX_RATIO = 100  # decompressed bytes per compressed byte, per entry (floor 1 KiB)
_RATIO_FLOOR = 1024
_ARCHIVE_EXT = (".zip", ".skill", ".jar", ".war", ".apk", ".tar", ".tgz", ".gz", ".bz2",
                ".xz", ".zst", ".7z", ".rar", ".cab", ".iso")
_ARCHIVE_MAGIC = (b"PK\x03\x04", b"PK\x05\x06", b"\x1f\x8b", b"BZh", b"\xfd7zXZ\x00",
                  b"7z\xbc\xaf\x27\x1c", b"Rar!\x1a\x07", b"\x28\xb5\x2f\xfd", b"MSCF")
# Junk a zip tool adds; dropped (never stored), reported as a warning.
_JUNK_DIRS = ("__MACOSX/",)
_JUNK_FILES = (".DS_Store", "Thumbs.db")
_S_IFMT, _S_IFLNK, _S_IFDIR, _S_IFREG = 0o170000, 0o120000, 0o040000, 0o100000
_DRIVE_RE = re.compile(r"^[A-Za-z]:")
# Methods whose decompression the read loop can bound chunk by chunk.
_ZIP_METHODS = (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)


@dataclass(frozen=True)
class Upload:
    """A skill read from an upload: its folder name and files (not validated)."""

    slug: str
    files: dict[str, bytes]
    warnings: tuple[str, ...] = ()


def _is_archive(path: str, head: bytes) -> bool:
    if path.lower().endswith(_ARCHIVE_EXT):
        return True
    if any(head.startswith(m) for m in _ARCHIVE_MAGIC):
        return True
    return len(head) >= 262 and head[257:262] == b"ustar"


def _zip_name_problem(name: str) -> str | None:
    if not name:
        return "an entry with no name"
    if "\\" in name:
        return f"{name!r}: backslash in the path"
    if name.startswith("/") or _DRIVE_RE.match(name) or ":" in name:
        return f"{name!r}: absolute path or drive letter"
    if any(ord(c) < 32 or c == "\x7f" for c in name):
        return f"{name!r}: control characters in the path"
    segs = name.rstrip("/").split("/")
    if any(s in ("", ".", "..") for s in segs):
        return f"{name!r}: empty, '.' or '..' segment"
    if len(segs) > MAX_DEPTH + 1:  # + the top-level skill folder
        return f"{name!r}: nested deeper than {MAX_DEPTH} folders"
    return None


def read_zip(data: bytes) -> tuple[dict[str, bytes], list[str]]:
    """A zip's files, in memory, with every safety check; raises SkillError.

    Decompressed bytes are counted as they are read (declared sizes are not
    trusted); entry count, depth and the per-entry ratio are capped; symlinks
    (the entry's Unix mode), encrypted entries, methods other than stored and
    deflate (checked before anything is read), duplicates, case or Unicode
    (NFC) collisions and nested archives are refused."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise SkillError([f"the archive is larger than {MAX_UPLOAD_BYTES} bytes"])
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        infos = zf.infolist()
    except (zipfile.BadZipFile, ValueError, OSError, EOFError) as e:
        raise SkillError([f"not a readable zip archive ({e.__class__.__name__})"]) from e
    if len(infos) > MAX_ZIP_ENTRIES:
        raise SkillError([f"{len(infos)} entries in the archive; at most {MAX_ZIP_ENTRIES}"])
    problems: list[str] = []
    seen_raw: set[str] = set()
    seen_folded: dict[str, str] = {}
    keep: list[zipfile.ZipInfo] = []
    dropped = 0
    for info in infos:
        name = info.filename
        if name in seen_raw:
            problems.append(f"{name!r}: appears twice in the archive")
            continue
        seen_raw.add(name)
        bad = _zip_name_problem(name)
        if bad:
            problems.append(bad)
            continue
        folded = unicodedata.normalize("NFC", name.rstrip("/")).casefold()
        if folded in seen_folded:
            problems.append(f"{name!r} and {seen_folded[folded]!r} collide (case or Unicode "
                            "normalisation)")
            continue
        seen_folded[folded] = name
        mode = (info.external_attr >> 16) & _S_IFMT
        if mode == _S_IFLNK:
            problems.append(f"{name!r}: symlinks are not allowed")
            continue
        if mode and mode not in (_S_IFDIR, _S_IFREG):
            problems.append(f"{name!r}: not a regular file")
            continue
        if info.flag_bits & 0x1:
            problems.append(f"{name!r}: encrypted entries are not allowed")
            continue
        if info.compress_type not in _ZIP_METHODS:
            # bzip2 / LZMA decompress a whole block inside zipfile before
            # the first read returns: the caps below would run too late.
            problems.append(f"{name!r}: compression method {info.compress_type} is not "
                            "allowed (stored or deflate only)")
            continue
        if name.startswith(_JUNK_DIRS) or name.rstrip("/").rsplit("/", 1)[-1] in _JUNK_FILES:
            dropped += 1
            continue
        if info.is_dir():
            continue
        keep.append(info)
    if problems:
        raise SkillError(problems)
    files: dict[str, bytes] = {}
    total = 0
    for info in keep:
        out = bytearray()
        limit = MAX_RATIO * max(info.compress_size, _RATIO_FLOOR)
        try:
            with zf.open(info) as f:
                while chunk := f.read(64 * 1024):
                    out += chunk
                    total += len(chunk)
                    if total > MAX_TOTAL_BYTES:
                        raise SkillError([f"more than {MAX_TOTAL_BYTES} bytes once "
                                          "decompressed"])
                    if len(out) > limit:
                        raise SkillError([f"{info.filename!r}: compression ratio above "
                                          f"{MAX_RATIO}:1"])
        except (zipfile.BadZipFile, zlib.error, OSError, EOFError, NotImplementedError,
                RuntimeError) as e:
            raise SkillError([f"{info.filename!r}: cannot be read "
                              f"({e.__class__.__name__})"]) from e
        body = bytes(out)
        if _is_archive(info.filename, body[:262]):
            problems.append(f"{info.filename!r}: archives inside the archive are not allowed")
            continue
        files[info.filename] = body
    if problems:
        raise SkillError(problems)
    warnings = [f"ignored {dropped} __MACOSX / .DS_Store entries"] if dropped else []
    return files, warnings


def _slug_from_skill_md(raw: bytes) -> str:
    if not _is_text(raw):
        raise SkillError(["SKILL.md is not UTF-8 text"])
    meta, _, _ = split_frontmatter(raw.decode("utf-8"))
    name = meta.get("name")
    if not isinstance(name, str) or not name:
        raise SkillError(["frontmatter name is missing"])
    return name


def read_upload(filename: str, data: bytes) -> Upload:
    """An uploaded `.zip` / `.skill` (one top-level skill folder, or the files
    at the root) or a lone `SKILL.md` as a skill tree (not validated yet)."""
    lower = (filename or "").lower()
    if lower.endswith(".md"):
        if len(data) > MAX_TOTAL_BYTES:
            raise SkillError([f"SKILL.md is larger than {MAX_TOTAL_BYTES} bytes"])
        return Upload(_slug_from_skill_md(data), {SKILL_FILE: data})
    if not lower.endswith((".zip", ".skill")):
        raise SkillError(["upload a .zip or .skill archive, or a SKILL.md file"])
    files, warnings = read_zip(data)
    if not files:
        raise SkillError(["the archive is empty"])
    if SKILL_FILE in files:
        return Upload(_slug_from_skill_md(files[SKILL_FILE]), files, tuple(warnings))
    tops = {p.split("/", 1)[0] for p in files}
    if len(tops) != 1 or any("/" not in p for p in files):
        raise SkillError(["put one skill folder at the top of the archive (<name>/SKILL.md) "
                          "or SKILL.md at its root"])
    (top,) = tops
    inner = {p.split("/", 1)[1]: d for p, d in files.items()}
    if SKILL_FILE not in inner:
        raise SkillError([f"no SKILL.md in {top}/"])
    return Upload(top, inner, tuple(warnings))


# --- Authoring -----------------------------------------------------------------------

def build_skill_md(slug: str, description: str, body: str, license: str = "") -> bytes:
    """SKILL.md from the editor: frontmatter (name, description, licence) + body."""
    meta: dict = {"name": slug, "description": description.strip()}
    if license.strip():
        meta["license"] = license.strip()
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, width=1_000_000)
    body = body.replace("\r\n", "\n")
    if body and not body.endswith("\n"):
        body += "\n"
    return f"---\n{front}---\n\n{body}".encode()


def authored_files(slug: str, description: str, body: str, extra: dict[str, str] | None,
                   license: str = "") -> dict[str, bytes]:
    """The editor's skill as a tree: the built SKILL.md + extra text files."""
    files = {SKILL_FILE: build_skill_md(slug, description, body, license)}
    for path, text in (extra or {}).items():
        if path.casefold() == SKILL_FILE.casefold():
            raise SkillError(["SKILL.md is built from the description and body, "
                              "not an extra file"])
        files[path] = text.replace("\r\n", "\n").encode("utf-8")
    return files


@dataclass(frozen=True)
class Checked:
    """A tree that passed validate, with its sha and scan."""

    meta: SkillMeta
    sha: str
    findings: list[dict]

    @property
    def worst(self) -> str:
        return worst(self.findings)


def check(slug: str, files: dict[str, bytes]) -> Checked:
    meta = validate(slug, files)
    return Checked(meta, canonical_sha(files), scan(files))


def store_version(db: Session, slug: str, files: dict[str, bytes], c: Checked,
                  by: str) -> AwakSkillVersion:
    """The next version of `slug` (active). The caller makes it current."""
    last = max([v.version for v in db.query(AwakSkillVersion).filter_by(slug=slug)], default=0)
    return _store_version(db, slug, last + 1, files, c.sha, c.findings, c.meta.warnings, by)


def used_by(db: Session) -> dict[str, list[dict]]:
    """slug -> the roles that list it: [{project, role, role_id}]."""
    out: dict[str, list[dict]] = {}
    for r in db.query(AwakRole).order_by(AwakRole.project_slug, AwakRole.name).all():
        for slug in r.skills or []:
            out.setdefault(slug, []).append(
                {"project": r.project_slug, "role": r.name, "role_id": r.id})
    return out
