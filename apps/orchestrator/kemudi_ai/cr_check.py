"""On-demand CR check: one Taiga story or issue against the approved baseline.

The AI only suggests. Every check is kept with the model that made it and who
asked; a project admin's verdict (agree / disagree, with an optional corrected
label) is stored beside the suggestion and never overwrites it.
"""

import csv
import io
import re
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import HTTPException

from .auth import TaigaUser, _client
from .baseline import BaselineItem
from .classify import classify
from .config import Settings
from .llm import LLM
from .pricing import RateCard
from .store import BaselineVersion, Contract, CrCheck

TicketKind = Literal["userstory", "issue"]

_PATHS = {"userstory": "/userstories/by_ref", "issue": "/issues/by_ref"}
_REF = re.compile(r"\bB\d+\b")
# Roles to estimate with when the project has no rate card yet: effort still
# comes back in person-days, priced at zero.
_NO_RATE_CARD = {"developer": 0}
MAX_TEXT = 8000
BOM = chr(0xFEFF)  # lets Excel read the UTF-8 CSV correctly


def fetch_ticket(settings: Settings, user: TaigaUser, slug: str, kind: str, ref: int) -> dict:
    """Subject and description of a story or issue, read as the caller, so
    Taiga's own permissions decide what they may see."""
    with _client(settings, user.token) as c:
        r = c.get(_PATHS[kind], params={"ref": ref, "project__slug": slug})
    if r.status_code == 404 or r.status_code == 403:
        raise HTTPException(404, f"no {kind} #{ref} in this project")
    if r.status_code != 200:
        raise HTTPException(502, f"Taiga answered HTTP {r.status_code}")
    data = r.json()
    return {"subject": data.get("subject") or "", "description": data.get("description") or ""}


def ticket_text(subject: str, description: str) -> str:
    text = subject.strip()
    if description.strip():
        text += "\n\n" + description.strip()
    return text[:MAX_TEXT]


def cited_items(clause: str, items: list[BaselineItem]) -> list[dict[str, Any]]:
    """The baseline items a clause names (B1, B7, ...), in order, once each."""
    by_ref = {i.ref: i for i in items}
    out, seen = [], set()
    for ref in _REF.findall(clause or ""):
        if ref in by_ref and ref not in seen:
            seen.add(ref)
            i = by_ref[ref]
            out.append({"ref": i.ref, "title": i.title, "clauses": i.clauses})
    return out


def latest_baseline(db, slug: str) -> tuple[Contract, BaselineVersion]:
    c = db.query(Contract).filter_by(project_slug=slug).one_or_none()
    b = None
    if c is not None:
        b = (
            db.query(BaselineVersion)
            .filter_by(contract_id=c.id, status="approved")
            .order_by(BaselineVersion.number.desc())
            .first()
        )
    if c is None or b is None:
        raise HTTPException(
            409,
            "this project has no approved contract baseline: upload the contract "
            "and approve its baseline on the Contract page first",
        )
    return c, b


def run_check(
    db,
    llm: LLM,
    model: str,
    contract: Contract,
    baseline: BaselineVersion,
    *,
    slug: str,
    kind: str,
    ref: int,
    subject: str,
    text: str,
    checked_by: str,
) -> CrCheck:
    items = [BaselineItem.model_validate(i) for i in baseline.items]
    per_day = (contract.rate_card or {}).get("per_day") or _NO_RATE_CARD
    rc = RateCard(per_day=per_day)
    result = classify(llm, text, items, rc, contract.lang)
    row = CrCheck(
        project_slug=slug,
        ticket_kind=kind,
        ticket_ref=ref,
        subject=subject[:500],
        text=text,
        baseline_version_id=baseline.id,
        baseline_number=baseline.number,
        label=result.label,
        reasoning=result.reason,
        clause=result.clause,
        cited=cited_items(result.clause, items),
        question=result.question,
        effort_days=result.effort_days,
        price_idr=result.price_idr,
        model=model,
        checked_by=checked_by,
    )
    db.add(row)
    db.commit()
    return row


def serialize(r: CrCheck, show_prices: bool) -> dict[str, Any]:
    return {
        "id": r.id,
        "ticket_kind": r.ticket_kind,
        "ticket_ref": r.ticket_ref,
        "subject": r.subject,
        "baseline_number": r.baseline_number,
        "label": r.label,
        "reasoning": r.reasoning,
        "clause": r.clause,
        "cited": r.cited,
        "question": r.question,
        "effort_days": r.effort_days,
        "effort_total_days": total_days(r),
        # Hidden, not zeroed: the client can't tell a hidden price from none.
        "price_idr": r.price_idr if show_prices else None,
        "model": r.model,
        "checked_by": r.checked_by,
        "checked_at": r.checked_at,
        "verdict": r.verdict,
        "corrected_label": r.corrected_label,
        "verdict_note": r.verdict_note,
        "decided_by": r.decided_by,
        "decided_at": r.decided_at,
    }


def total_days(r: CrCheck) -> float:
    return round(sum(float(d) for d in (r.effort_days or {}).values()), 2)


def decide(r: CrCheck, verdict: str, corrected_label: str | None, note: str, actor: str) -> None:
    r.verdict = verdict
    r.corrected_label = corrected_label if verdict == "disagree" else None
    r.verdict_note = note
    r.decided_by = actor
    r.decided_at = datetime.now(UTC)


CSV_COLUMNS = [
    "ref", "kind", "subject", "label", "reasoning", "clauses", "effort_days",
    "effort_breakdown", "price_idr", "verdict", "corrected_label", "note",
    "decided_by", "decided_at", "checked_by", "checked_at", "model",
]


def _cell(v: Any) -> str:
    """Plain text a spreadsheet won't run as a formula."""
    s = "" if v is None else str(v)
    if s[:1] in ("=", "+", "-", "@", "\t", "\r"):
        s = "'" + s
    return s


def _iso(d: datetime | None) -> str:
    return d.isoformat() if d else ""


def to_csv(rows: list[CrCheck], show_prices: bool) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(CSV_COLUMNS)
    for r in rows:
        clauses = r.clause or "; ".join(c["ref"] for c in r.cited or [])
        breakdown = ", ".join(f"{role} {days:g}" for role, days in (r.effort_days or {}).items())
        w.writerow([_cell(v) for v in (
            f"#{r.ticket_ref}", r.ticket_kind, r.subject, r.label, r.reasoning, clauses,
            f"{total_days(r):g}", breakdown, r.price_idr if show_prices else "",
            r.verdict or "", r.corrected_label or "", r.verdict_note,
            r.decided_by or "", _iso(r.decided_at), r.checked_by, _iso(r.checked_at), r.model,
        )])
    return buf.getvalue()
