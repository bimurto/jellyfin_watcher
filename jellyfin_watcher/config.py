"""Environment-driven configuration for jellyfin_watcher."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)


@dataclass(frozen=True)
class Config:
    source: Path
    movies_dst: Path
    tv_dst: Path
    state_root: Path
    log_path: Path
    lock_path: Path
    retries_path: Path
    cache_path: Path
    quarantine_path: Path
    tmdb_api_key: str | None
    searxng_url: str
    ollama_url: str
    ollama_model: str
    ollama_classify_model: str
    brave_api_key: str | None
    max_retries: int
    backoff_base_seconds: float
    batch_size: int
    copy_verify_full_hash_max_bytes: int
    notify_target: str
    debug: bool
    language: str = "en-US"

    def redacted(self) -> dict[str, object]:
        return {
            "source": str(self.source),
            "movies_dst": str(self.movies_dst),
            "tv_dst": str(self.tv_dst),
            "state_root": str(self.state_root),
            "log_path": str(self.log_path),
            "lock_path": str(self.lock_path),
            "retries_path": str(self.retries_path),
            "cache_path": str(self.cache_path),
            "quarantine_path": str(self.quarantine_path),
            "tmdb_api_key": "***" if self.tmdb_api_key else None,
            "searxng_url": self.searxng_url,
            "ollama_url": self.ollama_url,
            "ollama_model": self.ollama_model,
            "ollama_classify_model": self.ollama_classify_model,
            "brave_api_key": "***" if self.brave_api_key else None,
            "max_retries": self.max_retries,
            "backoff_base_seconds": self.backoff_base_seconds,
            "batch_size": self.batch_size,
            "copy_verify_full_hash_max_bytes": self.copy_verify_full_hash_max_bytes,
            "notify_target": self.notify_target,
            "debug": self.debug,
            "language": self.language,
        }


_VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".mov", ".m4v", ".wmv", ".flv", ".ts", ".m2ts", ".webm"}
_SUB_EXTS = {".srt", ".ass", ".ssa", ".sub", ".idx", ".vtt"}
_TEXT_EXTS = {".txt", ".url"}
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
_NFO_EXTS = {".nfo"}
_EXTRA_DIR_NAMES = {
    "extras",
    "behind the scenes",
    "trailers",
    "deleted scenes",
    "featurettes",
    "interviews",
    "shorts",
    "scenes",
    "other",
}

_MEDIA_EXTS = _VIDEO_EXTS | _SUB_EXTS | _TEXT_EXTS | _IMAGE_EXTS | _NFO_EXTS


@dataclass(frozen=True)
class MediaTypes:
    video_exts: set[str] = field(default_factory=lambda: _VIDEO_EXTS)
    sub_exts: set[str] = field(default_factory=lambda: _SUB_EXTS)
    text_exts: set[str] = field(default_factory=lambda: _TEXT_EXTS)
    image_exts: set[str] = field(default_factory=lambda: _IMAGE_EXTS)
    nfo_exts: set[str] = field(default_factory=lambda: _NFO_EXTS)
    media_exts: set[str] = field(default_factory=lambda: _MEDIA_EXTS)
    extra_dir_names: set[str] = field(default_factory=lambda: _EXTRA_DIR_NAMES)


MEDIA_TYPES = MediaTypes()


def load_config() -> Config:
    state_root = Path(os.getenv("JELLYFIN_WATCHER_STATE_ROOT", "/mnt/my_passport/Media/.jellyfin_watcher"))
    return Config(
        source=Path(os.getenv("JELLYFIN_WATCHER_SOURCE", "/mnt/seedhost_sftp/downloads/finished")),
        movies_dst=Path(os.getenv("JELLYFIN_WATCHER_MOVIES_DST", "/mnt/my_passport/Media/Movies")),
        tv_dst=Path(os.getenv("JELLYFIN_WATCHER_TV_DST", "/mnt/my_passport/Media/TV Shows")),
        state_root=state_root,
        log_path=state_root / "log" / "watcher.jsonl",
        lock_path=state_root / "lock" / "watcher.pid",
        retries_path=state_root / "state" / "retries.jsonl",
        cache_path=state_root / "state" / "classification_cache.sqlite",
        quarantine_path=Path(os.getenv("JELLYFIN_WATCHER_QUARANTINE_PATH", "/mnt/seedhost_sftp/downloads/_quarantine")),
        tmdb_api_key=os.getenv("TMDB_API_KEY"),
        searxng_url=os.getenv("SEARXNG_URL", "http://localhost:8888"),
        ollama_url=os.getenv("OLLAMA_URL", "http://localhost:11434"),
        ollama_model=os.getenv("OLLAMA_MODEL", "gemma4"),
        ollama_classify_model=os.getenv("OLLAMA_CLASSIFY_MODEL", "gemma4"),
        brave_api_key=os.getenv("BRAVE_SEARCH_API_KEY"),
        max_retries=int(os.getenv("MAX_RETRIES", "3")),
        backoff_base_seconds=float(os.getenv("BACKOFF_BASE_SECONDS", "300")),
        batch_size=int(os.getenv("BATCH_SIZE", "1")),
        copy_verify_full_hash_max_bytes=int(os.getenv("COPY_VERIFY_FULL_HASH_MAX_BYTES", str(2 * 1024 * 1024 * 1024))),
        notify_target=os.getenv("NOTIFY_TARGET", "telegram"),
        debug=os.getenv("DEBUG", "").lower() in {"1", "true", "yes"},
    )


if __name__ == "__main__":
    cfg = load_config()
    print(cfg.redacted())
