FROM python:3.12-slim

# git: the Awak loop clones, fetches and pushes awak/* branches.
# openssh-client: deploy keys (git over SSH), machine preflight and deploy.
RUN apt-get update && apt-get install -y --no-install-recommends git openssh-client \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY kemudi_ai ./kemudi_ai
RUN uv sync --frozen --no-dev
ENV PATH="/opt/venv/bin:$PATH"
EXPOSE 8700
CMD ["uvicorn", "kemudi_ai.api:app", "--host", "0.0.0.0", "--port", "8700"]
