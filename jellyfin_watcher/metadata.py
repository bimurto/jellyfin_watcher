"""TMDB and AniList metadata clients with SQLite cache."""
from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from jellyfin_watcher.config import Config


@dataclass(frozen=True)
class Classification:
    media_type: str  # 'movie' or 'tv'
    title: str
    year: str | None
    season: int | None
    source: str
    confidence: float


def _normalize_query(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower()).strip()


class MetadataCache:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(db_path), check_same_thread=False)
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                created_at REAL NOT NULL
            )
            """
        )
        self._db.commit()

    def get(self, key: str, ttl_seconds: int = 604800) -> Any | None:
        cur = self._db.execute("SELECT value, created_at FROM cache WHERE key = ?", (key,))
        row = cur.fetchone()
        if not row:
            return None
        value, created_at = row
        if time.time() - created_at > ttl_seconds:
            self._db.execute("DELETE FROM cache WHERE key = ?", (key,))
            self._db.commit()
            return None
        return json.loads(value)

    def set(self, key: str, value: Any) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO cache (key, value, created_at) VALUES (?, ?, ?)",
            (key, json.dumps(value, default=str), time.time()),
        )
        self._db.commit()


class TMDBClient:
    def __init__(self, api_key: str | None, cache: MetadataCache, language: str = "en-US") -> None:
        self.api_key = api_key
        self.cache = cache
        self.language = language
        self.client = httpx.Client(timeout=30.0, base_url="https://api.themoviedb.org/3")

    def search_movie(self, query: str, year: str | None = None) -> dict[str, Any] | None:
        if not self.api_key:
            return None
        key = f"tmdb:movie:{_normalize_query(query)}:{year}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached

        params: dict[str, Any] = {"api_key": self.api_key, "query": query, "language": self.language}
        if year:
            params["year"] = year
        try:
            resp = self.client.get("/search/movie", params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return None
        result = self._best_result(data.get("results", []), query, year=year)
        if result:
            self.cache.set(key, result)
        return result

    def search_tv(self, query: str) -> dict[str, Any] | None:
        if not self.api_key:
            return None
        key = f"tmdb:tv:{_normalize_query(query)}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached

        params = {"api_key": self.api_key, "query": query, "language": self.language}
        try:
            resp = self.client.get("/search/tv", params=params)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return None
        result = self._best_result(data.get("results", []), query)
        if result:
            self.cache.set(key, result)
        return result

    def _best_result(self, results: list[dict[str, Any]], query: str, year: str | None = None) -> dict[str, Any] | None:
        if not results:
            return None
        norm_query = _normalize_query(query)
        for r in results[:3]:
            title = r.get("title") or r.get("name") or ""
            if _normalize_query(title) == norm_query:
                if year and (r.get("release_date") or r.get("first_air_date") or "").startswith(year):
                    return r
                if not year:
                    return r
        first = results[0]
        title = first.get("title") or first.get("name") or ""
        if _normalize(title) in _normalize_query(query) or _normalize_query(query) in _normalize(title):
            return first
        return None


class AniListClient:
    URL = "https://graphql.anilist.co"

    def __init__(self, cache: MetadataCache) -> None:
        self.cache = cache
        self.client = httpx.Client(timeout=30.0)

    def search_anime(self, query: str) -> dict[str, Any] | None:
        key = f"anilist:{_normalize_query(query)}"
        cached = self.cache.get(key)
        if cached is not None:
            return cached

        q = """
        query ($search: String) {
            Media(search: $search, type: ANIME) {
                id
                title { romaji english native }
                format
                seasonYear
                startDate { year }
            }
        }
        """
        try:
            resp = self.client.post(self.URL, json={"query": q, "variables": {"search": query}})
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return None
        media = data.get("data", {}).get("Media")
        if media:
            self.cache.set(key, media)
        return media


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower()).strip()


def classify_from_metadata(
    query: str,
    year: str | None,
    tmdb: TMDBClient,
    anilist: AniListClient,
    is_anime_hint: bool = False,
) -> Classification | None:
    # Try TMDB movie first if we have a year or no strong anime hint.
    if not is_anime_hint:
        movie = tmdb.search_movie(query, year)
        if movie:
            return Classification(
                media_type="movie",
                title=movie.get("title", query),
                year=str(movie.get("release_date", ""))[:4] or year,
                season=None,
                source="tmdb_movie",
                confidence=0.9,
            )
        tv = tmdb.search_tv(query)
        if tv:
            return Classification(
                media_type="tv",
                title=tv.get("name", query),
                year=str(tv.get("first_air_date", ""))[:4] or None,
                season=None,
                source="tmdb_tv",
                confidence=0.9,
            )

    # AniList fallback (strong anime hint or TMDB miss).
    anime = anilist.search_anime(query)
    if anime:
        title = anime.get("title", {})
        chosen = title.get("english") or title.get("romaji") or query
        fmt = (anime.get("format") or "").upper()
        year_value = str(anime.get("seasonYear") or anime.get("startDate", {}).get("year") or "")
        media_type = "movie" if fmt == "MOVIE" else "tv"
        return Classification(
            media_type=media_type,
            title=chosen,
            year=year_value or year,
            season=None,
            source="anilist",
            confidence=0.85,
        )

    # If anime hint but no AniList, still fall back to TMDB TV as last resort.
    if is_anime_hint:
        tv = tmdb.search_tv(query)
        if tv:
            return Classification(
                media_type="tv",
                title=tv.get("name", query),
                year=str(tv.get("first_air_date", ""))[:4] or None,
                season=None,
                source="tmdb_tv_fallback",
                confidence=0.75,
            )

    return None
