from functools import cached_property

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

    objectstorage_queue: str = "document.upload"
    objectstorage_routing_keys: str = "document.upload.requested"

    storage_temp_dir: str = "./tmp/uploads"
    max_upload_bytes: int = 50 * 1024 * 1024

    s3_endpoint_url: str = ""
    s3_key_id: str = ""
    s3_key_secret: str = ""
    s3_bucket_name: str = ""
    s3_region: str = "us-east-1"
    s3_tenant_id: str = "default"

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
        return [
            key.strip()
            for key in self.objectstorage_routing_keys.split(",")
            if key.strip()
        ]


settings = Settings()