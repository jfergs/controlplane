from __future__ import annotations

import logging
import os


def configure_logging() -> None:
    """Configure application logging."""
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format='{"level":"%(levelname)s","time":"%(asctime)s","logger":"%(name)s","msg":"%(message)s"}',
    )
