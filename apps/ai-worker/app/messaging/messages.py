"""Message type dispatch for inbound worker messages."""

from aio_pika.abc import AbstractIncomingMessage
from contracts.events import DocumentConverted, DocumentUploaded

SUPPORTED_MESSAGE_TYPES = ("DocumentUploaded", "DocumentConverted")


def decode_message(message: AbstractIncomingMessage):
    """Parse an inbound AMQP message into its domain event.

    Returns the event parsed from ``message.type``, or ``None`` for an
    unsupported event type (the caller drops it with a warning).
    """
    if message.type == "DocumentUploaded":
        return DocumentUploaded.model_validate_json(message.body)
    if message.type == "DocumentConverted":
        return DocumentConverted.model_validate_json(message.body)
    return None