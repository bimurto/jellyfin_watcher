"""Hermes notification wrapper."""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger("jellyfin_watcher")

_HERMES_ROOT = Path("/home/bimurto/.hermes/hermes-agent")


def notify(target: str, message: str) -> None:
    try:
        sys.path.insert(0, str(_HERMES_ROOT))
        from tools.send_message_tool import send_message_tool

        result = send_message_tool({"action": "send", "target": target, "message": message})
        logger.info("notification_sent", extra={"event": "notification_sent", "target": target, "result": str(result)})
    except Exception as exc:
        logger.warning("notification_failed", extra={"event": "notification_failed", "target": target, "error": str(exc)})
    finally:
        try:
            sys.path.remove(str(_HERMES_ROOT))
        except ValueError:
            pass
