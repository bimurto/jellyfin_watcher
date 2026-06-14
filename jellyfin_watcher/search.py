"""Search fallback chain: SearXNG -> Ollama web_search -> Brave."""
from __future__ import annotations

import json
import re
from typing import Any

import httpx
from ollama import Client

from jellyfin_watcher.config import Config


def _clean_snippet(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()[:500]


class SearchChain:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.client = httpx.Client(timeout=30.0)
        self.ollama = Client(host=cfg.ollama_url)

    def search(self, query: str, limit: int = 5) -> list[dict[str, str]]:
        results = self._searxng(query, limit)
        if results:
            return results
        results = self._ollama_web_search(query, limit)
        if results:
            return results
        results = self._brave(query, limit)
        return results or []

    def _searxng(self, query: str, limit: int) -> list[dict[str, str]]:
        url = f"{self.cfg.searxng_url}/search"
        try:
            resp = self.client.get(url, params={"q": query, "format": "json", "pageno": 1})
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []
        items: list[dict[str, str]] = []
        for r in data.get("results", [])[:limit]:
            items.append(
                {
                    "title": _clean_snippet(r.get("title", "")),
                    "url": r.get("url", ""),
                    "description": _clean_snippet(r.get("content", "")),
                }
            )
        return items

    def _ollama_web_search(self, query: str, limit: int) -> list[dict[str, str]]:
        try:
            resp = self.ollama.web_search(query=query, max_results=limit)
        except Exception:
            return []
        items: list[dict[str, str]] = []
        # ollama web_search returns a model_dump; shape varies by version.
        raw = resp.model_dump() if hasattr(resp, "model_dump") else resp
        results = raw.get("results", []) if isinstance(raw, dict) else []
        for r in results[:limit]:
            if isinstance(r, dict):
                items.append(
                    {
                        "title": _clean_snippet(r.get("title", "")),
                        "url": r.get("url", ""),
                        "description": _clean_snippet(r.get("content", r.get("snippet", ""))),
                    }
                )
        return items

    def _brave(self, query: str, limit: int) -> list[dict[str, str]]:
        if not self.cfg.brave_api_key:
            return []
        try:
            resp = self.client.get(
                "https://api.search.brave.com/res/v1/web/search",
                params={"q": query, "count": limit},
                headers={"X-Subscription-Token": self.cfg.brave_api_key, "Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []
        items: list[dict[str, str]] = []
        for r in data.get("web", {}).get("results", [])[:limit]:
            items.append(
                {
                    "title": _clean_snippet(r.get("title", "")),
                    "url": r.get("url", ""),
                    "description": _clean_snippet(r.get("description", "")),
                }
            )
        return items
