"""The Awak loop: pick a story, code, gate, QA, and move the card.

One story at a time. Taiga is the source of truth for where a story is; the
job row only remembers attempts, feedback and cost between ticks.
"""

import fnmatch
import logging
import os
import re
import shutil
import socket
import threading
import time
import uuid
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable, Iterator

from sqlalchemy import or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings
from ..store import AwakJob, AwakKey, AwakProject, AwakWorkerLease, record_event
from . import checks, config_store, llm_conn, runbook, secrets, ssh, vault
from .config_store import QA_MODES, ProjectConfig, RepoConfig, RoleConfig
from .crypto import SecretKeyMissing
from .agent import Agent, AgentError
from .gitops import GitError, Repo, _force_remove, branch_for
from .intake import TAG, story_areas
from .merge import DONE_TAG, HUMAN_TAG, Merger, effective_mode, save_spec
from .runbook import Runbook
from .prompts import RoleScope, out_of_scope, prompt_version, render, render_role
from .runner import Runner, RunnerError, RunnerRejected
from .svc import Svc, SvcError, SvcRejected
from .stories import code_task, criteria, qa_task
from .taiga import Project, Taiga, TaigaError, tag_names
from .verdict import Verdict, evaluate, safe_screenshot

log = logging.getLogger(__name__)



class Stop(Exception):
    """A human took the story over; stop quietly (with one comment)."""


class NeedsHuman(Stop):
    """Awak cannot go on until a human fixes settings or the story: the card
    is blocked (a stopped In progress card would just be picked again)."""


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
    runbook: Runbook | None = None


def now() -> datetime:
    return datetime.now(UTC)


# Only one worker may run (the API's thread, `awak-tick --forever`, several
# uvicorn workers...). A crashed holder's lease lapses after this long.
LEASE_TTL_S = 120
SWEEP_EVERY_S = 600  # compose sweep when idle, at most this often
_SHA_RE = re.compile(r"[0-9a-f]{7,64}")


def _naive_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


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
        command_runner: ssh.CommandRunner = ssh.subprocess_runner,
        svc: Svc | None = None,
    ):
        self.s = settings
        self.sessions = sessions
        self.taiga = taiga
        self.qa_taiga = qa_taiga
        self.agent = agent
        self.runner = runner
        self.repo = repo
        self._secret_values = secrets.known_values() if secret_values is None else secret_values
        self.sleep = sleep
        self.command_runner = command_runner  # deploy over SSH
        self.svc = svc  # kemudi-svc: compose services (None: not configured)
        self._seeded = False
        self._swept = False
        self._services_swept = False
        self.clock: Callable[[], float] = time.monotonic
        self._last_compose_sweep: float | None = None
        self.holder = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"

    @property
    def secret_values(self) -> list[str]:
        """Env secrets plus every stored BYOK model key (read fresh, so a key
        saved after the worker started is scanned too)."""
        with self.sessions() as db:
            return [*self._secret_values, *llm_conn.stored_keys(db, self.s)]

    @property
    def redact_values(self) -> list[str]:
        """What comments and errors never show: the secrets plus the runbooks'
        env values (tokens or internal URLs an admin put there). Not used to
        scan diffs: an ordinary value would refuse ordinary code."""
        with self.sessions() as db:
            return [*self.secret_values, *runbook.all_env_values(db)]

    def redact_values_for(self, slug: str) -> list[str]:
        """`redact_values` plus the project's vault values in every encoding
        (comments, events, feedback to the agent and logs of its work)."""
        with self.sessions() as db:
            own = vault.redaction_values(db, self.s, slug)
        return [*own, *self.redact_values]

    def scan_values_for(self, slug: str) -> list[str]:
        """What a diff of the project must not add: `secret_values` plus its
        vault values of 8+ characters."""
        with self.sessions() as db:
            own = vault.scan_values(db, self.s, slug)
        return [*own, *self.secret_values]

    def _redact_detail(self, slug: str, detail):
        values = self.redact_values_for(slug)

        def walk(x):
            if isinstance(x, str):
                # a commit sha is read back (e.g. `prepared.base`); a short
                # value that happens to be hex inside it is no leak
                return x if _SHA_RE.fullmatch(x) else secrets.redact(x, values)
            if isinstance(x, dict):
                return {k: walk(v) for k, v in x.items()}
            if isinstance(x, list):
                return [walk(v) for v in x]
            return x

        return walk(detail)

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
            running = db.query(AwakJob).filter(
                or_(AwakJob.state == "running", AwakJob.merge_state == "merging")).all()
            if not self._swept and not any(j.state == "running" for j in running):
                self._sweep_old_workspaces()
            if not self._services_swept:
                self._sweep_services(db, running)
            for job in db.query(AwakJob).filter_by(state="running"):
                job.state = "queued"
                job.infra_errors += 1
                db.commit()
                record_event(db, job.id, "recovered", {"phase": job.phase})
            # A merge cut off by a crash starts over from the top (sync, branch
            # check, merge, gates); nothing half-done is pushed.
            for job in db.query(AwakJob).filter_by(merge_state="merging"):
                job.merge_state = "requested"
                db.commit()
                record_event(db, job.id, "recovered", {"merge": True})

    def _sweep_old_workspaces(self) -> None:
        """Delete the pre-stage-1 `<workspace>/awak-us-<n>` folders, once: they
        were shared between projects, so nothing in them is trusted. Stories
        that used one start again from the coding step (branches survive in the
        bare repos)."""
        self._swept = True
        root = Path(self.s.workspace_dir)
        for d in sorted(root.glob("awak-us-*")) if root.is_dir() else []:
            try:
                if d.is_symlink() or d.is_file():
                    d.unlink()
                elif d.is_dir():
                    shutil.rmtree(d, onerror=_force_remove)
            except OSError as e:
                log.warning("awak: could not delete old workspace %s: %s", d, e)

    def _compose_keep(self, db: Session) -> set[str]:
        """Compose projects a sweep leaves up: those of running jobs and merges
        in progress (the one place to add others, e.g. setup runs)."""
        keep: set[str] = set()
        busy = db.query(AwakJob).filter(
            or_(AwakJob.state == "running", AwakJob.merge_state == "merging")).all()
        for j in busy:
            rb = runbook.load(db, j.project_slug)
            keep |= set(checks.compose_projects(rb, j.project_slug,
                                                f"us{j.story_ref}").values())
        return keep

    def _sweep_compose(self, db: Session) -> None:
        """Every compose project kemudi-svc has, except `_compose_keep`, comes
        down with its images. Failures are logged, never fatal."""
        self._last_compose_sweep = self.clock()
        if self.svc is None:
            return
        try:
            res = self.svc.call("svc_sweep", keep=sorted(self._compose_keep(db)))
            if res.get("removed"):
                log.warning("awak: swept compose projects %s", res["removed"])
            if res.get("infra_error"):
                log.warning("awak: compose sweep failed: %s", res["infra_error"])
        except SvcError as e:
            log.warning("awak: compose sweep failed: %s", e)

    def idle_sweep(self) -> None:
        """When the worker has nothing to do: a compose sweep at most every
        SWEEP_EVERY_S, so nothing a story left behind (a crash between svc_up
        and svc_down, a timed-out call) stays in kemudi-dind for long."""
        if self.svc is None or self._last_compose_sweep is None:
            return  # the start sweep (recover) comes first
        if self.clock() - self._last_compose_sweep < SWEEP_EVERY_S:
            return
        with self.heartbeat(), self.sessions() as db:
            self._sweep_compose(db)

    def _sweep_services(self, db: Session, running: list[AwakJob]) -> None:
        """Once per worker: compose projects of jobs that are not running come
        down (kemudi-svc), and with no job running, the runner stops every
        process service left behind. Failures are logged, never fatal."""
        self._services_swept = True
        self._sweep_compose(db)
        if not running:
            try:
                self.runner.call("reap")
            except RunnerError as e:
                log.warning("awak: runner reap failed: %s", e)

    def tick(self) -> bool:
        """Process at most one story. Returns True if it did any work.

        A failure in one project (the bot cannot open it, Taiga refuses...) is
        logged and recorded on that project, and the next project is served.
        """
        self._seed()
        with self.sessions() as db:
            slugs = config_store.enabled_slugs(db)
        # Requested merges first: a human is waiting on the button.
        for slug in slugs:
            with self.sessions() as db:
                job = (db.query(AwakJob).filter_by(project_slug=slug, merge_state="requested")
                       .order_by(AwakJob.id).first())
            if job is None:
                continue
            try:
                self._requested_merge(self._project(slug), job)
            except Exception as e:  # noqa: BLE001 - other projects must still be served
                self._project_failed(slug, e)
                continue
            return True
        for slug in slugs:
            try:
                project = self._project(slug)
                picked = self._pick(project)
            except Exception as e:  # noqa: BLE001
                self._project_failed(slug, e)
                continue
            self._project_ok(slug)
            if picked:
                job_id, story = picked
                try:
                    self._process(project, job_id, story)
                except Exception as e:  # noqa: BLE001
                    self._project_failed(slug, e)
                return True
        return False

    def _project(self, slug: str) -> Project:
        try:
            return self.taiga.project(slug)
        except TaigaError as e:
            if "HTTP 404" in str(e) or "HTTP 403" in str(e):
                raise TaigaError(
                    f"Awak (user {self.taiga.username}) cannot open project {slug}: it is "
                    f"not a member. Give Awak access in Project settings → Agent.") from e
            raise

    def _project_failed(self, slug: str, error: Exception) -> None:
        log.warning("awak: project %s failed: %s", slug, error,
                    exc_info=not isinstance(error, TaigaError))
        text = secrets.redact(str(error) or type(error).__name__,
                              self.redact_values_for(slug))[:1000]
        with self.sessions() as db:
            p = db.get(AwakProject, slug)
            if p is not None:
                p.last_error, p.last_error_at = text, now()
                db.commit()

    def _project_ok(self, slug: str) -> None:
        with self.sessions() as db:
            p = db.get(AwakProject, slug)
            if p is not None and (p.last_error or p.last_error_at):
                p.last_error, p.last_error_at = "", None
                db.commit()

    def run_forever(self, stop_flag: Callable[[], bool] = lambda: False) -> None:
        held = False
        try:
            while not stop_flag():
                try:
                    if not self.claim_lease():
                        if held:
                            log.warning("awak worker %s lost the lease", self.holder)
                        held = False
                        self.sleep(self.s.poll_interval_s)
                        continue
                    if not held:
                        # Newly the only worker: whatever another left running is ours.
                        self.recover()
                        held = True
                    with self.heartbeat():
                        worked = self.tick()
                except Exception:  # noqa: BLE001 - the loop must survive anything
                    log.exception("awak tick failed")
                    worked = False
                if not worked:
                    if held:
                        try:
                            self.idle_sweep()
                        except Exception:  # noqa: BLE001
                            log.exception("awak idle sweep failed")
                    self.sleep(self.s.poll_interval_s)
        finally:
            if held:
                self.release_lease()

    # ----------------------------------------------------------------- lease
    def claim_lease(self) -> bool:
        """Take or renew the single worker lease; False if another holds it."""
        t = _naive_now()
        until = t + timedelta(seconds=LEASE_TTL_S)
        with self.sessions() as db:
            res = db.execute(
                update(AwakWorkerLease)
                .where(AwakWorkerLease.id == 1,
                       or_(AwakWorkerLease.holder == self.holder,
                           AwakWorkerLease.expires_at < t))
                .values(holder=self.holder, expires_at=until))
            db.commit()
            if res.rowcount == 1:
                return True
            if db.get(AwakWorkerLease, 1) is not None:
                return False
            db.add(AwakWorkerLease(id=1, holder=self.holder, expires_at=until))
            try:
                db.commit()
                return True
            except IntegrityError:
                db.rollback()
                return False

    def release_lease(self) -> None:
        with self.sessions() as db:
            db.execute(update(AwakWorkerLease)
                       .where(AwakWorkerLease.id == 1, AwakWorkerLease.holder == self.holder)
                       .values(expires_at=datetime(1970, 1, 1)))
            db.commit()

    @contextmanager
    def heartbeat(self) -> Iterator[None]:
        """Renew the lease while a (possibly hour-long) tick runs."""
        done = threading.Event()

        def beat() -> None:
            while not done.wait(LEASE_TTL_S / 4):
                try:
                    if not self.claim_lease():
                        log.warning("awak worker %s lost the lease mid-tick", self.holder)
                except Exception:  # noqa: BLE001
                    log.exception("awak lease renewal failed")

        t = threading.Thread(target=beat, name="awak-lease", daemon=True)
        t.start()
        try:
            yield
        finally:
            done.set()
            t.join(timeout=5)

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
            mode = config_store.load(db, project.slug).merge_mode
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
                if status == "ready" or not job.merge_mode:
                    job.merge_mode = mode  # snapshot; the stricter of it and the current wins
                job.state, job.updated_at = "running", now()
                db.commit()
                record_event(db, job.id, "picked", {"status": status})
                return job.id, st
        return None

    def _reset(self, job: AwakJob, feedback: str, fresh: bool = False) -> None:
        job.attempts, job.infra_errors, job.feedback = 0, 0, feedback
        job.started_at, job.cost_idr, job.phase = now(), 0.0, ""
        job.merge_state, job.merged_sha, job.merge_error = "", "", ""
        if fresh:
            # Back in Ready: route again (role, repo and prompt may have changed).
            job.role_id, job.repo_id, job.prompt_version = None, None, ""
            job.repo_url, job.repo_branch = "", ""

    def _human_feedback(self, story_id: int) -> str:
        bot = {self.taiga.username, self.s.qa_username}
        history = self.taiga.comments(story_id)
        # Taiga lists history newest first; order by time so the latest human
        # comment wins (the oldest one used to, e.g. a stale infra note).
        if history and all(h.get("created_at") for h in history):
            history = sorted(history, key=lambda h: h["created_at"])
        for h in reversed(history):
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
            except (NeedsHuman, checks.Unsupported) as e:
                self._block(project, story, job_id, f"Berhenti: {e}")
                return
            except checks.ServiceFailed as e:
                # A compose service, init/seed or the QA login: the redacted
                # logs go to the event and the card.
                self._event(job_id, "service_failed", {"error": str(e)[:1000],
                                                       "logs": e.logs[-4000:],
                                                       "infra": e.infra})
                logs = f"\n\n```\n{e.logs.strip()[-1500:]}\n```" if e.logs.strip() else ""
                if not e.infra:
                    self._block(project, story, job_id, f"Berhenti: {e}{logs}")
                    return
                job = self._set(job_id, infra_errors=job.infra_errors + 1)
                if job.infra_errors >= self.s.max_infra_errors:
                    self._block(project, story, job_id,
                                f"Gangguan lingkungan berulang ({job.infra_errors}x): {e}{logs}")
                    return
                self._say(story["id"], job_id,
                          f"Gangguan lingkungan, bukan kesalahan story ({e}). Dicoba lagi "
                          f"otomatis; tidak dihitung sebagai percobaan.{logs}")
                self.sleep(30 * job.infra_errors)
                continue
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
            feedback = secrets.redact(result.feedback, self.redact_values_for(project.slug))
            job = self._set(job_id, attempts=job.attempts + 1, feedback=feedback, phase="")
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
            siblings, unavailable = self._siblings(route, job)
            self._event(job.id, "prepared", {"base": base_sha})
            self._check_qa_repos(route)
            checks.run_install(self._runner, self._path(workdir),
                               checks.install_payloads(rc, route.runbook), workdir, rc.name)

            # code
            self._set(job.id, phase="code")
            task = code_task(str(workdir), job.story_ref, story["subject"],
                             story.get("description") or "", job.feedback,
                             siblings=[str(d) for d in siblings], unavailable=unavailable)
            system = render_role(role, route.config.repos)
            report, cost = self.agent.run("awak.code", role.model, system, task,
                                          slug=route.config.slug, role_id=role.id)
            self._add_cost(job.id, cost)
            self._set(job.id, phase="collect")
            self._runner("commit", path=self._path(workdir),
                         message=f"awak: uncommitted changes from attempt {n} "
                                 f"(US #{job.story_ref})")
        self._ours(story["id"], {"in-progress"}, project)

        # collect
        self._set(job.id, phase="collect")
        sha = repo.collect(job.branch)
        # A card put back in Ready keeps its branch. With no human feedback and
        # work already on the branch, "nothing to add" is a fair answer: check
        # the existing tip instead of failing the attempt.
        recheck = (sha == base_sha and not self._job(job.id).feedback
                   and bool(repo.changed_files(job.branch)))
        if recheck:
            self._event(job.id, "recheck", {"sha": sha})
        if sha == base_sha and not recheck:
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
                                            self.scan_values_for(job.project_slug))
        if leaked:
            return Fail("Your change contains a secret or key-like value in: "
                        + ", ".join(leaked) + ". Remove it.",
                        "Diff mengandung nilai mirip secret di "
                        + ", ".join(f"`{f}`" for f in leaked) + "; branch tidak di-push.")
        repo.push_branch(job.branch)
        self._set(job.id, last_sha=sha)

        # gates
        qa_mode, qa_note = self._qa_mode(route)
        gates: list[dict] = []
        if qa_mode != "off":
            self._set(job.id, phase="gates")
            payloads = checks.gate_payloads(rc, route.runbook, files, workdir)
            gates = checks.run_gates(
                self._runner, self._path(workdir), payloads,
                self.compose_for(job, route.runbook, workdir)
                if checks.needs_compose(payloads) else None)
        failed = [g for g in gates if not g.get("ok")]
        table = "\n".join(f"- {'✅' if g.get('ok') else '❌'} {g['name']}" for g in gates)
        if failed:
            fb = "\n\n".join(f"$ {g['name']}\n{g.get('output', '')[-3000:]}" for g in failed)
            return Fail("These checks failed:\n" + fb,
                        f"Branch `{job.branch}` @ `{sha[:8]}` gagal di pemeriksaan otomatis:\n"
                        f"{table}\n\n" + "\n\n".join(
                            f"**{g['name']}**\n```\n{g.get('output', '')[-1200:]}\n```"
                            for g in failed))
        if qa_mode != "browser":
            return self._done_without_qa(project, job, story, workdir, sha, route, n,
                                         qa_mode, qa_note, gates)
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
            # The checks ran in Awak's workspace; only `sha` gets merged. A pass
            # counts only if the workspace was exactly that commit.
            unclean = self._unclean(workdir, sha, rc, route.runbook)
            if unclean:
                return Fail(_unclean_feedback(unclean),
                            f"QA lulus, tetapi workspace tidak sama dengan commit `{sha[:8]}` "
                            "yang akan di-merge, jadi hasilnya tidak dipakai: "
                            + "; ".join(f"`{u}`" for u in unclean)
                            + "\n\nKembali ke In progress; Awak akan memperbaiki.")
            with self.sessions() as db:
                current = config_store.load(db, project.slug).merge_mode
            mode = effective_mode(self._job(job.id).merge_mode, current)
            if mode != "manual" and not save_spec(self.s, job.id, workdir):
                self._event(job.id, "qa_spec_missing", {})
            tags = sorted(set(tag_names(story)) | {DONE_TAG})
            self.taiga.update_story(story["id"], version=story["version"],
                                    status=project.status("done"), tags=tags)
            self._set(job.id, state="passed", phase="", attempts=n)
            head = f"QA lulus untuk `{sha[:8]}`:\n{_table(verdict, evidence)}\n\n"
            self._say(story["id"], job.id, head + _done_tail(mode, job.branch, repo), n)
            if mode == "auto":
                Merger(self).merge(self._job(job.id), project, story, require_qa_rerun=True)
            return None
        return Fail("QA failed these acceptance criteria:\n" + verdict.failures(),
                    f"QA gagal untuk `{sha[:8]}`:\n{_table(verdict, evidence)}\n\n"
                    f"Kembali ke In progress; Awak akan memperbaiki.")

    def _qa_mode(self, route: Route) -> tuple[str, str]:
        return qa_mode_for(route.config, route.rc, route.runbook, self.s.host_git)

    def _done_without_qa(self, project: Project, job: AwakJob, story: dict, workdir: Path,
                         sha: str, route: Route, n: int, qa_mode: str, note: str,
                         gates: list[dict]) -> Fail | None:
        """QA mode off or gates: Done + awaiting-merge, without browser QA. The
        clean check runs last, so Done is tied to the commit that gets merged."""
        unclean = self._unclean(workdir, sha, route.rc, route.runbook)
        if unclean:
            return Fail(_unclean_feedback(unclean),
                        f"Pemeriksaan selesai, tetapi workspace tidak sama dengan commit "
                        f"`{sha[:8]}` yang akan di-merge, jadi hasilnya tidak dipakai: "
                        + "; ".join(f"`{u}`" for u in unclean)
                        + "\n\nKembali ke In progress; Awak akan memperbaiki.")
        story = self._ours(story["id"], {"in-progress"}, project)
        with self.sessions() as db:
            current = config_store.load(db, project.slug).merge_mode
        mode = effective_mode(self._job(job.id).merge_mode, current)
        if mode == "auto":
            # Auto merge only follows browser QA. Saved on the job, so the
            # Merge button (which needs approve) works for this story.
            mode = "approve"
            self._set(job.id, merge_mode="approve")
            self._event(job.id, "merge_mode", {"merge_mode": "approve",
                                               "reason": "done without browser QA"})
        tags = sorted(set(tag_names(story)) | {DONE_TAG})
        self.taiga.update_story(story["id"], version=story["version"],
                                status=project.status("done"), tags=tags)
        self._set(job.id, state="passed", phase="", attempts=n)

        checked = ["cakupan berkas peran", "secret di diff"]
        if gates:
            checked.append("pemeriksaan otomatis di atas")
        checked.append("workspace sama persis dengan commit")
        if qa_mode == "off":
            label = "Off"
            skipped = ["pemeriksaan otomatis (tipe, lint, tes, build)",
                       "QA browser terhadap kriteria penerimaan"]
            head = f"Commit `{sha[:8]}` di branch `{job.branch}`."
        else:
            label = "Gates only"
            skipped = [] if gates else [
                "pemeriksaan otomatis (repo ini belum punya perintah check/build)"]
            skipped.append("QA browser terhadap kriteria penerimaan (tanpa bukti screenshot)")
            table = "\n".join(f"- ✅ {g['name']}" for g in gates)
            head = (f"Commit `{sha[:8]}` di branch `{job.branch}`. Pemeriksaan otomatis:\n"
                    f"{table}" if gates else f"Commit `{sha[:8]}` di branch `{job.branch}`.")
        text = (f"{head}\n\n" + (f"{note}\n\n" if note else "")
                + f"Mode QA proyek: {label}. Diperiksa: " + ", ".join(checked) + ". "
                + "Tidak diperiksa: " + "; ".join(skipped) + ".\n\n"
                + _done_tail(mode, job.branch, route.repo))
        self._say(story["id"], job.id, text, n)
        return None

    def _qa(self, project: Project, job: AwakJob, story: dict, workdir: Path,
            route: Route) -> Verdict:
        texts = criteria(story.get("description") or "")
        if not texts:
            raise NeedsHuman("story tidak punya kriteria penerimaan; tambahkan bagian "
                       "'Acceptance criteria' berisi daftar poin.")
        qa_role = route.config.qa_role()
        if qa_role is not None:
            model = qa_role.model or self.s.qa_model
            system = render_role(qa_role, route.config.repos)
        else:
            model = self.s.qa_model
            system = render("qa", "", RoleScope(repos=[route.rc.name]))
        plan = runbook_qa(route.runbook)
        token = self.qa_taiga.login() if plan is None else ""
        spec_feedback = ""
        for _ in range(2):
            self._runner("qa_reset", path=self._path(workdir))
            if plan is None:
                task = qa_task(str(workdir), job.story_ref, story["subject"], texts,
                               self.s.qa_project, spec_feedback, app_dir=route.rc.subdir)
            else:
                task = qa_task(str(workdir), job.story_ref, story["subject"], texts, "",
                               spec_feedback, app_dirs=plan["app_dirs"],
                               env_names=plan["qa_env"],
                               login_path=(plan["login"] or {}).get("path"),
                               backing=plan["compose"])
            _, cost = self.agent.run("awak.qa", model, system, task, slug=route.config.slug,
                                     role_id=qa_role.id if qa_role else None)
            self._add_cost(job.id, cost)
            if plan is not None:
                self.qa_siblings(route.config, route.rc, route.runbook, job.branch)
            report = self.run_qa(job, workdir, route.runbook, route.rc, plan, token)
            verdict = evaluate(report, texts)
            self._event(job.id, "qa", {"outcome": verdict.outcome, "reason": verdict.reason})
            if verdict.outcome != "spec":
                break
            spec_feedback = verdict.reason
        if verdict.outcome in ("spec", "infra"):
            raise Infra(f"QA tidak dapat berjalan: {verdict.reason}")
        return verdict

    def qa_payload(self, plan: dict | None, token: str, rc: RepoConfig,
                   external: dict[str, str] | None = None, login: dict | None = None,
                   spec_env: dict[str, str] | None = None) -> dict:
        """The runner's `qa` body: the runbook's services (plus the compose
        services' URLs, the resolved login and the spec's vault values), or
        Kemudi's vite path."""
        if plan is None:
            return {"token": token, "user": self.qa_taiga.me, "project": self.s.qa_project,
                    "subdir": rc.subdir}
        body = {"services": plan["services"], "base_service": plan["base_service"],
                "warm": plan["warm"]}
        if external:
            body["external"] = external
        if login:
            body["login"] = login
        if spec_env:
            body["spec_env"] = spec_env
        return body

    def run_qa(self, job: AwakJob, workdir: Path, rb: Runbook | None, rc: RepoConfig,
               plan: dict | None, token: str) -> dict:
        """One runner QA run (worker and merge re-run). With a runbook: its
        compose services up (kemudi-svc), init, seed and health first, the login
        and the spec's vault values resolved, and the services down afterwards,
        whatever happens."""
        if plan is None or rb is None:
            return self._runner("qa", path=self._path(workdir),
                                **self.qa_payload(plan, token, rc))
        values = self._vault(job.project_slug) if (
            plan["compose"] or plan["login"] or plan["qa_env"]) else {}
        login = checks.login_payload(rb, values)
        spec_env = checks.vault_env(rb, plan["qa_env"], values, "qa.env")
        compose = self.compose_for(job, rb, workdir, values) if plan["compose"] else None
        with compose.for_qa(plan) if compose else nullcontext({}) as urls:
            report = self._runner("qa", path=self._path(workdir),
                                  **self.qa_payload(plan, token, rc, urls, login, spec_env))
        if report.get("login_error"):
            raise checks.ServiceFailed(
                "login QA (qa.login) gagal; periksa selector dan nilai vault di runbook, atau "
                "kembalikan story ke In progress jika story ini mengubah halaman login.",
                logs=str(report["login_error"]), infra=False)
        return report

    def _vault(self, slug: str) -> dict[str, str]:
        try:
            with self.sessions() as db:
                return vault.values(db, self.s, slug)
        except SecretKeyMissing as e:
            raise checks.Unsupported(f"vault proyek tidak bisa dibaca: {e}") from e

    def compose_for(self, job: AwakJob, rb: Runbook | None, workdir: Path,
                    values: dict[str, str] | None = None) -> checks.Compose:
        """The job's compose services (projects `<slug>-us<ref>`), reached
        through kemudi-svc from the story folder's checkouts."""
        if rb is None:
            raise checks.Unsupported("tidak ada runbook untuk service compose.")
        slug = job.project_slug
        return checks.Compose(
            rb, self._svc, self._runner,
            checks.compose_projects(rb, slug, f"us{job.story_ref}"),
            lambda repo: self._path(workdir.parent / repo),
            self._vault(slug) if values is None else values,
            self.redact_values_for(slug),
            lambda kind, detail: self._event(job.id, kind, detail))

    def _svc(self, op: str, **payload) -> dict:
        if self.svc is None:
            raise checks.ServiceFailed("kemudi-svc belum dikonfigurasi (KEMUDI_SVC_KEY), jadi "
                                       "service compose tidak bisa berjalan.", infra=False)
        try:
            res = self.svc.call(op, **payload)
        except SvcRejected as e:
            raise checks.Unsupported(
                f"kemudi-svc menolak langkah {op}: {e}. Periksa service compose di runbook "
                "(file, compose_services, expose, env) dan compose file repo.") from e
        except SvcError as e:
            raise checks.ServiceFailed(f"kemudi-svc tidak bisa dihubungi ({op}): {e}") from e
        if res.get("infra_error"):
            raise checks.ServiceFailed(f"kemudi-svc {op}: {res['infra_error']}")
        return res

    # ------------------------------------------------------------- helpers
    def _route(self, job: AwakJob, story: dict, slug: str) -> Route:
        """Role and repo by the story's area tag, pinned on the job at its first
        attempt and kept for rework; the prompt version is what this attempt uses."""
        with self.sessions() as db:
            cfg = config_store.load(db, slug)
            row = db.get(AwakJob, job.id)
            if row.role_id is None:
                areas = story_areas(tag_names(story))
                role = cfg.role_for_story(areas)
                if role is None and len(areas) > 1:
                    raise NeedsHuman("story punya lebih dari satu tag area ("
                               + ", ".join(f"area-{a}" for a in areas) + "); sisakan satu, "
                               "atau tambahkan peran Fullstack (area Frontend + backend) di "
                               "Pengaturan proyek → Agen.")
                if role is None:
                    raise NeedsHuman(f"tidak ada peran agen aktif untuk area {areas[0]}; aktifkan "
                               f"di Pengaturan proyek → Agen.")
                rc = cfg.repo(role.repo_ids[0]) if role.repo_ids else None
                if rc is None:
                    raise NeedsHuman(f"peran {role.name} belum punya repo; pilih di Pengaturan "
                               f"proyek → Agen.")
                row.role_id, row.repo_id = role.id, rc.id
            else:
                role = cfg.role(row.role_id)
                if role is None or not role.enabled:
                    raise NeedsHuman("peran agen untuk story ini sudah dihapus atau dimatikan.")
                rc = cfg.repo(row.repo_id)
                if rc is None:
                    raise NeedsHuman("repo untuk story ini sudah dihapus dari pengaturan Agen.")
            # What this attempt runs against; Merge checks it is still the same.
            row.repo_url, row.repo_branch = rc.url, rc.default_branch
            version = prompt_version(role, cfg.repos)
            changed = row.prompt_version != version
            row.prompt_version = version
            db.commit()
            key = config_store.key_row(db, rc.key_id)
            rb = runbook.load(db, slug)
        if changed:
            self._event(job.id, "routed", {"role_id": role.id, "repo_id": rc.id,
                                           "prompt_version": version})
        return Route(cfg, role, rc, self._repo_of(cfg, rc, key), rb)

    def _repo_of(self, cfg: ProjectConfig, rc: RepoConfig, key: AwakKey | None) -> Repo:
        if self.repo is not None and rc.url == self.s.host_git:
            # The injected Kemudi repo (tests); placed like a configured one.
            self.repo.slug, self.repo.name = cfg.slug, rc.name
            return self.repo
        return repo_for(cfg, rc, self.s, key)

    def _siblings(self, route: Route, job: AwakJob) -> tuple[list[Path], list[str]]:
        """The project's other repos checked out at their default branch beside
        the story's (read-only context), and the names of those that could not
        be fetched (no key, unreachable...): left out, so one broken repo does
        not hold up every story. Never the injected repo: that one is the
        story's own."""
        with self.sessions() as db:
            rows = [(r, config_store.key_row(db, r.key_id))
                    for r in route.config.repos if r.id != route.rc.id]
        out, unavailable = [], []
        for r, key in rows:
            try:
                sib = repo_for(route.config, r, self.s, key)
                sib.sync_default()
                out.append(sib.checkout_default(job.branch))
            except GitError as e:
                log.warning("awak: sibling repo %s of %s unavailable: %s",
                            r.name, route.config.slug, e)
                self._event(job.id, "sibling_unavailable",
                            {"repo": r.name, "error": str(e)[:300]})
                unavailable.append(r.name)
        return out, unavailable

    def _check_qa_repos(self, route: Route) -> None:
        """Before paying for a coding run: every repo browser QA starts a
        service from must still be one of the project's repos."""
        if route.runbook is None or self._qa_mode(route)[0] != "browser" \
                or runbook_qa(route.runbook) is None:
            return
        names = {r.name for r in route.config.repos}
        for name in checks.qa_repos(route.runbook):
            if name not in names:
                raise checks.Unsupported(_gone_repo(name))

    def qa_siblings(self, cfg: ProjectConfig, rc: RepoConfig, rb: Runbook, branch: str) -> None:
        """Right before a QA run: the other repos the QA services start from,
        checked out again at their default branch and installed. Whatever the
        agents did to their read-only copies, or an older checkout (the merge
        re-run), never reaches QA."""
        for name in checks.qa_repos(rb):
            if name == rc.name:
                continue
            r = next((x for x in cfg.repos if x.name == name), None)
            if r is None:
                raise checks.Unsupported(_gone_repo(name))
            with self.sessions() as db:
                key = config_store.key_row(db, r.key_id)
            sib = repo_for(cfg, r, self.s, key)
            try:
                sib.sync_default()
            except GitError as e:
                raise Infra(f"repo {name} yang dibutuhkan service QA tidak bisa diambil "
                            f"({e}).") from e
            d = sib.checkout_default(branch)
            checks.run_install(self._runner, self._path(d), checks.qa_install_payloads(rb, name),
                               d, name)

    def _path(self, workdir: Path) -> str:
        return runner_path(self.s.workspace_dir, workdir)

    def _requested_merge(self, project: Project, job: AwakJob) -> None:
        """A human clicked Merge (approve mode). Re-checks the mode first."""
        with self.sessions() as db:
            cfg = config_store.load(db, project.slug)
            rb = runbook.load(db, project.slug)
        mode = effective_mode(job.merge_mode, cfg.merge_mode)
        merger = Merger(self)
        if mode == "manual":
            merger.fail(job.id, job.story_id,
                        "mode merge proyek sekarang manual; merge dibatalkan.")
            return
        # The QA re-run needs a spec, which only browser QA writes.
        rc = cfg.repo(job.repo_id)
        qa_mode = qa_mode_for(cfg, rc, rb, self.s.host_git)[0] if rc else "gates"
        merger.merge(job, project, {"id": job.story_id},
                     require_qa_rerun=mode == "auto" and qa_mode == "browser")

    def _unclean(self, workdir: Path, sha: str, rc: RepoConfig,
                 rb: Runbook | None = None) -> list[str]:
        """What in the workspace differs from `sha`, besides build output (in the
        repo's subdir and in the runbook's app dirs of the repo)."""
        apps = rb.apps_of(rc.name) if rb else []
        dirs = [rc.subdir, *(a.dir for a in apps)]
        generated = [f"{a.dir}/{g}" if a.dir else g for a in apps for g in a.generated]
        res = self._runner("clean_check", path=self._path(workdir))
        out = []
        head = str(res.get("head") or "")
        if head != sha:
            out.append(f"HEAD {head[:8] or '?'} != {sha[:8]}")
        entries = res.get("entries") or []
        out += [f"{e.get('status', '')} {e.get('path', '')}".strip() for e in entries
                if not build_output(str(e.get("status", "")), str(e.get("path", "")), dirs,
                                    generated)]
        if res.get("truncated"):
            out.append("(more paths not listed)")
        if out and all(u.startswith("!! ") for u in out):
            # Only ignored files, HEAD is the commit: almost always something the
            # install or a check generates. Telling the agent to "commit
            # everything" made it commit build artefacts, so a human decides.
            paths = ", ".join(f"`{u[3:]}`" for u in out[:10])
            raise NeedsHuman(f"setelah install dan pemeriksaan, workspace berisi berkas yang di-ignore "
                       f"git dan tidak dikenal sebagai hasil build: {paths}. Jika itu dibuat oleh "
                       f"install atau build, tambahkan ke `generated` app di runbook (Pengaturan "
                       f"proyek → Agen), lalu buka blokir story.")
        return out[:20]

    def _runner(self, op: str, **payload) -> dict:
        try:
            res = self.runner.call(op, **payload)
        except RunnerRejected as e:
            # The same request is refused again: a folder, command or env from
            # the runbook or the repo settings the runner cannot accept.
            raise checks.Unsupported(
                f"runner menolak langkah {op}: {e}. Periksa runbook (repo, folder, perintah, "
                "env) dan pengaturan repo di Pengaturan proyek → Agen.") from e
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
        """Every string in the detail is redacted (errors, QA reasons, logs)."""
        with self.sessions() as db:
            job = db.get(AwakJob, job_id)
            slug = job.project_slug if job is not None else ""
        detail = self._redact_detail(slug, detail)
        with self.sessions() as db:
            record_event(db, job_id, kind, detail)

    def _say(self, story_id: int, job_id: int, text: str, n: int | None = None) -> None:
        job = self._job(job_id)
        n = n or job.attempts
        mins = max(0, int((now() - _aware(job.started_at)).total_seconds() // 60))
        head = f"**Awak** · percobaan {max(n, 1)}/{self.s.max_attempts} · {mins} mnt"
        if job.cost_idr:
            head += f" · biaya model Rp{job.cost_idr:,.0f}".replace(",", ".")
        body = secrets.redact(f"{head}\n\n{text}", self.redact_values_for(job.project_slug))
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
                default_branch=repo_row.default_branch, subdir=repo_row.subdir, git_env=env,
                scratch_dir=str(Path(settings.repos_dir) / "scratch"), slug=config.slug,
                name=repo_row.name)


def qa_mode_for(cfg: ProjectConfig, rc: RepoConfig, rb: Runbook | None,
                host_git: str) -> tuple[str, str]:
    """The project's QA mode for a story of `rc`, and why it was lowered (if).
    Browser QA runs from the runbook's qa section, or, without one, only for
    Kemudi's own repo (iteration 1's vite path)."""
    mode = cfg.qa_mode if cfg.qa_mode in QA_MODES else "gates"
    if mode != "browser" or (rb is not None and rb.browser_qa_ready()):
        return mode, ""
    if rb is not None and rb.qa_service() is not None:
        return "gates", ("Mode QA proyek Browser, tetapi service QA di runbook bukan service "
                         "process (dev server app); diperlakukan sebagai Gates only.")
    if rc.url == host_git:
        return mode, ""
    return "gates", ("Mode QA proyek Browser, tetapi QA browser belum bisa berjalan "
                     f"untuk repo {rc.name} (perlu runbook dengan bagian QA); "
                     "diperlakukan sebagai Gates only.")


def runbook_qa(rb: Runbook | None) -> dict | None:
    """The runbook's QA plan when browser QA runs from it; None: Kemudi's path."""
    if rb is None or not rb.browser_qa_ready():
        return None
    return checks.qa_plan(rb)


def runner_path(workspace_dir: str, workdir: Path) -> str:
    """A checkout as the runner names it: relative to the workspace, `/`-joined
    (`<slug>/us-<ref>/<repo>`); the runner validates its shape."""
    return Path(workdir).relative_to(Path(workspace_dir)).as_posix()


# What the install, the gates and QA themselves leave in a workspace. Only
# untracked or ignored paths qualify; a changed tracked file never does.
QA_DIR = ".qa"                                   # repo root only, any status
ANYWHERE_DIRS = {"node_modules", "__pycache__"}  # at any depth
BUILD_DIRS = {"dist", ".vite", ".turbo", "coverage", ".pytest_cache", ".ruff_cache",
              ".mypy_cache", ".venv", "target", ".next"}  # at the repo root or an app dir
BUILD_SUFFIXES = (".tsbuildinfo",)               # at any depth
BUILD_FILES = {"next-env.d.ts"}                  # ignored, at the root or an app dir


def build_output(status: str, path: str, subdir: str | list[str] = "",
                 generated: list[str] | tuple[str, ...] = ()) -> bool:
    """Whether a `git status` entry is something install/gates/QA produce.
    `generated`: repo-relative globs from the runbook's apps; like
    BUILD_FILES they only excuse *ignored* paths (an untracked, unignored
    file is something the commit is missing)."""
    if status not in ("??", "!!"):
        return False
    parts = path.strip("/").split("/")
    if not parts or any(p in ("", ".", "..") for p in parts):
        return False
    if parts[0] == QA_DIR:
        # Kemudi's own folder (specs, results, process service logs), however
        # git lists it: as the folder or file by file.
        return True
    dirs = [subdir] if isinstance(subdir, str) else subdir
    app_dirs = {"", *(d.strip("/") for d in dirs)}
    if status == "!!" and not path.endswith("/"):
        if parts[-1] in BUILD_FILES and "/".join(parts[:-1]) in app_dirs:
            return True
        if any(fnmatch.fnmatchcase(path, g) for g in generated):
            return True
    if any(p in ANYWHERE_DIRS for p in parts[:-1]) or (
            path.endswith("/") and parts[-1] in ANYWHERE_DIRS):
        return True
    name, parent = parts[-1], "/".join(parts[:-1])
    if name.endswith(BUILD_SUFFIXES) and not path.endswith("/"):
        return True
    if not path.endswith("/"):
        return False
    if name == QA_DIR and parent == "":
        return True
    return name in BUILD_DIRS and parent in app_dirs


def _gone_repo(name: str) -> str:
    return (f"service QA di runbook berjalan dari repo {name}, yang tidak ada lagi di "
            "pengaturan Agen; perbaiki runbook di Pengaturan proyek → Agen.")


def _unclean_feedback(unclean: list[str]) -> str:
    return ("The checks and QA ran with files that are not in your commit "
            "(or HEAD was not your commit): " + "; ".join(unclean)
            + ". Commit everything the story needs and leave no other "
              "files (ignored ones included) in the workspace.")


def _done_tail(mode: str, branch: str, repo: Repo) -> str:
    """What happens next with a Done card, by merge mode."""
    if mode == "manual":
        return (f"Pindah ke Done dengan tag `{DONE_TAG}`: branch `{branch}` "
                f"belum di-merge dan perlu direview manusia.")
    if mode == "approve":
        return (f"Pindah ke Done dengan tag `{DONE_TAG}`: branch `{branch}` "
                f"menunggu Merge di Kemudi.")
    return (f"Pindah ke Done dengan tag `{DONE_TAG}`; merge otomatis ke "
            f"`{repo.default_branch}` berjalan.")


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
