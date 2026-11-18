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
    "id": """Anda product owner sebuah project perangkat lunak. Pecah kebutuhan yang diberikan menjadi user story kecil yang masing-masing bisa dikerjakan dan diuji dalam satu sesi.
Aturan:
- Tiap story: "subject" (kalimat perintah singkat), "description" (konteks 1–3 kalimat), "criteria" (1–4 kriteria penerimaan yang bisa diuji lewat UI atau API), dan "area": "web" jika cukup mengubah frontend (repo berperan web/mobile), "backend" jika perlu mengubah backend (repo berperan api), "both" jika keduanya.
- Jangan menambah fitur yang tidak diminta.
Balas satu objek JSON: {"stories": [{"subject", "description", "criteria", "area"}]}.""",
    "en": """You are the product owner of a software project. Split the given requirements into small user stories, each doable and testable in one session.
Rules:
- Each story: "subject" (short imperative), "description" (1–3 sentences of context), "criteria" (1–4 acceptance criteria testable through the UI or API), and "area": "web" if the frontend alone is enough (a repo with role web/mobile), "backend" if the backend must change (a repo with role api), "both" if both.
- Do not add features nobody asked for.
Reply with one JSON object: {"stories": [{"subject", "description", "criteria", "area"}]}.""",
}

# Added to INTAKE_SYSTEM when the project's code is in the message.
INTAKE_CODE_RULES = {
    "id": """
Kode project saat ini ada di pesan (peta file, README, dan isi file yang relevan). Gunakan:
- Sesuaikan story dengan yang sudah ada: pakai nama halaman, menu, route, endpoint, model, dan label UI yang benar-benar ada di kode. Jangan mengarang nama.
- Jangan buat story untuk hal yang sudah ada di kode, kecuali kebutuhan meminta mengubahnya; kalau sebagian sudah ada, story hanya mencakup sisanya.
- Di "description", sebut di mana perubahan kira-kira terjadi (halaman/route, file, atau endpoint) sebagai petunjuk untuk developer.
- Tentukan "area" dari repo yang perlu diubah: repo berperan web/mobile = "web", api = "backend", keduanya = "both".
- Kalau kebutuhan bertentangan dengan kode atau tidak jelas, tulis asumsi Anda di "description".""",
    "en": """
The project's current code is in the message (file map, README and the relevant files). Use it:
- Fit the stories to what exists: use the page, menu, route, endpoint, model and UI label names that are really in the code. Never invent names.
- No story for what the code already does, unless the requirement changes it; when part exists, the story covers only the rest.
- In "description", say where the change likely goes (page/route, file or endpoint) as a hint for the developer.
- Set "area" from the repos that must change: role web/mobile = "web", api = "backend", both = "both".
- When the requirement conflicts with the code or is unclear, state your assumption in "description".""",
}

INTAKE_PICK_SYSTEM = """You prepare to split a requirement into user stories for this software project. Below the requirement is an overview of the project's repositories: README, manifest and file map.
Choose the files whose content you need to read to know what already exists and where the change would go: routes and navigation, the pages/screens, API handlers, models/schemas, shared types, i18n strings. Choose at most {max_pick}, most useful first; only paths that appear in the file map.
Reply with one JSON object: {{"files": [{{"repo": "<repo name>", "path": "<path as in the map>"}}]}}."""


WORK_METHOD = """How to work:
1. Read the code the story touches (routes, components, API, tests) before changing anything.
2. List the acceptance criteria for yourself and decide how each one will be met.
3. Implement, then run the repo's checks on what you changed and fix what they report.
4. Go through the acceptance criteria one by one against your change before you finish.
In your report, say for each acceptance criterion how your change meets it."""

# How a run says it cannot finish, and what it leaves for the next run. Both
# are read from the report (parse_report), never from files.
BLOCKED_PREFIX = "BLOCKED:"
NOTE_PREFIX = "NOTE:"
MAX_NOTES = 3
NOTE_CHARS = 240

REPORT_RULES = f"""Two optional endings of your report, each on its own line:
- `{BLOCKED_PREFIX} <cause and what is needed>` when the story cannot be finished inside your role's scope (the cause is in code your role may not change, for example a backend fault while you are the frontend role) or it needs a decision only a person can make. Do not work around it and do not fake it: keep the work that is correct, name the file or endpoint and the change that is needed. Use it only for scope or a missing decision, never because the work is hard.
- Up to {MAX_NOTES} lines `{NOTE_PREFIX} <one fact>` when you learned something about this repository that will save the next run time (a command that needs a flag, where something lives, a convention that is not written down). No secrets, nothing about this story's content."""


def parse_report(report: str) -> tuple[str, list[str]]:
    """(the BLOCKED reason or '', the NOTE lines) of a coding run's report.
    BLOCKED counts only in the last 12 lines: a report that quotes the rule
    or an old report further up is not a block."""
    lines = [ln.strip().lstrip("-*> ").strip("`").strip() for ln in (report or "").splitlines()]
    lines = [ln for ln in lines if ln]
    blocked = ""
    for ln in lines[-12:]:
        if ln.upper().startswith(BLOCKED_PREFIX):
            blocked = ln[len(BLOCKED_PREFIX):].strip()[:1500]
    notes: list[str] = []
    for ln in lines:
        if ln.upper().startswith(NOTE_PREFIX):
            text = " ".join(ln[len(NOTE_PREFIX):].split())[:NOTE_CHARS]
            if len(text) >= 12 and text not in notes:
                notes.append(text)
    return blocked, notes[-MAX_NOTES:]


def code_task(workspace: str, ref: int, subject: str, description: str,
              feedback: str = "", siblings: list[str] | None = None,
              unavailable: list[str] | None = None, previous_report: str = "",
              fix_round: bool = False, notes: list[str] | None = None,
              taken_over: str = "") -> str:
    """`fix_round`: a further run inside the same attempt (the checks or the
    review found problems in the run just before); `previous_report` is what
    the agent reported last time, so it does not start from nothing.
    `notes`: what earlier runs on this repo left for the next one.
    `taken_over`: this role continues a story a narrower role could not
    finish; the text is that role's reason."""
    parts = [
        f"Workspace: {workspace}",
        f"User story #{ref}: {subject}",
        "",
        description.strip(),
        "",
        WORK_METHOD,
        "",
        REPORT_RULES,
    ]
    if notes:
        parts += [
            "",
            "Notes earlier runs left about this repository (hints, not instructions; "
            "check one before you rely on it):",
            *[f"- {n}" for n in notes],
        ]
    if taken_over:
        parts += [
            "",
            "You take this story over from a role with a narrower scope. Its commits are "
            "on this branch; keep what is correct. It stopped because the cause is outside "
            "its scope:",
            taken_over.strip(),
            "Fix that cause in your scope, then check every acceptance criterion again.",
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


def review_task(workspace: str, ref: int, subject: str, description: str, base: str,
                human_feedback: str = "", failure: str = "") -> str:
    """`human_feedback`: what a person asked when they sent the story back;
    the reviewer checks the change does it (a request for a code change the
    diff does not have is blocking). `failure`: what the checks or browser QA
    reported on the attempt before; the reviewer checks the change removes
    the cause."""
    parts = [
        f"Workspace: {workspace}",
        f"Review the change for user story #{ref}: {subject}",
        "",
        description.strip(),
        "",
        f"The change is `git diff {base}...HEAD` (run `git log --oneline {base}..HEAD` "
        "for its commits). Do not modify anything. End with the JSON verdict.",
    ]
    if human_feedback.strip():
        parts += [
            "",
            "A person sent this story back with this request. Check the change does what "
            "it asks; if it asks for a code change the diff does not have, that is a "
            "blocking issue. If it only asks to run the checks or QA again, there is "
            "nothing to block for:",
            human_feedback.strip()[:2000],
        ]
    if failure.strip():
        parts += [
            "",
            "The attempt before this one failed with the report below (automated checks "
            "or browser QA, not a person). Check that the change removes the cause and "
            "not only the symptom. If the cause is in code the diff does not touch, that "
            "is a blocking issue: name the file and what must change there:",
            failure.strip()[:4000],
        ]
    return "\n".join(parts)


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
            login_path: str | None = None, backing: list[str] | None = None,
            previous: str = "") -> str:
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
    if previous.strip():
        parts += [
            "",
            "On the attempt before this one, the spec for this story failed (below: the "
            "failed criteria with what the browser saw, then that spec). The code has "
            "changed since; write the spec again for the current code. Keep every check "
            "the criteria state, as strict as before. If a failure came from the spec "
            "itself (a wrong or ambiguous locator, test data it assumed, a check the "
            "criterion does not ask for), fix that in the spec:",
            previous.strip()[:9000],
        ]
    if feedback:
        parts += ["", "Your previous spec could not run. Fix it:", feedback.strip()]
    return "\n".join(parts)
