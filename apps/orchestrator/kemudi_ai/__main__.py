"""CLI: python -m kemudi_ai <extract|baseline|approve|backtest|intake|awak-tick> ..."""

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from .backtest import metrics, run_backtest
from .baseline import draft_baseline
from .config import get_settings
from .documents import extract_sections
from .llm import HermesLLM
from .store import BacktestResult, BaselineVersion, Contract, make_session, record_decision


def _fmt(v: float | None) -> str:
    return "—" if v is None else f"{v:.0%}"


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(prog="kemudi_ai")
    sub = p.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("extract")
    e.add_argument("file")
    b = sub.add_parser("baseline")
    b.add_argument("project")
    b.add_argument("file")
    b.add_argument("--lang", default="id")
    b.add_argument("--rate-card", help="JSON file with {per_day: {...}}; or a backtest dataset")
    a = sub.add_parser("approve")
    a.add_argument("project")
    a.add_argument("--by", required=True)
    t = sub.add_parser("backtest")
    t.add_argument("project")
    t.add_argument("dataset")
    i = sub.add_parser("intake", help="turn text or a document into agent-ready stories")
    i.add_argument("project")
    i.add_argument("text", nargs="?", default="")
    i.add_argument("--file")
    i.add_argument("--lang", default="id")
    w = sub.add_parser("awak-tick", help="process at most one story, then exit")
    w.add_argument("--forever", action="store_true")
    args = p.parse_args(argv)

    if args.cmd == "extract":
        path = Path(args.file)
        for s in extract_sections(path.name, path.read_bytes()):
            print(f"[{s.ref}] {s.title}\n{s.text}\n")
        return 0

    settings = get_settings()
    S = make_session(settings.ai_db_url)
    llm = HermesLLM(settings, S)

    if args.cmd == "intake":
        from .awak.intake import create_stories, draft_stories
        from .awak.taiga import Taiga
        from .documents import extract_text

        body = args.text
        if args.file:
            path = Path(args.file)
            body += "\n\n" + extract_text(path.name, path.read_bytes())
        drafts = draft_stories(llm, body, args.lang)
        bot = Taiga(settings.taiga_api_url, settings.awak_username, settings.awak_password)
        for c in create_stories(bot, args.project, drafts):
            state = "Ready" if c["ready"] else f"New ({c['reason']})"
            print(f"#{c['ref']:<5} {state:<12} {c['subject']}")
        return 0

    if args.cmd == "awak-tick":
        from .awak.service import build_worker

        worker = build_worker(settings, S)
        if args.forever:
            worker.run_forever()
            return 0
        worker.recover()
        print("worked" if worker.tick() else "nothing to do")
        return 0
    with S() as s:
        if args.cmd == "baseline":
            path = Path(args.file)
            sections = extract_sections(path.name, path.read_bytes())
            rc = {}
            if args.rate_card:
                rc = json.loads(Path(args.rate_card).read_text(encoding="utf-8"))
                rc = rc.get("rate_card", rc)
            c = s.query(Contract).filter_by(project_slug=args.project).one_or_none()
            if c is None:
                c = Contract(project_slug=args.project, filename=path.name)
                s.add(c)
            c.filename, c.lang, c.rate_card = path.name, args.lang, rc or c.rate_card
            c.sections = [x.model_dump() for x in sections]
            s.commit()
            items = draft_baseline(llm, sections, args.lang)
            draft = s.query(BaselineVersion).filter_by(contract_id=c.id, status="draft").one_or_none()
            if draft is None:
                draft = BaselineVersion(contract_id=c.id)
                s.add(draft)
            draft.items = [i.model_dump() for i in items]
            s.commit()
            for i in items:
                print(f"{i.ref:>4} {i.kind:<10} {i.title}  ({'; '.join(i.clauses)})")
            return 0

        c = s.query(Contract).filter_by(project_slug=args.project).one()
        if args.cmd == "approve":
            draft = s.query(BaselineVersion).filter_by(contract_id=c.id, status="draft").one()
            last = max([v.number for v in s.query(BaselineVersion).filter_by(contract_id=c.id)] or [0])
            draft.status, draft.number = "approved", last + 1
            draft.approved_by, draft.approved_at = args.by, datetime.now(UTC)
            s.commit()
            record_decision(s, args.by, "approve_baseline", args.project, {"version": draft.number})
            print(f"baseline v{draft.number} approved by {args.by}")
            return 0

        if args.cmd == "backtest":
            baseline = (
                s.query(BaselineVersion)
                .filter_by(contract_id=c.id, status="approved")
                .order_by(BaselineVersion.number.desc())
                .first()
            )
            dataset = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
            if not c.rate_card and dataset.get("rate_card"):
                c.rate_card = dataset["rate_card"]
                s.commit()
            run = run_backtest(s, llm, c, baseline, dataset, dataset_name=Path(args.dataset).name)
            results = s.query(BacktestResult).filter_by(run_id=run.id).all()
            for r in results:
                pred = (r.predicted or {}).get("label", "ERROR")
                mark = "ok " if pred == r.expected.get("label") else "XX "
                print(f"{mark}{r.ticket_id:<4} expected={r.expected.get('label'):<20} predicted={pred:<20} "
                      f"Rp{(r.predicted or {}).get('price_idr', 0):>12,}")
            m = metrics(results)
            print(f"\nrun {run.id}: accuracy {_fmt(m.accuracy)} ({m.correct}/{m.total}), errors {m.errors}")
            print(f"CR caught {_fmt(m.cr_recall)}, false CR {_fmt(m.false_cr_rate)}")
            print(f"value: PM Rp{m.value_expected_idr:,} | AI Rp{m.value_predicted_idr:,} | caught Rp{m.value_caught_idr:,}")
            print(json.dumps(m.confusion, indent=1))
            return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
