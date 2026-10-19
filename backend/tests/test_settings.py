import pytest
from pydantic import ValidationError

from app.foundation.settings import Settings

PROD_OVERRIDES = {
    "ITP_ENV": "prod",
    "ITP_PII_HASH_KEY": "k" * 32,
    "ITP_OIDC_CLIENT_SECRET": "s" * 32,
    "ITP_DIRECTORY_API_KEY": "d" * 32,
    "ITP_COOKIE_SECURE": "true",
}


def _set(monkeypatch: pytest.MonkeyPatch, env: dict[str, str]) -> None:
    for k, v in env.items():
        monkeypatch.setenv(k, v)


def test_dev_defaults_allowed_in_dev(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ITP_ENV", raising=False)
    assert Settings().env == "dev"


def test_non_dev_with_all_overrides_boots(monkeypatch: pytest.MonkeyPatch) -> None:
    _set(monkeypatch, PROD_OVERRIDES)
    s = Settings()
    assert s.cookie_secure is True


@pytest.mark.parametrize(
    "missing",
    [
        ("ITP_PII_HASH_KEY", "local-dev-pii-hash-key"),
        ("ITP_OIDC_CLIENT_SECRET", "local-dev-not-a-secret"),
        ("ITP_DIRECTORY_API_KEY", "local-dev-directory-key"),
        ("ITP_COOKIE_SECURE", "false"),
    ],
)
def test_non_dev_refuses_each_dev_default(monkeypatch: pytest.MonkeyPatch, missing: tuple[str, str]) -> None:
    _set(monkeypatch, PROD_OVERRIDES)
    name, dev_value = missing
    monkeypatch.setenv(name, dev_value)
    with pytest.raises(ValidationError, match=name):
        Settings()


def test_non_dev_with_no_overrides_lists_all(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in PROD_OVERRIDES:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ITP_ENV", "staging")
    with pytest.raises(ValidationError) as e:
        Settings()
    msg = str(e.value)
    names = ("ITP_PII_HASH_KEY", "ITP_OIDC_CLIENT_SECRET", "ITP_DIRECTORY_API_KEY", "ITP_COOKIE_SECURE")
    assert all(n in msg for n in names)


@pytest.mark.parametrize("name", ["ITP_PII_HASH_KEY", "ITP_OIDC_CLIENT_SECRET", "ITP_DIRECTORY_API_KEY"])
def test_non_dev_refuses_empty_or_short_secret(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    _set(monkeypatch, PROD_OVERRIDES)
    for bad in ("", "x" * 31):
        monkeypatch.setenv(name, bad)
        with pytest.raises(ValidationError, match=name):
            Settings()


@pytest.mark.parametrize("env", ["prod", "staging", "Dev", "development", ""])
def test_any_env_other_than_dev_is_checked(monkeypatch: pytest.MonkeyPatch, env: str) -> None:
    for k in PROD_OVERRIDES:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ITP_ENV", env)
    with pytest.raises(ValidationError, match="ITP_DIRECTORY_API_KEY"):
        Settings()
