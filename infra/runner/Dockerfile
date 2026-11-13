# kemudi-runner: runs branch code for the Awak loop (installs, gates, QA specs).
#
# Built from the Hermes image for its Node, git and system Chromium libraries.
# It holds no secrets; the orchestrator calls it over the internal network.
FROM kemudi/kemudi-hermes:dev

USER root
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    NPM_CONFIG_UPDATE_NOTIFIER=false \
    PNPM_HOME=/opt/pnpm
# Versions match apps/web (packageManager pnpm@10.30.1, playwright 1.59.1).
RUN npm install -g pnpm@10.30.1 @playwright/test@1.59.1 \
 && mkdir -p /ms-playwright /pnpm-store /workspace
# Playwright 1.59's own installer hangs while extracting on the image's Node 26,
# so fetch its pinned Chromium builds (revision 1217) and unpack them where
# Playwright looks. The Hermes image already has Chromium's system libraries.
COPY install-browsers.py /tmp/install-browsers.py
RUN /opt/hermes/.venv/bin/python3 /tmp/install-browsers.py /ms-playwright \
 && chown -R 10000:10000 /ms-playwright /pnpm-store /workspace

COPY --chmod=0755 runner.py /opt/runner/runner.py
COPY --chmod=0644 playwright.config.cjs /opt/runner/playwright.config.cjs

USER 10000:10000
WORKDIR /workspace
EXPOSE 8800
ENTRYPOINT ["/opt/hermes/.venv/bin/python3", "/opt/runner/runner.py"]
