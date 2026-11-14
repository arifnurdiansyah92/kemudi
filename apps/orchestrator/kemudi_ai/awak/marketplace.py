"""Skill marketplaces: GitHub repos listing Claude Code plugins and their skills.

docs/superpowers/plans/2026-11-14-awak-skills-pr3-marketplace.md, Task 2
(design: "Panel review" -> "Marketplace fetch"). The runner fetches a repo
at a full commit sha (fetched.py); this module reads
`.claude-plugin/marketplace.json` (or a bare `skills/` folder), resolves the
plugin sources one level deep (relative paths, or `{source: github}` repos
fetched once more), and lists every plugin's skills with their description,
licence, version, validation and scan level. Installing copies one skill
folder at the pinned sha (plus the plugin's and the repo's LICENSE / NOTICE
files) into a new `marketplace` skill version; checking for an update
fetches the origin again and stores a `pending` version for an admin to
approve or reject. Nothing fetched is ever executed.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from ..config import Settings
from ..store import AwakSkill, AwakSkillMarketplace, AwakSkillVersion
from . import skills
from .fetched import FetchError, Tree, TreeError, fetched
from .runner import Runner

log = logging.getLogger(__name__)

BUILTIN_MARKETPLACES = (("anthropics", "skills"), ("pbakaus", "impeccable"))
MARKETPLACE_FILE = ".claude-plugin/marketplace.json"
PLUGIN_FILE = ".claude-plugin/plugin.json"
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_PLUGINS = 200
MAX_GITHUB_SOURCES = 10
MAX_SKILLS_PER_PLUGIN = 100
MAX_LICENSE_BYTES = 256 * 1024
LICENSE_FILES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "NOTICE", "NOTICE.md", "NOTICE.txt",
                 "COPYING")
TEXT_MAX = 500  # descriptions etc. in the cached listing

OWNER_RE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})")
REPO_RE = re.compile(r"[A-Za-z0-9._-]{1,100}")
REF_RE = re.compile(r"[A-Za-z0-9._/-]{1,200}")


class MarketplaceError(ValueError):
    """A request the marketplace code refuses; the message is for the admin."""


# --- repos ----------

def check_ref(ref: str) -> str:
    if ref and (not REF_RE.fullmatch(ref) or ref.startswith(("-", "/", "."))
                or ref.endswith(("/", ".lock")) or ".." in ref or "//" in ref):
        raise MarketplaceError(f"{ref!r} is not a valid git ref")
    return ref


def check_owner_repo(owner: str, repo: str) -> tuple[str, str]:
    if not OWNER_RE.fullmatch(owner or ""):
        raise MarketplaceError(f"{owner!r} is not a valid GitHub owner")
    if not REPO_RE.fullmatch(repo or "") or repo in (".", "..") or repo.endswith(".git"):
        raise MarketplaceError(f"{repo!r} is not a valid GitHub repository name")
    return owner, repo


def parse_repo(text: str) -> tuple[str, str, str]:
    """`owner/repo`, `owner/repo@ref`, `https://github.com/owner/repo[.git]`
    or `.../tree/<ref>` -> (owner, repo, ref). Other hosts are refused."""
    text = (text or "").strip()
    if not text:
        raise MarketplaceError("enter a GitHub repository as owner/repo")
    if "://" in text or text.startswith(("git@", "www.", "github.com/")):
        if text.startswith("git@"):
            raise MarketplaceError("only GitHub repositories over https are supported "
                                   "(github.com/<owner>/<repo>)")
        u = urlsplit(text if "://" in text else "https://" + text)
        host = (u.hostname or "").lower()
        if u.scheme not in ("https", "http") or host not in ("github.com", "www.github.com") \
                or u.port not in (None, 443) or u.username or u.password:
            raise MarketplaceError("only GitHub repositories are supported "
                                   "(https://github.com/<owner>/<repo>)")
        parts = [p for p in u.path.split("/") if p]
        if len(parts) < 2:
            raise MarketplaceError("the URL names no repository (github.com/<owner>/<repo>)")
        owner, repo = parts[0], parts[1].removesuffix(".git")
        ref = ""
        if len(parts) > 2:
            if parts[2] != "tree" or len(parts) < 4:
                raise MarketplaceError("use the repository's URL (github.com/<owner>/<repo>)")
            ref = "/".join(parts[3:])
        if u.query or u.fragment:
            raise MarketplaceError("use the repository's URL without ? or #")
    else:
        main, _, ref = text.partition("@")
        bits = main.split("/")
        if len(bits) != 2:
            raise MarketplaceError("enter a GitHub repository as owner/repo or owner/repo@ref")
        owner, repo = bits[0], bits[1].removesuffix(".git")
    check_owner_repo(owner, repo)
    return owner, repo, check_ref(ref)


def _rel(path: str, base: str = "") -> str:
    """`path` (from a manifest, relative to `base`) as a clean tree path."""
    if not isinstance(path, str):
        raise MarketplaceError("a path is not text")
    p = path.strip()
    if p.startswith("/") or "\\" in p or ":" in p or "\x00" in p:
        raise MarketplaceError(f"{path!r}: not a relative path")
    parts = [x for x in PurePosixPath(base, p).parts if x not in (".", "")]
    if ".." in parts:
        raise MarketplaceError(f"{path!r}: '..' is not allowed")
    return "/".join(parts)


def _join(*parts: str) -> str:
    return "/".join(p for p in parts if p)


def _text(v, limit: int = TEXT_MAX) -> str:
    if not isinstance(v, (str, int, float)) or isinstance(v, bool):
        return ""
    s = str(v).strip()
    return s if len(s) <= limit else s[:limit - 1].rstrip() + "…"


# --- licences ----------

def license_files(tree: Tree, *dirs: str) -> dict[str, bytes]:
    """LICENSE / NOTICE files of the first of `dirs` that has each name."""
    out: dict[str, bytes] = {}
    for d in dirs:
        for name in LICENSE_FILES:
            if name in out:
                continue
            try:
                data = tree.read(_join(d, name), MAX_LICENSE_BYTES)
            except TreeError:
                continue
            if data is not None and skills._is_text(data):
                out[name] = data
    return out


def detect_license(declared: str, files: dict[str, bytes]) -> str:
    """The frontmatter `license` if any (a known licence when it only points
    at a LICENSE file, e.g. "Complete terms in LICENSE.txt"), else a guess
    from LICENSE / COPYING text, else '' (unspecified)."""
    if declared:
        if re.search(r"\b(LICEN[SC]E|COPYING)\b", declared):
            guess = _guess_license(files)
            if guess and not guess.startswith("see "):
                return guess
        return declared[:100]
    return _guess_license(files)


def _guess_license(files: dict[str, bytes]) -> str:
    for name in ("LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING"):
        text = files.get(name, b"")[:4000].decode("utf-8", errors="ignore")
        if not text:
            continue
        if "Apache License" in text and "2.0" in text:
            return "Apache-2.0"
        if "MIT License" in text or "Permission is hereby granted, free of charge" in text:
            return "MIT"
        if "BSD" in text and "Redistribution and use" in text:
            return "BSD"
        if "Mozilla Public License" in text:
            return "MPL-2.0"
        if "GNU GENERAL PUBLIC LICENSE" in text.upper():
            return "GPL"
        return f"see {name}"
    return ""


def skill_files(tree: Tree, skill_path: str, plugin_root: str) -> dict[str, bytes]:
    """The skill folder plus the plugin's and the repo's LICENSE / NOTICE
    files (a name the folder already has is kept as is)."""
    files = tree.read_folder(skill_path, skills.MAX_FILES, skills.MAX_TOTAL_BYTES)
    for name, data in license_files(tree, plugin_root, "").items():
        if name not in files and not any(p.casefold() == name.casefold() for p in files):
            files[name] = data
    return files


def skill_slug(skill_path: str, files: dict[str, bytes], fallback: str) -> str:
    """The folder name; a skill at a repo root takes its frontmatter name."""
    base = PurePosixPath(skill_path).name
    if base:
        return base
    try:
        meta, _, _ = skills.split_frontmatter(files.get(skills.SKILL_FILE, b"").decode("utf-8"))
    except (skills.SkillError, UnicodeDecodeError):
        return fallback
    name = meta.get("name")
    return name if isinstance(name, str) and skills.NAME_RE.match(name) else fallback


# --- listing ----------

def _describe_skill(tree: Tree, skill_path: str, plugin_root: str, plugin_version: str,
                    fallback: str) -> dict:
    out = {"name": PurePosixPath(skill_path).name or fallback, "path": skill_path,
           "description": "", "license": "", "version": plugin_version, "valid": False,
           "problems": [], "scan_level": "", "files": 0, "size": 0, "sha256": ""}
    try:
        files = skill_files(tree, skill_path, plugin_root)
    except (TreeError, FetchError) as e:
        out["problems"] = [str(e)]
        # still say what it is, from SKILL.md alone
        try:
            raw = tree.read(_join(skill_path, skills.SKILL_FILE), skills.MAX_TOTAL_BYTES)
            meta, _, _ = skills.split_frontmatter((raw or b"").decode("utf-8"))
        except (TreeError, skills.SkillError, UnicodeDecodeError):
            return out
        out["description"] = _text(meta.get("description"))
        if isinstance(meta.get("license"), str):
            out["license"] = meta["license"].strip()[:100]
        return out
    slug = skill_slug(skill_path, files, fallback)
    out["name"] = slug
    raw = files.get(skills.SKILL_FILE, b"")
    meta: dict = {}
    try:
        meta, _, _ = skills.split_frontmatter(raw.decode("utf-8"))
    except (skills.SkillError, UnicodeDecodeError):
        pass
    out["description"] = _text(meta.get("description"))
    md = meta.get("metadata") if isinstance(meta.get("metadata"), dict) else {}
    out["version"] = _text(md.get("version"), 40) or plugin_version
    lic = meta.get("license") if isinstance(meta.get("license"), str) else ""
    out["license"] = detect_license(lic.strip(), files)
    out["files"] = len(files)
    out["size"] = sum(len(d) for d in files.values())
    try:
        c = skills.check(slug, files)
    except skills.SkillError as e:
        out["problems"] = e.problems[:20]
        return out
    out.update(valid=True, scan_level=c.worst, sha256=c.sha)
    return out


def plugin_skill_paths(tree: Tree, root: str, declared) -> list[str]:
    """The skill folders of a plugin rooted at `root`: the `skills` list of
    its manifest entry (each a skill folder, or a folder of skill folders),
    else the plugin's `.claude-plugin/plugin.json` `skills`, else
    `skills/<name>/SKILL.md`, else the root itself when it holds SKILL.md."""
    if declared is None:
        try:
            raw = tree.read(_join(root, PLUGIN_FILE), MAX_MANIFEST_BYTES)
            manifest = json.loads(raw) if raw else None
        except (TreeError, ValueError):
            manifest = None
        if isinstance(manifest, dict) and isinstance(manifest.get("skills"), (str, list)):
            declared = manifest["skills"]
    paths: list[str] = []

    def add_dir(d: str) -> None:
        if tree.is_file(_join(d, skills.SKILL_FILE)):
            paths.append(d)
            return
        for name, kind in tree.listdir(d):
            if kind == "dir" and tree.is_file(_join(d, name, skills.SKILL_FILE)):
                paths.append(_join(d, name))

    if declared is not None:
        for entry in [declared] if isinstance(declared, str) else declared:
            add_dir(_rel(entry, root))
    else:
        if tree.is_dir(_join(root, "skills")):
            add_dir(_join(root, "skills"))
        if not paths and tree.is_file(_join(root, skills.SKILL_FILE)):
            paths.append(root)
    seen: set[str] = set()
    out = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out[:MAX_SKILLS_PER_PLUGIN]


def _plugin_base(entry: dict) -> dict:
    return {"name": _text(entry.get("name"), 100) or "plugin",
            "description": _text(entry.get("description")),
            "version": _text(entry.get("version"), 40),
            "category": _text(entry.get("category"), 60),
            "source": {}, "supported": False, "reason": "", "skills": []}


def _fill_skills(p: dict, tree: Tree, root: str, declared) -> None:
    try:
        paths = plugin_skill_paths(tree, root, declared)
    except (MarketplaceError, TreeError) as e:
        p["reason"] = str(e)
        return
    p["skills"] = [_describe_skill(tree, sp, root, p["version"], p["name"]) for sp in paths]
    p["supported"] = True
    if not paths:
        p["reason"] = "no skills in this plugin (commands, agents and hooks are not imported)"


def _source(entry: dict, plugin_root_prefix: str) -> tuple[dict, str]:
    """(source description, reason it is unsupported or '')."""
    src = entry.get("source")
    if isinstance(src, str):
        if src.startswith(("./", "../")) or src in (".", "./"):
            base = ""
        else:  # a bare name: under metadata.pluginRoot
            base = plugin_root_prefix
        try:
            return {"type": "relative", "path": _rel(src, base)}, ""
        except MarketplaceError as e:
            return {"type": "relative", "path": _text(src, 200)}, str(e)
    if isinstance(src, dict):
        kind = _text(src.get("source"), 40)
        if kind == "github":
            repo = src.get("repo") if isinstance(src.get("repo"), str) else ""
            ref = src.get("ref") if isinstance(src.get("ref"), str) else ""
            sha = src.get("sha") if isinstance(src.get("sha"), str) else ""
            out = {"type": "github", "repo": _text(repo, 200), "ref": _text(ref, 200),
                   "sha": _text(sha, 40)}
            try:
                owner, name = repo.split("/") if repo.count("/") == 1 else ("", "")
                check_owner_repo(owner, name)
                check_ref(ref)
                if sha and not re.fullmatch(r"[0-9a-f]{40}", sha):
                    raise MarketplaceError("sha must be a full commit sha")
            except MarketplaceError as e:
                return out, str(e)
            return out, ""
        if kind == "url":
            return ({"type": "url", "url": _text(src.get("url"), 300)},
                    "git URL sources are not supported yet (GitHub repositories only)")
        if kind:
            return {"type": kind}, f"{kind} sources are not supported (relative or github only)"
    return {"type": "unknown"}, "the plugin has no source Kemudi can read"


def read_listing(tree: Tree, repo_name: str) -> tuple[dict, list[dict]]:
    """The listing of one fetched marketplace repo, and the github-source
    plugins still to fetch ([plugin dict] whose `source` says where)."""
    listing = {"name": repo_name, "owner": "", "description": "", "kind": "marketplace",
               "plugins": []}
    try:
        raw = tree.read(MARKETPLACE_FILE, MAX_MANIFEST_BYTES)
    except TreeError as e:
        raise MarketplaceError(f"{MARKETPLACE_FILE}: {e}") from e
    if raw is None:
        listing["kind"] = "skills"
        p = _plugin_base({"name": repo_name})
        p["source"] = {"type": "relative", "path": ""}
        root_dirs = None
        if not tree.is_dir("skills") and not tree.is_file(skills.SKILL_FILE):
            # a repo of <name>/SKILL.md folders at its root
            root_dirs = [n for n, k in tree.listdir("")
                         if k == "dir" and tree.is_file(_join(n, skills.SKILL_FILE))]
            if not root_dirs:
                raise MarketplaceError(f"no {MARKETPLACE_FILE} and no skills (skills/<name>/"
                                       "SKILL.md) in this repository")
        _fill_skills(p, tree, "", root_dirs)
        listing["plugins"] = [p]
        return listing, []
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise MarketplaceError(f"{MARKETPLACE_FILE} is not valid JSON") from e
    if not isinstance(data, dict) or not isinstance(data.get("plugins"), list):
        raise MarketplaceError(f"{MARKETPLACE_FILE} has no plugins list")
    owner = data.get("owner")
    meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    listing.update(name=_text(data.get("name"), 100) or repo_name,
                   owner=_text(owner.get("name"), 100) if isinstance(owner, dict) else "",
                   description=_text(meta.get("description") or data.get("description")))
    root_prefix = ""
    if isinstance(meta.get("pluginRoot"), str):
        try:
            root_prefix = _rel(meta["pluginRoot"])
        except MarketplaceError:
            root_prefix = ""
    pending: list[dict] = []
    for entry in data["plugins"][:MAX_PLUGINS]:
        if not isinstance(entry, dict):
            continue
        p = _plugin_base(entry)
        p["source"], reason = _source(entry, root_prefix)
        declared = entry.get("skills")
        if declared is not None and not (
                isinstance(declared, str)
                or (isinstance(declared, list) and all(isinstance(x, str) for x in declared))):
            reason = reason or "the plugin's skills list is not a list of paths"
        if reason:
            p["reason"] = reason
        elif p["source"]["type"] == "relative":
            root = p["source"]["path"]
            if root and not tree.is_dir(root):
                p["reason"] = f"{root}: no such folder in the repository"
            else:
                _fill_skills(p, tree, root, declared)
        else:  # github: fetched in a second pass
            p["_declared"] = declared
            pending.append(p)
        listing["plugins"].append(p)
    return listing, pending


def build_listing(runner: Runner, settings: Settings, owner: str, repo: str,
                  ref: str) -> dict:
    """Fetch the marketplace (and its github plugin sources, one level deep)
    and list every plugin's skills. Raises FetchError / MarketplaceError."""
    with fetched(runner, settings, owner, repo, ref) as tree:
        listing, pending = read_listing(tree, repo)
        listing["sha"] = tree.sha
        listing["repo"] = f"{owner}/{repo}"
    for i, p in enumerate(pending):
        declared = p.pop("_declared", None)
        src = p["source"]
        if i >= MAX_GITHUB_SOURCES:
            p["reason"] = f"more than {MAX_GITHUB_SOURCES} external repositories in one " \
                          "marketplace; this one was not fetched"
            continue
        o, r = src["repo"].split("/")
        try:
            with fetched(runner, settings, o, r, src.get("sha") or src.get("ref") or "") as t:
                src["resolved_sha"] = t.sha
                _fill_skills(p, t, "", declared)
        except (FetchError, MarketplaceError) as e:
            p["reason"] = str(e)[:500]
    return listing


def find(listing: dict, plugin: str, skill: str) -> tuple[dict, dict]:
    for p in listing.get("plugins") or []:
        if p.get("name") != plugin:
            continue
        for s in p.get("skills") or []:
            if s.get("name") == skill:
                return p, s
    raise MarketplaceError(f"no skill {skill!r} in plugin {plugin!r}; refresh the marketplace")


def source_of(mp: AwakSkillMarketplace, plugin: dict) -> dict:
    """Where a plugin's files come from: {owner, repo, sha, follow_ref, root}.
    `follow_ref` is what an update check fetches."""
    src = plugin.get("source") or {}
    if src.get("type") == "github":
        o, r = src["repo"].split("/")
        sha = src.get("resolved_sha") or src.get("sha") or ""
        return {"owner": o, "repo": r, "sha": sha,
                "follow_ref": src.get("ref") or src.get("sha") or "", "root": ""}
    return {"owner": mp.owner, "repo": mp.repo, "sha": mp.last_sha, "follow_ref": mp.ref,
            "root": src.get("path", "")}


# --- DB ----------

def seed_builtin_marketplaces(db: Session) -> list[str]:
    """Register the built-in marketplaces (not fetched). Idempotent."""
    added = []
    rows = db.query(AwakSkillMarketplace).all()
    have = {(m.owner.lower(), m.repo.lower()) for m in rows}
    for owner, repo in BUILTIN_MARKETPLACES:
        if (owner.lower(), repo.lower()) in have:
            for m in rows:
                if (m.owner.lower(), m.repo.lower()) == (owner.lower(), repo.lower()):
                    m.builtin = True
            continue
        db.add(AwakSkillMarketplace(name=f"{owner}/{repo}", owner=owner, repo=repo, ref="",
                                    builtin=True, created_by="builtin"))
        added.append(f"{owner}/{repo}")
    db.commit()
    return added


def find_marketplace(db: Session, owner: str, repo: str, ref: str) -> AwakSkillMarketplace | None:
    for m in db.query(AwakSkillMarketplace).all():
        if (m.owner.lower(), m.repo.lower(), m.ref) == (owner.lower(), repo.lower(), ref):
            return m
    return None


def counts(listing: dict) -> tuple[int, int]:
    plugins = listing.get("plugins") or []
    return len(plugins), sum(len(p.get("skills") or []) for p in plugins)


def refresh(db: Session, runner: Runner, settings: Settings,
            mp: AwakSkillMarketplace) -> AwakSkillMarketplace:
    """Fetch and cache the listing; a failure is kept in `error` (the old
    listing stays) and raised."""
    try:
        listing = build_listing(runner, settings, mp.owner, mp.repo, mp.ref)
    except (FetchError, MarketplaceError) as e:
        mp.error = str(e)[:1000]
        mp.last_fetched_at = datetime.now(UTC)
        db.commit()
        raise
    mp.listing = listing
    mp.name = listing.get("name") or f"{mp.owner}/{mp.repo}"
    mp.last_sha = listing["sha"]
    mp.last_fetched_at = datetime.now(UTC)
    mp.error = ""
    db.commit()
    return mp


def installed_info(db: Session, mp: AwakSkillMarketplace, plugin: dict, s: dict) -> dict | None:
    sk = db.get(AwakSkill, s.get("name"))
    if sk is None:
        return None
    origin = sk.origin or {}
    src = source_of(mp, plugin)
    same = (sk.source == "marketplace"
            and str(origin.get("repo", "")).lower() == f"{src['owner']}/{src['repo']}".lower()
            and origin.get("path") == s.get("path"))
    return {"slug": sk.slug, "source": sk.source, "version": sk.current_version,
            "enabled": sk.enabled, "same_origin": same, "sha": origin.get("sha", "")}


def install(db: Session, runner: Runner, settings: Settings, mp: AwakSkillMarketplace,
            plugin_name: str, skill_name: str, by: str) -> tuple[AwakSkill, AwakSkillVersion]:
    """A new `marketplace` skill (disabled) from the cached listing, its files
    fetched again at the pinned sha. Raises MarketplaceError (bad request),
    SkillError (invalid), FetchError, or SkillClash (the slug exists)."""
    if not mp.last_sha:
        raise MarketplaceError("refresh the marketplace first")
    plugin, s = find(mp.listing or {}, plugin_name, skill_name)
    if not plugin.get("supported"):
        raise MarketplaceError(f"plugin {plugin_name!r} is not supported: {plugin.get('reason')}")
    slug = s["name"]
    existing = db.get(AwakSkill, slug)
    if existing is not None:
        raise SkillClash(existing)
    src = source_of(mp, plugin)
    if not src["sha"]:
        raise MarketplaceError("the plugin's repository was not fetched; refresh the marketplace")
    with fetched(runner, settings, src["owner"], src["repo"], src["sha"]) as tree:
        if tree.sha != src["sha"]:
            raise FetchError("the runner fetched another commit than the pinned one")
        try:
            files = skill_files(tree, s["path"], src["root"])
        except TreeError as e:
            raise skills.SkillError([str(e)]) from e
    c = skills.check(slug, files)
    lic = _license_of(files, c)
    origin = {"marketplace_id": mp.id, "marketplace": mp.name,
              "repo": f"{src['owner']}/{src['repo']}", "ref": src["follow_ref"],
              "sha": src["sha"], "plugin": plugin_name, "path": s["path"],
              "plugin_root": src["root"]}
    sk = AwakSkill(slug=slug, source="marketplace", title=slug, description=c.meta.description,
                   license=lic, enabled=False, current_version=1, origin=origin, created_by=by)
    db.add(sk)
    v = skills.store_version(db, slug, files, c, by)
    v.origin = {"repo": origin["repo"], "sha": src["sha"], "path": s["path"], "license": lic}
    sk.current_version = v.version
    db.commit()
    return sk, v


def _license_of(files: dict[str, bytes], c: skills.Checked) -> str:
    return detect_license(c.meta.license, files)


class SkillClash(Exception):
    def __init__(self, sk: AwakSkill):
        super().__init__(f"a {sk.source} skill named {sk.slug} exists")
        self.skill = sk


# --- updates ----------

def diff(old: dict[str, bytes], new: dict[str, bytes]) -> dict:
    return {"added": sorted(set(new) - set(old)), "removed": sorted(set(old) - set(new)),
            "changed": sorted(p for p in set(old) & set(new) if old[p] != new[p])}


def check_update(db: Session, runner: Runner, settings: Settings, sk: AwakSkill,
                 by: str) -> dict:
    """Fetch the skill's origin at its followed ref. Returns {status, ...}:
    `up_to_date`, `pending` (a new pending version, or the one already
    there), `rejected` (the upstream tree was rejected before), `invalid`
    (problems) or `missing` (the folder is gone upstream)."""
    origin = dict(sk.origin or {})
    repo = str(origin.get("repo", ""))
    if sk.source != "marketplace" or repo.count("/") != 1 or not origin.get("path"):
        raise MarketplaceError("only marketplace skills can be checked for updates")
    owner, name = repo.split("/")
    check_owner_repo(owner, name)
    cur = (db.query(AwakSkillVersion)
           .filter_by(slug=sk.slug, version=sk.current_version).one_or_none())
    with fetched(runner, settings, owner, name, check_ref(str(origin.get("ref") or ""))) as tree:
        sha = tree.sha
        if not tree.is_dir(origin["path"]):
            out = {"status": "missing", "sha": sha,
                   "message": f"{origin['path']} is no longer in {repo} at {sha[:12]}"}
            files = None
        else:
            try:
                files = skill_files(tree, origin["path"], str(origin.get("plugin_root") or ""))
            except TreeError as e:
                return _checked(db, sk, origin, sha, {"status": "invalid", "sha": sha,
                                                      "problems": [str(e)]})
    if files is None:
        return _checked(db, sk, origin, sha, out)
    tree_sha = skills.canonical_sha(files)
    if cur is not None and cur.sha256 == tree_sha:
        for p in db.query(AwakSkillVersion).filter_by(slug=sk.slug, status="pending"):
            db.delete(p)  # upstream went back to the current tree
        return _checked(db, sk, origin, sha, {"status": "up_to_date", "sha": sha})
    if origin.get("rejected") == tree_sha:
        return _checked(db, sk, origin, sha, {"status": "rejected", "sha": sha})
    pending = db.query(AwakSkillVersion).filter_by(slug=sk.slug, status="pending").all()
    for p in pending:
        if p.sha256 == tree_sha:
            return _checked(db, sk, origin, sha, {"status": "pending", "sha": sha,
                                                  "version": p.version, "new": False})
    try:
        c = skills.check(sk.slug, files)
    except skills.SkillError as e:
        return _checked(db, sk, origin, sha, {"status": "invalid", "sha": sha,
                                              "problems": e.problems[:20]})
    for p in pending:  # one pending version at a time: the newest upstream
        db.delete(p)
    db.flush()
    v = skills.store_version(db, sk.slug, files, c, by)
    v.status = "pending"
    v.origin = {"repo": repo, "sha": sha, "path": origin["path"],
                "license": _license_of(files, c)}
    db.flush()
    return _checked(db, sk, origin, sha, {"status": "pending", "sha": sha,
                                          "version": v.version, "new": True})


def _checked(db: Session, sk: AwakSkill, origin: dict, sha: str, out: dict) -> dict:
    origin["checked_sha"] = sha
    origin["checked_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    origin["check_status"] = out["status"]
    sk.origin = origin
    db.commit()
    return out


def pending_detail(db: Session, sk: AwakSkill) -> list[dict]:
    """Pending versions with their diff against the current one."""
    cur = (db.query(AwakSkillVersion)
           .filter_by(slug=sk.slug, version=sk.current_version).one_or_none())
    old = skills.decode_files(cur.files or {}) if cur is not None else {}
    out = []
    for v in (db.query(AwakSkillVersion).filter_by(slug=sk.slug, status="pending")
              .order_by(AwakSkillVersion.version.desc())):
        new = skills.decode_files(v.files or {})
        scan = v.scan or {}
        out.append({"version": v.version, "sha256": v.sha256, "origin": v.origin or {},
                    "diff": diff(old, new), "findings": scan.get("findings", []),
                    "warnings": scan.get("warnings", []), "scan_level": scan.get("worst", ""),
                    "previous_scan_level": ((cur.scan or {}).get("worst", "")
                                            if cur is not None else ""),
                    "created_by": v.created_by, "created_at": v.created_at})
    return out
