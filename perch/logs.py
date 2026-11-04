"""Log setup (S47): plain text by default, one JSON object a line with PERCH_LOG_FORMAT=json.

The JSON line holds time, level, logger and the formatted message. Exception text is never
written, only the exception class name, because an exception message can carry a user's
words. Call sites already log lengths, ids and class names; this formatter adds no field
from a request, a body or a user.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from perch.config import env

PLAIN = "%(asctime)s %(levelname)s %(message)s"


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds")
        out = {"ts": ts, "level": record.levelname, "logger": record.name,
               "msg": record.getMessage()}
        if record.exc_info and record.exc_info[0] is not None:
            out["exc"] = record.exc_info[0].__name__
        return json.dumps(out, ensure_ascii=False)


def json_mode() -> bool:
    return (env("PERCH_LOG_FORMAT", "") or "").lower() == "json"


def configure(level: int = logging.INFO) -> None:
    """Root logging for the worker."""
    if json_mode():
        h = logging.StreamHandler()
        h.setFormatter(JsonFormatter())
        logging.basicConfig(level=level, handlers=[h], force=True)
    else:
        logging.basicConfig(level=level, format=PLAIN)


def uvicorn_log_config(level: str) -> dict | None:
    """A uvicorn log_config in JSON mode, else None (uvicorn's own default)."""
    if not json_mode():
        return None
    lv = level.upper()
    return {"version": 1, "disable_existing_loggers": False,
            "formatters": {"json": {"()": "perch.logs.JsonFormatter"}},
            "handlers": {"h": {"class": "logging.StreamHandler", "formatter": "json"}},
            "loggers": {"uvicorn": {"handlers": ["h"], "level": lv, "propagate": False},
                        "uvicorn.error": {"level": lv}, "uvicorn.access": {"level": lv}},
            "root": {"handlers": ["h"], "level": lv}}
