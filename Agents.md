# Claude Code Agent Context

## Project Overview

This repository contains `jellyfin_watcher`, an AI-enabled Python service that watches a staging folder for new media downloads, classifies each item as a movie or TV/anime show, and restructures it into Jellyfin-compatible paths on a local media library.

## Key responsibilities

When working on this codebase, the agent should:

- Preserve the existing modular structure under `jellyfin_watcher/`.
- Reuse existing helper logic from the Jellyfin reorg scripts mounted at `/mnt/my_passport/Media/.codex_*.py` rather than duplicating regex/parsing logic.
- Keep configuration environment-driven via `.env`.
- Maintain the systemd timer behavior (every 5 minutes, single oneshot run, file lock).
- Ensure destructive operations require `--apply` and support `--dry-run`.
- Preserve JSONL structured logging to `/mnt/my_passport/Media/.jellyfin_watcher/log/watcher.jsonl`.
- Keep classification order deterministic: filename pattern → TMDB → AniList → search fallback chain → local LLM.
- Treat anime as TV unless AniList reports the format as `MOVIE`.

## Common tasks

- Adding new sidecar file handling: update `jellyfin_watcher/naming.py` and `jellyfin_watcher/config.py` `MediaTypes`.
- Adding a new search provider: implement in `jellyfin_watcher/search.py` and wire into `SearchChain.search()`.
- Adjusting retry/quarantine behavior: modify `jellyfin_watcher/quarantine.py` and `jellyfin_watcher/worker.py`.
- Changing classification prompts: edit `jellyfin_watcher/llm.py`.

## Architecture

- `config.py`: loads `.env` and exposes a frozen `Config` dataclass.
- `logging_setup.py`: JSONL logging with `ContextLog` helpers.
- `lock.py`: `fcntl` PID lock to prevent overlapping runs.
- `metadata.py`: TMDB and AniList clients with SQLite caching.
- `search.py`: SearXNG, Ollama web search, and Brave Search fallback chain.
- `llm.py`: Ollama-based classifier returning structured JSON.
- `classify.py`: orchestrates all classification stages.
- `naming.py`: builds Jellyfin-compatible destination `Op` lists.
- `copy_verify.py`: copies and verifies files with size/hash checks.
- `quarantine.py`: retry tracking and quarantine moves.
- `notify.py`: Hermes `send_message_tool` notifications.
- `worker.py`: per-folder processing and `run_once()` orchestration.
- `main.py`: CLI entrypoint.

## Testing

- Run dry-run: `uv run python -m jellyfin_watcher.main --dry-run --once`
- Process one folder: `uv run python -m jellyfin_watcher.main --apply --folder <path>`
- Watch systemd: `journalctl --user -u jellyfin-watcher.service -f`
- Read logs: `tail -f /mnt/my_passport/Media/.jellyfin_watcher/log/watcher.jsonl`

## Important paths

- Source watch folder: `/mnt/seedhost_sftp/downloads/finished`
- Movie destination: `/mnt/my_passport/Media/Movies`
- TV destination: `/mnt/my_passport/Media/TV Shows`
- Runtime state: `/mnt/my_passport/Media/.jellyfin_watcher/`
- Quarantine: `/mnt/seedhost_sftp/downloads/_quarantine`
