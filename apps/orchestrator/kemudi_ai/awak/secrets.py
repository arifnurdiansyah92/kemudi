"""Catch secrets before they reach a commit that gets pushed, or a comment."""

import os
import re

PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
]
# Env vars whose values must never appear anywhere the agent can write.
SENSITIVE_SUFFIXES = ("_KEY", "_PASSWORD", "_SECRET", "_TOKEN")


def known_values(environ: dict[str, str] | None = None) -> list[str]:
    env = os.environ if environ is None else environ
    return [
        v for k, v in env.items()
        if k.upper().endswith(SENSITIVE_SUFFIXES) and v and len(v) >= 8
    ]


def find(text: str, values: list[str]) -> list[str]:
    """Names of what matched (never the matched value itself)."""
    hits = []
    for v in values:
        if v in text:
            hits.append("a configured secret value")
            break
    for p in PATTERNS:
        if p.search(text):
            hits.append(f"pattern {p.pattern[:24]}…")
    return hits


def files_with_secrets(diff: str, values: list[str]) -> list[str]:
    """File names in a unified diff whose added lines contain a secret."""
    bad: list[str] = []
    current = ""
    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else line[4:]
        elif line.startswith("+") and not line.startswith("+++"):
            if find(line, values) and current not in bad:
                bad.append(current)
    return bad


def redact(text: str, values: list[str]) -> str:
    for v in values:
        text = text.replace(v, "[disembunyikan]")
    for p in PATTERNS:
        text = p.sub("[disembunyikan]", text)
    return text
