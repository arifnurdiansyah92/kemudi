"""The project's delivery data, as numbers.

Read from Taiga with the caller's own token (their permissions apply) and
from Awak's job table. `metrics()` is pure: the report's numbers come from
here, never from a model.
"""

import math
import statistics
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy.orm import Session

from ..store import AwakJob


class Source(Protocol):
    """What a run reads from Taiga."""

    def project(self, slug: str) -> dict: ...
    def stories(self, project_id: int) -> list[dict]: ...
    def milestones(self, project_id: int) -> list[dict]: ...
    def issues(self, project_id: int) -> list[dict]: ...


class TaigaSource:
    """Taiga as the caller (awak.taiga.Taiga.with_token: local stack only)."""

    def __init__(self, api_url: str, token: str, transport=None):
        from ..awak.taiga import Taiga

        self.t = Taiga.with_token(api_url, token, transport)

    def _list(self, url: str, project_id: int) -> list[dict]:
        data = self.t._req("GET", url, params={"project": project_id}).json()
        return data if isinstance(data, list) else []

    def project(self, slug: str) -> dict:
        return self.t.project_detail(slug)

    def stories(self, project_id: int) -> list[dict]:
        return self._list("/userstories", project_id)

    def milestones(self, project_id: int) -> list[dict]:
        return self._list("/milestones", project_id)

    def issues(self, project_id: int) -> list[dict]:
        return self._list("/issues", project_id)


def _dt(value) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        d = value
    else:
        try:
            d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def _status(item: dict) -> str:
    return str((item.get("status_extra_info") or {}).get("name") or "?")


def _who(item: dict) -> str:
    info = item.get("assigned_to_extra_info") or {}
    return str(info.get("full_name_display") or info.get("username") or "")


def _round(x: float) -> float:
    return round(x, 1)


def awak_jobs(db: Session, slug: str, since: datetime) -> list[dict]:
    naive = since.astimezone(UTC).replace(tzinfo=None)
    rows = db.query(AwakJob).filter(AwakJob.project_slug == slug).all()
    out = []
    for j in rows:
        updated = _dt(j.updated_at)
        if updated is None or updated.replace(tzinfo=None) < naive:
            continue
        out.append({"ref": j.story_ref, "state": j.state, "attempts": j.attempts,
                    "merge_state": j.merge_state, "started_at": _dt(j.started_at),
                    "updated_at": updated})
    return out


def metrics(project: dict, stories: list[dict], milestones: list[dict], issues: list[dict],
            jobs: list[dict], now: datetime, days: int) -> dict:
    """Everything the data report states, for the last `days` days."""
    start = now - timedelta(days=days)
    order = {s.get("name"): s.get("order", 0) for s in project.get("us_statuses") or []}
    counts = Counter(_status(s) for s in stories)
    by_status = [{"status": name, "count": n} for name, n in
                 sorted(counts.items(), key=lambda kv: (order.get(kv[0], 999), kv[0]))]

    open_ = [s for s in stories if not s.get("is_closed")]
    created_in = [s for s in stories if (_dt(s.get("created_date")) or now) >= start]
    closed_in = [s for s in stories
                 if s.get("is_closed") and (_dt(s.get("finish_date")) or start - timedelta(1)) >= start]

    cycle = []
    for s in closed_in:
        a, b = _dt(s.get("created_date")), _dt(s.get("finish_date"))
        if a and b and b >= a:
            cycle.append((b - a).total_seconds() / 86400)
    cycle.sort()

    weeks = min(13, max(1, math.ceil(days / 7)))
    weekly = []
    for w in range(weeks - 1, -1, -1):
        hi, lo = now - timedelta(days=7 * w), now - timedelta(days=7 * (w + 1))
        n = sum(1 for s in stories if s.get("is_closed")
                and (d := _dt(s.get("finish_date"))) and lo < d <= hi)
        weekly.append({"week_ending": hi.date().isoformat(), "closed": n})

    def age(s) -> int:
        d = _dt(s.get("created_date"))
        return max(0, (now - d).days) if d else 0

    oldest = sorted(open_, key=age, reverse=True)[:5]
    blocked = [s for s in open_ if s.get("is_blocked")]

    today = now.date().isoformat()
    sprint = None
    live = [m for m in milestones if not m.get("closed")]
    current = [m for m in live if str(m.get("estimated_start") or "") <= today
               <= str(m.get("estimated_finish") or "")]
    pick = (current or sorted(live, key=lambda m: str(m.get("estimated_start") or "")))[:1]
    if pick:
        m = pick[0]
        us = m.get("user_stories") or []
        finish = _dt(m.get("estimated_finish"))
        sprint = {"name": str(m.get("name") or ""),
                  "start": str(m.get("estimated_start") or ""),
                  "finish": str(m.get("estimated_finish") or ""),
                  "days_left": (finish.date() - now.date()).days if finish else None,
                  "stories": len(us),
                  "stories_closed": sum(1 for u in us if u.get("is_closed")),
                  "points": m.get("total_points") or 0,
                  "points_closed": m.get("closed_points") or 0}

    done = [j for j in jobs if j["state"] == "passed"]
    gave_up = [j for j in jobs if j["state"] == "failed"]
    finished = len(done) + len(gave_up)
    minutes = sorted((j["updated_at"] - j["started_at"]).total_seconds() / 60
                     for j in done if j.get("started_at") and j.get("updated_at"))
    awak = {
        "stories": len(jobs), "passed": len(done), "needs_human": len(gave_up),
        "in_progress": sum(1 for j in jobs if j["state"] in ("queued", "running")),
        "pass_rate_pct": _round(100 * len(done) / finished) if finished else None,
        "first_try_pct": (_round(100 * sum(1 for j in done if j["attempts"] <= 1) / finished)
                          if finished else None),
        "avg_attempts": _round(statistics.mean(j["attempts"] for j in done)) if done else None,
        "median_minutes": _round(statistics.median(minutes)) if minutes else None,
        "awaiting_merge": sum(1 for j in done if j.get("merge_state") != "merged"),
    }

    return {
        "project": str(project.get("name") or ""),
        "period": {"days": days, "from": start.date().isoformat(), "to": now.date().isoformat()},
        "stories": {
            "total": len(stories), "open": len(open_),
            "created": len(created_in), "closed": len(closed_in),
            "unassigned_open": sum(1 for s in open_ if not s.get("assigned_to")),
            "by_status": by_status,
        },
        "cycle_time_days": {
            "count": len(cycle),
            "median": _round(statistics.median(cycle)) if cycle else None,
            "p85": _round(cycle[min(len(cycle) - 1, math.ceil(0.85 * len(cycle)) - 1)])
            if cycle else None,
        },
        "throughput": weekly,
        "oldest_open": [{"ref": s.get("ref"), "subject": str(s.get("subject") or "")[:120],
                         "status": _status(s), "age_days": age(s), "assigned": _who(s)}
                        for s in oldest],
        "blocked": [{"ref": s.get("ref"), "subject": str(s.get("subject") or "")[:120],
                     "note": str(s.get("blocked_note") or "")[:200]} for s in blocked[:10]],
        "sprint": sprint,
        "issues": {
            "open": sum(1 for i in issues if not i.get("is_closed")),
            "created": sum(1 for i in issues if (_dt(i.get("created_date")) or now) >= start),
            "closed": sum(1 for i in issues if i.get("is_closed")
                          and (_dt(i.get("finished_date")) or start - timedelta(1)) >= start),
        },
        "awak": awak,
    }


def collect(source: Source, db: Session, slug: str, now: datetime, days: int) -> dict:
    project = source.project(slug)
    pid = project["id"]
    return metrics(project, source.stories(pid), source.milestones(pid), source.issues(pid),
                   awak_jobs(db, slug, now - timedelta(days=days)), now, days)


def backlog(source: Source, slug: str, open_max: int = 80, closed_max: int = 30) -> dict:
    """What is planned and what was just done, for the feature agent: subjects
    only (no descriptions, no people)."""
    project = source.project(slug)
    stories = source.stories(project["id"])
    open_ = [s for s in stories if not s.get("is_closed")]
    closed = sorted((s for s in stories if s.get("is_closed")),
                    key=lambda s: str(s.get("finish_date") or ""), reverse=True)

    def row(s):
        return {"ref": s.get("ref"), "subject": str(s.get("subject") or "")[:160],
                "status": _status(s)}

    return {"name": str(project.get("name") or ""),
            "description": str(project.get("description") or "")[:1500],
            "open": [row(s) for s in open_[:open_max]],
            "open_total": len(open_),
            "recently_closed": [row(s) for s in closed[:closed_max]]}


# --- the numbers as Markdown ----------------------------------------------------

_T = {
    "id": {"numbers": "Angka", "period": "Periode", "days": "hari", "metric": "Metrik",
           "value": "Nilai", "stories_total": "Story total", "stories_open": "Story terbuka",
           "created": "Story dibuat (periode)", "closed": "Story selesai (periode)",
           "unassigned": "Story terbuka tanpa penanggung jawab",
           "cycle_median": "Waktu siklus median (hari)", "cycle_p85": "Waktu siklus P85 (hari)",
           "issues_open": "Issue terbuka", "issues_created": "Issue dibuat (periode)",
           "issues_closed": "Issue ditutup (periode)", "by_status": "Story per status",
           "status": "Status", "count": "Jumlah", "throughput": "Story selesai per minggu",
           "week": "Minggu berakhir", "sprint": "Sprint berjalan", "left": "sisa hari",
           "oldest": "Story terbuka paling lama", "age": "Umur (hari)", "owner": "Penanggung jawab",
           "blocked": "Story terblokir", "note": "Catatan", "awak": "Awak (agen coding)",
           "awak_stories": "Story dikerjakan", "awak_passed": "Lulus",
           "awak_human": "Butuh bantuan manusia", "awak_rate": "Tingkat lulus",
           "awak_first": "Lulus di percobaan pertama", "awak_attempts": "Rata-rata percobaan",
           "awak_minutes": "Durasi median (menit)", "awak_merge": "Menunggu merge",
           "none": "tidak ada", "story": "Story"},
    "en": {"numbers": "Numbers", "period": "Period", "days": "days", "metric": "Metric",
           "value": "Value", "stories_total": "Stories in total", "stories_open": "Open stories",
           "created": "Stories created (period)", "closed": "Stories closed (period)",
           "unassigned": "Open stories without an owner",
           "cycle_median": "Median cycle time (days)", "cycle_p85": "P85 cycle time (days)",
           "issues_open": "Open issues", "issues_created": "Issues created (period)",
           "issues_closed": "Issues closed (period)", "by_status": "Stories by status",
           "status": "Status", "count": "Count", "throughput": "Stories closed per week",
           "week": "Week ending", "sprint": "Current sprint", "left": "days left",
           "oldest": "Oldest open stories", "age": "Age (days)", "owner": "Owner",
           "blocked": "Blocked stories", "note": "Note", "awak": "Awak (coding agent)",
           "awak_stories": "Stories worked on", "awak_passed": "Passed",
           "awak_human": "Needed a person", "awak_rate": "Pass rate",
           "awak_first": "Passed on the first attempt", "awak_attempts": "Average attempts",
           "awak_minutes": "Median duration (minutes)", "awak_merge": "Waiting for merge",
           "none": "none", "story": "Story"},
}


def _cell(value) -> str:
    return str(value if value is not None else "-").replace("|", "/").replace("\n", " ")


def _table(head: list[str], rows: list[list]) -> list[str]:
    out = ["| " + " | ".join(head) + " |", "| " + " | ".join("---" for _ in head) + " |"]
    out += ["| " + " | ".join(_cell(c) for c in r) + " |" for r in rows]
    return out + [""]


def _pct(v) -> str:
    return "-" if v is None else f"{v}%"


def numbers_md(m: dict, lang: str) -> str:
    t = _T.get(lang, _T["id"])
    s, c, i, a = m["stories"], m["cycle_time_days"], m["issues"], m["awak"]
    p = m["period"]
    out = [f"## {t['numbers']}", "",
           f"{t['period']}: {p['from']} – {p['to']} ({p['days']} {t['days']}).", ""]
    out += _table([t["metric"], t["value"]], [
        [t["stories_total"], s["total"]], [t["stories_open"], s["open"]],
        [t["created"], s["created"]], [t["closed"], s["closed"]],
        [t["unassigned"], s["unassigned_open"]],
        [t["cycle_median"], c["median"]], [t["cycle_p85"], c["p85"]],
        [t["issues_open"], i["open"]], [t["issues_created"], i["created"]],
        [t["issues_closed"], i["closed"]],
    ])
    if s["by_status"]:
        out += [f"### {t['by_status']}", ""]
        out += _table([t["status"], t["count"]], [[r["status"], r["count"]] for r in s["by_status"]])
    out += [f"### {t['throughput']}", ""]
    out += _table([t["week"], t["count"]], [[w["week_ending"], w["closed"]] for w in m["throughput"]])
    if m["sprint"]:
        sp = m["sprint"]
        left = "" if sp["days_left"] is None else f", {sp['days_left']} {t['left']}"
        out += [f"### {t['sprint']}", "",
                f"**{_cell(sp['name'])}** ({sp['start']} – {sp['finish']}{left}): "
                f"{sp['stories_closed']}/{sp['stories']} story, "
                f"{sp['points_closed']}/{sp['points']} poin.", ""]
    if m["oldest_open"]:
        out += [f"### {t['oldest']}", ""]
        out += _table([t["story"], t["status"], t["age"], t["owner"]],
                      [[f"#{r['ref']} {r['subject']}", r["status"], r["age_days"],
                        r["assigned"] or "-"] for r in m["oldest_open"]])
    out += [f"### {t['blocked']}", ""]
    if m["blocked"]:
        out += _table([t["story"], t["note"]],
                      [[f"#{r['ref']} {r['subject']}", r["note"] or "-"] for r in m["blocked"]])
    else:
        out += [t["none"].capitalize() + ".", ""]
    if a["stories"]:
        out += [f"### {t['awak']}", ""]
        out += _table([t["metric"], t["value"]], [
            [t["awak_stories"], a["stories"]], [t["awak_passed"], a["passed"]],
            [t["awak_human"], a["needs_human"]], [t["awak_rate"], _pct(a["pass_rate_pct"])],
            [t["awak_first"], _pct(a["first_try_pct"])], [t["awak_attempts"], a["avg_attempts"]],
            [t["awak_minutes"], a["median_minutes"]], [t["awak_merge"], a["awaiting_merge"]],
        ])
    return "\n".join(out).rstrip() + "\n"
