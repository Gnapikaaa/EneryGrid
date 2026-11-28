import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.constants import Environment, validate_iso4217_currency

_VALID_TEST_DB_URL = "postgresql+psycopg://user:pass@localhost:5432/energygrid_test"
_STRONG_SECRET = "a-very-strong-production-signing-key-64-bytes-long-1234567890"


def test_production_blocks_dev_auth_bypass() -> None:
    with pytest.raises(ValidationError, match="ALLOW_DEV_AUTH_BYPASS"):
        Settings(
            _env_file=None,
            environment=Environment.PRODUCTION,
            database_url=_VALID_TEST_DB_URL,
            jwt_secret_key=_STRONG_SECRET,
            allow_dev_auth_bypass=True,
        )


def test_staging_blocks_weak_jwt_secret() -> None:
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY"):
        Settings(
            _env_file=None,
            environment=Environment.STAGING,
            database_url=_VALID_TEST_DB_URL,
            jwt_secret_key="change-me-in-local-dev-only-at-least-32-bytes",
            allow_dev_auth_bypass=False,
        )


def test_production_accepts_hardened_configuration() -> None:
    settings = Settings(
        _env_file=None,
        environment=Environment.PRODUCTION,
        database_url=_VALID_TEST_DB_URL,
        jwt_secret_key=_STRONG_SECRET,
        allow_dev_auth_bypass=False,
        allowed_origins="https://energygrid.example.com,https://app.energygrid.example.com",
        cors_allow_credentials=True,
    )
    assert settings.environment == Environment.PRODUCTION
    assert settings.allowed_origins == [
        "https://energygrid.example.com",
        "https://app.energygrid.example.com",
    ]


def test_wildcard_cors_rejected_with_credentials() -> None:
    with pytest.raises(ValidationError, match="ALLOWED_ORIGINS"):
        Settings(
            _env_file=None,
            environment=Environment.DEVELOPMENT,
            database_url=_VALID_TEST_DB_URL,
            allowed_origins=["*"],
            cors_allow_credentials=True,
        )


def test_iso4217_currency_validation() -> None:
    assert validate_iso4217_currency("inr") == "INR"
    assert validate_iso4217_currency(" USD ") == "USD"
    assert validate_iso4217_currency("EUR") == "EUR"

    for invalid in ("", "IN", "XYZ", "123", "EURO"):
        with pytest.raises(ValueError, match="Unsupported currency code"):
            validate_iso4217_currency(invalid)


def test_jwt_algorithm_and_expiration_validation() -> None:
    with pytest.raises(ValidationError, match="JWT_ALGORITHM"):
        Settings(
            _env_file=None,
            environment=Environment.DEVELOPMENT,
            database_url=_VALID_TEST_DB_URL,
            jwt_algorithm="none",
        )

    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            environment=Environment.DEVELOPMENT,
            database_url=_VALID_TEST_DB_URL,
            access_token_expire_minutes=0,
        )


def test_allowed_origins_dotenv_formats(tmp_path) -> None:
    csv_env = tmp_path / ".env.csv"
    csv_env.write_text(
        f"DATABASE_URL={_VALID_TEST_DB_URL}\n"
        "ALLOWED_ORIGINS=http://localhost:3000, http://127.0.0.1:3000\n",
        encoding="utf-8",
    )
    s_csv = Settings(_env_file=csv_env)
    assert s_csv.allowed_origins == ["http://localhost:3000", "http://127.0.0.1:3000"]

    json_env = tmp_path / ".env.json"
    json_env.write_text(
        f"DATABASE_URL={_VALID_TEST_DB_URL}\n"
        'ALLOWED_ORIGINS=["http://localhost:3000","http://127.0.0.1:3000"]\n',
        encoding="utf-8",
    )
    s_json = Settings(_env_file=json_env)
    assert s_json.allowed_origins == ["http://localhost:3000", "http://127.0.0.1:3000"]

    empty_env = tmp_path / ".env.empty"
    empty_env.write_text(
        f"DATABASE_URL={_VALID_TEST_DB_URL}\n"
        "ALLOWED_ORIGINS=\n",
        encoding="utf-8",
    )
    s_empty = Settings(_env_file=empty_env)
    assert s_empty.allowed_origins == []


