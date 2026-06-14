"""Local Ollama-based classification decision."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from ollama import Client

from jellyfin_watcher.config import Config


logger = logging.getLogger("jellyfin_watcher")


class LLMClassifier:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.client = Client(host=cfg.ollama_url)

    def classify(
        self,
        folder_name: str,
        filenames: list[str],
        search_results: list[dict[str, str]],
        metadata_guess: str | None = None,
    ) -> dict[str, Any] | None:
        snippets = "\n".join(
            f"- {r['title']}: {r['description']}" for r in search_results[:6]
        )
        prompt = f"""You are a media librarian. A new folder has arrived with video files. Determine if it is a movie or a TV show (anime counts as TV unless it is a standalone film).

Folder name: {folder_name}
Video filenames:
{chr(10).join(f"- {fn}" for fn in filenames[:20])}

{"Prior metadata guess: " + metadata_guess if metadata_guess else ""}

Web search snippets:
{snippets}

Return ONLY a JSON object with these keys:
- "type": either "movie" or "tv"
- "title": the canonical English title
- "year": release year as a 4-digit string, or null if unknown
- "season": season number if it is a TV show and known, otherwise null
- "confidence": a number from 0.0 to 1.0
- "reason": one sentence explaining your decision

No markdown, no commentary, only JSON."""
        try:
            resp = self.client.generate(
                model=self.cfg.ollama_classify_model,
                prompt=prompt,
                stream=False,
                options={"temperature": 0.1, "num_predict": 256},
            )
        except Exception as exc:
            logger.warning("llm_generate_failed", extra={"event": "llm_generate_failed", "error": str(exc)})
            return None

        raw = resp.get("response", "") if isinstance(resp, dict) else getattr(resp, "response", "")
        return self._parse_json(raw)

    def _parse_json(self, text: str) -> dict[str, Any] | None:
        text = text.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # Try to extract the first JSON object.
            m = re.search(r"\{.*\}", text, re.S)
            if not m:
                return None
            try:
                data = json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
        if data.get("type") not in {"movie", "tv"}:
            return None
        return data
