"""Is a request covered by the baseline, a Change Request, or unclear?"""

from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

from .baseline import BaselineItem
from .llm import LLM, LLMError
from .pricing import RateCard, price

Label = Literal["in_baseline", "cr_candidate", "needs_clarification"]
LABELS: tuple[str, ...] = ("in_baseline", "cr_candidate", "needs_clarification")


class Classification(BaseModel):
    label: Label
    reason: str
    clause: str = ""
    effort_days: dict[str, float] = Field(default_factory=dict)
    price_idr: int = 0
    question: str | None = None

    @field_validator("effort_days", mode="before")
    @classmethod
    def _effort(cls, v):
        if not v:
            return {}
        if not isinstance(v, dict):
            raise ValueError("effort_days must be an object of role: days")
        out = {}
        for role, days in v.items():
            if isinstance(days, str):
                days = days.replace(",", ".").split()[0] if days.strip() else 0
            out[str(role).strip().lower()] = float(days or 0)
        return out

    @field_validator("clause", "reason", mode="before")
    @classmethod
    def _text(cls, v):
        if isinstance(v, list):
            return "; ".join(map(str, v))
        return "" if v is None else str(v)


SYSTEM = {
    "id": """Anda delivery manager di vendor IT yang menjaga margin proyek. Tentukan apakah permintaan klien termasuk lingkup kontrak (baseline) atau Change Request (CR).
Label:
- "in_baseline": perbaikan bug/error atau gangguan pada fitur yang sudah tercantum di baseline, termasuk kewajiban garansi. Permintaan yang terdengar seperti fitur baru tetap in_baseline jika fitur itu sebenarnya sudah tercantum.
- "cr_candidate": perilaku, data, layar, job, integrasi, atau aturan baru yang tidak tercantum di baseline, walaupun klien menyebutnya "bug" atau "error".
- "needs_clarification": jawabannya bergantung pada detail yang tidak ditulis di kontrak (spesifikasi tidak ada); sebutkan pertanyaan yang perlu diajukan ke klien di "question".
Untuk cr_candidate dan needs_clarification, estimasikan effort dalam hari-orang per peran memakai peran yang tersedia saja, dengan kelipatan 0,25 hari. Untuk in_baseline, effort_days kosong.
"clause" berisi ref baseline (misalnya "B7") dan kutipan singkat yang menjadi dasar keputusan.
Balas satu objek JSON: {"label", "reason", "clause", "effort_days": {peran: hari}, "question"}. "reason" satu sampai dua kalimat dalam bahasa Indonesia.""",
    "en": """You are a delivery manager at an IT vendor protecting project margin. Decide whether a client request is covered by the contract baseline or is a Change Request (CR).
Labels:
- "in_baseline": fixing a bug, error or outage in a feature the baseline lists, including warranty obligations. A request that sounds new is still in_baseline if the feature is already listed.
- "cr_candidate": new behaviour, data, screens, jobs, integrations or rules the baseline does not list, even if the client calls it a "bug".
- "needs_clarification": the answer depends on detail the contract does not specify; put the question to ask the client in "question".
For cr_candidate and needs_clarification, estimate effort in person-days per role using only the roles given, in steps of 0.25 days. For in_baseline, leave effort_days empty.
"clause" is the baseline ref (e.g. "B7") and a short quote the decision rests on.
Reply with one JSON object: {"label", "reason", "clause", "effort_days": {role: days}, "question"}. "reason" is one or two sentences in English.""",
}


def baseline_prompt(baseline: list[BaselineItem]) -> str:
    lines = []
    for b in baseline:
        clauses = "; ".join(b.clauses)
        lines.append(f"{b.ref} [{b.kind}] {b.title} — {b.description} ({clauses})".strip())
    return "\n".join(lines)


def classify(
    llm: LLM,
    ticket_text: str,
    baseline: list[BaselineItem],
    rc: RateCard,
    lang: str = "id",
) -> Classification:
    roles = ", ".join(rc.per_day)
    user = (
        f"BASELINE:\n{baseline_prompt(baseline)}\n\n"
        f"PERAN / ROLES: {roles}\n\n"
        f"PERMINTAAN / REQUEST:\n{ticket_text}"
    )
    reply = llm.json("classify", SYSTEM.get(lang, SYSTEM["id"]), user)
    reply.pop("price_idr", None)  # the rate card prices it, never the model
    try:
        c = Classification.model_validate(reply)
    except ValidationError as e:
        raise LLMError(f"invalid classification: {e}", str(reply)) from e
    if c.label == "in_baseline":
        c.effort_days = {}
    c.effort_days = {r: float(d) for r, d in c.effort_days.items() if d}
    try:
        c.price_idr = price(c.effort_days, rc)
    except KeyError as e:
        raise LLMError(f"invalid classification: {e}", str(reply)) from e
    return c
