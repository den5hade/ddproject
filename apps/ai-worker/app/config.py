from functools import cached_property
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    rabbitmq_url: str = ""
    rabbitmq_host: str = "localhost"
    rabbitmq_port: int = 5672
    rabbitmq_user: str = ""
    rabbitmq_password: str = ""
    rabbitmq_vhost: str = "/"

    ai_worker_queue: str = "document.convert"
    ai_worker_routing_keys: str = "document.uploaded,document.converted"

    ai_base_url: str = "https://foundation-models.api.cloud.ru/v1"
    ai_api_key: str = ""
    ai_model: str = "Qwen/Qwen3.5-397B-A17B"
    ai_temperature: float = 0.3
    ai_max_tokens: int = 4096

    s3_endpoint_url: str = ""
    s3_key_id: str = ""
    s3_key_secret: str = ""
    s3_bucket_name: str = ""
    s3_region: str = ""
    s3_tenant_id: str = "default"

    prompts_dir: str = "app/prompts"

    pdf_dpi: int = 300
    pdf_format: Literal["png", "jpeg"] = "png"

    @cached_property
    def rabbitmq_dsn(self) -> str:
        if self.rabbitmq_url:
            return self.rabbitmq_url
        vhost = self.rabbitmq_vhost.lstrip("/")
        return (
            f"amqp://{self.rabbitmq_user}:{self.rabbitmq_password}"
            f"@{self.rabbitmq_host}:{self.rabbitmq_port}/{vhost}"
        )

    @cached_property
    def routing_key_list(self) -> list[str]:
        return [key.strip() for key in self.ai_worker_routing_keys.split(",") if key.strip()]

    @cached_property
    def prompts_path(self) -> Path:
        return Path(self.prompts_dir)


settings = Settings()
