"""Tests for the runner's marketplace fetch (fetch.py and the fetch ops).

Run: python -m pytest infra/runner -q
"""

import hashlib
import importlib.util
import io
import json
import os
import re
import sys
import tarfile
import threading
import time
import urllib.error
import urllib.request
from email.message import Message
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

HERE = Path(__file__).parent
SHA = "a" * 40
OTHER_SHA = "b" * 40


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def fetch():
    mod = _load("kemudi_fetch_under_test", HERE / "fetch.py")
    yield mod
    sys.modules.pop("kemudi_fetch_under_test", None)


@pytest.fixture
def runner(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNNER_WORKSPACE", str(tmp_path / "ws"))
    monkeypatch.setenv("RUNNER_SKILLS_FETCH", str(tmp_path / "skills-fetch"))
    mod = _load("kemudi_runner_fetch_ops", HERE / "runner.py")
    yield mod
    sys.modules.pop("kemudi_runner_fetch_ops", None)


# --- tarballs ---------------------------------------------------------------------

def tarball(entries, top="owner-repo-aaaaaaa", comment=SHA) -> bytes:
    """entries: [(name, kind, data_or_target)], kind file|dir|symlink|hardlink|fifo;
    names are inside `top` unless they start with '!'."""
    buf = io.BytesIO()
    pax = {"comment": comment} if comment else {}
    with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.PAX_FORMAT,
                      pax_headers=pax) as tf:
        if top:
            d = tarfile.TarInfo(top + "/")
            d.type = tarfile.DIRTYPE
            tf.addfile(d)
        for name, kind, data in entries:
            full = name[1:] if name.startswith("!") else f"{top}/{name}"
            info = tarfile.TarInfo(full)
            if kind == "file":
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
                continue
            if kind == "dir":
                info.type = tarfile.DIRTYPE
            elif kind == "symlink":
                info.type, info.linkname = tarfile.SYMTYPE, data
            elif kind == "hardlink":
                info.type, info.linkname = tarfile.LNKTYPE, data
            elif kind == "fifo":
                info.type = tarfile.FIFOTYPE
            tf.addfile(info)
    return buf.getvalue()


GOOD = [(".claude-plugin", "dir", None),
        (".claude-plugin/marketplace.json", "file", b'{"name": "m", "plugins": []}'),
        ("skills/demo/SKILL.md", "file", b"---\nname: demo\ndescription: d\n---\n# Demo\n"),
        ("LICENSE", "file", b"Apache License\n")]


def tree(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


# --- arguments -----------------------------------------------------------------------

def test_check_args(fetch):
    fetch.check_args("anthropics", "skills", "")
    fetch.check_args("pbakaus", "impeccable", "v1.2.3")
    fetch.check_args("a-b", "x.y_z", "feature/x")
    for owner, repo, ref in [("", "r", ""), ("-a", "r", ""), ("a/b", "r", ""),
                             ("a", "..", ""), ("a", "r/x", ""), ("a", "r.git", ""),
                             ("a", "r", "../x"), ("a", "r", "-x"), ("a", "r", "a b"),
                             ("a", "r", "/x"), ("a", "r", "x//y"), ("a", "r", "x.lock"),
                             ("a" * 40, "r", ""), (1, "r", ""), ("a", "r", "x;rm")]:
        with pytest.raises(ValueError):
            fetch.check_args(owner, repo, ref)


# --- URLs, redirects -------------------------------------------------------------------

def test_only_github_https_urls(fetch):
    fetch.check_url("https://api.github.com/repos/a/b/commits/HEAD")
    fetch.check_url("https://codeload.github.com/a/b/tar.gz/" + SHA)
    for bad in ("http://api.github.com/x", "https://github.com/a/b",
                "https://evil.example/x", "https://api.github.com:8443/x",
                "https://user:pw@api.github.com/x", "file:///etc/passwd",
                "https://api.github.com.evil.example/x"):
        with pytest.raises(fetch.FetchError):
            fetch.check_url(bad)


def test_redirect_to_other_host_refused(fetch):
    h = fetch._Redirects()
    req = urllib.request.Request("https://api.github.com/repos/a/b/commits/HEAD")
    with pytest.raises(fetch.FetchError, match="refused to follow"):
        h.redirect_request(req, None, 302, "Found", Message(), "https://example.com/x")
    with pytest.raises(fetch.FetchError):
        h.redirect_request(req, None, 302, "Found", Message(),
                           "http://codeload.github.com/a/b/tar.gz/x")
    ok = h.redirect_request(req, None, 301, "Moved", Message(),
                            "https://api.github.com/repositories/1/commits/HEAD")
    assert ok.full_url.startswith("https://api.github.com/repositories/1")


def test_default_urlopen_refuses_before_connecting(fetch):
    with pytest.raises(fetch.FetchError):
        fetch.default_urlopen("https://example.com/", {}, 1)
    with pytest.raises(fetch.FetchError):
        fetch.default_urlopen("http://api.github.com/", {}, 1)


def test_private_addresses_refused(fetch, monkeypatch):
    monkeypatch.setattr(fetch.socket, "getaddrinfo", lambda *a, **k: [
        (2, 1, 6, "", ("10.0.0.5", 443)), (2, 1, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(fetch.FetchError, match="no public address"):
        fetch._public_addr("api.github.com", 443)
    monkeypatch.setattr(fetch.socket, "getaddrinfo", lambda *a, **k: [
        (2, 1, 6, "", ("169.254.1.1", 443)), (2, 1, 6, "", ("140.82.112.6", 443))])
    assert fetch._public_addr("api.github.com", 443)[1] == ("140.82.112.6", 443)
    conn = fetch._GuardedHTTPSConnection("example.com", 443)
    with pytest.raises(fetch.FetchError, match="refused"):
        conn.connect()


# --- GitHub API ------------------------------------------------------------------------

class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, headers=None):
        super().__init__(body)
        self.headers = headers or {}
        self.status = 200


def fake_opener(routes: dict, seen: list | None = None):
    """routes: url regex -> bytes | (code, headers)."""
    def urlopen(url, headers, timeout):
        if seen is not None:
            seen.append((url, headers))
        for pat, ans in routes.items():
            if re.fullmatch(pat, url):
                if isinstance(ans, tuple):
                    code, h = ans
                    msg = Message()
                    for k, v in h.items():
                        msg[k] = v
                    raise urllib.error.HTTPError(url, code, "err", msg, io.BytesIO(b""))
                return FakeResponse(ans, {"Content-Length": str(len(ans))})
        raise AssertionError(f"unexpected url {url}")
    return urlopen


def test_resolve_sha(fetch):
    seen = []
    op = fake_opener({r"https://api\.github\.com/repos/a/b/commits/HEAD": SHA.encode() + b"\n",
                      r"https://api\.github\.com/repos/a/b/commits/feature/x": OTHER_SHA.encode()},
                     seen)
    assert fetch.resolve_sha("a", "b", "", op) == SHA
    assert seen[0][1]["Accept"] == "application/vnd.github.sha"
    assert "Authorization" not in seen[0][1]  # no token, ever
    assert fetch.resolve_sha("a", "b", "feature/x", op) == OTHER_SHA
    seen.clear()
    assert fetch.resolve_sha("a", "b", SHA, op) == SHA and not seen  # a full sha: no call


def test_resolve_sha_errors(fetch):
    cases = {
        (404, ()): "not found",
        (422, ()): "not found",
        (403, (("X-RateLimit-Remaining", "0"), ("X-RateLimit-Reset", "1700000000"))):
            "rate limit.*after",
        (429, ()): "rate limit",
        (500, ()): "GitHub answered 500",
    }
    for (code, headers), msg in cases.items():
        op = fake_opener({r".*": (code, dict(headers))})
        with pytest.raises(fetch.FetchError, match=msg):
            fetch.resolve_sha("a", "b", "main", op)
    with pytest.raises(fetch.FetchError, match="commit sha"):
        fetch.resolve_sha("a", "b", "main", fake_opener({r".*": b"<html>"}))

    def down(url, headers, timeout):
        raise urllib.error.URLError("no route")
    with pytest.raises(fetch.FetchError, match="cannot reach GitHub"):
        fetch.resolve_sha("a", "b", "main", down)


def test_download_caps(fetch):
    data = b"x" * 1000
    out = io.BytesIO()
    assert fetch.download("a", "b", SHA, out, fake_opener({r".*": data})) == 1000
    with pytest.raises(fetch.FetchError, match="larger than"):
        fetch.download("a", "b", SHA, io.BytesIO(), fake_opener({r".*": data}), cap=999)

    def no_length(url, headers, timeout):  # a stream without Content-Length
        return FakeResponse(b"y" * 5000, {})
    with pytest.raises(fetch.FetchError, match="larger than"):
        fetch.download("a", "b", SHA, io.BytesIO(), no_length, cap=4096)
    with pytest.raises(fetch.FetchError, match="not found"):
        fetch.download("a", "b", SHA, io.BytesIO(), fake_opener({r".*": (404, {})}))


# --- extraction --------------------------------------------------------------------------

def test_extract_plain_tree(fetch, tmp_path):
    res = fetch.extract(io.BytesIO(tarball(GOOD)), tmp_path, expect_sha=SHA)
    assert res["files"] == 3 and res["skipped"] == [] and res["skipped_truncated"] is False
    t = tree(tmp_path)
    assert set(t) == {".claude-plugin/marketplace.json", "skills/demo/SKILL.md", "LICENSE"}
    # the manifest: every extracted file's sha256
    assert res["manifest"] == {p: hashlib.sha256(d).hexdigest() for p, d in t.items()}


def test_extract_flags_a_truncated_skipped_list(fetch, tmp_path, monkeypatch):
    monkeypatch.setattr(fetch, "MAX_SKIPPED_LISTED", 2)
    data = tarball(GOOD + [(f"l{i}", "symlink", "/etc/passwd") for i in range(3)])
    res = fetch.extract(io.BytesIO(data), tmp_path)
    assert len(res["skipped"]) == 2 and res["skipped_truncated"] is True


def _long_header_tar(fmt) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", format=fmt) as tf:
        info = tarfile.TarInfo("top/" + "a/" * 40_000 + "f")  # an 80 KB name
        info.size = 1
        tf.addfile(info, io.BytesIO(b"x"))
    return buf.getvalue()


@pytest.mark.parametrize("fmt,msg", [(tarfile.GNU_FORMAT, "long-name header"),
                                     (tarfile.PAX_FORMAT, "PAX header")])
def test_extract_refuses_huge_name_headers(fetch, tmp_path, fmt, msg):
    """The header's size is checked before tarfile reads its data."""
    with pytest.raises(fetch.FetchError, match=msg):
        fetch.extract(io.BytesIO(_long_header_tar(fmt)), tmp_path)


def test_bounded_tarinfo_overrides_real_methods(fetch):
    """The guarded methods exist in this Python's tarfile (else the guard is
    silently dead)."""
    for name in ("_proc_gnulong", "_proc_pax", "_proc_sparse", "_proc_gnusparse_00",
                 "_proc_gnusparse_01", "_proc_gnusparse_10"):
        assert callable(getattr(tarfile.TarInfo, name)), name
        assert getattr(fetch._BoundedTarInfo, name) is not getattr(tarfile.TarInfo, name)


def test_extract_checks_the_deadline(fetch, tmp_path):
    with pytest.raises(fetch.FetchError, match="took too long"):
        fetch.extract(io.BytesIO(tarball(GOOD)), tmp_path, deadline=time.monotonic() - 1)


@pytest.mark.skipif(os.name != "posix", reason="resource limits are POSIX only")
def test_limit_self_in_a_child(fetch):
    import subprocess

    code = ("import importlib.util, resource, sys\n"
            "spec = importlib.util.spec_from_file_location('f', sys.argv[1])\n"
            "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)\n"
            "m.limit_self()\n"
            "print(resource.getrlimit(resource.RLIMIT_AS)[0], "
            "resource.getrlimit(resource.RLIMIT_CPU)[0])\n")
    out = subprocess.run([sys.executable, "-c", code, str(HERE / "fetch.py")],
                         capture_output=True, text=True, check=True).stdout.split()
    assert int(out[0]) <= fetch.MAX_MEMORY and int(out[1]) <= fetch.CPU_SECONDS


def test_extract_skips_links_and_special_files(fetch, tmp_path):
    data = tarball(GOOD + [("skills/demo/link", "symlink", "/etc/passwd"),
                           ("skills/demo/hard", "hardlink", "owner-repo-aaaaaaa/LICENSE"),
                           ("pipe", "fifo", None)])
    res = fetch.extract(io.BytesIO(data), tmp_path)
    assert {(s["path"], s["reason"]) for s in res["skipped"]} == {
        ("skills/demo/link", "symlink"), ("skills/demo/hard", "hardlink"),
        ("pipe", "special file")}
    assert not os.path.lexists(tmp_path / "skills/demo/link")
    assert not os.path.lexists(tmp_path / "skills/demo/hard")
    assert not os.path.lexists(tmp_path / "pipe")


@pytest.mark.parametrize("entries,msg", [
    ([("../escape", "file", b"x")], "unsafe path"),
    ([("!/abs/file", "file", b"x")], "unsafe path"),
    ([("!other-top/file", "file", b"x")], "more than one top folder"),
    ([("a", "file", b"1"), ("a", "file", b"2")], "appears twice"),
])
def test_extract_refuses_unsafe_archives(fetch, tmp_path, entries, msg):
    with pytest.raises(fetch.FetchError, match=msg):
        fetch.extract(io.BytesIO(tarball(entries)), tmp_path)


def test_extract_caps(fetch, tmp_path, monkeypatch):
    for d in "abcd":
        (tmp_path / d).mkdir()
    monkeypatch.setattr(fetch, "MAX_FILE_BYTES", 10)
    res = fetch.extract(io.BytesIO(tarball([("big", "file", b"x" * 11),
                                            ("small", "file", b"ok")])), tmp_path / "a")
    assert [s["path"] for s in res["skipped"]] == ["big"] and res["files"] == 1
    monkeypatch.setattr(fetch, "MAX_ENTRIES", 3)
    with pytest.raises(fetch.FetchError, match="more than 3 entries"):
        fetch.extract(io.BytesIO(tarball([(f"f{i}", "file", b"") for i in range(5)])),
                      tmp_path / "b")
    monkeypatch.setattr(fetch, "MAX_ENTRIES", 1000)
    monkeypatch.setattr(fetch, "MAX_EXTRACT_BYTES", 15)
    with pytest.raises(fetch.FetchError, match="more than"):
        fetch.extract(io.BytesIO(tarball([(f"f{i}", "file", b"x" * 8) for i in range(3)])),
                      tmp_path / "c")
    monkeypatch.setattr(fetch, "MAX_DEPTH", 2)
    res = fetch.extract(io.BytesIO(tarball([("a/b/c", "file", b"x")])), tmp_path / "d")
    assert res["skipped"] == [{"path": "a/b/c", "reason": "nested too deep"}]


def test_extract_checks_commit_and_damage(fetch, tmp_path):
    for d in "abc":
        (tmp_path / d).mkdir()
    with pytest.raises(fetch.FetchError, match="not the commit"):
        fetch.extract(io.BytesIO(tarball(GOOD, comment=OTHER_SHA)), tmp_path / "a",
                      expect_sha=SHA)
    with pytest.raises(fetch.FetchError):
        fetch.extract(io.BytesIO(b"not a tarball"), tmp_path / "b")
    with pytest.raises(fetch.FetchError):
        fetch.extract(io.BytesIO(tarball(GOOD)[:200]), tmp_path / "c")


def test_extract_refuses_planted_symlink(fetch, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    dest = tmp_path / "dest"
    dest.mkdir()
    try:
        os.symlink(outside, dest / "skills", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("cannot create symlinks here")
    with pytest.raises(fetch.FetchError, match="not a plain folder"):
        fetch.extract(io.BytesIO(tarball(GOOD)), dest)
    assert list(outside.iterdir()) == []


# --- a whole fetch against a local fake GitHub ---------------------------------------------

@pytest.fixture
def fake_github():
    """A local HTTP server answering the two GitHub URLs; `urlopen` maps the
    https://<github host>/... URLs onto it."""
    state = {"tar": tarball(GOOD), "sha": SHA, "commits": 200, "hits": []}

    class H(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            state["hits"].append(self.path)
            if self.path.startswith("/api/repos/"):
                if state["commits"] != 200:
                    self.send_response(state["commits"])
                    self.send_header("X-RateLimit-Remaining", "0")
                    self.end_headers()
                    return
                body = state["sha"].encode()
            elif self.path.startswith("/codeload/"):
                body = state["tar"]
            else:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    plain = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def urlopen(url, headers, timeout):
        url = (url.replace("https://api.github.com/", base + "/api/")
                  .replace("https://codeload.github.com/", base + "/codeload/"))
        return plain.open(urllib.request.Request(url, headers=headers), timeout=timeout)

    state["urlopen"] = urlopen
    yield state
    srv.shutdown()


def test_fetch_end_to_end(fetch, tmp_path, fake_github):
    dest = tmp_path / ".skills-fetch" / ("0" * 32)
    res = fetch.fetch("anthropics", "skills", "", dest, fake_github["urlopen"])
    assert res["sha"] == SHA and res["files"] == 3
    assert fake_github["hits"] == ["/api/repos/anthropics/skills/commits/HEAD",
                                   f"/codeload/anthropics/skills/tar.gz/{SHA}"]
    assert (dest / "skills/demo/SKILL.md").read_bytes().startswith(b"---")


def test_fetch_failure_removes_dest(fetch, tmp_path, fake_github):
    dest = tmp_path / ".skills-fetch" / ("1" * 32)
    fake_github["tar"] = tarball([("../x", "file", b"x")])
    with pytest.raises(fetch.FetchError):
        fetch.fetch("a", "b", "main", dest, fake_github["urlopen"])
    assert not dest.exists()
    fake_github["commits"] = 403
    with pytest.raises(fetch.FetchError, match="rate limit"):
        fetch.fetch("a", "b", "main", dest, fake_github["urlopen"])
    assert not dest.exists()


def test_main_prints_one_json_line(fetch, tmp_path, capsys):
    fetch.main(["fetch.py", json.dumps({"owner": "a", "repo": "..", "ref": "",
                                        "dest": str(tmp_path / "x")})])
    out = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert "bad GitHub repository" in out["error"]


def test_sweep_removes_stale_fetches(fetch, tmp_path):
    old, new, other = tmp_path / ("a" * 32), tmp_path / ("b" * 32), tmp_path / "keep-me"
    for p in (old, new, other):
        p.mkdir()
    past = time.time() - 7200
    os.utime(old, (past, past))
    os.utime(other, (past, past))
    assert fetch.sweep(tmp_path) == ["a" * 32]
    assert not old.exists() and new.exists() and other.exists()


# --- runner ops ----------------------------------------------------------------------------

def test_op_fetch_repo(runner, monkeypatch):
    calls = []

    def child(args):
        calls.append(args)
        return {"sha": SHA, "files": 3, "bytes": 10, "skipped": [], "skipped_truncated": True,
                "manifest": {"a": "0" * 64}}
    monkeypatch.setattr(runner, "_run_fetch_child", child)
    res = runner.op_fetch_repo({"owner": "anthropics", "repo": "skills"})
    assert res["ok"] and res["sha"] == SHA
    assert re.fullmatch(r"[0-9a-f]{32}", res["dir"])
    # the dedicated fetch volume, never the workspace
    assert calls[0]["dest"] == str(runner.FETCH_ROOT / res["dir"])
    assert not calls[0]["dest"].startswith(str(runner.WORKSPACE))
    assert calls[0]["ref"] == ""
    assert res["manifest"] == {"a": "0" * 64} and res["skipped_truncated"] is True
    monkeypatch.setattr(runner, "_run_fetch_child", lambda a: {"error": "rate limit"})
    assert runner.op_fetch_repo({"owner": "a", "repo": "b", "ref": "main"}) == {
        "ok": False, "error": "rate limit"}
    # a child killed on the timeout leaves a partial folder: removed at once
    def killed(args):
        d = Path(args["dest"])
        (d / "skills").mkdir(parents=True)
        (d / "skills" / "half").write_text("x")
        calls.append(args)
        return {"error": "the fetch took longer than 300 s"}
    monkeypatch.setattr(runner, "_run_fetch_child", killed)
    assert runner.op_fetch_repo({"owner": "a", "repo": "b"})["ok"] is False
    assert not os.path.lexists(calls[-1]["dest"])
    # no manifest: refused (and removed) too
    monkeypatch.setattr(runner, "_run_fetch_child", lambda a: {"sha": SHA})
    assert runner.op_fetch_repo({"owner": "a", "repo": "b"})["ok"] is False
    for bad in ({"owner": "a/b", "repo": "c"}, {"owner": "a", "repo": "../x"},
                {"owner": "a", "repo": "b", "ref": "../../etc"}, {}):
        with pytest.raises(ValueError):
            runner.op_fetch_repo(bad)


def test_fetch_child_glue(runner, monkeypatch, tmp_path):
    script = tmp_path / "fake_fetch.py"
    script.write_text("import json, sys\nargs = json.loads(sys.argv[1])\nprint('noise')\n"
                      "print(json.dumps({'sha': 'c' * 40, 'echo': args['repo']}))\n")
    monkeypatch.setattr(runner, "FETCH_SCRIPT", script)
    assert runner._run_fetch_child({"repo": "r"}) == {"sha": "c" * 40, "echo": "r"}
    script.write_text("import sys\nsys.stderr.write('boom')\nsys.exit(1)\n")
    assert "boom" in runner._run_fetch_child({})["error"]


def test_fetch_child_kw(runner, monkeypatch):
    """As root the fetch child runs as FETCH_UID, not the workspace uid."""
    monkeypatch.setattr(runner, "dropping", lambda: True)
    monkeypatch.setattr(runner, "_child_home", lambda: "/home/hermes")
    assert runner.fetch_kw() == {"user": 10001, "group": 10001, "extra_groups": []}
    assert runner.child_kw()["user"] == runner.CHILD_UID != runner.FETCH_UID
    env = runner.fetch_env()
    assert env["HOME"] == "/tmp" and not any(k.startswith("KEMUDI_") for k in env)


def test_op_fetch_cleanup(runner):
    d = runner.FETCH_ROOT / ("c" * 32)
    (d / "skills").mkdir(parents=True)
    (d / "skills" / "x").write_text("x")
    assert runner.op_fetch_cleanup({"dir": "c" * 32}) == {"ok": True, "removed": True}
    assert not d.exists()
    for bad in ("", "../x", "/etc", "abc", "x/" + "c" * 32, "C" * 32,
                ".skills-fetch/" + "c" * 32):
        with pytest.raises(ValueError):
            runner.op_fetch_cleanup({"dir": bad})
