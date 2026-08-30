import os
import sys
from collections.abc import Callable

from loguru import logger


def setup_logging() -> Callable[[], None]:
    """
    Configure a single stdout sink and return a shutdown hook that flushes the
    async queue created by enqueue=True.
    """
    logger.remove()

    sink_id = logger.add(
        sys.stdout,
        level=os.getenv("LOG_LEVEL", "DEBUG"),
        enqueue=True,
    )

    def shutdown() -> None:
        logger.remove(sink_id)
        logger.complete()

    return shutdown


shutdown_logging = setup_logging()
