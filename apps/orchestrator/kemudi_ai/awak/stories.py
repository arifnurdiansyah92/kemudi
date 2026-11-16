"""Story text <-> acceptance criteria, and the prompts that use them."""

import json
import re
from dataclasses import dataclass

AC_HEADING = "Acceptance criteria"
_AC_LINE = re.compile(r"^\s*[-*]\s*(?:\[[ xX]\]\s*)?(.+?)\s*$")


def format_description(description: str, criteria: list[str]) -> str:
    lines = [description.strip(), "", f"## {AC_HEADING}", ""]
    lines += [f"- {c.strip()}" for c in criteria]
    return "\n".join(lines).strip() + "\n"


def criteria(description: str) -> list[str]:
    """Bullet lines under an 'Acceptance criteria' heading (any level)."""
    out: list[str] = []
    inside = False
    for line in (description or "").splitlines():
        stripped = line.strip()
        is_bullet = stripped[:2] in ("- ", "* ")
        named = (AC_HEADING.lower() in stripped.lower() or "kriteria" in stripped.lower())
        if (stripped.startswith("#") or (stripped.endswith(":") and len(stripped) < 60)
                or (named and not is_bullet and len(stripped) < 60)):
            inside = AC_HEADING.lower() in stripped.lower() or "kriteria" in stripped.lower()
            continue
        if inside:
            m = _AC_LINE.match(line)
            if m:
                out.append(m.group(1))
    return out


# The coding and QA prompts live in prompts.py (layered); these names stay for old imports.
from .prompts import CODE_SYSTEM, QA_SYSTEM  # noqa: E402,F401

INTAKE_SYSTEM = {
    "id": """Anda product owner untuk Kemudi, aplikasi manajemen proyek (fork Taiga) dengan frontend React di apps/web dan backend Django di services/kemudi-back. Pecah kebutuhan yang diberikan menjadi user story kecil yang masing-masing bisa dikerjakan dan diuji dalam satu sesi.
Aturan:
- Tiap story: "subject" (kalimat perintah singkat), "description" (konteks 1–3 kalimat), "criteria" (1–4 kriteria penerimaan yang bisa diuji lewat UI atau API), dan "area": "web" jika cukup mengubah apps/web, "backend" jika perlu mengubah backend, "both" jika keduanya.
- Jangan menambah fitur yang tidak diminta.
Balas satu objek JSON: {"stories": [{"subject", "description", "criteria", "area"}]}.""",
    "en": """You are the product owner for Kemudi, a project management app (a Taiga fork) with a React frontend in apps/web and a Django backend in services/kemudi-back. Split the given requirements into small user stories, each doable and testable in one session.
Rules:
- Each story: "subject" (short imperative), "description" (1–3 sentences of context), "criteria" (1–4 acceptance criteria testable through the UI or API), and "area": "web" if apps/web alone is enough, "backend" if the backend must change, "both" if both.
- Do not add features nobody asked for.
Reply with one JSON object: {"stories": [{"subject", "description", "criteria", "area"}]}.""",
}


WORK_METHOD = """How to work:
1. Read the code the story touches (routes, components, API, tests) before changing anything.
2. List the acceptance criteria for yourself and decide how each one will be met.
3. Implement, then run the repo's checks on what you changed and fix what they report.
4. Go through the acceptance criteria one by one against your change before you finish.
In your report, say for each acceptance criterion how your change meets it."""


def code_task(workspace: str, ref: int, subject: str, description: str,
              feedback: str = "", siblings: list[str] | None = None,
              unavailable: list[str] | None = None, previous_report: str = "",
              fix_round: bool = False) -> str:
    """`fix_round`: a further run inside the same attempt (the checks or the
    review found problems in the run just before); `previous_report` is what
    the agent reported last time, so it does not start from nothing."""
    parts = [
        f"Workspace: {workspace}",
        f"User story #{ref}: {subject}",
        "",
        description.strip(),
        "",
        WORK_METHOD,
    ]
    if siblings:
        parts += [
            "",
            "The project's other repositories are checked out next to the workspace, "
            "at their default branch, as read-only context (contracts, shared types, "
            "how they call this repo). Changes there are discarded; commit only in the "
            "workspace:",
            *[f"- {s}" for s in siblings],
        ]
    if unavailable:
        parts += [
            "",
            "These repositories of the project could not be fetched and are not checked "
            "out; do not rely on reading them: " + ", ".join(unavailable),
        ]
    if feedback:
        lead = ("This is a fix round: you already worked on this story and your commit(s) "
                "are on this branch. Fix these problems, found by the checks or by a "
                "reviewer, and commit again:" if fix_round else
                "This is a rework attempt. Your previous commit(s) are on this branch. "
                "Fix these problems found by checks or review:")
        parts += ["", lead, feedback.strip()]
    if previous_report.strip():
        parts += ["", "Your report from the previous run (what you already did):",
                  previous_report.strip()[-3000:]]
    return "\n".join(parts)


def review_task(workspace: str, ref: int, subject: str, description: str, base: str) -> str:
    return "\n".join([
        f"Workspace: {workspace}",
        f"Review the change for user story #{ref}: {subject}",
        "",
        description.strip(),
        "",
        f"The change is `git diff {base}...HEAD` (run `git log --oneline {base}..HEAD` "
        "for its commits). Do not modify anything. End with the JSON verdict.",
    ])


@dataclass
class Review:
    verdict: str  # "approve" | "changes" | "unparsed"
    issues: list[dict]

    def blocking(self) -> bool:
        return self.verdict == "changes" and bool(self.issues)

    def feedback(self) -> str:
        return "\n".join(
            f"- {i['file'] or '(general)'}: {i['problem']}"
            + (f" Fix: {i['fix']}" if i["fix"] else "") for i in self.issues)


def parse_review(text: str) -> Review:
    """The reviewer's last JSON verdict. Anything unreadable counts as no
    verdict (the change goes on to QA), never as a block."""
    text = text or ""
    decoder = json.JSONDecoder()
    for m in reversed(list(re.finditer(r"\{", text))):
        try:
            data, _ = decoder.raw_decode(text[m.start():])
        except ValueError:
            continue
        if not isinstance(data, dict) or "verdict" not in data:
            continue
        verdict = str(data.get("verdict") or "").lower()
        raw = data.get("issues") if isinstance(data.get("issues"), list) else []
        issues = [{k: str(i.get(k) or "")[:600] for k in ("file", "problem", "fix")}
                  for i in raw if isinstance(i, dict) and i.get("problem")][:10]
        if verdict in ("approve", "changes"):
            return Review(verdict, issues)
    return Review("unparsed", [])


def qa_task(workspace: str, ref: int, subject: str, criteria_list: list[str],
            project_slug: str, feedback: str = "", app_dir: str | None = None,
            app_dirs: list[str] | None = None, env_names: list[str] | None = None,
            login_path: str | None = None, backing: list[str] | None = None) -> str:
    """`app_dirs`: QA runs against the project's runbook services (not Kemudi's
    own app): no QA project, a dev server that compiles on first hit, logged in
    through `login_path` when the runbook has a login. `env_names`: the vault
    values the spec may read (names only, never a value)."""
    numbered = "\n".join(f"AC{i}: {c}" for i, c in enumerate(criteria_list, 1))
    parts = [f"Workspace: {workspace}"]
    if app_dirs is None:
        parts.append(f"QA project slug: {project_slug}")
    if app_dir is not None:
        parts.append(f"App directory: {app_dir or '(repository root)'}")
    if app_dirs is not None:
        parts += [
            "App directories (relative to the story folder, the workspace's parent): "
            + ", ".join(app_dirs),
            "",
            "This project's app is started by the runner from the project's runbook; the "
            "configured baseURL (http://localhost:<port>) points at it. Use relative URLs. "
            "There is no QA project slug and no KEMUDI_QA_TOKEN: ignore those parts of your "
            "instructions.",
            (f"The browser starts logged in: before the tests the runner signs in once "
             f"through the login form at {login_path} with the project's QA account and "
             "every test starts with that session. Do not log out; to test the login page "
             "itself, use a fresh browser context." if login_path else
             "The browser starts logged out."),
            ("Your spec may read these environment variables, set by the runner from the "
             "project's test values: " + ", ".join(f"process.env.{n}" for n in env_names)
             + ". Use them only through process.env; never print, log, assert on or "
               "hard-code their values." if env_names else
             "The spec gets no project environment variables."),
            *([f"Backing services ({', '.join(backing)}) are started fresh for each QA run "
               "and shared by both spec runs (one database)."] if backing else []),
            "Besides the spec, write the paths your tests visit, one per line (at most 10, "
            "e.g. `/` or `/campaigns`), to <workspace>/.qa/routes.txt. The runner loads each "
            "once before the tests, because the dev server compiles a page on its first hit.",
            "The spec runs twice in a row against the same running app and the same data: "
            "create what you need with unique names and never assume an empty state.",
            "",
        ]
    parts += [
        f"User story #{ref}: {subject}",
        "",
        "Acceptance criteria:",
        numbered,
    ]
    if feedback:
        parts += ["", "Your previous spec could not run. Fix it:", feedback.strip()]
    return "\n".join(parts)
