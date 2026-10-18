from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Local-dev defaults. Everything is overridable via ITP_* env vars."""

    model_config = SettingsConfigDict(env_prefix="ITP_", env_file=None)

    env: str = "dev"
    database_url: str = "postgresql+psycopg://itp_app:itp_app@localhost:54320/itp"
    owner_database_url: str = "postgresql+psycopg://itp_owner:itp_owner@localhost:54320/itp"
    public_base_url: str = "http://localhost:5173"
    oidc_issuer: str = "http://localhost:8081/entra"
    oidc_client_id: str = "itp-local"
    oidc_client_secret: str = "local-dev-not-a-secret"  # noqa: S105 - mock IdP accepts any secret
    mocks_base_url: str = "http://localhost:8090"
    session_idle_minutes: int = 30
    session_absolute_hours: int = 8
    roles_revalidate_seconds: int = 60
    cookie_secure: bool = False
    # Keyed-hash secret for searchable PII hashes and audit diff fingerprints. Dev default only.
    pii_hash_key: str = "local-dev-pii-hash-key"
    files_dir: str = "var/files"
    rate_limit_default: str = "300/minute"
    rate_limit_sensitive: str = "30/minute"
    worker_poll_seconds: float = 0.5
    disable_scheduler: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
