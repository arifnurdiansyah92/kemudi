"""What the browser saw during a failed QA test, from its Playwright trace.

A failed assertion says what was missing ("User deleted" never appeared), not
why. The trace knows: the request that answered 500, the error in the
console. This prints them as one JSON object, small enough for a prompt:

    {"http": [{"method", "url", "status", "body"}], "console": ["..."]}

Run as the runner's child (the trace is a file the test wrote): stdlib only,
bounded reads, never extracts to disk.

Usage: python3 trace_evidence.py <trace.zip>
"""

import json
import sys
import zipfile
from urllib.parse import urlsplit

MAX_ZIP = 300 * 1024 * 1024    # a bigger trace is skipped
MAX_MEMBER = 20 * 1024 * 1024  # per .trace/.network file read
MAX_LINE = 200_000             # a longer line is a snapshot, not an event
MAX_HTTP = 8
MAX_CONSOLE = 8
BODY_CHARS = 400
TEXT_CHARS = 300
# Noise the browser logs for every failed request (the request is listed).
_SKIP_CONSOLE = ("Failed to load resource",)
_TEXT_TYPES = ("json", "text", "xml", "javascript", "html")


def _path(url: str) -> str:
    """Path and query without the origin (the port changes per run)."""
    try:
        u = urlsplit(url)
    except ValueError:
        return url[:200]
    q = f"?{u.query}" if u.query else ""
    return (u.path or "/")[:200] + q[:100]


def _lines(z: zipfile.ZipFile, name: str):
    try:
        info = z.getinfo(name)
        if info.file_size > MAX_MEMBER:
            return
        with z.open(name) as f:
            for raw in f:
                if len(raw) > MAX_LINE:
                    continue
                try:
                    yield json.loads(raw)
                except ValueError:
                    continue
    except (KeyError, OSError, zipfile.BadZipFile):
        return


def _body(z: zipfile.ZipFile, content: dict) -> str:
    sha = content.get("_sha1") or ""
    mime = str(content.get("mimeType") or "")
    if not sha or "/" in sha or ".." in sha or not any(t in mime for t in _TEXT_TYPES):
        return ""
    try:
        info = z.getinfo(f"resources/{sha}")
        if info.file_size > MAX_MEMBER:
            return ""
        with z.open(info) as f:
            text = f.read(BODY_CHARS * 4).decode(errors="replace")
    except (KeyError, OSError, zipfile.BadZipFile):
        return ""
    return " ".join(text.split())[:BODY_CHARS]


def evidence(path: str) -> dict:
    http: list[dict] = []
    console: list[str] = []
    seen_http, seen_console = set(), set()
    try:
        z = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile):
        return {"http": [], "console": []}
    with z:
        if sum(i.file_size for i in z.infolist()) > MAX_ZIP:
            return {"http": [], "console": []}
        names = z.namelist()
        for name in names:
            if not name.endswith(".network"):
                continue
            for ev in _lines(z, name):
                snap = ev.get("snapshot") if ev.get("type") == "resource-snapshot" else None
                if not isinstance(snap, dict):
                    continue
                req, res = snap.get("request") or {}, snap.get("response") or {}
                status = res.get("status")
                # -1/0: the request never got an answer (refused, aborted).
                if not isinstance(status, int) or 0 < status < 400:
                    continue
                key = (req.get("method"), _path(str(req.get("url") or "")), status)
                if key in seen_http:
                    continue
                seen_http.add(key)
                if len(http) < MAX_HTTP:
                    http.append({"method": str(key[0] or "")[:10], "url": key[1],
                                 "status": status,
                                 "body": _body(z, res.get("content") or {})})
        for name in names:
            if not name.endswith(".trace"):
                continue
            for ev in _lines(z, name):
                text = ""
                if ev.get("type") == "console" and ev.get("messageType") == "error":
                    text = str(ev.get("text") or "")
                    if text.startswith(_SKIP_CONSOLE):
                        continue
                elif ev.get("type") == "event" and ev.get("method") == "pageError":
                    err = ((ev.get("params") or {}).get("error") or {}).get("error") or {}
                    text = "Uncaught " + str(err.get("message") or "")
                text = " ".join(text.split())[:TEXT_CHARS]
                if text and text not in seen_console:
                    seen_console.add(text)
                    if len(console) < MAX_CONSOLE:
                        console.append(text)
    return {"http": http, "console": console}


if __name__ == "__main__":
    print(json.dumps(evidence(sys.argv[1]) if len(sys.argv) > 1 else {}))
