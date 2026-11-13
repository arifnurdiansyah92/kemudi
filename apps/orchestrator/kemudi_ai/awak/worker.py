"""The Awak loop: pick a story, code, gate, QA, and move the card.

One story at a time. Taiga is the source of truth for where a story is; the
job row only remembers attempts, feedback and cost between ticks.
"""

import logging
import shlex
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from contextlib import contextmanager
from typing import Callable, Iterator

from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings
from ..store import AwakJob, AwakKey, record_event
from . import config_store, secrets, ssh
from .config_store import ProjectConfig, RepoConfig, RoleConfig
from .crypto import SecretKeyMissing
from .agent import Agent, AgentError
from .gitops import GitError, Repo, branch_for
from .intake import TAG, story_areas
from .prompts import RoleScope, out_of_scope, prompt_version, render, render_role
from .runner import Runner, RunnerError
from .stories import code_task, criteria, qa_task
from .taiga import Project, Taiga, TaigaError, tag_names
from .verdict import Verdict, evaluate, safe_screenshot

log = logging.getLogger(__name__)

DONE_TAG = "awaiting-merge"
HUMAN_TAG = "needs-human"


class Stop(Exception):
    """A human took the story over; stop quietly (with one comment)."""


class Infra(Exception):
    """Something outside the story failed; retry without using an attempt."""


@dataclass
class Fail:
    feedback: str
    comment: str


@dataclass
class Route:
    """What a job runs with: pinned on the job at its first attempt."""

    config: ProjectConfig
    role: RoleConfig
    rc: RepoConfig
    repo: Repo


def now() -> datetime:
    return datetime.now(UTC)


class Worker:
    def __init__(
        self,
        settings: Settings,
        sessions: sessionmaker[Session],
        taiga: Taiga,
        qa_taiga: Taiga,
        agent: Agent,
        runner: Runner,
        repo: Repo | None = None,
        secret_values: list[str] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.s = settings
        self.sessions = sessions
        self.taiga = taiga
        self.qa_taiga = qa_taiga
        self.agent = agent
        self.runner = runner
        self.repo = repo
        self.secret_values = secrets.known_values() if secret_values is None else secret_values
        self.sleep = sleep
        self._seeded = False

    # ------------------------------------------------------------------ loop
    def _seed(self) -> None:
        if not self._seeded:
            with self.sessions() as db:
                config_store.seed_from_env(db, self.s)
            self._seeded = True

    def recover(self) -> None:
        """A job left running by a crash becomes queued again (infra error)."""
        self._seed()
        with self.sessions() as db:
            for job in db.query(AwakJob).filter_by(state="running"):
                job.state = "queued"
                job.infra_errors += 1
                db.commit()
                record_event(db, job.id, "recovered", {"phase": job.phase})

    def tick(self) -> bool:
        """Process at most one story. Returns True if it did any work."""
        self._seed()
        with self.sessions() as db:
            slugs = config_store.enabled_slugs(db)
        for slug in slugs:
            project = self.taiga.project(slug)
            picked = self._pick(project)
            if picked:
                job_id, story = picked
                self._process(project, job_id, story)
                return True
        return False

    def run_forever(self, stop_flag: Callable[[], bool] = lambda: False) -> None:
        self.recover()
        while not stop_flag():
            try:
                worked = self.tick()
            except Exception:  # noqa: BLE001 - the loop must survive anything
                log.exception("awak tick failed")
                worked = False
            if not worked:
                self.sleep(self.s.poll_interval_s)

    # ---------------------------------------------------------------- picking
    def _pick(self, project: Project) -> tuple[int, dict] | None:
        candidates: list[tuple[str, dict]] = []
        for status in ("ready", "in-progress", "ready-for-test"):
            if status not in project.statuses:
                continue
            for st in self.taiga.stories(project.id, project.status(status), TAG):
                if not st.get("is_blocked"):
                    candidates.append((status, st))
        candidates.sort(key=lambda x: x[1]["ref"])
        with self.sessions() as db:
            for status, st in candidates:
                job = db.query(AwakJob).filter_by(
                    project_slug=project.slug, story_id=st["id"]).one_or_none()
                if status == "ready":
                    if job is None:
                        job = AwakJob(project_slug=project.slug, story_id=st["id"],
                                      story_ref=st["ref"], branch=branch_for(st["ref"]))
                        db.add(job)
                    else:
                        self._reset(job, "", fresh=True)
                elif job is None:
                    continue  # in progress by a human, not ours
                elif job.state == "running":
                    continue
                elif job.state == "queued":
                    pass  # crash recovery
                elif (status == "in-progress" and job.state == "failed"
                      and job.infra_errors >= self.s.max_infra_errors):
                    # Unblocked after an environment problem: carry on where it
                    # stopped, keeping attempts and Awak's work.
                    job.infra_errors = 0
                elif status == "in-progress":
                    # A human sent it back (or unblocked it): rework with their words.
                    self._reset(job, self._human_feedback(st["id"]))
                else:
                    continue
                job.state, job.updated_at = "running", now()
                db.commit()
                record_event(db, job.id, "picked", {"status": status})
                return job.id, st
        return None

    def _reset(self, job: AwakJob, feedback: str, fresh: bool = False) -> None:
        job.attempts, job.infra_errors, job.feedback = 0, 0, feedback
        job.started_at, job.cost_idr, job.phase = now(), 0.0, ""
        if fresh:
            # Back in Ready: route again (role, repo and prompt may have changed).
            job.role_id, job.repo_id, job.prompt_version = None, None, ""

    def _human_feedback(self, story_id: int) -> str:
        bot = {self.taiga.username, self.s.qa_username}
        for h in reversed(self.taiga.comments(story_id)):
            user = (h.get("user") or {}).get("username")
            if user not in bot:
                return h["comment"]
        return ""

    # ------------------------------------------------------------- one story
    def _process(self, project: Project, job_id: int, story: dict) -> None:
        while True:
            job = self._job(job_id)
            if job.attempts >= self.s.max_attempts:
                self._give_up(project, job, story)
                return
            try:
                result = self._attempt(project, job, story)
            except Stop as e:
                self._set(job_id, state="stopped")
                self._say(story["id"], job_id, f"Berhenti: {e}")
                return
            except (Infra, AgentError, RunnerError, GitError, TaigaError) as e:
                job = self._set(job_id, infra_errors=job.infra_errors + 1)
                self._event(job_id, "infra", {"error": str(e)[:500]})
                if job.infra_errors >= self.s.max_infra_errors:
                    self._block(project, story, job_id,
                                f"Gangguan lingkungan berulang ({job.infra_errors}x): {e}")
                    return
                self._say(story["id"], job_id,
                          f"Gangguan lingkungan, bukan kesalahan story ({e}). "
                          f"Dicoba lagi otomatis; tidak dihitung sebagai percobaan.")
                self.sleep(30 * job.infra_errors)
                continue
            if result is None:  # passed
                return
            job = self._set(job_id, attempts=job.attempts + 1, feedback=result.feedback,
                            phase="")
            self._move(story["id"], project.status("in-progress"))
            self._say(story["id"], job_id, result.comment)

    def _attempt(self, project: Project, job: AwakJob, story: dict) -> Fail | None:
        n = job.attempts + 1
        story = self._ours(story["id"], {"ready", "in-progress", "ready-for-test"}, project)
        route = self._route(job, story, project.slug)
        repo, rc, role = route.repo, route.rc, route.role
        self.taiga.update_story(
            story["id"], version=story["version"],
            status=project.status("in-progress"),
            assigned_to=self.taiga.me.get("id"),
        )
        self._say(story["id"], job.id, f"Percobaan {n}/{self.s.max_attempts} dimulai.", n)

        # After an infra error past the coding step, keep Awak's work and resume
        # from collect instead of paying for the coding run again.
        workdir = repo.job_dir(job.branch)
        prepared = self._last_event(job.id, "prepared")
        resume = (job.phase in ("collect", "gates", "qa") and workdir.exists()
                  and prepared is not None)
        report = ""
        if resume:
            base_sha = prepared["base"]
            self._event(job.id, "resumed", {"phase": job.phase})
        else:
            # prepare
            self._set(job.id, phase="prepare")
            main_sha = repo.sync_default()
            base_sha = (repo.sha(job.branch) if repo.has_branch(job.branch)
                        else main_sha)
            workdir = repo.prepare(job.branch)
            self._event(job.id, "prepared", {"base": base_sha})
            self._runner("install", job=workdir.name, **_commands(rc, "install"))

            # code
            self._set(job.id, phase="code")
            task = code_task(str(workdir), job.story_ref, story["subject"],
                             story.get("description") or "", job.feedback)
            system = render_role(role, route.config.repos)
            report, cost = self.agent.run("awak.code", role.model, system, task)
            self._add_cost(job.id, cost)
            self._set(job.id, phase="collect")
            self._runner("commit", job=workdir.name,
                         message=f"awak: uncommitted changes from attempt {n} "
                                 f"(US #{job.story_ref})")
        self._ours(story["id"], {"in-progress"}, project)

        # collect
        self._set(job.id, phase="collect")
        sha = repo.collect(job.branch)
        if sha == base_sha:
            return Fail("You made no commit. Implement the story and commit it.",
                        "Awak tidak menghasilkan commit. Laporan Awak:\n\n"
                        + _quote(report))
        files = repo.changed_files(job.branch)
        outside = out_of_scope(files, role.allowed_paths, role.denied_paths)
        if outside:
            limits = []
            if role.allowed_paths:
                limits.append("allowed: " + ", ".join(role.allowed_paths))
            if role.denied_paths:
                limits.append("never: " + ", ".join(role.denied_paths))
            return Fail("These files are outside your role's scope ("
                        + "; ".join(limits) + "). Revert: " + ", ".join(outside),
                        f"Awak mengubah berkas di luar cakupan peran {role.name}: "
                        + ", ".join(f"`{f}`" for f in outside))
        leaked = secrets.files_with_secrets(repo.diff_from_main(job.branch),
                                            self.secret_values)
        if leaked:
            return Fail("Your change contains a secret or key-like value in: "
                        + ", ".join(leaked) + ". Remove it.",
                        "Diff mengandung nilai mirip secret di "
                        + ", ".join(f"`{f}`" for f in leaked) + "; branch tidak di-push.")
        repo.push_branch(job.branch)
        self._set(job.id, last_sha=sha)

        # gates
        self._set(job.id, phase="gates")
        gates = (self._runner("gates", job=workdir.name, **_commands(rc, "gates"))
                 .get("gates") or [])
        failed = [g for g in gates if not g.get("ok")]
        table = "\n".join(f"- {'✅' if g.get('ok') else '❌'} {g['name']}" for g in gates)
        if failed:
            fb = "\n\n".join(f"$ {g['name']}\n{g.get('output', '')[-3000:]}" for g in failed)
            return Fail("These checks failed:\n" + fb,
                        f"Branch `{job.branch}` @ `{sha[:8]}` gagal di pemeriksaan otomatis:\n"
                        f"{table}\n\n" + "\n\n".join(
                            f"**{g['name']}**\n```\n{g.get('output', '')[-1200:]}\n```"
                            for g in failed))
        story = self._ours(story["id"], {"in-progress"}, project)
        self._move(story["id"], project.status("ready-for-test"), story["version"])
        self._say(story["id"], job.id,
                  f"Commit `{sha[:8]}` di branch `{job.branch}`. Pemeriksaan otomatis:\n"
                  f"{table}\n\nMasuk Ready for test; QA berjalan.", n)

        # QA
        self._set(job.id, phase="qa")
        verdict = self._qa(project, job, story, workdir, route)
        story = self._ours(story["id"], {"ready-for-test"}, project)
        evidence = self._upload(project, story["id"], verdict, workdir, f"us{job.story_ref}-a{n}")
        if verdict.outcome == "pass":
            tags = sorted(set(tag_names(story)) | {DONE_TAG})
            self.taiga.update_story(story["id"], version=story["version"],
                                    status=project.status("done"), tags=tags)
            self._set(job.id, state="passed", phase="", attempts=n)
            self._say(story["id"], job.id,
                      f"QA lulus untuk `{sha[:8]}`:\n{_table(verdict, evidence)}\n\n"
                      f"Pindah ke Done dengan tag `{DONE_TAG}`: branch `{job.branch}` "
                      f"belum di-merge dan perlu direview manusia.", n)
            return None
        return Fail("QA failed these acceptance criteria:\n" + verdict.failures(),
                    f"QA gagal untuk `{sha[:8]}`:\n{_table(verdict, evidence)}\n\n"
                    f"Kembali ke In progress; Awak akan memperbaiki.")

    def _qa(self, project: Project, job: AwakJob, story: dict, workdir: Path,
            route: Route) -> Verdict:
        texts = criteria(story.get("description") or "")
        if not texts:
            raise Stop("story tidak punya kriteria penerimaan; tambahkan bagian "
                       "'Acceptance criteria' berisi daftar poin.")
        qa_role = route.config.qa_role()
        if qa_role is not None:
            model, system = qa_role.model, render_role(qa_role, route.config.repos)
        else:
            model = self.s.qa_model
            system = render("qa", "", RoleScope(repos=[route.rc.name]))
        token = self.qa_taiga.login()
        spec_feedback = ""
        for _ in range(2):
            self._runner("qa_reset", job=workdir.name)
            task = qa_task(str(workdir), job.story_ref, story["subject"], texts,
                           self.s.qa_project, spec_feedback, app_dir=route.rc.subdir)
            _, cost = self.agent.run("awak.qa", model, system, task)
            self._add_cost(job.id, cost)
            report = self._runner("qa", job=workdir.name, token=token,
                                  user=self.qa_taiga.me, project=self.s.qa_project,
                                  subdir=route.rc.subdir)
            verdict = evaluate(report, texts)
            self._event(job.id, "qa", {"outcome": verdict.outcome, "reason": verdict.reason})
            if verdict.outcome != "spec":
                break
            spec_feedback = verdict.reason
        if verdict.outcome in ("spec", "infra"):
            raise Infra(f"QA tidak dapat berjalan: {verdict.reason}")
        return verdict

    # ------------------------------------------------------------- helpers
    def _route(self, job: AwakJob, story: dict, slug: str) -> Route:
        """Role and repo by the story's area tag, pinned on the job at its first
        attempt and kept for rework; the prompt version is what this attempt uses."""
        with self.sessions() as db:
            cfg = config_store.load(db, slug)
            row = db.get(AwakJob, job.id)
            if row.role_id is None:
                areas = story_areas(tag_names(story))
                if len(areas) > 1:
                    raise Stop("story punya lebih dari satu tag area ("
                               + ", ".join(f"area-{a}" for a in areas) + "); sisakan satu.")
                role = cfg.role_for_area(areas[0])
                if role is None:
                    raise Stop(f"tidak ada peran agen aktif untuk area {areas[0]}; aktifkan "
                               f"di Pengaturan proyek → Agen.")
                rc = cfg.repo(role.repo_ids[0]) if role.repo_ids else None
                if rc is None:
                    raise Stop(f"peran {role.name} belum punya repo; pilih di Pengaturan "
                               f"proyek → Agen.")
                row.role_id, row.repo_id = role.id, rc.id
            else:
                role = cfg.role(row.role_id)
                if role is None or not role.enabled:
                    raise Stop("peran agen untuk story ini sudah dihapus atau dimatikan.")
                rc = cfg.repo(row.repo_id)
                if rc is None:
                    raise Stop("repo untuk story ini sudah dihapus dari pengaturan Agen.")
            version = prompt_version(role, cfg.repos)
            changed = row.prompt_version != version
            row.prompt_version = version
            db.commit()
            key = config_store.key_row(db, rc.key_id)
        if changed:
            self._event(job.id, "routed", {"role_id": role.id, "repo_id": rc.id,
                                           "prompt_version": version})
        if self.repo is not None and rc.url == self.s.host_git:
            repo = self.repo  # the injected Kemudi repo (iteration 1 wiring, tests)
        else:
            repo = repo_for(cfg, rc, self.s, key)
        return Route(cfg, role, rc, repo)

    def _runner(self, op: str, **payload) -> dict:
        res = self.runner.call(op, **payload)
        if res.get("infra_error"):
            raise Infra(f"{op}: {res['infra_error']}")
        return res

    def _ours(self, story_id: int, statuses: set[str], project: Project) -> dict:
        with self.sessions() as db:
            if not config_store.is_enabled(db, project.slug):
                raise Stop("Awak dimatikan untuk proyek ini.")
        st = self.taiga.story(story_id)
        if TAG not in tag_names(st):
            raise Stop(f"tag `{TAG}` dihapus.")
        if st.get("is_blocked"):
            raise Stop("story diblokir oleh manusia.")
        allowed = {project.statuses[s] for s in statuses if s in project.statuses}
        if st["status"] not in allowed:
            name = project.status_names.get(st["status"], st["status"])
            raise Stop(f"status dipindah manual ke {name}.")
        return st

    def _move(self, story_id: int, status: int, version: int | None = None) -> None:
        kw = {"status": status}
        if version is not None:
            kw["version"] = version
        self.taiga.update_story(story_id, **kw)

    def _give_up(self, project: Project, job: AwakJob, story: dict) -> None:
        self._block(project, story, job.id,
                    f"Gagal setelah {job.attempts} percobaan. Masalah terakhir:\n"
                    f"{job.feedback[-1500:]}")

    def _block(self, project: Project, story: dict, job_id: int, reason: str) -> None:
        st = self.taiga.story(story["id"])
        tags = sorted(set(tag_names(st)) | {HUMAN_TAG})
        owner = st.get("owner")
        self.taiga.update_story(st["id"], version=st["version"], is_blocked=True,
                                blocked_note=reason[:200], tags=tags, assigned_to=owner)
        self._set(job_id, state="failed")  # keep phase: unblocking resumes
        self._say(st["id"], job_id, f"Butuh bantuan manusia. {reason}")

    def _job(self, job_id: int) -> AwakJob:
        with self.sessions() as db:
            return db.get(AwakJob, job_id)

    def _set(self, job_id: int, **fields) -> AwakJob:
        with self.sessions() as db:
            job = db.get(AwakJob, job_id)
            for k, v in fields.items():
                setattr(job, k, v)
            job.updated_at = now()
            db.commit()
            return job

    def _add_cost(self, job_id: int, cost: float) -> None:
        job = self._job(job_id)
        self._set(job_id, cost_idr=job.cost_idr + cost)

    def _last_event(self, job_id: int, kind: str) -> dict | None:
        from ..store import AwakEvent

        with self.sessions() as db:
            row = (db.query(AwakEvent).filter_by(job_id=job_id, kind=kind)
                   .order_by(AwakEvent.id.desc()).first())
            return row.detail if row else None

    def _event(self, job_id: int, kind: str, detail: dict) -> None:
        with self.sessions() as db:
            record_event(db, job_id, kind, detail)

    def _say(self, story_id: int, job_id: int, text: str, n: int | None = None) -> None:
        job = self._job(job_id)
        n = n or job.attempts
        mins = max(0, int((now() - _aware(job.started_at)).total_seconds() // 60))
        head = f"**Awak** · percobaan {max(n, 1)}/{self.s.max_attempts} · {mins} mnt"
        if job.cost_idr:
            head += f" · biaya model Rp{job.cost_idr:,.0f}".replace(",", ".")
        body = secrets.redact(f"{head}\n\n{text}", self.secret_values)
        self.taiga.comment(story_id, body)
        self._event(job_id, "comment", {"text": body[:500]})

    def _upload(self, project: Project, story_id: int, verdict: Verdict,
                workdir: Path, prefix: str) -> dict[int, list[str]]:
        """Attach valid screenshots; returns AC number -> attachment names."""
        qa_dir = workdir / ".qa"
        names: dict[int, list[str]] = {}
        for c in verdict.criteria:
            for i, raw in enumerate(c.screenshots[:2], 1):
                p = safe_screenshot(raw, qa_dir)
                if p is None:
                    continue
                name = f"{prefix}-ac{c.n}-{i}.png"
                self.taiga.attach(project.id, story_id, str(p), name)
                names.setdefault(c.n, []).append(name)
        return names


def repo_for(config: ProjectConfig, repo_row: RepoConfig, settings: Settings,
             key_row: AwakKey | None = None) -> Repo:
    """A `Repo` for a configured repo. The seeded Kemudi repo (the local
    host_git) keeps iteration 1's bare repo; others get {repos_dir}/{id}.git."""
    if repo_row.url == settings.host_git:
        bare = settings.bare_repo
    else:
        bare = str(Path(settings.repos_dir) / f"{repo_row.id}.git")
    env = None
    if not ssh.is_local_url(repo_row.url):
        slug = config.slug

        @contextmanager
        def env() -> Iterator[dict[str, str]]:
            if key_row is None:
                raise GitError(f"repo {repo_row.name} has no deploy key; generate one "
                               f"in Project settings -> Agent")
            known_hosts = ssh.known_hosts_path(settings, slug)
            known_hosts.parent.mkdir(parents=True, exist_ok=True)
            try:
                with ssh.key_file(settings, key_row) as key_path:
                    yield ssh.git_ssh_env(key_path, known_hosts)
            except SecretKeyMissing as e:
                raise GitError(str(e)) from e

    return Repo(bare, repo_row.url, settings.workspace_dir, settings.awak_uid,
                default_branch=repo_row.default_branch, subdir=repo_row.subdir, git_env=env)


def command_lines(text: str) -> list[list[str]]:
    """Newline-separated command lines -> argv lists (no shell)."""
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(shlex.split(line))
    return out


_TIMEOUTS = {"install_cmd": 900, "check_cmd": 900, "build_cmd": 600}


def _commands(rc: RepoConfig, op: str) -> dict:
    """Runner payload: the repo's subdir and command list for `install`/`gates`."""
    fields = ("install_cmd",) if op == "install" else ("check_cmd", "build_cmd")
    cmds = []
    try:
        for f in fields:
            for argv in command_lines(getattr(rc, f)):
                cmds.append({"name": shlex.join(argv), "argv": argv, "timeout": _TIMEOUTS[f]})
    except ValueError as e:
        raise Stop(f"perintah repo {rc.name} tidak valid ({e}); perbaiki di "
                   f"Pengaturan proyek → Agen.") from e
    return {"subdir": rc.subdir, "commands": cmds}


def _quote(text: str) -> str:
    return "\n".join("> " + line for line in (text or "(kosong)").strip()[:1500].splitlines())


def _table(v: Verdict, evidence: dict[int, list[str]]) -> str:
    rows = ["| Kriteria | Hasil | Bukti |", "| --- | --- | --- |"]
    for c in v.criteria:
        result = "✅ lulus" if c.passed else f"❌ {c.error[:150]}".replace("\n", " ")
        shots = ", ".join(evidence.get(c.n, [])) or "-"
        rows.append(f"| AC{c.n}: {c.text[:80]} | {result} | {shots} |".replace("\n", " "))
    return "\n".join(rows)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
