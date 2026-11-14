"""Merge modes: after QA passes, a story's branch goes into the default branch.

What gets pushed to the default branch is always one of:
- the exact commit QA passed (`job.last_sha`) as a fast-forward, or
- a merge commit of it onto the latest default branch that passed the gates
  again (and, in `auto` mode, the saved QA spec again) in a fresh workspace.

The push is never forced: if the remote moved meanwhile, git refuses, and the
merge starts over once from the latest default branch. Any failure leaves the
default branch untouched and asks a human (`needs-human`).
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ..store import AwakJob
from . import config_store, secrets, ssh
from .agent import AgentError
from .crypto import SecretKeyMissing
from .gitops import GitError, MergeConflict, PushRejected, Repo, _chown
from .runner import RunnerError
from .stories import criteria
from .taiga import Project, TaigaError, tag_names
from .verdict import Verdict, evaluate

if TYPE_CHECKING:
    from .worker import Worker

log = logging.getLogger(__name__)

STRICTNESS = {"manual": 0, "approve": 1, "auto": 2}
MERGED_TAG = "merged"
DONE_TAG = "awaiting-merge"   # same names as worker.py (which imports this module)
HUMAN_TAG = "needs-human"
DEPLOY_TIMEOUT = 900
SPEC_NAME = "story.spec.ts"


def effective_mode(snapshot: str, current: str) -> str:
    """The stricter (lower) of the mode saved at pick time and the current one.
    An unknown or empty value counts as `manual` (iteration 1 jobs)."""
    a = snapshot if snapshot in STRICTNESS else "manual"
    b = current if current in STRICTNESS else "manual"
    return a if STRICTNESS[a] <= STRICTNESS[b] else b


def deploy_secrets(command: str) -> list[str]:
    """Strings of the deploy command to hide from its output: the command
    itself, `NAME=value` values and long words (a token passed inline)."""
    values = [command] if command else []
    for word in command.split():
        value = word.split("=", 1)[1] if "=" in word else word
        value = value.strip("'\"")
        if len(value) >= 16 or ("=" in word and len(value) >= 8):
            values.append(value)
    return sorted(set(values), key=len, reverse=True)  # longest first


class MergeFailed(Exception):
    """The merge cannot go ahead; nothing was pushed to the default branch."""


@dataclass
class MergeResult:
    ok: bool
    sha: str = ""
    checks: list[str] = field(default_factory=list)
    error: str = ""


def spec_path(settings, job_id: int) -> Path:
    return Path(settings.repos_dir) / "qa-specs" / f"{job_id}.spec.ts"


def save_spec(settings, job_id: int, workdir: Path) -> bool:
    """Keep the spec that passed QA, for a QA re-run on a merge result."""
    specs = sorted((workdir / ".qa" / "spec").glob("*.spec.ts"))
    if not specs:
        return False
    dest = spec_path(settings, job_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(specs[0], dest)
    return True


class Merger:
    def __init__(self, worker: Worker):
        self.w = worker

    # ----------------------------------------------------------------- entry
    def merge(self, job: AwakJob, project: Project, story: dict,
              require_qa_rerun: bool) -> MergeResult:
        from .worker import Infra, Stop

        w = self.w
        w._set(job.id, merge_state="merging", merge_error="")
        w._event(job.id, "merge", {"qa_rerun": require_qa_rerun})
        workdir: Path | None = None
        try:
            story = self._card(project, story["id"])
            cfg, rc, repo = self._repo(job)
            target, checks, workdir = self._merge(job, story, rc, repo, require_qa_rerun)
        except (MergeFailed, Stop, Infra, GitError, RunnerError, AgentError, TaigaError,
                SecretKeyMissing) as e:
            return self.fail(job.id, story["id"], str(e))

        w._set(job.id, merge_state="merged", merged_sha=target, merge_error="")
        w._event(job.id, "merged", {"sha": target, "checks": checks})
        try:
            st = w.taiga.story(story["id"])
            tags = sorted((set(tag_names(st)) - {DONE_TAG}) | {MERGED_TAG})
            w.taiga.update_story(st["id"], version=st["version"], tags=tags)
        except TaigaError as e:
            log.warning("could not tag merged story %s: %s", story["id"], e)
        w._say(story["id"], job.id,
               f"Di-merge ke `{repo.default_branch}` sebagai `{target[:8]}`. "
               f"Pemeriksaan: {'; '.join(checks)}.")
        if cfg.deploy_command.strip():
            self._deploy(cfg, job, story["id"], rc, repo, target, workdir)
        return MergeResult(True, target, checks)

    def fail(self, job_id: int, story_id: int, reason: str) -> MergeResult:
        w = self.w
        reason = secrets.redact(reason, w.secret_values)[:500]
        w._set(job_id, merge_state="failed", merge_error=reason)
        w._event(job_id, "merge_failed", {"error": reason})
        try:
            st = w.taiga.story(story_id)
            tags = sorted(set(tag_names(st)) | {HUMAN_TAG})
            w.taiga.update_story(st["id"], version=st["version"], tags=tags)
            w._say(story_id, job_id,
                   f"Merge gagal; tidak ada yang di-push ke default branch. {reason}")
        except TaigaError as e:
            log.warning("could not report a failed merge on story %s: %s", story_id, e)
        return MergeResult(False, error=reason)

    # ----------------------------------------------------------------- steps
    def _card(self, project: Project, story_id: int) -> dict:
        st = self.w.taiga.story(story_id)
        if (st["status"] != project.status("done") or DONE_TAG not in tag_names(st)
                or st.get("is_blocked")):
            raise MergeFailed("kartu sudah diubah (bukan lagi Done dengan tag "
                              f"`{DONE_TAG}`, atau diblokir).")
        return st

    def _repo(self, job: AwakJob):
        with self.w.sessions() as db:
            cfg = config_store.load(db, job.project_slug)
            rc = cfg.repo(job.repo_id)
            if rc is None:
                raise MergeFailed("repo untuk story ini sudah dihapus dari pengaturan Agen.")
            row = db.get(AwakJob, job.id)
            pinned = (row.repo_url, row.repo_branch) if row else ("", "")
            if pinned[0] and pinned != (rc.url, rc.default_branch):
                raise MergeFailed(
                    f"repo {rc.name} diubah sejak QA (`{pinned[0]}` @ `{pinned[1]}` -> "
                    f"`{rc.url}` @ `{rc.default_branch}`); pindahkan story ke Ready untuk "
                    f"menjalankannya ulang.")
            key = config_store.key_row(db, rc.key_id)
        return cfg, rc, self.w._repo_of(cfg, rc, key)

    def _merge(self, job: AwakJob, story: dict, rc, repo: Repo,
               require_qa_rerun: bool) -> tuple[str, list[str], Path | None]:
        from .worker import _commands

        w = self.w
        job = w._job(job.id)
        if not job.last_sha:
            raise MergeFailed("job tidak punya commit yang lulus QA.")
        for attempt in (1, 2):
            default_sha = repo.sync_default()
            branch_sha = repo.sha(job.branch)
            if branch_sha != job.last_sha:
                raise MergeFailed(f"branch berubah sejak QA (`{branch_sha[:8]}` bukan "
                                  f"`{job.last_sha[:8]}`).")
            workdir = None
            if repo.is_ancestor(default_sha, branch_sha):
                # A fast-forward to the exact commit QA passed: nothing new to check.
                target = branch_sha
                checks = [f"fast-forward ke commit yang lulus QA `{target[:8]}`"]
            else:
                ref = f"refs/kemudi/merge/{job.id}"
                try:
                    target = repo.merge_commit(
                        default_sha, branch_sha,
                        f"Merge {job.branch} (US #{job.story_ref}) via Kemudi", ref)
                except MergeConflict as e:
                    raise MergeFailed(f"konflik saat merge ke `{repo.default_branch}`; "
                                      f"selesaikan manual. ({e})") from e
                w._event(job.id, "merge_commit", {"sha": target, "onto": default_sha})
                workdir = repo.prepare_at(job.branch, ref, target)
                w._runner("install", path=w._path(workdir), **_commands(rc, "install"))
                gates = (w._runner("gates", path=w._path(workdir), **_commands(rc, "gates"))
                         .get("gates") or [])
                failed = [g["name"] for g in gates if not g.get("ok")]
                if failed:
                    raise MergeFailed("pemeriksaan otomatis gagal pada hasil merge "
                                      f"`{target[:8]}`: " + ", ".join(failed))
                checks = [f"merge commit `{target[:8]}`",
                          "gates ulang lulus (" + ", ".join(g["name"] for g in gates) + ")"]
                if require_qa_rerun:
                    verdict = self._rerun_qa(job, story, workdir, rc, repo)
                    if verdict.outcome != "pass":
                        raise MergeFailed(f"QA ulang pada hasil merge tidak lulus "
                                          f"({verdict.outcome}): {verdict.reason}")
                    checks.append("QA ulang lulus")
            try:
                repo.push_default(target)
                return target, checks, workdir
            except PushRejected as e:
                if attempt == 2:
                    raise MergeFailed(f"`{repo.default_branch}` di remote terus bergerak; "
                                      f"push ditolak dua kali.") from e
                w._event(job.id, "merge_retry", {"reason": "push rejected"})
        raise AssertionError("unreachable")

    def _rerun_qa(self, job: AwakJob, story: dict, workdir: Path, rc, repo: Repo) -> Verdict:
        w = self.w
        saved = spec_path(w.s, job.id)
        if not saved.exists():
            raise MergeFailed("spec QA yang lulus tidak tersimpan; QA ulang tidak bisa jalan.")
        texts = criteria(story.get("description") or "")
        w._runner("qa_reset", path=w._path(workdir))
        spec_dir = workdir / ".qa" / "spec"
        spec_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(saved, spec_dir / SPEC_NAME)
        _chown(workdir / ".qa", repo.uid)
        token = w.qa_taiga.login()
        report = w._runner("qa", path=w._path(workdir), token=token, user=w.qa_taiga.me,
                           project=w.s.qa_project, subdir=rc.subdir)
        verdict = evaluate(report, texts)
        w._event(job.id, "qa_rerun", {"outcome": verdict.outcome, "reason": verdict.reason})
        return verdict

    # ---------------------------------------------------------------- deploy
    def _deploy(self, cfg, job: AwakJob, story_id: int, rc, repo: Repo, target: str,
                workdir: Path | None) -> None:
        w = self.w
        command = cfg.deploy_command.strip()
        try:
            if cfg.executor == "ssh":
                ok, out = self._deploy_ssh(cfg, command)
            else:
                if workdir is None:
                    job_now = w._job(job.id)
                    workdir = repo.prepare_at(job_now.branch, f"refs/heads/{job_now.branch}",
                                              target)
                res = w.runner.call("deploy", path=w._path(workdir), command=command)
                if res.get("infra_error"):
                    ok, out = False, str(res["infra_error"])
                else:
                    ok, out = bool(res.get("ok")), str(res.get("output") or "")
        except (GitError, RunnerError, SecretKeyMissing, OSError) as e:
            ok, out = False, f"{type(e).__name__}: {e}"
        tail = (secrets.redact(out, [*w.secret_values, *deploy_secrets(command)])[-1500:]
                .strip() or "(tanpa output)")
        w._event(job.id, "deploy", {"ok": ok})
        if ok:
            w._say(story_id, job.id, f"Deploy selesai:\n```\n{tail}\n```")
            return
        try:
            st = w.taiga.story(story_id)
            tags = sorted(set(tag_names(st)) | {HUMAN_TAG})
            w.taiga.update_story(st["id"], version=st["version"], tags=tags)
        except TaigaError as e:
            log.warning("could not tag story %s after a failed deploy: %s", story_id, e)
        w._say(story_id, job.id,
               f"Deploy gagal; merge tetap berlaku. Output:\n```\n{tail}\n```")

    def _deploy_ssh(self, cfg, command: str) -> tuple[bool, str]:
        w = self.w
        with w.sessions() as db:
            from ..store import AwakProject

            p = db.get(AwakProject, cfg.slug)
            key = config_store.key_row(db, p.ssh_key_id if p else None)
        if key is None or not (cfg.ssh_host and cfg.ssh_user):
            return False, "mesin SSH belum lengkap (host, user, atau kunci belum dibuat)."
        known_hosts = ssh.known_hosts_path(w.s, cfg.slug)
        known_hosts.parent.mkdir(parents=True, exist_ok=True)
        with ssh.key_file(w.s, key) as key_path:
            argv = ssh.ssh_base(key_path, known_hosts, cfg.ssh_port) + [
                f"{cfg.ssh_user}@{cfg.ssh_host}", command]
            env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
            code, out = w.command_runner(argv, env, DEPLOY_TIMEOUT)
            out = out.replace(str(key_path), "<key>")
        return code == 0, out
