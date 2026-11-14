"""Stage 1b on the merge path: run_in gates and the QA re-run with compose
services (kemudi-svc), on a real remote."""

from kemudi_ai.awak import runbook, vault
from kemudi_ai.store import AwakJob

from .conftest import SECRET_KEY
from .test_compose_qa import URL, FakeSvc, Runner, _run_in_spec, creds, parsed
from .test_merge import _advance_during_code, remote, repo  # noqa: F401 (fixtures)
from .test_merge import make as make_merge


# --- merge --------------------------------------------------------------------------------


def test_merge_regates_run_in_and_reruns_qa_against_compose(tmp_path, repo, remote):
    order: list[str] = []
    runner = Runner(tmp_path / "ws", order, qa=["pass", "pass"])
    w, taiga, sessions, _ = make_merge(tmp_path, repo, mode="auto", runner=runner,
                                       agent=_advance_during_code(tmp_path, remote),
                                       secret_key=SECRET_KEY)
    w.svc = FakeSvc(order)
    values = creds()
    with sessions() as db:
        runbook.save(db, "kemudi", parsed(_run_in_spec()), "pm")
        for k, val in values.items():
            vault.put(db, w.s, "kemudi", k, val, True, "pm")
    w.tick()
    with sessions() as db:
        job = db.query(AwakJob).one()
    assert job.merge_state == "merged", job.merge_error
    assert "QA ulang lulus" in taiga.texts(1)[-1]
    # story: gates (run_in) + QA; merge: gates (run_in) + QA re-run
    assert order.count("svc_up") == order.count("svc_down") == 4
    assert order.count("health") == 2 and order.count("qa") == 2
    reran = [b for op, b in runner.payloads if op == "qa"][-1]
    assert reran["external"] == {"api": URL} and reran["login"]["path"] == "/login"
    assert {p["project"] for p in w.svc.ops("svc_up")} == {"kemudi-us12"}


def test_merge_service_failure_fails_the_merge_with_the_reason(tmp_path, repo, remote):
    order: list[str] = []
    runner = Runner(tmp_path / "ws", order, qa=["pass", "pass"])
    w, taiga, sessions, _ = make_merge(tmp_path, repo, mode="auto", runner=runner,
                                       agent=_advance_during_code(tmp_path, remote),
                                       secret_key=SECRET_KEY)
    w.svc = FakeSvc(order)
    with sessions() as db:
        runbook.save(db, "kemudi", parsed(), "pm")
        for k, val in creds().items():
            vault.put(db, w.s, "kemudi", k, val, True, "pm")
    # the story's QA is healthy; the merge re-run's API is not
    runner.health = [{"ok": True}, {"ok": False, "error": "no 2xx/3xx answer"}]
    w.tick()
    with sessions() as db:
        job = db.query(AwakJob).one()
    assert job.merge_state == "failed" and "tidak sehat" in job.merge_error
    assert order.count("svc_up") == order.count("svc_down") == 2
