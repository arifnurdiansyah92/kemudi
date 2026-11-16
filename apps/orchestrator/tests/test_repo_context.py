"""Intake reads the project's repos as context (awak/repo_context.py)."""

import json
import subprocess

from kemudi_ai.awak import repo_context
from kemudi_ai.awak.intake import draft_stories
from kemudi_ai.awak.repo_context import RepoContext, Source, file_map, keep
from kemudi_ai.llm import LLMError
from kemudi_ai.store import AwakProject, AwakRepo

from .conftest import MEMBER
from .fakes import FakeLLM

STORIES = {"stories": [{"subject": "Tambah filter status", "description": "di /orders",
                        "criteria": ["filter tampil"], "area": "web"}]}


def fake_source(files: dict[str, str], name="web-app", role="web") -> Source:
    def git(*args):
        if args[0] == "ls-tree":
            return "\0".join(files)
        path = args[-1].split(":", 1)[1]
        if path not in files:
            from kemudi_ai.awak.gitops import GitError
            raise GitError("missing")
        return files[path]
    return Source(name=name, role=role, branch="main", git=git)


FILES = {
    "README.md": "# Toko\nAplikasi pesanan.",
    "package.json": json.dumps({"name": "toko", "scripts": {"dev": "vite"},
                                "dependencies": {"react": "18"}, "private": True}),
    "src/routes.tsx": "export const routes = ['/orders', '/customers']",
    "src/pages/Orders.tsx": "export function Orders() { return <h1>Pesanan</h1> }",
    "node_modules/react/index.js": "x",
    "public/logo.png": "\0PNG",
    "package-lock.json": "{}",
}


def test_keep_skips_vendor_binaries_and_lockfiles():
    assert keep("src/a.ts") and keep("README.md")
    assert not keep("node_modules/x/index.js")
    assert not keep("web/dist/app.js")
    assert not keep("public/logo.png")
    assert not keep("package-lock.json")


def test_file_map_collapses_deep_folders_when_too_big():
    paths = [f"src/feature{i}/part/file{j}.ts" for i in range(20) for j in range(30)]
    text = file_map(paths, 2_000)
    assert len(text) <= 2_000
    assert "src/feature0/part/… (30 file)" in text or "src/feature0/… (30 file)" in text
    assert file_map(["a.ts", "b/c.ts"], 1000) == "a.ts\nb/c.ts"


def test_overview_has_readme_manifest_and_map():
    ctx = RepoContext(sources=[fake_source(FILES)], unavailable=["api"])
    text = ctx.overview()
    assert "Repo `web-app` (peran: web" in text
    assert "Aplikasi pesanan." in text
    assert '"scripts": ["dev"]' in text and '"dependencies": ["react"]' in text
    assert '"private"' not in text  # package.json reduced to the stack
    assert "src/pages/Orders.tsx" in text
    assert "node_modules" not in text and "logo.png" not in text
    assert "tidak bisa dibaca" in text and "api" in text


def test_read_only_returns_known_paths_within_budget():
    ctx = RepoContext(sources=[fake_source(FILES)])
    text = ctx.read([{"repo": "web-app", "path": "src/routes.tsx"},
                     {"repo": "web-app", "path": "src/secret/../../etc/passwd"},
                     {"repo": "other", "path": "src/pages/Orders.tsx"},
                     {"path": "/src/pages/Orders.tsx"},  # one repo: repo may be left out
                     {"repo": "web-app", "path": "src/routes.tsx"},  # duplicate
                     "nonsense"])
    assert "'/orders'" in text and "Pesanan" in text
    assert ctx.read_files == ["web-app:src/routes.tsx", "web-app:src/pages/Orders.tsx"]


def test_read_caps_large_files():
    big = {"big.ts": "x" * (repo_context.FILE_CHARS + 500)}
    ctx = RepoContext(sources=[fake_source(big)])
    assert "dipotong" in ctx.read([{"path": "big.ts"}])


def test_draft_with_code_picks_files_then_drafts_against_them():
    llm = FakeLLM({"awak.intake.files": [{"files": [{"repo": "web-app",
                                                     "path": "src/routes.tsx"}]}],
                   "awak.intake": [STORIES]})
    ctx = RepoContext(sources=[fake_source(FILES)])
    drafts = draft_stories(llm, "butuh filter status pesanan", "id", ctx)
    assert [d.subject for d in drafts] == ["Tambah filter status"]
    (p1, _, u1), (p2, s2, u2) = llm.calls
    assert p1 == "awak.intake.files" and "src/pages/Orders.tsx" in u1
    assert p2 == "awak.intake"
    assert "Jangan mengarang nama" in s2 and "`web-app` (web)" in s2
    assert "butuh filter status pesanan" in u2 and "['/orders', '/customers']" in u2
    assert ctx.summary() == {"repos": ["web-app"], "files": ["web-app:src/routes.tsx"],
                             "unavailable": []}


def test_failed_pick_still_drafts_with_the_overview():
    llm = FakeLLM({"awak.intake.files": [LLMError("bad")], "awak.intake": [STORIES]})
    ctx = RepoContext(sources=[fake_source(FILES)])
    assert draft_stories(llm, "x", "en", ctx)
    _, system, user = llm.calls[-1]
    assert "Never invent names" in system and "src/routes.tsx" in user


def test_no_repos_drafts_from_text_only():
    llm = FakeLLM({"awak.intake": [STORIES]})
    draft_stories(llm, "butuh badge", "id", RepoContext(sources=[]))
    assert [c[0] for c in llm.calls] == ["awak.intake"]
    assert llm.calls[0][2] == "butuh badge"


def _git(cwd, *args):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=cwd,
                   check=True, capture_output=True)


def test_draft_endpoint_reads_the_configured_repo(agent_client, tmp_path):
    src = tmp_path / "remote"
    (src / "src").mkdir(parents=True)
    (src / "README.md").write_text("# Toko online\n")
    (src / "src" / "Orders.tsx").write_text("export const title = 'Daftar Pesanan'\n")
    _git(src, "init", "-q", "-b", "main")
    _git(src, "add", ".")
    _git(src, "commit", "-qm", "init")
    with agent_client.S() as db:
        db.add(AwakProject(slug="demo", enabled=True))
        db.add(AwakRepo(project_slug="demo", name="toko", role="web", url=str(src),
                        default_branch="main"))
        db.add(AwakRepo(project_slug="demo", name="api", role="api",
                        url="git@example.invalid:x/api.git", default_branch="main"))
        db.commit()
    llm = FakeLLM({"awak.intake.files": [{"files": [{"repo": "toko", "path": "src/Orders.tsx"}]}],
                   "awak.intake": [STORIES]})
    from kemudi_ai.api import app
    from kemudi_ai.deps import get_llm
    app.dependency_overrides[get_llm] = lambda: llm
    r = agent_client.post("/projects/demo/intake/draft", headers=MEMBER,
                          data={"text": "filter pesanan", "lang": "id"})
    assert r.status_code == 200, r.text
    assert r.json()["context"] == {"repos": ["toko"], "files": ["toko:src/Orders.tsx"],
                                   "unavailable": ["api"]}
    assert "Daftar Pesanan" in llm.calls[-1][2] and "Toko online" in llm.calls[-1][2]
