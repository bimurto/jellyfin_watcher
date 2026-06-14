"""End-to-end classification of a folder into movie or TV."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jellyfin_watcher.config import Config
from jellyfin_watcher.logging_setup import ContextLog
from jellyfin_watcher.metadata import (
    AniListClient,
    Classification,
    MetadataCache,
    TMDBClient,
    classify_from_metadata,
)
from jellyfin_watcher.reorg_bridge import clean_spaces, infer_episode, normalize_show
from jellyfin_watcher.search import SearchChain
from jellyfin_watcher.llm import LLMClassifier


_ANIME_TOKENS = re.compile(
    r"(?i)\b(?:"
    r"SubsPlease|MTBB|Erai-raws|Judas|EMBER|Sokudo|Anime Time|Pahe|HorribleSubs|Commie|GJM|ASW|DKB"
    r"|OVA|OAD|NCOP|NCED|Batch|Dual Audio|Hi10|BDRip|WEBRip|x265|HEVC|10bit"
    r")\b"
)
_JAPANESE_RE = re.compile(r"[぀-ゟ゠-ヿ一-龯]")
_YEAR_RE = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")


@dataclass(frozen=True)
class FolderInfo:
    folder_name: str
    video_files: list[Path]
    years: list[str]
    has_episode_pattern: bool
    is_anime_hint: bool


def gather_folder_info(folder: Path) -> FolderInfo:
    videos = [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in {".mkv", ".mp4", ".avi", ".mov", ".m4v", ".wmv", ".flv", ".ts", ".m2ts", ".webm"}]
    years: list[str] = []
    has_ep = False
    anime_hint = False
    for v in videos:
        name = v.name
        years.extend(_YEAR_RE.findall(name))
        if infer_episode(v)[0] is not None:
            has_ep = True
        if _ANIME_TOKENS.search(name) or _JAPANESE_RE.search(name):
            anime_hint = True
    if not anime_hint:
        anime_hint = _ANIME_TOKENS.search(folder.name) is not None or _JAPANESE_RE.search(folder.name) is not None
    return FolderInfo(folder.name, sorted(videos), years, has_ep, anime_hint)


def _best_title_guess(info: FolderInfo) -> tuple[str, str | None]:
    year = info.years[0] if info.years else None
    # Prefer folder name, stripped of trailing season/episode noise.
    name = clean_spaces(info.folder_name)
    name = re.sub(r"(?i)\bS\d{1,2}(?:\s*[-+]\s*S\d{1,2})?.*$", "", name)
    name = re.sub(r"(?i)\bSeason\s*\d{1,2}\b.*$", "", name)
    name = re.sub(r"(?i)\b\(\d{1,3}\s*-\s*\d{1,3}\)\b.*$", "", name)
    # Remove year from title for search.
    title = re.sub(r"(?i)\(\d{4}\)", "", name).strip()
    return title, year


class Classifier:
    def __init__(self, cfg: Config, cache: MetadataCache, log: ContextLog) -> None:
        self.cfg = cfg
        self.log = log
        self.tmdb = TMDBClient(cfg.tmdb_api_key, cache, language=cfg.language)
        self.anilist = AniListClient(cache)
        self.search = SearchChain(cfg)
        self.llm = LLMClassifier(cfg)

    def classify(self, folder: Path) -> Classification | None:
        info = gather_folder_info(folder)
        title, year = _best_title_guess(info)

        # Very strong TV prior from filename patterns.
        if info.has_episode_pattern and not info.is_anime_hint:
            show = normalize_show(title)
            if show and show != "Unknown":
                self.log.info(
                    "classification_decision",
                    "Detected TV episode pattern",
                    decision="tv",
                    title=show,
                    source="filename_pattern",
                )
                return Classification("tv", show, year, None, "filename_pattern", 0.9)

        # Metadata classification.
        meta = classify_from_metadata(title, year, self.tmdb, self.anilist, is_anime_hint=info.is_anime_hint)
        if meta:
            self.log.info(
                "classification_decision",
                f"Classified via {meta.source}",
                decision=meta.media_type,
                title=meta.title,
                year=meta.year,
                source=meta.source,
            )
            return meta

        # Search + LLM fallback.
        search_results = self.search.search(f"{title} {year or ''} movie or tv show")
        metadata_guess = f"Candidate title: {title}, year: {year}, anime_hint: {info.is_anime_hint}"
        llm_result = self.llm.classify(
            folder_name=info.folder_name,
            filenames=[v.name for v in info.video_files],
            search_results=search_results,
            metadata_guess=metadata_guess,
        )
        if llm_result:
            media_type = llm_result.get("type")
            chosen_title = llm_result.get("title") or title
            chosen_year = str(llm_result.get("year")) if llm_result.get("year") else year
            season = llm_result.get("season")
            confidence = float(llm_result.get("confidence", 0.5))
            reason = llm_result.get("reason", "")
            if media_type in {"movie", "tv"}:
                self.log.info(
                    "classification_decision",
                    f"Classified via LLM: {reason}",
                    decision=media_type,
                    title=chosen_title,
                    year=chosen_year,
                    source="llm",
                    confidence=confidence,
                )
                return Classification(media_type, chosen_title, chosen_year, season, "llm", confidence)

        self.log.warning("classification_failed", "Could not classify folder", folder=info.folder_name)
        return None
