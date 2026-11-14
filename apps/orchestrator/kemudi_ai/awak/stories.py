"""Story text <-> acceptance criteria, and the prompts that use them."""

import re

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


def code_task(workspace: str, ref: int, subject: str, description: str,
              feedback: str = "", siblings: list[str] | None = None) -> str:
    parts = [
        f"Workspace: {workspace}",
        f"User story #{ref}: {subject}",
        "",
        description.strip(),
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
    if feedback:
        parts += [
            "",
            "This is a rework attempt. Your previous commit(s) are on this branch. "
            "Fix these problems found by checks or review:",
            feedback.strip(),
        ]
    return "\n".join(parts)


def qa_task(workspace: str, ref: int, subject: str, criteria_list: list[str],
            project_slug: str, feedback: str = "", app_dir: str | None = None,
            app_dirs: list[str] | None = None) -> str:
    """`app_dirs`: QA runs against the project's runbook services (not Kemudi's
    own app): no login, no QA project, a dev server that compiles on first hit."""
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
            "The browser starts logged out, and there is no QA project slug and no "
            "KEMUDI_QA_TOKEN: ignore those parts of your instructions.",
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
