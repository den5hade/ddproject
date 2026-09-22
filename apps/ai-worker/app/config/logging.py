"""Process-wide logging configuration for the ai-worker."""

import logging

_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format=_LOG_FORMAT)