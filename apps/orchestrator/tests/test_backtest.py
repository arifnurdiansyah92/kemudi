from kemudi_ai.backtest import metrics, run_backtest
from kemudi_ai.llm import LLMError
from kemudi_ai.store import (
    BacktestResult,
    BacktestRun,
    BaselineVersion,
    Contract,
    make_session,
)

from .fakes import FakeLLM

RC = {"per_day": {"backend": 1_000_000}}
DATASET = {
    "rate_card": RC,
    "tickets": [
        {"id": "T1", "text": "bug VA", "expected": {"label": "in_baseline"}},
        {"id": "T2", "text": "fitur baru", "expected": {"label": "cr_candidate", "price_idr": 2_000_000}},
    ],
}
OK = {"label": "in_baseline", "reason": "bug", "clause": "B1"}
CR = {"label": "cr_candidate", "reason": "baru", "effort_days": {"backend": 2}}


def setup():
    S = make_session("sqlite:///:memory:")
    s = S()
    c = Contract(project_slug="p", filename="c.pdf", rate_card=RC)
    s.add(c)
    s.flush()
    b = BaselineVersion(
        contract_id=c.id, status="approved", number=1,
        items=[{"ref": "B1", "kind": "epic", "title": "Payment", "clauses": ["S1"]}],
    )
    s.add(b)
    s.commit()
    return s, c, b


def test_resume_skips_done():
    s, c, b = setup()
    first = FakeLLM({"classify": [OK, LLMError("down", "")]})
    run = run_backtest(s, first, c, b, DATASET)
    assert [r.status for r in s.query(BacktestResult).order_by(BacktestResult.id)] == ["ok", "error"]
    second = FakeLLM({"classify": [CR]})
    run_backtest(s, second, c, b, DATASET, run=run)
    assert len(second.calls) == 1
    rows = s.query(BacktestResult).filter_by(run_id=run.id).all()
    assert len(rows) == 2 and all(r.status == "ok" for r in rows)
    assert rows[1].predicted["price_idr"] == 2_000_000


def test_error_counts_wrong():
    s, c, b = setup()
    run = run_backtest(s, FakeLLM({"classify": [OK, LLMError("x", "raw")]}), c, b, DATASET)
    m = metrics(s.query(BacktestResult).filter_by(run_id=run.id).all())
    assert (m.correct, m.errors, m.accuracy) == (1, 1, 0.5)
    assert m.confusion["cr_candidate"]["error"] == 1


def test_metrics_empty_is_none():
    m = metrics([])
    assert m.accuracy is None and m.cr_recall is None and m.false_cr_rate is None


def r(exp, pred, price=0, verdict=None):
    return BacktestResult(
        ticket_id="x", text="", status="ok", verdict=verdict,
        expected={"label": exp, "price_idr": price},
        predicted={"label": pred, "price_idr": price},
    )


def test_cr_recall_counts_clarification_as_caught():
    m = metrics([
        r("cr_candidate", "needs_clarification", 3_000_000),
        r("cr_candidate", "in_baseline", 1_000_000),
        r("in_baseline", "cr_candidate", verdict="wrong"),
        r("in_baseline", "in_baseline", verdict="right"),
    ])
    assert m.cr_recall == 0.5
    assert m.false_cr_rate == 0.5
    assert m.value_caught_idr == 3_000_000
    assert m.value_expected_idr == 4_000_000
    assert m.verdicts == {"right": 1, "wrong": 1, "pending": 2}
