"""Build Jellyfin-compatible destination paths from classification."""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jellyfin_watcher.config import Config, MEDIA_TYPES
from jellyfin_watcher.logging_setup import ContextLog
from jellyfin_watcher.reorg_bridge import (
    Op,
    clean_spaces,
    normalize_show,
    safe_name,
    unique_path,
    video_quality_label,
)

_VIDEO_EXTS = MEDIA_TYPES.video_exts
_SUB_EXTS = MEDIA_TYPES.sub_exts
_TEXT_EXTS = MEDIA_TYPES.text_exts
_IMAGE_EXTS = MEDIA_TYPES.image_exts
_NFO_EXTS = MEDIA_TYPES.nfo_exts
_MEDIA_EXTS = MEDIA_TYPES.media_exts
_EXTRA_DIR_NAMES = MEDIA_TYPES.extra_dir_names

_SE_RE = re.compile(r"(?i)\bS(\d{1,2})[\s._-]*E(\d{1,3})(?:\s*-\s*E?(\d{1,3})|E(\d{1,3}))?")
_SEASON_RE = re.compile(r"(?i)\b(?:season|s)\s*0?(\d{1,2})\b")
_ABS_EP_RE = re.compile(r"(?i)(?:^|[\s\[\(\-_])(\d{1,3})(?:[\s\]\)\-_]|$)")


@dataclass(frozen=True)
class Episode:
    show: str
    season: int
    episode: int
    end_episode: int | None = None
    special: bool = False


def _infer_season(path: Path) -> int:
    for part in reversed(path.parent.parts):
        m = _SEASON_RE.search(part)
        if m:
            return int(m.group(1))
    return 1


def _infer_episode(path: Path, default_show: str) -> Episode | None:
    raw = clean_spaces(path.stem)
    m = _SE_RE.search(raw)
    if m:
        season = int(m.group(1))
        ep = int(m.group(2))
        end_ep = int(m.group(3) or m.group(4)) if (m.group(3) or m.group(4)) else None
        return Episode(default_show, season, ep, end_ep)

    season = _infer_season(path)
    m = _ABS_EP_RE.search(path.stem)
    if m:
        return Episode(default_show, season, int(m.group(1)))

    lower = path.name.lower()
    if "ova" in lower or "oad" in lower or re.search(r"(?i)\b(?:nc|op|ed)\s*\d*", lower):
        return Episode(default_show, 0, 0, None, True)

    return None


def _has_episode_pattern(path: Path) -> bool:
    return _infer_episode(path, "") is not None


def _build_movie_ops(src_dir: Path, dst_root: Path, title: str, year: str | None, reserved: set[Path], log: ContextLog) -> list[Op]:
    ops: list[Op] = []
    folder_name = safe_name(f"{title} ({year})" if year else title)
    folder = dst_root / folder_name

    videos = sorted(p for p in src_dir.rglob("*") if p.is_file() and p.suffix.lower() in _VIDEO_EXTS)
    if not videos:
        return ops

    multi_version = len(videos) > 1
    targets: list[Path] = []
    for v in videos:
        label = f" - {video_quality_label(v)}" if multi_version else ""
        base = f"{folder_name}{label}"
        dst = unique_path(folder / f"{base}{v.suffix.lower()}", reserved, v)
        ops.append(Op(v, dst, "movie_video"))
        targets.append(dst)

    target_dir = targets[0].parent
    for src in src_dir.rglob("*"):
        if not src.is_file() or src.suffix.lower() not in _MEDIA_EXTS or src in videos:
            continue
        ext = src.suffix.lower()
        if ext in _SUB_EXTS:
            lang = ".en" if re.search(r"(?i)(eng|english|_en|\ben\b)", src.name) else ""
            flag = ".hi" if re.search(r"(?i)(hi|hearing)\b", src.name) else ""
            dst = unique_path(target_dir / f"{folder_name}{lang}{flag}{ext}", reserved, src)
            ops.append(Op(src, dst, "movie_subtitle"))
        elif ext in _NFO_EXTS:
            dst = unique_path(target_dir / f"{folder_name}.nfo", reserved, src)
            ops.append(Op(src, dst, "movie_nfo"))
        elif ext in _IMAGE_EXTS:
            lower = src.name.lower()
            art = "poster" if any(t in lower for t in ("poster", "cover", "yify", "yts")) else src.stem
            dst = unique_path(target_dir / f"{safe_name(art)}{ext}", reserved, src)
            ops.append(Op(src, dst, "movie_image"))
        elif ext in _TEXT_EXTS:
            dst = unique_path(target_dir / "other" / f"{safe_name(src.stem)}{ext}", reserved, src)
            ops.append(Op(src, dst, "movie_text"))

    for sub in src_dir.iterdir():
        if sub.is_dir() and sub.name.lower() in _EXTRA_DIR_NAMES:
            dst = unique_path(target_dir / sub.name, reserved, sub)
            ops.append(Op(sub, dst, "movie_extra_dir"))

    return ops


def _build_tv_ops(src_dir: Path, dst_root: Path, show_title: str, reserved: set[Path], log: ContextLog) -> list[Op]:
    ops: list[Op] = []
    show = normalize_show(show_title)
    videos = sorted(p for p in src_dir.rglob("*") if p.is_file() and p.suffix.lower() in _VIDEO_EXTS)
    if not videos:
        return ops

    inferred: dict[Path, Episode | None] = {}
    special_groups: dict[str, list[Path]] = defaultdict(list)

    for v in videos:
        ep = _infer_episode(v, show)
        if ep and ep.special and ep.episode == 0:
            special_groups[ep.show].append(v)
        inferred[v] = ep

    special_numbers: dict[Path, int] = {}
    for sshow, sources in special_groups.items():
        start = 101
        existing = list((dst_root / sshow / "Season 00").glob(f"{sshow} S00E*.mkv")) if (dst_root / sshow / "Season 00").exists() else []
        used: list[int] = []
        for p in existing:
            m = re.search(r"S00E(\d{2,3})", p.name)
            if m:
                used.append(int(m.group(1)))
        if used:
            start = max(max(used) + 1, start)
        for i, src in enumerate(sorted(sources, key=lambda p: str(p).casefold()), start=start):
            special_numbers[src] = i

    video_targets: dict[Path, Path] = {}
    extra_counter = 1
    extras_dir = dst_root / show / "extras"
    for v, ep in inferred.items():
        if ep is None:
            log.info("tv_extra_video", "Unparseable video treated as extra", file=v.name)
            dst = unique_path(extras_dir / f"{show} - extra {extra_counter:02d}{v.suffix.lower()}", reserved, v)
            ops.append(Op(v, dst, "tv_extra_video"))
            video_targets[v] = dst
            extra_counter += 1
            continue
        ep_num = special_numbers.get(v, ep.episode)
        if ep.end_episode is not None:
            ep_token = f"S{ep.season:02d}E{ep.episode:02d}-E{ep.end_episode:02d}"
        else:
            ep_token = f"S{ep.season:02d}E{ep_num:02d}"
        season_dir = dst_root / ep.show / f"Season {ep.season:02d}"
        dst = unique_path(season_dir / f"{ep.show} {ep_token}{v.suffix.lower()}", reserved, v)
        ops.append(Op(v, dst, "tv_video"))
        video_targets[v] = dst

    for src in src_dir.rglob("*"):
        if not src.is_file() or src.suffix.lower() not in _MEDIA_EXTS or src in videos:
            continue
        video = _closest_video(src, videos)
        target_dir = video_targets[video].parent if (video and video in video_targets) else extras_dir
        base = video_targets[video].stem if (video and video in video_targets) else f"{show} - extra"
        ext = src.suffix.lower()
        if ext in _SUB_EXTS:
            lang = ".en" if re.search(r"(?i)(eng|english|_en|\ben\b)", src.name) else ""
            flag = ".hi" if re.search(r"(?i)(hi|hearing)\b", src.name) else ""
            dst = unique_path(target_dir / f"{base}{lang}{flag}{ext}", reserved, src)
            ops.append(Op(src, dst, "tv_subtitle"))
        elif ext in _NFO_EXTS:
            dst = unique_path(target_dir / f"{base}.nfo", reserved, src)
            ops.append(Op(src, dst, "tv_nfo"))
        elif ext in _IMAGE_EXTS:
            lower = src.name.lower()
            art = "poster" if "poster" in lower else ("fanart" if "fanart" in lower else safe_name(src.stem))
            dst = unique_path(target_dir.parent / f"{art}{ext}", reserved, src)
            ops.append(Op(src, dst, "tv_image"))
        elif ext in _TEXT_EXTS:
            dst = unique_path(target_dir / "other" / f"{safe_name(src.stem)}{ext}", reserved, src)
            ops.append(Op(src, dst, "tv_text"))

    for sub in src_dir.iterdir():
        if sub.is_dir() and sub.name.lower() in _EXTRA_DIR_NAMES:
            dst = unique_path(dst_root / show / sub.name, reserved, sub)
            ops.append(Op(sub, dst, "tv_extra_dir"))

    return ops


def _closest_video(sidecar: Path, videos: list[Path]) -> Path | None:
    if not videos:
        return None
    same_dir = [v for v in videos if v.parent == sidecar.parent]
    if same_dir:
        return same_dir[0]
    base = sidecar.stem
    for v in videos:
        if v.stem.startswith(base) or base.startswith(v.stem):
            return v
    return videos[0]


def build_ops(
    src_dir: Path,
    classification: Any,
    cfg: Config,
    reserved: set[Path],
    log: ContextLog,
) -> list[Op]:
    media_type = classification.media_type
    title = classification.title
    year = classification.year
    if media_type == "movie":
        return _build_movie_ops(src_dir, cfg.movies_dst, title, year, reserved, log)
    return _build_tv_ops(src_dir, cfg.tv_dst, title, reserved, log)
