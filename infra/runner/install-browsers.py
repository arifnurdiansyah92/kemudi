"""Install the Chromium builds Playwright 1.59.1 expects (revision 1217).

Playwright's installer hangs while extracting on Node 26, so this does the same
job: download the two Chrome for Testing zips from Playwright's CDN and unpack
them into the directory layout Playwright resolves under
PLAYWRIGHT_BROWSERS_PATH. Update REVISION/VERSION together with apps/web's
playwright version (see node_modules/playwright-core/browsers.json).
"""

import os
import stat
import sys
import urllib.request
import zipfile
from pathlib import Path

REVISION = "1217"
VERSION = "147.0.7727.15"
BASE = f"https://cdn.playwright.dev/builds/cft/{VERSION}/linux64"
BUILDS = [
    (f"chromium-{REVISION}", "chrome-linux64.zip"),
    (f"chromium_headless_shell-{REVISION}", "chrome-headless-shell-linux64.zip"),
]


def unpack(zip_path: Path, dest: Path) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            target = dest / info.filename
            if not target.resolve().is_relative_to(dest.resolve()):
                raise SystemExit(f"unsafe path in zip: {info.filename}")
            zf.extract(info, dest)
            mode = (info.external_attr >> 16) & 0o777
            if mode and not info.is_dir():
                os.chmod(target, mode)


def main(root: str) -> None:
    for dirname, archive in BUILDS:
        dest = Path(root) / dirname
        dest.mkdir(parents=True, exist_ok=True)
        tmp = Path("/tmp") / archive
        print(f"downloading {archive}", flush=True)
        urllib.request.urlretrieve(f"{BASE}/{archive}", tmp)
        unpack(tmp, dest)
        tmp.unlink()
        (dest / "INSTALLATION_COMPLETE").touch()
        (dest / "DEPENDENCIES_VALIDATED").touch()
        for exe in dest.rglob("*"):
            if exe.name in ("chrome", "chrome-headless-shell", "chrome_crashpad_handler"):
                exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        print(f"installed {dirname}", flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
