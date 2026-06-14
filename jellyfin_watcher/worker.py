"""Per-folder processing and run orchestration."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from jellyfin_watcher.classify import Classifier
from jellyfin_watcher.config import Config, MEDIA_TYPES
from jellyfin_watcher.copy_verify import copy_tree_with_verify, remove_source_tree
from jellyfin_watcher.logging_setup import ContextLog
from jellyfin_watcher.naming import build_ops
from jellyfin_watcher.notify import notify
from jellyfin_watcher.quarantine import RetryTracker, move_to_quarantine
from jellyfin_watcher.reorg_bridge import Op, validate_ops


_VIDEO_EXTS = MEDIA_TYPES.video_exts


def _destination_exists(src_dir: Path, classification: Any, cfg: Config) -> bool:
    media_type = classification.media_type
    title = classification.title
    year = classification.year
    if media_type == "movie":
        folder = cfg.movies_dst / _safe_folder_name(title, year)
    else:
        folder = cfg.tv_dst / _normalize_show(title)
    return folder.exists()


def _safe_folder_name(title: str, year: str | None) -> str:
    from jellyfin_watcher.reorg_bridge import safe_name

    return safe_name(f"{title} ({year})" if year else title)


def _normalize_show(title: str) -> str:
    from jellyfin_watcher.reorg_bridge import normalize_show

    return normalize_show(title)


def process_folder(src_dir: Path, cfg: Config, classifier: Classifier, tracker: RetryTracker, log: ContextLog, *, dry_run: bool = False) -> bool:
    folder_log = log.with_folder(src_dir.name)
    videos = [p for p in src_dir.rglob("*") if p.is_file() and p.suffix.lower() in _VIDEO_EXTS]
    if not videos:
        folder_log.warning("no_videos", "No video files found; skipping")
        return False

    if not tracker.should_retry(src_dir.name):
        folder_log.info("retry_backoff", "Folder still in backoff; skipping")
        return False

    try:
        classification = classifier.classify(src_dir)
    except Exception as exc:
        folder_log.error("classification_error", f"Classification failed: {exc}", error=str(exc))
        attempts = tracker.record_failure(src_dir.name, str(exc))
        if attempts >= cfg.max_retries:
            dst = move_to_quarantine(src_dir, cfg.quarantine_path)
            notify(cfg.notify_target, f"Quarantined {src_dir.name} after classification failure: {exc} ({dst})")
        return False

    if classification is None:
        folder_log.warning("unclassifiable", "Could not classify folder")
        attempts = tracker.record_failure(src_dir.name, "unclassifiable")
        if attempts >= cfg.max_retries:
            dst = move_to_quarantine(src_dir, cfg.quarantine_path)
            notify(cfg.notify_target, f"Quarantined unclassifiable folder {src_dir.name} ({dst})")
        return False

    if _destination_exists(src_dir, classification, cfg):
        folder_log.info("destination_exists", "Destination already exists; skipping", destination=str(classification.title))
        return False

    folder_log.info("classified", "Classification succeeded", decision=classification.media_type, title=classification.title)

    reserved: set[Path] = set()
    try:
        ops = build_ops(src_dir, classification, cfg, reserved, folder_log)
    except Exception as exc:
        folder_log.error("naming_error", f"Failed to build destination paths: {exc}", error=str(exc))
        tracker.record_failure(src_dir.name, str(exc))
        return False

    if not ops:
        folder_log.warning("no_ops", "No operations generated; skipping")
        return False

    for op in ops:
        folder_log.info("planned_op", "Planned operation", source=str(op.src), destination=str(op.dst), reason=op.reason)

    if dry_run:
        folder_log.info("dry_run_complete", "Dry run complete", planned_ops=len(ops))
        return True

    try:
        validate_ops(ops)
    except Exception as exc:
        folder_log.error("validation_error", f"Validation failed: {exc}", error=str(exc))
        tracker.record_failure(src_dir.name, str(exc))
        return False

    try:
        copy_tree_with_verify(ops, cfg.copy_verify_full_hash_max_bytes)
    except Exception as exc:
        folder_log.error("copy_error", f"Copy/verification failed: {exc}", error=str(exc))
        _cleanup_ops(ops)
        attempts = tracker.record_failure(src_dir.name, str(exc))
        if attempts >= cfg.max_retries:
            dst = move_to_quarantine(src_dir, cfg.quarantine_path)
            notify(cfg.notify_target, f"Quarantined {src_dir.name} after copy failure: {exc} ({dst})")
        return False

    try:
        # Apply sidecar moves already done by copy_tree_with_verify since ops include them.
        # Remove source tree after verification.
        remove_source_tree(src_dir)
        tracker.record_success(src_dir.name)
        folder_log.info("processed", "Folder processed successfully", copied_ops=len(ops))
        return True
    except Exception as exc:
        folder_log.error("cleanup_error", f"Failed to remove source: {exc}", error=str(exc))
        tracker.record_failure(src_dir.name, str(exc))
        return False


def _cleanup_ops(ops: list[Op]) -> None:
    for op in ops:
        try:
            if op.dst.exists() and op.dst != op.src:
                if op.dst.is_dir():
                    shutil.rmtree(op.dst, ignore_errors=True)
                else:
                    op.dst.unlink(missing_ok=True)
        except Exception:
            pass


def run_once(cfg: Config, classifier: Classifier, tracker: RetryTracker, log: ContextLog, *, dry_run: bool = False) -> int:
    cfg.source.mkdir(parents=True, exist_ok=True)
    cfg.quarantine_path.mkdir(parents=True, exist_ok=True)

    items = []
    for child in cfg.source.iterdir():
        if not child.is_dir():
            continue
        if child.name.startswith("."):
            continue
        if child.resolve() == cfg.quarantine_path.resolve():
            continue
        items.append((child.stat().st_mtime, child))
    items.sort(key=lambda x: x[0])

    processed = 0
    considered = 0
    for _, src in items:
        if considered >= cfg.batch_size * 3:
            break
        considered += 1
        if process_folder(src, cfg, classifier, tracker, log, dry_run=dry_run):
            processed += 1
            if processed >= cfg.batch_size:
                break
    return processed
