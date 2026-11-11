"""Replay past requests through the classifier and score it against the PM."""

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import Session

from .baseline import BaselineItem
from .classify import LABELS, classify
from .llm import LLM, LLMError
from .pricing import RateCard
from .store import BacktestResult, BacktestRun, BaselineVersion, Contract

CAUGHT = ("cr_candidate", "needs_clarification")  # both stop work before it starts


class Metrics(BaseModel):
    total: int
    errors: int
    correct: int
    accuracy: float | None
    per_label: dict[str, dict[str, int]]
    confusion: dict[str, dict[str, int]]
    cr_recall: float | None
    false_cr_rate: float | None
    value_expected_idr: int
    value_predicted_idr: int
    value_caught_idr: int
    verdicts: dict[str, int]


def _ratio(n: int, d: int) -> float | None:
    return n / d if d else None


def predicted_label(r: BacktestResult) -> str | None:
    return (r.predicted or {}).get("label") if r.status == "ok" else None


def metrics(results: list[BacktestResult]) -> Metrics:
    confusion = {e: {p: 0 for p in (*LABELS, "error")} for e in LABELS}
    per_label = {l: {"expected": 0, "predicted": 0, "correct": 0} for l in LABELS}
    correct = errors = 0
    value_expected = value_predicted = value_caught = 0
    cr_total = cr_caught = base_total = base_false_cr = 0
    verdicts = {"right": 0, "wrong": 0, "pending": 0}
    for r in results:
        exp = r.expected.get("label")
        pred = predicted_label(r)
        verdicts[r.verdict or "pending"] += 1
        if r.status != "ok":
            errors += 1
        if exp in confusion:
            confusion[exp][pred or "error"] += 1
            per_label[exp]["expected"] += 1
        if pred in per_label:
            per_label[pred]["predicted"] += 1
        if pred is not None and pred == exp:
            correct += 1
            per_label[exp]["correct"] += 1
        exp_price = int(r.expected.get("price_idr") or 0)
        pred_price = int((r.predicted or {}).get("price_idr") or 0) if pred else 0
        if exp in CAUGHT:
            value_expected += exp_price
        if pred in CAUGHT:
            value_predicted += pred_price
        if exp == "cr_candidate":
            cr_total += 1
            if pred in CAUGHT:
                cr_caught += 1
                value_caught += exp_price
        if exp == "in_baseline":
            base_total += 1
            if pred == "cr_candidate":
                base_false_cr += 1
    return Metrics(
        total=len(results),
        errors=errors,
        correct=correct,
        accuracy=_ratio(correct, len(results)),
        per_label=per_label,
        confusion=confusion,
        cr_recall=_ratio(cr_caught, cr_total),
        false_cr_rate=_ratio(base_false_cr, base_total),
        value_expected_idr=value_expected,
        value_predicted_idr=value_predicted,
        value_caught_idr=value_caught,
        verdicts=verdicts,
    )


def run_backtest(
    session: Session,
    llm: LLM,
    contract: Contract,
    baseline: BaselineVersion,
    dataset: dict[str, Any],
    run: BacktestRun | None = None,
    dataset_name: str = "dataset",
) -> BacktestRun:
    """Classify every ticket; resumes a run by skipping tickets already done."""
    if run is None:
        run = BacktestRun(
            contract_id=contract.id,
            baseline_version_id=baseline.id,
            dataset_name=dataset_name,
        )
        session.add(run)
        session.commit()
    items = [BaselineItem.model_validate(i) for i in baseline.items]
    rc = RateCard.model_validate(contract.rate_card or dataset.get("rate_card") or {"per_day": {}})
    existing = {
        r.ticket_id: r
        for r in session.query(BacktestResult).filter_by(run_id=run.id)
    }
    for t in dataset.get("tickets", []):
        prior = existing.get(t["id"])
        if prior is not None and prior.status == "ok":
            continue
        row = prior or BacktestResult(
            run_id=run.id,
            ticket_id=t["id"],
            source=t.get("source", ""),
            date=t.get("date", ""),
            text=t["text"],
            expected=t.get("expected", {}),
        )
        try:
            row.predicted = classify(llm, t["text"], items, rc, contract.lang).model_dump()
            row.status = "ok"
        except LLMError as e:
            row.predicted = {"error": str(e), "raw": e.raw[:2000]}
            row.status = "error"
        session.add(row)
        session.commit()
    run.finished_at = datetime.now(UTC)
    session.commit()
    return run
