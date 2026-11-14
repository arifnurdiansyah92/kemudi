import logging
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Everything comes from the environment (infra/.env in the dev stack)."""

    model_config = SettingsConfigDict(env_prefix="KEMUDI_", extra="ignore")

    # dev (default) | production. In production the service refuses to start
    # with an empty or placeholder secret (`check_production`).
    env: str = "dev"
    # ai_calls keeps the full prompt and response only when this is on; off
    # (the default) keeps their SHA-256, token counts, cost and model.
    ai_log_prompts: bool = False
    # ai_calls older than this are deleted at start and daily; 0 keeps them.
    ai_log_retention_days: int = 90

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
    # Repos kemudi-runner fetched for the skill marketplace (the
    # kemudi-skills-fetch volume, read-only here; awak/fetched.py). Fetch
    # folders belong to skills_fetch_uid, the runner's fetch child.
    skills_fetch_dir: str = "/var/lib/kemudi-ai/skills-fetch"
    skills_fetch_uid: int = 10001
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
    # Shared bearer token Awak sends to /llm/v1 (infra/awak/config.yaml).
    # Required: empty closes the proxy (503).
    llm_proxy_token: str = ""
    # Upstream read timeout of the proxy (what kemudi-llm-proxy used).
    llm_proxy_timeout_s: float = 600.0

    # --- Awak usage and budget (kemudi_ai/awak/usage.py)
    # Model prices per 1M tokens, JSON, merged over the built-in table:
    # {"<model>": {"input": 0.28, "cached_input": 0.028, "output": 0.42,
    #  "currency": "USD"}}. currency USD or IDR. A model with no price has an
    # unknown cost (shown as such, never as 0).
    llm_prices: str = ""
    # USD prices are stored in Rupiah at this rate.
    usd_idr_rate: float = 16500.0
    # Ask the provider for usage in streamed answers (stream_options.include_usage).
    llm_stream_usage: bool = True
    # What the Agent settings suggest as a monthly budget when none is set.
    token_budget_recommended: int = 50_000_000

    # --- Awak skills (docs/superpowers/specs/2026-11-14-awak-skills-design.md)
    # Kemudi instance admins: they manage the skill library (project admins
    # only assign enabled skills). Taiga user ids (comma-separated; `GET
    # /api/kemudi/me` shows yours) are the primary match: a username can be
    # changed by its owner. Usernames are a fallback for a quick setup.
    admin_user_ids: str = ""
    admin_usernames: str = ""
    # Skill sets (/opt/skills/sets/<setid>, read-only in kemudi-awak at the
    # same path) and their Hermes profiles (kemudi-awak's /opt/data/profiles).
    awak_skills_dir: str = "/opt/skills"
    awak_profiles_dir: str = "/opt/awak-profiles"
    # How long a run waits for Hermes to serve a new profile (its watcher
    # rescans every 30 s).
    awak_profile_wait_s: float = 90.0

    def model_choices(self) -> list[str]:
        extra = [m.strip() for m in self.awak_models.split(",") if m.strip()]
        return list(dict.fromkeys([self.awak_model, self.qa_model, *extra]))

    def admin_user_id_set(self) -> set[int]:
        out: set[int] = set()
        for part in self.admin_user_ids.split(","):
            part = part.strip()
            if part.isdigit():
                out.add(int(part))
            elif part:
                logging.getLogger(__name__).warning(
                    "KEMUDI_ADMIN_USER_IDS: %r is not a Taiga user id; ignored", part)
        return out

    def admin_username_set(self) -> set[str]:
        return {u.strip() for u in self.admin_usernames.split(",") if u.strip()}

    def awak_project_slugs(self) -> list[str]:
        return [s.strip() for s in self.awak_projects.split(",") if s.strip()]


# Values that are never a real secret: .env.example placeholders and the like.
_PLACEHOLDERS = {"unset", "none", "null", "secret", "password", "default", "test", "dev",
                 "example", "xxx", "todo"}
_PLACEHOLDER_PREFIXES = ("change-me", "changeme", "change_me", "replace-me", "replaceme",
                         "your-", "<")


def is_placeholder(value: str) -> bool:
    v = (value or "").strip().lower()
    return not v or v in _PLACEHOLDERS or v.startswith(_PLACEHOLDER_PREFIXES)


class InsecureConfig(RuntimeError):
    """A production start with a missing or placeholder secret."""


def production_problems(settings: Settings) -> list[str]:
    """Why this configuration must not run in production; [] outside it."""
    if settings.env.strip().lower() not in ("production", "prod"):
        return []
    problems = []
    if is_placeholder(settings.secret_key):
        problems.append("KEMUDI_SECRET_KEY is empty or a placeholder (generate a Fernet key: "
                        "python -c \"from cryptography.fernet import Fernet; "
                        "print(Fernet.generate_key().decode())\")")
    else:
        from cryptography.fernet import Fernet

        try:
            Fernet(settings.secret_key.strip().encode())
        except (ValueError, TypeError):
            problems.append("KEMUDI_SECRET_KEY is not a valid Fernet key")
    if is_placeholder(settings.llm_proxy_token):
        problems.append("KEMUDI_LLM_PROXY_TOKEN is empty or a placeholder "
                        "(openssl rand -hex 32)")
    return problems


def check_production(settings: Settings) -> None:
    """Raises InsecureConfig (and logs it) when KEMUDI_ENV=production and a
    required secret is empty or a known placeholder."""
    problems = production_problems(settings)
    if problems:
        message = ("refusing to start with KEMUDI_ENV=production: " + "; ".join(problems))
        logging.getLogger(__name__).critical(message)
        raise InsecureConfig(message)


@lru_cache
def get_settings() -> Settings:
    return Settings()
