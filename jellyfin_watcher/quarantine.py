"""Retry tracking and quarantine moves."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

from jellyfin_watcher.config import Config


class RetryTracker:
    def __init__(self, path: Path, max_retries: int, backoff_base_seconds: float) -> None:
        self.path = path
        self.max_retries = max_retries
        self.backoff_base_seconds = backoff_base_seconds
        path.parent.mkdir(parents=True, exist_ok=True)

    def _read(self) -> dict[str, dict[str, Any]]:
        if not self.path.exists():
            return {}
        data: dict[str, dict[str, Any]] = {}
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    name = entry.get("folder", "")
                    if name:
                        data[name] = entry
                except json.JSONDecodeError:
                    continue
        return data

    def record_failure(self, folder_name: str, error: str) -> int:
        data = self._read()
        entry = data.get(folder_name, {"folder": folder_name, "attempts": 0, "last_error": ""})
        entry["attempts"] = entry.get("attempts", 0) + 1
        entry["last_error"] = error
        entry["last_attempt"] = datetime.now(timezone.utc).isoformat()
        data[folder_name] = entry
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")
        return entry["attempts"]

    def record_success(self, folder_name: str) -> None:
        entry = {"folder": folder_name, "attempts": 0, "last_attempt": datetime.now(timezone.utc).isoformat(), "status": "success"}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")

    def should_quarantine(self, folder_name: str) -> bool:
        data = self._read()
        entry = data.get(folder_name, {})
        return entry.get("attempts", 0) >= self.max_retries

    def should_retry(self, folder_name: str) -> bool:
        data = self._read()
        entry = data.get(folder_name, {})
        attempts = entry.get("attempts", 0)
        if attempts == 0:
            return True
        last = entry.get("last_attempt")
        if not last:
            return True
        try:
            last_ts = datetime.fromisoformat(last).timestamp()
        except Exception:
            return True
        delay = min(self.backoff_base_seconds * (2 ** (attempts - 1)), 1200)
        return time.time() - last_ts >= delay


def move_to_quarantine(src: Path, quarantine_root: Path) -> Path:
    quarantine_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dst = quarantine_root / f"{timestamp}_{src.name}"
    src.rename(dst)
    return dst
