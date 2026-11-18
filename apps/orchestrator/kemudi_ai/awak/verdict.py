"""Turn the runner's QA report into pass / fail / spec error / infra error.

The verdict comes from test results, never from what a model says about them.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
MAX_SHOT_BYTES = 5 * 1024 * 1024
_AC = re.compile(r"^\s*AC\s*(\d+)\b", re.I)
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


@dataclass
class Criterion:
    n: int
    text: str
    passed: bool = False
    error: str = ""
    screenshots: list[str] = field(default_factory=list)
    # What the browser saw while the test failed (failed requests, console
    # errors), one line; '' when the runner sent none.
    evidence: str = ""


def evidence_line(raw) -> str:
    """The runner's `evidence` of a failed test ({"http", "console"}) as one
    line for the coder and the card."""
    if not isinstance(raw, dict):
        return ""
    parts = []
    for h in (raw.get("http") or [])[:6]:
        if not isinstance(h, dict):
            continue
        status = h.get("status")
        answer = "no response" if not isinstance(status, int) or status <= 0 else str(status)
        body = " ".join(str(h.get("body") or "").split())[:200]
        parts.append(f"{str(h.get('method') or '')[:10]} {str(h.get('url') or '')[:200]} "
                     f"-> {answer}" + (f" {body}" if body else ""))
    for c in (raw.get("console") or [])[:4]:
        parts.append("console: " + " ".join(str(c).split())[:200])
    return _ANSI.sub("", "; ".join(parts))[:1200]


@dataclass
class Verdict:
    outcome: str  # pass | fail | spec | infra
    reason: str = ""
    criteria: list[Criterion] = field(default_factory=list)

    def failures(self) -> str:
        return "\n".join(
            f"- AC{c.n} ({c.text}): {c.error or 'gagal'}"
            + (f"\n  The browser saw: {c.evidence}" if c.evidence else "")
            for c in self.criteria if not c.passed
        )


def ac_number(title: str) -> int | None:
    # Titles may arrive as "story.spec.ts > AC1: ..." from some reporters.
    m = _AC.match(title.split(" > ")[-1])
    return int(m.group(1)) if m else None


def evaluate(report: dict, criteria_texts: list[str]) -> Verdict:
    if report.get("infra_error"):
        return Verdict("infra", report["infra_error"])
    if report.get("spec_error"):
        return Verdict("spec", report["spec_error"])
    runs = report.get("runs") or []
    if len(runs) < 2:
        return Verdict("infra", "QA spec was not run twice")

    per_run: list[dict[int, dict]] = []
    for run in runs[:2]:
        by_n: dict[int, dict] = {}
        for t in run.get("tests") or []:
            n = ac_number(t.get("title", ""))
            if n is not None:
                by_n[n] = t
        per_run.append(by_n)

    missing = [i for i in range(1, len(criteria_texts) + 1) if i not in per_run[0]]
    if missing:
        return Verdict("spec", "spec has no test for " + ", ".join(f"AC{i}" for i in missing))

    out: list[Criterion] = []
    for i, text in enumerate(criteria_texts, 1):
        a, b = per_run[0][i], per_run[1].get(i)
        pa = a.get("status") == "passed"
        pb = bool(b) and b.get("status") == "passed"
        if pa != pb:
            return Verdict("infra", f"AC{i} gave different results on two runs (flaky)")
        c = Criterion(n=i, text=text, passed=pa,
                      error=_ANSI.sub("", a.get("error") or "")[:400],
                      screenshots=list(a.get("screenshots") or []),
                      evidence="" if pa else evidence_line(a.get("evidence")))
        if c.passed and not c.screenshots:
            c.passed, c.error = False, "lulus tanpa screenshot bukti"
        out.append(c)

    if all(c.passed for c in out):
        return Verdict("pass", criteria=out)
    return Verdict("fail", criteria=out)


def safe_screenshot(path: str, qa_dir: Path) -> Path | None:
    """The path, if it is a real PNG file inside the job's .qa directory."""
    try:
        p = Path(path)
        if p.is_symlink():
            return None
        real = p.resolve(strict=True)
        root = qa_dir.resolve(strict=True)
        if root not in real.parents or not real.is_file():
            return None
        if real.stat().st_size > MAX_SHOT_BYTES:
            return None
        with real.open("rb") as fh:
            if fh.read(8) != PNG_MAGIC:
                return None
        return real
    except (OSError, ValueError):
        return None
