"""Minimal structured logging for ASCOM MCP Server."""

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

# Configure logging to stderr (MCP requirement)
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(message)s")


class StructuredLogger:
    """Minimal structured logger for MCP servers."""

    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
        self.name = name

    def _log(self, level: str, event: str, **kwargs: Any):
        """Log structured event."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": level,
            "logger": self.name,
            "event": event,
            **kwargs,
        }
        getattr(self.logger, level)(json.dumps(entry))

    def info(self, event: str, **kwargs: Any):
        self._log("info", event, **kwargs)

    def error(self, event: str, **kwargs: Any):
        self._log("error", event, **kwargs)

    def warning(self, event: str, **kwargs: Any):
        self._log("warning", event, **kwargs)

    def debug(self, event: str, **kwargs: Any):
        self._log("debug", event, **kwargs)


# Usage example:
# logger = StructuredLogger("ascom.telescope")
# logger.info("telescope_connected", device_id="telescope_0", ra=5.5, dec=-5.4)
