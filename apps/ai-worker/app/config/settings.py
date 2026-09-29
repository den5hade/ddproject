from functools import cached_property
from pathlib import Path
from typing import Literal

from messaging.topology import DOCUMENT_CONVERT_QUEUE, DOCUMENT_CONVERT_ROUTING_KEYS
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

    ai_worker_queue: str = DOCUMENT_CONVERT_QUEUE
    ai_worker_routing_keys: str = ",".join(DOCUMENT_CONVERT_ROUTING_KEYS)

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

    pii_fingerprint_secret: str = ""
    """HMAC key for PII value fingerprints (env ``PII_FINGERPRINT_SECRET``).

    The default is empty on purpose — there is **no usable default**, because a
    default secret is a hard-coded secret and a hard-coded secret is no secret
    at all (plan Phase 8). An empty or whitespace-only value is rejected by
    ``app.pii.detectors.build_detector_chain`` with ``InvalidPIIInputError``
    rather than degrading to a plain, brute-forceable digest, so a deployment
    that forgets this variable fails closed at worker start-up instead of
    shipping unkeyed fingerprints.

    Generate one with ``python -c "import secrets;
    print(secrets.token_urlsafe(32))"`` and treat it as config, not as an
    ephemeral value: rotating it changes every fingerprint, so the pipeline's
    output changes with it (plan §7 R5). Nothing reads or persists a
    fingerprint, which is what keeps rotation a non-event for stored data.
    """

    llm_mode: Literal["internal_llm", "external_llm"] = "internal_llm"
    """Which trust boundary ``ai_base_url`` sits on (env ``LLM_MODE``).

    ``internal_llm`` (the default) means the provider named in ``ai_base_url``
    is on the trusted side, so PII is neither redacted nor blocked on the way
    out — the whole of M5's dormancy so far. ``external_llm`` says the opposite
    and switches on the ``REDACT_ON_EXTERNAL`` override
    (:func:`app.pii.policy.resolve_destination`), which is the only way
    ``destination`` stops being a constant (plan §7 decision 12).

    Only the two boundaries the worker can be configured *for* are settable.
    ``PIIDestination.PERSISTENCE`` is the canonical guard's own constant and
    ``UNKNOWN`` is the fail-closed placeholder — neither is a state a
    deployment may select, so ``Literal`` rather than a free string keeps a
    typo a construction error instead of a silently unrecognised mode.

    Read through :func:`app.pii.policy.resolve_destination` and never directly:
    the pair ``internal_llm`` + an untrusted ``ai_base_url`` is a
    misconfiguration that would send medical data off-boundary while the
    operator believed the boundary was trusted, and the worker refuses to start
    on it (plan Phase 15 decision 3).

    This says nothing about OCR. The same ``ai_*`` settings drive the OCR call
    in ``handle_converting``, which runs *before* the gate and consumes the
    image; see the "Boundaries this pipeline does not gate" section in
    ``app/pipeline/pipeline.py``.
    """

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
