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
              feedback: str = "") -> str:
    parts = [
        f"Workspace: {workspace}",
        f"User story #{ref}: {subject}",
        "",
        description.strip(),
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
            project_slug: str, feedback: str = "", app_dir: str | None = None) -> str:
    numbered = "\n".join(f"AC{i}: {c}" for i, c in enumerate(criteria_list, 1))
    parts = [
        f"Workspace: {workspace}",
        f"QA project slug: {project_slug}",
    ]
    if app_dir is not None:
        parts.append(f"App directory: {app_dir or '(repository root)'}")
    parts += [
        f"User story #{ref}: {subject}",
        "",
        "Acceptance criteria:",
        numbered,
    ]
    if feedback:
        parts += ["", "Your previous spec could not run. Fix it:", feedback.strip()]
    return "\n".join(parts)
