from functools import lru_cache
from typing import Self

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_ENV = "dev"
# Fields whose defaults are local-dev values; outside env=dev they must be set (non-empty, non-default).
DEV_ONLY_DEFAULTS = ("oidc_client_secret", "pii_hash_key", "cookie_secure")


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
    # Shared secret for the directory (and mock admin) API. Dev default only; set ITP_DIRECTORY_API_KEY.
    directory_api_key: str = "local-dev-directory-key"
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

    @model_validator(mode="after")
    def _refuse_dev_defaults_outside_dev(self) -> Self:
        if self.env == DEV_ENV:
            return self
        fields = type(self).model_fields
        bad = [k for k in DEV_ONLY_DEFAULTS if not getattr(self, k) or getattr(self, k) == fields[k].default]
        if bad:
            names = ", ".join(f"ITP_{k.upper()}" for k in bad)
            raise ValueError(f"refusing to start with env={self.env!r}: set {names} (dev defaults in effect)")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
