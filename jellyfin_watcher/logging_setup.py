"""JSONL structured logging for jellyfin_watcher."""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "module": record.name,
            "message": record.getMessage(),
        }
        for key in ("folder", "event", "source", "decision", "reason", "destination", "error"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class _ContextAdapter(logging.LoggerAdapter):
    def process(self, msg: str, kwargs: Any) -> tuple[str, Any]:
        extra = kwargs.setdefault("extra", {})
        extra.update(self.extra)
        return msg, kwargs


class ContextLog:
    def __init__(self, logger: logging.Logger, folder: str | None = None) -> None:
        self._logger = logger
        self._base_extra: dict[str, Any] = {"folder": folder} if folder else {}

    def _log(self, level: int, event: str, msg: str, **kwargs: Any) -> None:
        extra = {"event": event}
        extra.update(self._base_extra)
        extra.update(kwargs)
        self._logger.log(level, msg, extra=extra)

    def info(self, event: str, msg: str, **kwargs: Any) -> None:
        self._log(logging.INFO, event, msg, **kwargs)

    def warning(self, event: str, msg: str, **kwargs: Any) -> None:
        self._log(logging.WARNING, event, msg, **kwargs)

    def error(self, event: str, msg: str, **kwargs: Any) -> None:
        self._log(logging.ERROR, event, msg, **kwargs)

    def debug(self, event: str, msg: str, **kwargs: Any) -> None:
        self._log(logging.DEBUG, event, msg, **kwargs)

    def with_folder(self, folder: str) -> "ContextLog":
        new_extra = dict(self._base_extra)
        new_extra["folder"] = folder
        new_log = ContextLog(self._logger)
        new_log._base_extra = new_extra
        return new_log


def setup_logging(log_path: Path, *, debug: bool = False) -> ContextLog:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if debug else logging.INFO)
    root.handlers.clear()

    file_handler = logging.FileHandler(log_path, mode="a")
    file_handler.setFormatter(JSONFormatter())
    root.addHandler(file_handler)

    if debug:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(JSONFormatter())
        root.addHandler(console_handler)

    logger = logging.getLogger("jellyfin_watcher")
    return ContextLog(logger)
