"""Reading a runner-fetched repo from the workspace volume (awak/fetched.py)."""

import os

import pytest

from kemudi_ai.awak import fetched

from .fetch_fakes import FakeFetchRunner

SHA = "a" * 40


@pytest.fixture
def fake(agent_settings):
    r = FakeFetchRunner(agent_settings.skills_fetch_dir)
    r.publish("o/r", SHA, {"README.md": "hi", "skills/demo/SKILL.md": "---\nname: demo\n---\n",
                           "skills/demo/ref/a.md": "a", "big.bin": b"x" * 100})
    return r


def test_fetched_reads_and_cleans_up(fake, agent_settings):
    with fetched.fetched(fake, agent_settings, "o", "r") as t:
        assert t.sha == SHA
        assert t.read("README.md", 10) == b"hi"
        assert t.read("missing.md", 10) is None
        assert t.is_dir("skills/demo") and t.is_file("skills/demo/SKILL.md")
        assert not t.is_file("skills") and not t.is_dir("README.md")
        assert t.listdir("skills") == [("demo", "dir")]
        assert t.read_folder("skills/demo", 10, 1000) == {
            "SKILL.md": b"---\nname: demo\n---\n", "ref/a.md": b"a"}
        with pytest.raises(fetched.TreeError, match="larger than"):
            t.read("big.bin", 10)
        with pytest.raises(fetched.TreeError, match="more than 1 files"):
            t.read_folder("skills/demo", 1, 1000)
        with pytest.raises(fetched.TreeError, match="more than 5 bytes of files"):
            t.read_folder("skills/demo", 10, 5)
        for bad in ("../x", "/etc/passwd", "a\\b", "skills/../../x"):
            with pytest.raises(fetched.TreeError):
                t.read(bad, 10)
    assert fake.live_dirs() == []
    assert [c[0] for c in fake.calls] == ["fetch_repo", "fetch_cleanup"]


def test_fetched_cleans_up_after_an_error(fake, agent_settings):
    with pytest.raises(RuntimeError), fetched.fetched(fake, agent_settings, "o", "r"):
        raise RuntimeError("boom")
    assert fake.live_dirs() == []


def test_fetch_failures(fake, agent_settings):
    fake.fail = "GitHub's API rate limit was reached"
    with pytest.raises(fetched.FetchError, match="rate limit"), \
            fetched.fetched(fake, agent_settings, "o", "r"):
        pass
    fake.fail, fake.down = None, True
    with pytest.raises(fetched.FetchError, match="runner could not fetch"), \
            fetched.fetched(fake, agent_settings, "o", "r"):
        pass


def test_open_tree_refuses_bad_answers(agent_settings):
    ok = {"a.md": "0" * 64}
    for name, sha, manifest in [("../etc", SHA, ok), ("xyz", SHA, ok),
                                (".skills-fetch/" + "a" * 32, SHA, ok),
                                ("a" * 32, "main", ok), ("a" * 32, SHA, None),
                                ("a" * 32, SHA, {"a.md": "nope"}), ("a" * 32, SHA, [])]:
        with pytest.raises(fetched.FetchError):
            fetched.open_tree(agent_settings, {"dir": name, "sha": sha, "manifest": manifest})


def test_open_tree_missing_folder_is_a_fetch_error(agent_settings):
    """An OSError (the folder is gone) is a FetchError, not a crash."""
    with pytest.raises(fetched.FetchError, match="cannot be read"):
        fetched.open_tree(agent_settings, {"dir": "a" * 32, "sha": SHA, "manifest": {}})


@pytest.mark.skipif(os.name != "posix", reason="owners are POSIX only")
def test_open_tree_checks_owners_and_modes(fake, agent_settings):
    res = fake.call("fetch_repo", owner="o", repo="r", ref="")
    agent_settings.skills_fetch_uid = os.getuid() + 1  # another uid wrote it
    with pytest.raises(fetched.FetchError, match="belongs to uid"):
        fetched.open_tree(agent_settings, res)
    agent_settings.skills_fetch_uid = os.getuid()
    root = fake.base / res["dir"]
    os.chmod(root, 0o777)
    with pytest.raises(fetched.FetchError, match="writable by others"):
        fetched.open_tree(agent_settings, res)
    os.chmod(root, 0o755)
    assert fetched.open_tree(agent_settings, res).read("README.md", 10) == b"hi"


def test_reads_are_checked_against_the_manifest(fake, agent_settings):
    with fetched.fetched(fake, agent_settings, "o", "r") as t:
        # swapped after the extraction
        (t.root / "README.md").write_bytes(b"ho")
        with pytest.raises(fetched.TreeError, match="changed after the fetch"):
            t.read("README.md", 10)
        # planted: not in the manifest
        (t.root / "skills" / "demo" / "evil.md").write_bytes(b"x")
        with pytest.raises(fetched.TreeError, match="not in the fetch's manifest"):
            t.read_folder("skills/demo", 10, 1000)
        os.unlink(t.root / "skills" / "demo" / "evil.md")
        # removed: the folder no longer holds what was fetched
        os.unlink(t.root / "skills" / "demo" / "ref" / "a.md")
        with pytest.raises(fetched.TreeError, match="ref/a.md: missing"):
            t.read_folder("skills/demo", 10, 1000)


def test_skipped_links_fail_the_folder(fake, agent_settings):
    fake.publish("o/r", "b" * 40, {"skills/demo/SKILL.md": "x", "skills/other/SKILL.md": "y"},
                 ref="v2", skipped=[{"path": "skills/demo/link", "reason": "symlink"}])
    with fetched.fetched(fake, agent_settings, "o", "r", "v2") as t:
        with pytest.raises(fetched.TreeError, match="symlink"):
            t.read_folder("skills/demo", 10, 100)
        # only entries under the folder count; at the root every entry does
        assert t.read_folder("skills/other", 10, 100) == {"SKILL.md": b"y"}
        with pytest.raises(fetched.TreeError, match="symlink"):
            t.read_folder("", 10, 100)


def test_truncated_skipped_list_fails_every_folder(fake, agent_settings):
    fake.publish("o/r", "c" * 40, {"skills/demo/SKILL.md": "x"}, ref="v3",
                 skipped=[{"path": "x/link", "reason": "symlink"}], truncated=True)
    with fetched.fetched(fake, agent_settings, "o", "r", "v3") as t:
        with pytest.raises(fetched.TreeError, match="too many links"):
            t.read_folder("skills/demo", 10, 100)


def test_planted_symlink_is_refused(fake, agent_settings, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_text("s")
    with fetched.fetched(fake, agent_settings, "o", "r") as t:
        try:
            os.symlink(outside, t.root / "skills" / "evil", target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("cannot create symlinks here")
        with pytest.raises(fetched.TreeError, match="symlink"):
            t.read("skills/evil/secret", 10)
        with pytest.raises(fetched.TreeError, match="symlink"):
            t.read_folder("skills", 10, 100)
        assert ("evil", "dir") not in t.listdir("skills")
