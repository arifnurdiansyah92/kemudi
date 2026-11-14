# kemudi-svc: the only client of the sandboxed Docker daemon (kemudi-dind).
#
# The docker CLI with its compose and buildx plugins, plus Python for svc.py
# (stdlib only). It talks to kemudi-dind over the unix socket in
# DOCKER_HOST; the orchestrator calls it with KEMUDI_SVC_KEY. It never runs
# branch code: builds and containers run inside kemudi-dind. See svc.py.
FROM docker:27-cli

RUN apk add --no-cache python3

COPY --chmod=0644 svc.py sanitize.py /opt/svc/

# root, with only SETUID, SETGID, KILL and DAC_READ_SEARCH (compose:
# cap_drop ALL, cap_add those); the compose file is first read as uid 10000.
USER 0:0
WORKDIR /
EXPOSE 8810
ENTRYPOINT ["python3", "/opt/svc/svc.py"]
