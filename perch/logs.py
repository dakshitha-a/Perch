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


class AccessFilter(logging.Filter):
    """Rewrites uvicorn access lines to `METHOD path status`: no query string (it carries the
    OIDC code and state on /auth/callback) and no client address."""

    def filter(self, record: logging.LogRecord) -> bool:
        a = record.args
        if isinstance(a, tuple) and len(a) >= 5:
            method, path, status = a[1], str(a[2]).split("?", 1)[0], a[4]
            record.msg, record.args = "%s %s %s", (method, path, status)
        else:  # an unknown shape is dropped rather than risk logging a query
            return False
        return True


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
            "filters": {"access": {"()": "perch.logs.AccessFilter"}},
            "handlers": {"h": {"class": "logging.StreamHandler", "formatter": "json"},
                         "acc": {"class": "logging.StreamHandler", "formatter": "json",
                                 "filters": ["access"]}},
            "loggers": {"uvicorn": {"handlers": ["h"], "level": lv, "propagate": False},
                        "uvicorn.error": {"level": lv},
                        "uvicorn.access": {"handlers": ["acc"], "level": lv,
                                           "propagate": False}},
            "root": {"handlers": ["h"], "level": lv}}
