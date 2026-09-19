from dataclasses import dataclass


@dataclass(frozen=True)
class ConsumerBinding:
    queue: str
    routing_keys: list[str]


DOCUMENT_CONVERT_QUEUE = "document.convert"
DOCUMENT_CONVERT_ROUTING_KEYS = ["document.uploaded", "document.converted"]

CONSUMER_QUEUES: list[ConsumerBinding] = [
    ConsumerBinding(DOCUMENT_CONVERT_QUEUE, DOCUMENT_CONVERT_ROUTING_KEYS),
]