"""The compose sanitizer (sanitize.py) on JSON fixtures: no Docker.

playfast.json is `docker compose config --no-interpolate --format json` of
playfast's compose file (defaults trimmed), with the checkout as @CHECKOUT@.
"""

import copy
import json
import os
from pathlib import Path

import pytest

from conftest import FIXTURES, load

sanitize = load("kemudi_svc_sanitize", "sanitize.py")
Refused = sanitize.Refused


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / "ws" / "playfast" / "us-1" / "pf-web"
    for sub in ("backend", "frontend", "sales-inbox/backend", "sales-inbox/frontend"):
        (root / sub).mkdir(parents=True)
    for f in ("backend/Dockerfile", "frontend/Dockerfile", "sales-inbox/backend/Dockerfile",
              "sales-inbox/frontend/Dockerfile", "docker-compose.yml"):
        (root / f).write_text("FROM scratch\n")
    return root


@pytest.fixture
def doc(checkout):
    text = (FIXTURES / "playfast.json").read_text(encoding="utf-8")
    return json.loads(text.replace("@CHECKOUT@", checkout.as_posix()))


def test_playfast_reduced_to_postgres_redis_backend(doc, checkout):
    reduced = sanitize.reduce(doc, ["backend"], checkout)
    assert list(reduced["services"]) == ["backend", "postgres", "redis"]
    assert set(reduced) == {"services", "volumes"}
    assert reduced["volumes"] == {"pgdata": {}, "uploads": {}}
    for s in reduced["services"].values():
        assert not {"networks", "logging", "labels", "container_name"} & set(s)
    # the unselected services, and their `:?` variables, are gone untouched
    text = json.dumps(reduced)
    assert "INBOX_SSO_SECRET:?" not in text and "inbox-backend" not in text
    assert "inbox_media" not in text
    # the selected one's `:?` stays for compose to interpolate
    assert reduced["services"]["backend"]["environment"]["JWT_SECRET_KEY"].startswith(
        "${JWT_SECRET_KEY:?")


def test_rewrite(doc, checkout):
    reduced = sanitize.reduce(doc, ["backend"], checkout)
    reduced["services"]["redis"]["mem_limit"] = "512m"
    reduced["services"]["postgres"]["mem_limit"] = "8g"
    reduced["services"]["postgres"]["pids_limit"] = 4096
    # what interpolation adds back
    reduced["name"] = "playfast-us1"
    reduced["networks"] = {"default": {"name": "playfast-us1_default"}}
    for s in reduced["services"].values():
        s["networks"] = {"default": None}
    out = sanitize.rewrite(reduced, "playfast-us1", ("backend", 5000))

    assert out["name"] == "playfast-us1" and "networks" not in out
    b, pg, rd = (out["services"][n] for n in ("backend", "postgres", "redis"))
    assert b["image"] == "kemudi-playfast-us1-backend"
    assert b["build"]["labels"] == {"kemudi.project": "playfast-us1"}
    assert b["ports"] == ["0.0.0.0::5000"]
    assert "ports" not in pg and "ports" not in rd
    for s in (b, pg, rd):
        assert s["restart"] == "no" and s["labels"] == {"kemudi.project": "playfast-us1"}
        assert "networks" not in s
    assert b["mem_limit"] == sanitize.MEM_CAP and pg["mem_limit"] == sanitize.MEM_CAP
    assert rd["mem_limit"] == 512 * 1024 ** 2
    assert pg["pids_limit"] == 512 and b["pids_limit"] == 512
    assert pg["image"] == "postgres:17-alpine"
    assert out["volumes"] == {v: {"labels": {"kemudi.project": "playfast-us1"}}
                              for v in ("pgdata", "uploads")}

    with pytest.raises(Refused, match="expose"):
        sanitize.rewrite(reduced, "playfast-us1", ("frontend", 3000))


REFUSED_SERVICE_KEYS = {
    "privileged": True, "cap_add": ["SYS_ADMIN"], "devices": ["/dev/kmsg"],
    "device_cgroup_rules": ["a *:* rwm"], "security_opt": ["seccomp=unconfined"],
    "pid": "host", "ipc": "host", "network_mode": "host", "userns_mode": "host",
    "uts": "host", "cgroup": "host", "cgroup_parent": "x", "volumes_from": ["redis"],
    "extra_hosts": ["a:1.2.3.4"], "sysctls": {"net.ipv4.ip_forward": "1"},
    "runtime": "runc", "isolation": "default", "env_file": [{"path": "/run/svc/x"}],
    "secrets": [{"source": "s"}], "configs": [{"source": "c"}], "hostname": "x",
    "extends": {"service": "redis"}, "init": True, "platform": "linux/amd64",
}


@pytest.mark.parametrize("key", sorted(REFUSED_SERVICE_KEYS))
def test_refused_service_key(doc, checkout, key):
    doc["services"]["backend"][key] = REFUSED_SERVICE_KEYS[key]
    with pytest.raises(Refused, match=f"service 'backend': key '{key}' is not allowed"):
        sanitize.reduce(doc, ["backend"], checkout)
    # the same key in a service that is not started does not matter
    d2 = copy.deepcopy(doc)
    del d2["services"]["backend"][key]
    d2["services"]["inbox-frontend"][key] = REFUSED_SERVICE_KEYS[key]
    sanitize.reduce(d2, ["backend"], checkout)


def test_refused_in_a_dependency(doc, checkout):
    doc["services"]["postgres"]["privileged"] = True
    with pytest.raises(Refused, match="service 'postgres': key 'privileged'"):
        sanitize.reduce(doc, ["backend"], checkout)


@pytest.mark.parametrize("key", ["network", "dockerfile_inline", "ssh", "secrets",
                                 "additional_contexts", "privileged", "entitlements"])
def test_refused_build_key(doc, checkout, key):
    doc["services"]["backend"]["build"][key] = "host"
    with pytest.raises(Refused, match=f"key 'build.{key}' is not allowed"):
        sanitize.reduce(doc, ["backend"], checkout)


@pytest.mark.parametrize("key", ["secrets", "configs", "include", "extends", "version_x"])
def test_refused_top_level_key(doc, checkout, key):
    doc[key] = {}
    with pytest.raises(Refused, match=f"top-level key '{key}'"):
        sanitize.reduce(doc, ["backend"], checkout)


def test_extensions_dropped(doc, checkout):
    doc["x-common"] = {"a": 1}
    doc["services"]["backend"]["x-note"] = "hi"
    reduced = sanitize.reduce(doc, ["backend"], checkout)
    assert "x-note" not in reduced["services"]["backend"] and "x-common" not in reduced


@pytest.mark.parametrize("spec,match", [
    ({"driver": "local"}, "key 'driver'"),
    ({"driver_opts": {"type": "none", "o": "bind", "device": "/"}}, "key 'driver_opts'"),
    ({"external": True}, "key 'external'"),
    ({"name": "someone-elses-volume"}, "key 'name'"),
])
def test_refused_volume_keys(doc, checkout, spec, match):
    doc["volumes"]["pgdata"] = spec
    with pytest.raises(Refused, match=f"volume 'pgdata': {match}"):
        sanitize.reduce(doc, ["backend"], checkout)


def test_unused_volume_is_not_checked(doc, checkout):
    doc["volumes"]["inbox_media"] = {"external": True}
    assert "inbox_media" not in sanitize.reduce(doc, ["backend"], checkout)["volumes"]


@pytest.mark.parametrize("mount,match", [
    ({"type": "bind", "source": "/", "target": "/host"}, "only named volumes and tmpfs"),
    ({"type": "npipe", "source": "x", "target": "/x"}, "only named volumes and tmpfs"),
    ({"type": "volume", "source": "nope", "target": "/x"}, "not a named volume"),
    ({"type": "volume", "source": "pgdata", "target": "/x", "bind": {}}, "volumes\\[\\].bind"),
    ({"type": "volume", "source": "pgdata", "target": "/x", "volume": {"driver": "x"}},
     "volumes\\[\\].volume.driver"),
    ("/:/host", "long form"),
])
def test_refused_mounts(doc, checkout, mount, match):
    doc["services"]["backend"]["volumes"].append(mount)
    with pytest.raises(Refused, match=match):
        sanitize.reduce(doc, ["backend"], checkout)


def test_allowed_mounts(doc, checkout):
    doc["services"]["backend"]["volumes"] += [
        {"type": "volume", "target": "/anon", "volume": {}},
        {"type": "tmpfs", "target": "/scratch", "tmpfs": {"size": 1000}},
        {"type": "volume", "source": "pgdata", "target": "/ro", "read_only": True},
    ]
    doc["services"]["backend"]["tmpfs"] = ["/run:size=10m"]
    sanitize.reduce(doc, ["backend"], checkout)


@pytest.mark.parametrize("context", ["/etc", "@PARENT@", "@CHECKOUT@/../other",
                                     "@CHECKOUT@/missing", "https://github.com/x/y.git",
                                     "git@github.com:x/y.git"])
def test_build_context_outside_the_checkout(doc, checkout, context):
    doc["services"]["backend"]["build"]["context"] = (
        context.replace("@CHECKOUT@", checkout.as_posix())
        .replace("@PARENT@", checkout.parent.as_posix()))
    (checkout.parent / "other").mkdir(exist_ok=True)
    with pytest.raises(Refused, match="build.context"):
        sanitize.reduce(doc, ["backend"], checkout)


@pytest.mark.parametrize("dockerfile", ["../../Dockerfile", "missing/Dockerfile", "backend",
                                        "/etc/passwd"])
def test_dockerfile_outside_the_checkout(doc, checkout, dockerfile):
    (checkout.parent / "Dockerfile").write_text("FROM scratch\n")
    doc["services"]["backend"]["build"]["dockerfile"] = dockerfile
    with pytest.raises(Refused, match="build.dockerfile"):
        sanitize.reduce(doc, ["backend"], checkout)


def _symlink(link: Path, target: Path) -> None:
    try:
        os.symlink(target, link, target_is_directory=target.is_dir())
    except (OSError, NotImplementedError):
        pytest.skip("cannot create symlinks here")


def test_build_context_through_a_symlink(doc, checkout, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "Dockerfile").write_text("FROM scratch\n")
    _symlink(checkout / "link", outside)
    doc["services"]["backend"]["build"] = {"context": (checkout / "link").as_posix()}
    with pytest.raises(Refused, match="symlink"):
        sanitize.reduce(doc, ["backend"], checkout)
    # a symlinked Dockerfile in a real folder, too
    _symlink(checkout / "backend" / "Dockerfile.link", outside / "Dockerfile")
    doc["services"]["backend"]["build"] = {"context": checkout.as_posix(),
                                           "dockerfile": "backend/Dockerfile.link"}
    with pytest.raises(Refused, match="symlink"):
        sanitize.reduce(doc, ["backend"], checkout)


def test_service_needs_image_or_build_and_kemudi_images_are_reserved(doc, checkout):
    doc["services"]["redis"]["image"] = "kemudi-other-us2-backend"
    with pytest.raises(Refused, match="reserved"):
        sanitize.reduce(doc, ["backend"], checkout)
    del doc["services"]["redis"]["image"]
    with pytest.raises(Refused, match="needs an image or a build"):
        sanitize.reduce(doc, ["backend"], checkout)


def test_closure(doc, checkout):
    assert sanitize.closure(doc["services"], ["frontend"]) == [
        "frontend", "backend", "postgres", "redis"]
    with pytest.raises(Refused, match="no service 'nope'"):
        sanitize.reduce(doc, ["nope"], checkout)


def test_depends_on_keys(doc, checkout):
    doc["services"]["backend"]["depends_on"]["redis"]["weird"] = 1
    with pytest.raises(Refused, match="depends_on.redis.weird"):
        sanitize.reduce(doc, ["backend"], checkout)


@pytest.mark.parametrize("text", [
    "include:\n  - other.yml\nservices: {}\n",
    "services:\n  a:\n    extends:\n      file: /run/svc/x/compose.json\n",
    "services:\n  a:\n    env_file: .env\n",
    "services:\n  a: {label_file: x}\n",
    '{"services": {"a": {"extends": {"file": "x"}}}}',
])
def test_precheck_refuses_keys_that_read_other_files(text):
    with pytest.raises(Refused, match="is not allowed"):
        sanitize.precheck_text(text)


def test_precheck_ignores_comments():
    sanitize.precheck_text("services:\n  a:\n    # env_file: .env\n    image: x\n")


def test_compose_file(checkout):
    assert sanitize.compose_file(checkout, None) == checkout / "docker-compose.yml"
    for bad in ("../x.yml", "/etc/passwd", "a/../docker-compose.yml", "C:x", "missing.yml",
                "backend", "./docker-compose.yml"):
        with pytest.raises(Refused):
            sanitize.compose_file(checkout, bad)


def test_request_values():
    assert sanitize.project_name("playfast-us1") == "playfast-us1"
    for bad in ("", "Playfast", "-x", "a_b", "x" * 64, "../x"):
        with pytest.raises(Refused):
            sanitize.project_name(bad)
    assert sanitize.parse_expose("backend:5000") == ("backend", 5000)
    assert sanitize.parse_expose(None) is None
    for bad in ("backend", "backend:0", "backend:70000", ":80", "a b:80"):
        with pytest.raises(Refused):
            sanitize.parse_expose(bad)
    with pytest.raises(Refused):
        sanitize.service_names([])
    with pytest.raises(Refused):
        sanitize.service_names(["ok", "../x"])
    assert sanitize.service_names(["a", "b", "a"]) == ["a", "b"]


@pytest.mark.parametrize("name", ["KEMUDI_SVC_KEY", "DOCKER_HOST", "COMPOSE_FILE", "GIT_DIR",
                                  "PATH", "HOME", "LD_PRELOAD", "BUILDKIT_HOST", "1X", "A-B"])
def test_request_env_refuses(name):
    with pytest.raises(Refused):
        sanitize.request_env({name: "v"})


def test_env_file_text_escapes():
    value = 'a$b"c\\d\ne' + "'f"
    text = sanitize.env_file_text({"JWT_SECRET_KEY": value, "EMPTY": ""})
    assert text == 'JWT_SECRET_KEY="a\\$b\\"c\\\\d\\ne\'f"\nEMPTY=""\n'


def test_redact():
    token = "tok" + "en-" + "12345"
    out = sanitize.redact(f"login {token} ok {token[:6]} abc", [token, token[:6], "abc", ""])
    assert out == "login [redacted] ok [redacted] abc"


def test_parse_bytes():
    assert sanitize.parse_bytes("2g") == 2 * 1024 ** 3
    assert sanitize.parse_bytes("512m") == 512 * 1024 ** 2
    assert sanitize.parse_bytes("1073741824") == 1024 ** 3
    assert sanitize.parse_bytes(1000) == 1000
    assert sanitize.parse_bytes(None) is None
    with pytest.raises(Refused):
        sanitize.parse_bytes("lots")


def test_rewrite_environment_overrides(doc, checkout):
    reduced = sanitize.reduce(doc, ["backend"], checkout)
    over = sanitize.request_environment(
        {"backend": {"DATABASE_URL": "postgresql+psycopg2://pg/db", "PRICE": "$5"}})
    out = sanitize.rewrite(reduced, "playfast-us1", ("backend", 5000), over)
    env = out["services"]["backend"]["environment"]
    assert env["DATABASE_URL"] == "postgresql+psycopg2://pg/db"
    assert env["PRICE"] == "$$5"  # compose reads the final file again
    assert "JWT_SECRET_KEY" in env  # the rest of the service's environment stays
    assert "DATABASE_URL" not in (out["services"]["postgres"].get("environment") or {})


@pytest.mark.parametrize("raw", [[], {"backend": []}, {"bad name!": {}},
                                 {"backend": {"DOCKER_HOST": "x"}}, {"backend": {"A": 1}}])
def test_request_environment_refuses(raw):
    with pytest.raises(sanitize.Refused):
        sanitize.request_environment(raw)


def test_rewrite_environment_unknown_service(doc, checkout):
    reduced = sanitize.reduce(doc, ["backend"], checkout)
    with pytest.raises(sanitize.Refused):
        sanitize.rewrite(reduced, "p", None, {"inbox-backend": {"A": "b"}})
