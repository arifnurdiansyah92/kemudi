from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Everything comes from the environment (infra/.env in the dev stack)."""

    model_config = SettingsConfigDict(env_prefix="KEMUDI_", extra="ignore")

    hermes_url: str = "http://localhost:8642/v1"
    hermes_api_key: str = ""
    ai_model: str = "deepseek-flash"
    ai_db_url: str = "sqlite:///data/kemudi-ai.db"
    taiga_api_url: str = "http://localhost:9100/api/v1"
    # Rough cost estimate for the audit log; 0 means "not tracked".
    token_price_idr_per_1k: float = 0.0
    llm_timeout_s: float = 180.0

    # --- Awak dev loop (docs/superpowers/specs/2026-11-13-awak-dev-loop-design.md)
    # Comma-separated project slugs the worker serves; empty = worker off.
    awak_projects: str = ""
    awak_username: str = "awak"
    awak_password: str = ""
    qa_username: str = "awak-qa"
    qa_password: str = ""
    qa_project: str = "awak-qa-sandbox"
    awak_url: str = "http://kemudi-awak:8642/v1"
    awak_api_key: str = ""
    awak_model: str = "deepseek-flash"
    qa_model: str = "deepseek-flash"
    awak_timeout_s: float = 1500.0
    runner_url: str = "http://kemudi-runner:8800"
    runner_key: str = ""
    # kemudi-svc (infra/svc): the only client of the sandboxed Docker daemon
    # (kemudi-dind); starts a project's compose services. Own key.
    svc_url: str = "http://kemudi-svc:8810"
    svc_key: str = ""
    workspace_dir: str = "/workspace"
    bare_repo: str = "/var/lib/kemudi-ai/awak.git"
    host_git: str = "/host-git"
    awak_uid: int = 10000
    poll_interval_s: float = 20.0
    max_attempts: int = 3
    max_infra_errors: int = 3
    lang: str = "id"

    # --- Awak project setup (docs/superpowers/specs/2026-11-14-awak-project-setup-design.md)
    # Fernet key (urlsafe base64, 32 bytes) that encrypts generated SSH keys at
    # rest. Empty = key generation and key use answer 503.
    secret_key: str = ""
    ssh_dir: str = "/var/lib/kemudi-ai/ssh"
    repos_dir: str = "/var/lib/kemudi-ai/repos"
    # Extra models offered in the role editor (comma-separated), besides
    # awak_model and qa_model.
    awak_models: str = ""

    # --- Awak BYOK (docs/superpowers/specs/2026-11-14-awak-byok-design.md)
    # The server-default model connection, used when neither the agent nor the
    # project sets one. Awak reaches every connection through the orchestrator's
    # /llm/v1 proxy, which adds the key.
    ai_base_url: str = ""
    ai_api_key: str = ""
    # Shared bearer token Awak sends to /llm/v1 (infra/awak/config.yaml). Empty
    # = the per-run alias alone admits a request (dev only).
    llm_proxy_token: str = ""
    # Upstream read timeout of the proxy (what kemudi-llm-proxy used).
    llm_proxy_timeout_s: float = 600.0

    def model_choices(self) -> list[str]:
        extra = [m.strip() for m in self.awak_models.split(",") if m.strip()]
        return list(dict.fromkeys([self.awak_model, self.qa_model, *extra]))

    def awak_project_slugs(self) -> list[str]:
        return [s.strip() for s in self.awak_projects.split(",") if s.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
