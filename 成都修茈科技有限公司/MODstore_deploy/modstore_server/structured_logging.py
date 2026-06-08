from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone


class StructuredJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "request_id": getattr(record, "request_id", None),
            "name": record.name,
        }
        if record.exc_info and record.exc_info[1]:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def setup_structured_logging() -> None:
    if os.environ.get("MODSTORE_STRUCTURED_LOGGING") != "1":
        return
    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler()
    handler.setFormatter(StructuredJsonFormatter())
    root.addHandler(handler)
    root.setLevel(logging.INFO)
