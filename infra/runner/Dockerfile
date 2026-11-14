# kemudi-runner: runs branch code for the Awak loop (installs, gates, QA specs).
#
# Built from the Hermes image for its Node, git and system Chromium libraries.
# The orchestrator calls it over the internal network with KEMUDI_RUNNER_KEY.
#
# The server runs as root with only SETUID, SETGID and KILL (compose:
# cap_drop ALL, cap_add those three, no-new-privileges); every child it starts
# (branch code, process services, Playwright, git) runs as 10000:10000 with a
# clean environment, so no child can read the key from /proc/<pid>/environ.
# See runner.py's module doc.
FROM kemudi/kemudi-hermes:dev

USER root
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    NPM_CONFIG_UPDATE_NOTIFIER=false \
    PNPM_HOME=/opt/pnpm \
    RUNNER_CHILD_UID=10000 \
    RUNNER_CHILD_GID=10000
# Versions match apps/web (packageManager pnpm@10.30.1, playwright 1.59.1).
RUN npm install -g pnpm@10.30.1 @playwright/test@1.59.1 \
 && ln -sf "$(npm prefix -g)/bin/pnpm" /usr/local/bin/pnpm \
 && mkdir -p /ms-playwright /pnpm-store /workspace
# Playwright 1.59's own installer hangs while extracting on the image's Node 26,
# so fetch its pinned Chromium builds (revision 1217) and unpack them where
# Playwright looks. The Hermes image already has Chromium's system libraries.
COPY install-browsers.py /tmp/install-browsers.py
RUN /opt/hermes/.venv/bin/python3 /tmp/install-browsers.py /ms-playwright \
 && chown -R 10000:10000 /ms-playwright /pnpm-store /workspace

COPY --chmod=0755 runner.py /opt/runner/runner.py
COPY --chmod=0644 playwright.config.cjs login.cjs screenshot.cjs /opt/runner/

# root, for the uid switch; the workspace and caches stay owned by 10000.
USER 0:0
WORKDIR /workspace
EXPOSE 8800
ENTRYPOINT ["/opt/hermes/.venv/bin/python3", "/opt/runner/runner.py"]
