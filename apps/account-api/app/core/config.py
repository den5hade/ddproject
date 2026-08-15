from functools import cached_property

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "ddproject"
    debug: bool = False
    api_prefix: str = "/api/v1"

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------
    log_level: str = "INFO"
    log_to_file: bool = False
    log_dir: str = "logs"
    log_max_bytes: int = 10 * 1024 * 1024
    log_backup_count: int = 5
    enable_request_logging: bool = True
    log_request_body: bool = True
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


settings = Settings()