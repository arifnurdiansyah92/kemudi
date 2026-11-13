"""In-memory doubles for the Awak loop: Taiga, the agent and the runner."""

import subprocess
from pathlib import Path

from kemudi_ai.awak.taiga import Project, TaigaError, tag_names

PNG = bytes([0x89]) + b"PNG" + bytes([13, 10, 26, 10]) + b"0" * 32
STATUSES = {"new": 1, "ready": 2, "in-progress": 3, "ready-for-test": 4, "done": 5}


class FakeTaiga:
    def __init__(self, username="awak"):
        self.username = username
        self.me = {"id": 99, "username": username}
        self.stories_by_id: dict[int, dict] = {}
        self.comments_by_id: dict[int, list[dict]] = {}
        self.attachments: list[tuple[int, str]] = []
        self.logins = 0

    def login(self):
        self.logins += 1
        return "qa-token"

    def project(self, slug):
        return Project(id=7, slug=slug, statuses=dict(STATUSES),
                       status_names={v: k for k, v in STATUSES.items()})

    def add(self, sid, ref, subject, description, status="ready", tags=("agent-ready",)):
        self.stories_by_id[sid] = {
            "id": sid, "ref": ref, "subject": subject, "description": description,
            "status": STATUSES[status], "tags": [[t, None] for t in tags],
            "version": 1, "is_blocked": False, "owner": 5, "assigned_to": None,
        }
        self.comments_by_id[sid] = []
        return self.stories_by_id[sid]

    def stories(self, project_id, status_id, tag):
        return [dict(s) for s in self.stories_by_id.values()
                if s["status"] == status_id and tag in tag_names(s)]

    def story(self, sid):
        return dict(self.stories_by_id[sid])

    def comments(self, sid):
        return list(self.comments_by_id[sid])

    def create_story(self, project_id, **fields):
        sid = max(self.stories_by_id, default=0) + 1
        st = self.add(sid, sid + 100, fields["subject"], fields.get("description", ""),
                      tags=fields.get("tags") or [])
        st["status"] = fields["status"]
        return dict(st)

    def update_story(self, sid, **fields):
        st = self.stories_by_id[sid]
        version = fields.pop("version", st["version"])
        if version != st["version"]:
            raise TaigaError("HTTP 400 version conflict")
        comment = fields.pop("comment", None)
        if comment:
            self.comments_by_id[sid].append({"user": {"username": self.username},
                                             "comment": comment})
        if "tags" in fields:
            fields["tags"] = [[t, None] for t in fields["tags"]]
        st.update(fields)
        st["version"] += 1
        return dict(st)

    def comment(self, sid, text):
        return self.update_story(sid, comment=text)

    def attach(self, project_id, sid, path, name):
        self.attachments.append((sid, name))
        return {"id": len(self.attachments)}

    # helpers for tests
    def human_comment(self, sid, text):
        self.comments_by_id[sid].append({"user": {"username": "pm"}, "comment": text})

    def status_of(self, sid):
        return {v: k for k, v in STATUSES.items()}[self.stories_by_id[sid]["status"]]

    def texts(self, sid):
        return [c["comment"] for c in self.comments_by_id[sid]]


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


class FakeAgent:
    """Coding runs call `code(workdir, n)`; QA runs write nothing."""

    def __init__(self, code=None, fail_with=None):
        self.code = code or (lambda workdir, n: commit_file(workdir, f"feature{n}.txt", "x"))
        self.fail_with = fail_with or []
        self.calls: list[tuple[str, str]] = []
        self.runs: list[dict] = []

    def run(self, purpose, model, system, task):
        self.calls.append((purpose, task))
        self.runs.append({"purpose": purpose, "model": model, "system": system, "task": task})
        if self.fail_with:
            err = self.fail_with.pop(0)
            if err:
                raise err
        if purpose == "awak.code":
            workdir = task.splitlines()[0].removeprefix("Workspace: ").strip()
            n = sum(1 for p, _ in self.calls if p == "awak.code")
            self.code(Path(workdir), n)
            return "changed things", 10.0
        if purpose == "awak.qa":
            workdir = Path(task.splitlines()[0].removeprefix("Workspace: ").strip())
            spec = workdir / ".qa" / "spec" / "story.spec.ts"
            spec.parent.mkdir(parents=True, exist_ok=True)
            spec.write_text("test('AC1: thing', () => {})")
        return "spec written", 5.0


def commit_file(workdir: Path, name: str, content: str):
    (workdir / name).write_text(content)
    git(workdir, "add", "-A")
    git(workdir, "commit", "-m", f"add {name}")


class FakeRunner:
    """`qa` entries are reports, or "pass"/"fail" to build one with real PNGs."""

    def __init__(self, workspace: Path, gates=None, qa=None, n_criteria=2, deploy=None):
        self.workspace = Path(workspace)
        self.gates = list(gates or [])
        self.qa = list(qa or [])
        self.n = n_criteria
        self.deploy = list(deploy or [])
        self.calls: list[str] = []
        self.payloads: list[tuple[str, dict]] = []

    def call(self, op, **payload):
        self.calls.append(op)
        self.payloads.append((op, payload))
        if op == "deploy" and self.deploy:
            return self.deploy.pop(0)
        if op == "gates":
            return self.gates.pop(0) if self.gates else {"gates": [{"name": "tsc", "ok": True}]}
        if op == "qa":
            entry = self.qa.pop(0)
            if isinstance(entry, str):
                shots = []
                qa = self.workspace / payload["job"] / ".qa" / "results"
                qa.mkdir(parents=True, exist_ok=True)
                for i in range(1, self.n + 1):
                    f = qa / f"ac{i}.png"
                    f.write_bytes(PNG)
                    shots.append(str(f))
                status = "passed" if entry == "pass" else "failed"
                return qa_report([status] * self.n, shots)
            return entry
        return {"ok": True}


def qa_report(statuses: list[str], shots: list[str] | None = None, runs=2):
    tests = []
    for i, s in enumerate(statuses, 1):
        tests.append({"title": f"AC{i}: thing", "status": s,
                      "error": "" if s == "passed" else "expected visible",
                      "screenshots": [shots[i - 1]] if shots else []})
    return {"runs": [{"tests": [dict(t) for t in tests]} for _ in range(runs)]}
