from kemudi_ai import store
from kemudi_ai.store import BaselineVersion, Contract, make_session


def test_roundtrip_contract_and_baseline():
    S = make_session("sqlite:///:memory:")
    with S() as s:
        c = Contract(project_slug="demo", filename="c.pdf", sections=[])
        s.add(c)
        s.flush()
        s.add(
            BaselineVersion(
                contract_id=c.id, items=[{"ref": "B1"}, {"ref": "B2"}]
            )
        )
        s.commit()
    with S() as s:
        b = s.query(BaselineVersion).one()
        assert [i["ref"] for i in b.items] == ["B1", "B2"]
        assert b.status == "draft"


def test_ai_calls_append_only():
    writers = [n for n in store.__all__ if n.startswith(("record_", "update_", "delete_"))]
    assert sorted(writers) == ["record_ai_call", "record_decision", "record_event"]
