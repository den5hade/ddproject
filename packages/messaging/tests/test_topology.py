from messaging.topology import (
    CONSUMER_QUEUES,
    DOCUMENT_CONVERT_QUEUE,
    DOCUMENT_CONVERT_ROUTING_KEYS,
)


def test_document_convert_binding_present():
    assert DOCUMENT_CONVERT_QUEUE in {spec.queue for spec in CONSUMER_QUEUES}


def test_queue_names_unique():
    queues = [spec.queue for spec in CONSUMER_QUEUES]
    assert len(queues) == len(set(queues))


def test_routing_keys_non_empty():
    for spec in CONSUMER_QUEUES:
        assert spec.routing_keys


def test_constants_match_spec():
    spec = next(
        spec for spec in CONSUMER_QUEUES if spec.queue == DOCUMENT_CONVERT_QUEUE
    )
    assert spec.routing_keys == DOCUMENT_CONVERT_ROUTING_KEYS


def test_document_convert_keys_match_ai_worker_spec():
    assert DOCUMENT_CONVERT_ROUTING_KEYS == [
        "document.uploaded",
        "document.converted",
    ]