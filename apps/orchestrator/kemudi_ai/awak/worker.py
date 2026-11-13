"""The Awak loop: pick a story, code, gate, QA, and move the card.

One story at a time. Taiga is the source of truth for where a story is; the
job row only remembers attempts, feedback and cost between ticks.
"""

import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings
from ..store import AwakJob, record_event
from . import config_store, secrets
from .agent import Agent, AgentError
from .gitops import GitError, Repo, branch_for
from .intake import TAG
from .runner import Runner, RunnerError
from .stories import CODE_SYSTEM, QA_SYSTEM, code_task, criteria, qa_task
from .taiga import Project, Taiga, TaigaError, tag_names
from .verdict import Verdict, evaluate, safe_screenshot

log = logging.getLogger(__name__)

DONE_TAG = "awaiting-merge"
HUMAN_TAG = "needs-human"
BACKEND_PREFIXES = ("services/kemudi-back/",)


class Stop(Exception):
    """A human took the story over; stop quietly (with one comment)."""


class Infra(Exception):
    """Something outside the story failed; retry without using an attempt."""


@dataclass
class Fail:
    feedback: str
    comment: str


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
        repo: Repo,
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
                        self._reset(job, "")
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

    def _reset(self, job: AwakJob, feedback: str) -> None:
        job.attempts, job.infra_errors, job.feedback = 0, 0, feedback
        job.started_at, job.cost_idr, job.phase = now(), 0.0, ""

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
        self.taiga.update_story(
            story["id"], version=story["version"],
            status=project.status("in-progress"),
            assigned_to=self.taiga.me.get("id"),
        )
        self._say(story["id"], job.id, f"Percobaan {n}/{self.s.max_attempts} dimulai.", n)

        # After an infra error past the coding step, keep Awak's work and resume
        # from collect instead of paying for the coding run again.
        workdir = self.repo.job_dir(job.branch)
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
            main_sha = self.repo.sync_main()
            base_sha = (self.repo.sha(job.branch) if self.repo.has_branch(job.branch)
                        else main_sha)
            workdir = self.repo.prepare(job.branch)
            self._event(job.id, "prepared", {"base": base_sha})
            self._runner("install", job=workdir.name)

            # code
            self._set(job.id, phase="code")
            task = code_task(str(workdir), job.story_ref, story["subject"],
                             story.get("description") or "", job.feedback)
            report, cost = self.agent.run("awak.code", self.s.awak_model, CODE_SYSTEM, task)
            self._add_cost(job.id, cost)
            self._set(job.id, phase="collect")
            self._runner("commit", job=workdir.name,
                         message=f"awak: uncommitted changes from attempt {n} "
                                 f"(US #{job.story_ref})")
        self._ours(story["id"], {"in-progress"}, project)

        # collect
        self._set(job.id, phase="collect")
        sha = self.repo.collect(job.branch)
        if sha == base_sha:
            return Fail("You made no commit. Implement the story and commit it.",
                        "Awak tidak menghasilkan commit. Laporan Awak:\n\n"
                        + _quote(report))
        files = self.repo.changed_files(job.branch)
        backend = [f for f in files if f.startswith(BACKEND_PREFIXES)]
        if backend:
            return Fail("Do not change services/kemudi-back; this story is frontend only. "
                        "Revert: " + ", ".join(backend),
                        "Awak mengubah backend, padahal story ini khusus frontend: "
                        + ", ".join(f"`{f}`" for f in backend))
        leaked = secrets.files_with_secrets(self.repo.diff_from_main(job.branch),
                                            self.secret_values)
        if leaked:
            return Fail("Your change contains a secret or key-like value in: "
                        + ", ".join(leaked) + ". Remove it.",
                        "Diff mengandung nilai mirip secret di "
                        + ", ".join(f"`{f}`" for f in leaked) + "; branch tidak di-push.")
        self.repo.push_host(job.branch)
        self._set(job.id, last_sha=sha)

        # gates
        self._set(job.id, phase="gates")
        gates = self._runner("gates", job=workdir.name).get("gates") or []
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
        verdict = self._qa(project, job, story, workdir)
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

    def _qa(self, project: Project, job: AwakJob, story: dict, workdir: Path) -> Verdict:
        texts = criteria(story.get("description") or "")
        if not texts:
            raise Stop("story tidak punya kriteria penerimaan; tambahkan bagian "
                       "'Acceptance criteria' berisi daftar poin.")
        token = self.qa_taiga.login()
        spec_feedback = ""
        for _ in range(2):
            self._runner("qa_reset", job=workdir.name)
            task = qa_task(str(workdir), job.story_ref, story["subject"], texts,
                           self.s.qa_project, spec_feedback)
            _, cost = self.agent.run("awak.qa", self.s.qa_model, QA_SYSTEM, task)
            self._add_cost(job.id, cost)
            report = self._runner("qa", job=workdir.name, token=token,
                                  user=self.qa_taiga.me, project=self.s.qa_project)
            verdict = evaluate(report, texts)
            self._event(job.id, "qa", {"outcome": verdict.outcome, "reason": verdict.reason})
            if verdict.outcome != "spec":
                break
            spec_feedback = verdict.reason
        if verdict.outcome in ("spec", "infra"):
            raise Infra(f"QA tidak dapat berjalan: {verdict.reason}")
        return verdict

    # ------------------------------------------------------------- helpers
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
