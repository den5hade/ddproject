import logging
from functools import cached_property

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

ENVIRONMENTS = ("development", "production")
MIN_SECRET_LENGTH = 32

_KEY_SETTINGS = (
    "jwt_secret_key",
    "auth_hmac_key",
    "auth_otp_pepper",
    "auth_pin_pepper",
    "integration_api_hmac_key",
)
_EXACT_PLACEHOLDERS = frozenset({"pdf123", "minioadmin", "change-me-in-production"})
_PLACEHOLDER_PREFIXES = ("change-me", "super-secret-")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    app_name: str = "ddproject"
    debug: bool = False
    environment: str = Field(
        default="development",
        validation_alias=AliasChoices("APP_ENV", "ENVIRONMENT"),
    )
    api_prefix: str = "/api/v1"
    api_timezone: str = "Europe/Moscow"

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    log_level: str = "INFO"
    log_to_file: bool = False
    log_dir: str = "logs"
    log_max_bytes: int = 10 * 1024 * 1024
    log_backup_count: int = 5
    enable_request_logging: bool = True
    log_request_body: bool = False
    log_response_body: bool = False
    max_log_body_size: int = 10000

    # ------------------------------------------------------------------
    # PostgreSQL
    # ------------------------------------------------------------------
    database_url: str = "postgresql+asyncpg://pdf:pdf123@localhost:5432/pdf_platform"
    postgres_db: str = "ddproject"
    postgres_user: str = "pdf"
    postgres_password: str = "pdf123"

    # ------------------------------------------------------------------
    # Auth (JWT + one-time codes)
    # ------------------------------------------------------------------
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_expire_minutes: int = 15
    jwt_refresh_expire_days: int = 30
    auth_pin_pepper: str = ""
    auth_otp_pepper: str = ""
    auth_hmac_key: str = ""

    # ------------------------------------------------------------------
    # Messaging (RabbitMQ)
    # Credentials come from the environment, not hardcoded here.
    # ------------------------------------------------------------------
    rabbitmq_url: str = ""
    rabbitmq_host: str = "localhost"
    rabbitmq_port: int = 5672
    rabbitmq_user: str = ""
    rabbitmq_password: str = ""
    rabbitmq_vhost: str = "/"

    @cached_property
    def rabbitmq_dsn(self) -> str:
        """Full AMQP DSN: explicit RABBITMQ_URL wins, otherwise build from parts."""
        if self.rabbitmq_url:
            return self.rabbitmq_url
        vhost = self.rabbitmq_vhost.lstrip("/")
        return (
            f"amqp://{self.rabbitmq_user}:{self.rabbitmq_password}"
            f"@{self.rabbitmq_host}:{self.rabbitmq_port}/{vhost}"
        )

    # ------------------------------------------------------------------
    # S3-compatible object storage (cloud.ru)
    # ------------------------------------------------------------------
    s3_endpoint_url: str = ""
    s3_key_id: str = ""
    s3_key_secret: str = ""
    s3_tenant_id: str = ""
    s3_bucket_name: str = ""
    s3_region: str = "us-east-1"

    # ------------------------------------------------------------------
    # Redis
    # ------------------------------------------------------------------
    redis_url: str = "redis://localhost:6379/0"

    # ------------------------------------------------------------------
    # Documents / object storage pipeline
    # ------------------------------------------------------------------
    storage_temp_dir: str = "./tmp/uploads"
    max_upload_bytes: int = 50 * 1024 * 1024
    document_events_queue: str = "document_events"
    document_events_routing_keys: str = (
        "document.stored,document.converted,document.analysis.completed,document.processing.failed"
    )

    @cached_property
    def document_events_routing_key_list(self) -> list[str]:
        return [
            key.strip()
            for key in self.document_events_routing_keys.split(",")
            if key.strip()
        ]

    # ------------------------------------------------------------------
    # Organization integration
    # ------------------------------------------------------------------
    integration_api_hmac_key: str = ""
    integration_api_key_prefix: str = "ddorg"
    integration_validate_inn_checksum: bool = True
    integration_rate_limit_per_minute: int = 120
    integration_request_log_sample: float = 1.0

    # ------------------------------------------------------------------
    # AI Feature (cloud.ru model API)
    # ------------------------------------------------------------------
    ai_feature: bool = False
    ai_base_url: str = "https://foundation-models.api.cloud.ru/v1"
    ai_api_key: str = ""
    ai_model: str = ""
    ai_embedding_base_url: str = "https://foundation-models.api.cloud.ru/v1"
    ai_embedding_model: str = "Qwen/Qwen3-Embedding-0.6B"
    ai_embedding_dimension: int = 1024

    # ------------------------------------------------------------------
    # Qdrant vector store
    # ------------------------------------------------------------------
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_api_key: str = ""

    @cached_property
    def qdrant_url(self) -> str:
        return f"http://{self.qdrant_host}:{self.qdrant_port}"

    # ------------------------------------------------------------------
    # Web SPA origin(s) for CORS
    # ------------------------------------------------------------------
    web_origins: str = "http://localhost:5173"

    @cached_property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.web_origins.split(",") if origin.strip()]

    def model_post_init(self, context: object) -> None:
        env = self.environment.strip().lower()
        if env not in ENVIRONMENTS:
            raise ValueError(
                f"unsupported environment '{self.environment}': "
                "expected 'development' or 'production'"
            )
        issues = self._security_issues()
        if not issues:
            return
        if env == "production":
            raise RuntimeError(
                f"refusing to start with insecure settings (APP_ENV={env}): "
                + "; ".join(issues)
            )
        logger.warning("insecure settings detected: %s", "; ".join(issues))

    def _security_issue(self, name: str, value: str, *, min_length: int = 0) -> list[str]:
        stripped = value.strip()
        if not stripped:
            return [f"{name} is empty"]
        lowered = stripped.lower()
        if lowered in _EXACT_PLACEHOLDERS or lowered.startswith(_PLACEHOLDER_PREFIXES):
            return [f"{name} matches a known insecure placeholder"]
        if min_length and len(stripped) < min_length:
            return [f"{name} is shorter than {min_length} characters"]
        return []

    def _security_issues(self) -> list[str]:
        issues: list[str] = []
        values: dict[str, str] = {}
        for name in _KEY_SETTINGS:
            value = str(getattr(self, name))
            values[name] = value
            issues += self._security_issue(name, value, min_length=MIN_SECRET_LENGTH)

        for name in ("postgres_password", "s3_key_secret"):
            value = str(getattr(self, name))
            values[name] = value
            issues += self._security_issue(name, value)
        if not self.rabbitmq_url:
            values["rabbitmq_password"] = self.rabbitmq_password
            issues += self._security_issue("rabbitmq_password", self.rabbitmq_password)

        if self.s3_endpoint_url:
            for name in ("s3_key_id", "s3_bucket_name"):
                issues += self._security_issue(name, str(getattr(self, name)))
        if self.ai_feature:
            issues += self._security_issue("ai_api_key", self.ai_api_key)

        seen: dict[str, str] = {}
        for name, value in values.items():
            stripped = value.strip()
            if not stripped:
                continue
            if stripped in seen:
                issues.append(f"{name} must differ from {seen[stripped]}")
            else:
                seen[stripped] = name
        return issues


settings = Settings()