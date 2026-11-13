"""Per-project Awak configuration, stored in the orchestrator DB.

`load` returns plain dataclasses without any key material: key rows are read
on their own (`key_row`) by the code that needs to decrypt them.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from ..config import Settings
from ..store import AwakKey, AwakProject, AwakRepo, AwakRole
from .prompts import KEMUDI_QA_OVERLAY, KEMUDI_WEB_OVERLAY  # noqa: F401 (re-exported)

DEFAULTS = {
    "enabled": False,
    "merge_mode": "approve",
    "deploy_command": "",
    "executor": "local",
    "ssh_host": "",
    "ssh_port": 22,
    "ssh_user": "",
}
SETTING_FIELDS = tuple(DEFAULTS)

# Iteration 1's hard-coded apps/web commands (infra/runner/runner.py).
KEMUDI_WEB_COMMANDS = {
    "install_cmd": "pnpm install --frozen-lockfile --ignore-scripts --store-dir /pnpm-store "
                   "--reporter append-only",
    "check_cmd": "pnpm exec tsc -b\npnpm exec eslint .\npnpm exec vitest run --browser.headless",
    "build_cmd": "pnpm exec vite build",
    "run_cmd": "pnpm exec vite",
}

@dataclass(frozen=True)
class RepoConfig:
    id: int
    name: str
    role: str
    url: str
    default_branch: str = "main"
    subdir: str = ""
    install_cmd: str = ""
    check_cmd: str = ""
    build_cmd: str = ""
    run_cmd: str = ""
    key_id: int | None = None
    position: int = 0


@dataclass(frozen=True)
class RoleConfig:
    id: int
    template: str
    name: str
    area: str
    model: str
    repo_ids: list[int] = field(default_factory=list)
    allowed_paths: list[str] = field(default_factory=list)
    denied_paths: list[str] = field(default_factory=list)
    prompt_overlay: str = ""
    enabled: bool = True
    version: int = 1


@dataclass(frozen=True)
class ProjectConfig:
    slug: str
    enabled: bool = False
    merge_mode: str = "approve"
    deploy_command: str = ""
    executor: str = "local"
    ssh_host: str = ""
    ssh_port: int = 22
    ssh_user: str = ""
    repos: list[RepoConfig] = field(default_factory=list)
    roles: list[RoleConfig] = field(default_factory=list)

    def repo(self, repo_id: int | None) -> RepoConfig | None:
        return next((r for r in self.repos if r.id == repo_id), None)

    def role(self, role_id: int | None) -> RoleConfig | None:
        return next((r for r in self.roles if r.id == role_id), None)

    def role_for_area(self, area: str) -> RoleConfig | None:
        """The first enabled role serving `area` (roles are ordered by id)."""
        return next((r for r in self.roles if r.enabled and r.area == area), None)

    def qa_role(self) -> RoleConfig | None:
        return next((r for r in self.roles if r.enabled and r.template == "qa"), None)


def now() -> datetime:
    return datetime.now(UTC)


def seed_from_env(db: Session, settings: Settings) -> None:
    """KEMUDI_AWAK_PROJECTS as a bootstrap seed: iteration 1's setup, once per slug."""
    for slug in settings.awak_project_slugs():
        if db.get(AwakProject, slug) is not None:
            continue
        db.add(AwakProject(slug=slug, enabled=True, merge_mode="manual", updated_by="seed"))
        repo = AwakRepo(project_slug=slug, name="kemudi", role="web", url=settings.host_git,
                        default_branch="main", subdir="apps/web", position=0,
                        updated_by="seed", **KEMUDI_WEB_COMMANDS)
        db.add(repo)
        db.flush()
        db.add_all([
            AwakRole(project_slug=slug, template="frontend", name="Frontend dev", area="web",
                     model=settings.awak_model, repo_ids=[repo.id],
                     denied_paths=["services/kemudi-back/", "infra/", ".github/"],
                     prompt_overlay=KEMUDI_WEB_OVERLAY, enabled=True, updated_by="seed"),
            AwakRole(project_slug=slug, template="backend", name="Backend dev", area="backend",
                     model=settings.awak_model, repo_ids=[repo.id], enabled=False,
                     updated_by="seed"),
            AwakRole(project_slug=slug, template="qa", name="QA", area="qa",
                     model=settings.qa_model, repo_ids=[repo.id], enabled=True,
                     prompt_overlay=KEMUDI_QA_OVERLAY, updated_by="seed"),
        ])
        db.commit()


def enabled_slugs(db: Session) -> list[str]:
    rows = db.query(AwakProject).filter_by(enabled=True).order_by(AwakProject.slug).all()
    return [p.slug for p in rows]


def is_enabled(db: Session, slug: str) -> bool:
    p = db.get(AwakProject, slug)
    return bool(p and p.enabled)


def _repo(r: AwakRepo) -> RepoConfig:
    return RepoConfig(id=r.id, name=r.name, role=r.role, url=r.url,
                      default_branch=r.default_branch, subdir=r.subdir,
                      install_cmd=r.install_cmd, check_cmd=r.check_cmd, build_cmd=r.build_cmd,
                      run_cmd=r.run_cmd, key_id=r.key_id, position=r.position)


def _role(r: AwakRole) -> RoleConfig:
    return RoleConfig(id=r.id, template=r.template, name=r.name, area=r.area, model=r.model,
                      repo_ids=list(r.repo_ids or []), allowed_paths=list(r.allowed_paths or []),
                      denied_paths=list(r.denied_paths or []), prompt_overlay=r.prompt_overlay,
                      enabled=r.enabled, version=r.version)


def load(db: Session, slug: str) -> ProjectConfig:
    p = db.get(AwakProject, slug)
    repos = (db.query(AwakRepo).filter_by(project_slug=slug)
             .order_by(AwakRepo.position, AwakRepo.id).all())
    roles = db.query(AwakRole).filter_by(project_slug=slug).order_by(AwakRole.id).all()
    values = {k: getattr(p, k) for k in SETTING_FIELDS} if p else dict(DEFAULTS)
    return ProjectConfig(slug=slug, repos=[_repo(r) for r in repos],
                         roles=[_role(r) for r in roles], **values)


def key_row(db: Session, key_id: int | None) -> AwakKey | None:
    """The stored key (encrypted private half included); never send it anywhere."""
    return db.get(AwakKey, key_id) if key_id else None
