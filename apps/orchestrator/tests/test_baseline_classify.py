import pytest

from kemudi_ai.baseline import BaselineItem, draft_baseline
from kemudi_ai.classify import classify
from kemudi_ai.documents import Section
from kemudi_ai.llm import LLMError
from kemudi_ai.pricing import RateCard, price

from .fakes import FakeLLM

RC = RateCard(per_day={"backend": 1_500_000, "frontend": 1_250_000, "qa": 1_000_000})
SECTIONS = [Section(ref="S1", title="RUANG LINGKUP", text="1 Payment")]
BASELINE = [
    BaselineItem(ref="B1", kind="epic", title="Payment", clauses=["S1: Payment"]),
]


def test_draft_validates_and_renumbers():
    llm = FakeLLM({"baseline": [{"items": [
        {"ref": "x", "kind": "epic", "title": "Payment", "clauses": ["S1"]},
        {"ref": "y", "kind": "story", "title": "VA", "clauses": ["S1"], "parent": "x"},
        {"ref": "z", "kind": "term", "title": "CR berbayar", "clauses": ["S9"]},
    ]}]})
    items = draft_baseline(llm, SECTIONS)
    assert [i.ref for i in items] == ["B1", "B2", "B3"]
    assert [i.kind for i in items] == ["epic", "story", "term"]
    assert items[1].parent == "B1"


def test_draft_rejects_items_without_clauses():
    llm = FakeLLM({"baseline": [{"items": [
        {"kind": "epic", "title": "A", "clauses": []},
        {"kind": "bogus", "title": "B", "clauses": ["S1"]},
        {"kind": "epic", "title": "C", "clauses": ["S1"]},
    ]}]})
    assert [i.title for i in draft_baseline(llm, SECTIONS)] == ["C"]


def test_price_sums_roles():
    assert price({"backend": 2, "qa": 0.5}, RC) == 3_500_000
    with pytest.raises(KeyError, match="designer"):
        price({"designer": 1}, RC)


def test_price_computed_not_trusted():
    llm = FakeLLM({"classify": [{
        "label": "cr_candidate", "reason": "fitur baru", "clause": "B1",
        "effort_days": {"backend": 2, "qa": 0.5}, "price_idr": 1,
    }]})
    c = classify(llm, "tolong tambah export excel", BASELINE, RC)
    assert c.price_idr == 3_500_000


def test_in_baseline_clears_effort():
    llm = FakeLLM({"classify": [{
        "label": "in_baseline", "reason": "bug", "clause": "B1",
        "effort_days": {"backend": 1},
    }]})
    c = classify(llm, "VA tidak terverifikasi", BASELINE, RC)
    assert (c.effort_days, c.price_idr) == ({}, 0)


def test_invalid_label_raises_llmerror():
    llm = FakeLLM({"classify": [{"label": "maybe", "reason": "?"}]})
    with pytest.raises(LLMError):
        classify(llm, "x", BASELINE, RC)


def test_unknown_role_in_effort_maps_to_error():
    llm = FakeLLM({"classify": [{
        "label": "cr_candidate", "reason": "r", "effort_days": {"designer": 1},
    }]})
    with pytest.raises(LLMError, match="designer"):
        classify(llm, "x", BASELINE, RC)


def test_draft_accepts_strings_for_lists_and_prices():
    llm = FakeLLM({"baseline": [{"items": [
        {"kind": "term", "title": "Garansi", "acceptance": "Garansi 1 tahun.",
         "clauses": "S7: Masa Garansi", "price_idr": "Rp 30.000.000"},
    ]}]})
    [item] = draft_baseline(llm, SECTIONS)
    assert item.acceptance == ["Garansi 1 tahun."]
    assert item.clauses == ["S7: Masa Garansi"]
    assert item.price_idr == 30_000_000
