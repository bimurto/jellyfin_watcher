"""CLI entrypoint for jellyfin_watcher."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from jellyfin_watcher.classify import Classifier
from jellyfin_watcher.config import load_config
from jellyfin_watcher.lock import acquire_lock
from jellyfin_watcher.logging_setup import setup_logging
from jellyfin_watcher.metadata import MetadataCache
from jellyfin_watcher.quarantine import RetryTracker
from jellyfin_watcher.worker import process_folder, run_once


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI-enabled Jellyfin media organizer")
    parser.add_argument("--dry-run", action="store_true", help="Plan only; do not copy or delete")
    parser.add_argument("--once", action="store_true", help="Run one pass and exit")
    parser.add_argument("--folder", type=Path, help="Process a single folder")
    parser.add_argument("--apply", action="store_true", help="Required for destructive operations")
    parser.add_argument("--log-level", default="INFO", help="Logging level")
    args = parser.parse_args(argv)

    cfg = load_config()
    log = setup_logging(cfg.log_path, debug=cfg.debug or args.log_level.upper() == "DEBUG")
    log.info("startup", "jellyfin_watcher started", config=cfg.redacted())

    if not args.apply and not args.dry_run:
        log.error("missing_apply", "Refusing to run without --apply or --dry-run")
        return 2

    cache = MetadataCache(cfg.cache_path)
    classifier = Classifier(cfg, cache, log)
    tracker = RetryTracker(cfg.retries_path, cfg.max_retries, cfg.backoff_base_seconds)

    if args.folder:
        ok = process_folder(args.folder, cfg, classifier, tracker, log, dry_run=args.dry_run)
        return 0 if ok else 1

    with acquire_lock(cfg.lock_path) as locked:
        if not locked:
            return 0
        processed = run_once(cfg, classifier, tracker, log, dry_run=args.dry_run)
        log.info("run_complete", "Run complete", processed=processed, dry_run=args.dry_run)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
