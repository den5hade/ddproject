import logging

import pytest
from app.core.config import Settings

logger_name = "app.core.config"

VALID_SECRETS = {
    "jwt_secret_key": "jwt-" + "a" * 32,
    "auth_hmac_key": "hmac-" + "b" * 32,
    "auth_otp_pepper": "otp-pepper-" + "c" * 32,
    "auth_pin_pepper": "pin-pepper-" + "d" * 32,
    "integration_api_hmac_key": "ioapihmac-" + "e" * 32,
    "postgres_password": "pg-prod-pass-1",
    "rabbitmq_password": "rmq-prod-pass-1",
    "s3_key_secret": "s3-prod-secret-1",
}

SENSITIVE_ENV_VARS = [
    "APP_ENV",
    "ENVIRONMENT",
    "DEBUG",
    "JWT_SECRET_KEY",
    "AUTH_HMAC_KEY",
    "AUTH_OTP_PEPPER",
    "AUTH_PIN_PEPPER",
    "INTEGRATION_API_HMAC_KEY",
    "POSTGRES_PASSWORD",
    "DATABASE_URL",
    "RABBITMQ_URL",
    "RABBITMQ_HOST",
    "RABBITMQ_USER",
    "RABBITMQ_PASSWORD",
    "S3_ENDPOINT_URL",
    "S3_KEY_ID",
    "S3_KEY_SECRET",
    "S3_BUCKET_NAME",
    "AI_FEATURE",
    "AI_API_KEY",
]


def _make_settings(monkeypatch, **overrides) -> Settings:
    for var in SENSITIVE_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    values = {**VALID_SECRETS, **overrides}
    return Settings(_env_file=None, **values)


def test_production_boots_with_valid_secrets(monkeypatch):
    settings = _make_settings(monkeypatch, environment="production")
    assert settings.environment == "production"


def test_production_fails_on_empty_secret(monkeypatch):
    with pytest.raises(RuntimeError, match="jwt_secret_key"):
        _make_settings(monkeypatch, environment="production", jwt_secret_key="")


def test_production_fails_on_placeholder(monkeypatch):
    with pytest.raises(RuntimeError, match="postgres_password"):
        _make_settings(
            monkeypatch, environment="production", postgres_password="pdf123"
        )
    with pytest.raises(RuntimeError, match="rabbitmq_password"):
        _make_settings(
            monkeypatch,
            environment="production",
            rabbitmq_password="super-secret-dev-password",
        )


def test_production_fails_on_short_key(monkeypatch):
    with pytest.raises(RuntimeError, match="auth_hmac_key"):
        _make_settings(monkeypatch, environment="production", auth_hmac_key="short")


def test_production_fails_on_duplicate_secrets(monkeypatch):
    with pytest.raises(RuntimeError, match="auth_otp_pepper.*must differ"):
        _make_settings(
            monkeypatch,
            environment="production",
            auth_otp_pepper=VALID_SECRETS["auth_hmac_key"],
        )


def test_production_error_message_never_contains_secret_value(monkeypatch):
    weak_secret = "short-but-real-looking-secret"
    with pytest.raises(RuntimeError) as exc_info:
        _make_settings(monkeypatch, environment="production", auth_hmac_key=weak_secret)
    assert weak_secret not in str(exc_info.value)


def test_development_warns_instead_of_raising(monkeypatch, caplog):
    with caplog.at_level(logging.WARNING, logger=logger_name):
        settings = _make_settings(
            monkeypatch,
            environment="development",
            jwt_secret_key="",
            auth_hmac_key="short",
        )
    assert settings.environment == "development"
    messages = [record.getMessage() for record in caplog.records]
    assert any("insecure settings detected" in message for message in messages)
    assert any("jwt_secret_key" in message for message in messages)


def test_debug_flag_does_not_bypass_production_checks(monkeypatch):
    with pytest.raises(RuntimeError, match="jwt_secret_key"):
        _make_settings(
            monkeypatch,
            environment="production",
            debug=True,
            jwt_secret_key="",
        )


def test_unknown_environment_rejected(monkeypatch):
    with pytest.raises(ValueError, match="unsupported environment"):
        _make_settings(monkeypatch, environment="staging")


def test_app_env_alias_wiring(monkeypatch):
    for var in SENSITIVE_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    for name, value in {**VALID_SECRETS}.items():
        monkeypatch.setenv(name.upper(), value)
    assert Settings(_env_file=None).environment == "production"


def test_rabbitmq_url_skips_password_check(monkeypatch):
    settings = _make_settings(
        monkeypatch,
        environment="production",
        rabbitmq_password="",
        rabbitmq_url="amqp://user:pass@broker:5672/vhost",
    )
    assert settings.rabbitmq_dsn == "amqp://user:pass@broker:5672/vhost"


def test_s3_credentials_required_only_when_enabled(monkeypatch):
    with pytest.raises(RuntimeError, match="s3_key_id"):
        _make_settings(
            monkeypatch,
            environment="production",
            s3_endpoint_url="https://s3.example.com",
            s3_key_id="",
        )
    settings = _make_settings(
        monkeypatch,
        environment="production",
        s3_endpoint_url="https://s3.example.com",
        s3_key_id="s3-key-id-1",
        s3_bucket_name="docs-prod",
    )
    assert settings.s3_key_id == "s3-key-id-1"


def test_ai_api_key_required_only_when_feature_enabled(monkeypatch):
    with pytest.raises(RuntimeError, match="ai_api_key"):
        _make_settings(
            monkeypatch,
            environment="production",
            ai_feature=True,
            ai_api_key="",
        )
