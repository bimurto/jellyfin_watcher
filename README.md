# jellyfin_watcher

AI-enabled folder watcher that organizes finished downloads into Jellyfin-compatible paths.

## What it does

`jellyfin_watcher` monitors a staging folder (by default `/mnt/seedhost_sftp/downloads/finished`) and, for every new folder it finds:

1. Classifies the content as a **movie** or **TV/anime show**
2. Copies it to the correct Jellyfin library path
3. Renames files and sidecars to Jellyfin conventions
4. Verifies copied files using size + SHA-256 hash checks
5. Removes the source folder once verification succeeds

If a folder cannot be processed after a configurable number of retries, it is moved to a quarantine folder and a notification is sent via [Hermes](https://github.com/anthropics/hermes) (Telegram by default).

## Classification pipeline

Classification runs in the following order:

1. Filename pattern detection (`SxxExx`, `Season XX`, etc.)
2. [TMDB](https://www.themoviedb.org/) metadata search
3. [AniList](https://anilist.co/) fallback for anime
4. Web search fallback chain:
   - Local [SearXNG](https://docs.searxng.org/) instance
   - [Ollama](https://ollama.com/) web search
   - [Brave Search API](https://brave.com/search/api/)
5. Local LLM (Ollama) final decision

## Project layout

```
applications/jellyfin_watcher/
├── jellyfin_watcher/          # Python package
│   ├── config.py              # Environment-driven configuration
│   ├── logging_setup.py       # JSONL structured logging
│   ├── lock.py                # PID file lock
│   ├── metadata.py            # TMDB + AniList clients with SQLite cache
│   ├── search.py              # Search fallback chain
│   ├── llm.py                 # Local Ollama classifier
│   ├── classify.py            # End-to-end classification orchestrator
│   ├── naming.py              # Jellyfin-compatible path builder
│   ├── copy_verify.py         # Copy + verification
│   ├── quarantine.py          # Retry state + quarantine
│   ├── notify.py              # Hermes notification wrapper
│   ├── worker.py              # Per-folder processing
│   └── main.py                # CLI entrypoint
├── scripts/jellyfin_watcher   # uv wrapper for systemd
├── systemd/                   # Example systemd files
│   ├── jellyfin-watcher.service
│   └── jellyfin-watcher.timer
├── pyproject.toml
└── .env.example
```

## Requirements

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- Local Ollama server
- TMDB API key
- Optional: SearXNG, Brave Search API key
- Optional: Hermes for Telegram notifications

## Installation

```bash
git clone https://github.com/bimurto/jellyfin_watcher.git
cd jellyfin_watcher
uv sync
cp .env.example .env
# Edit .env with your API keys
```

## Configuration

Copy `.env.example` to `.env` and fill in the values:

```bash
JELLYFIN_WATCHER_SOURCE=/mnt/seedhost_sftp/downloads/finished
JELLYFIN_WATCHER_MOVIES_DST=/mnt/my_passport/Media/Movies
JELLYFIN_WATCHER_TV_DST=/mnt/my_passport/Media/TV Shows
JELLYFIN_WATCHER_STATE_ROOT=/mnt/my_passport/Media/.jellyfin_watcher

TMDB_API_KEY=your_tmdb_key
BRAVE_SEARCH_API_KEY=your_brave_key

OLLAMA_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2:3b
OLLAMA_CLASSIFY_MODEL=llama3.2:3b

NOTIFY_TARGET=telegram
```

## Usage

### Manual run (dry-run)

```bash
uv run python -m jellyfin_watcher.main --dry-run --once
```

### Process a single folder

```bash
uv run python -m jellyfin_watcher.main --apply --folder /mnt/seedhost_sftp/downloads/finished/My.Show.S01
```

### Run continuously via systemd

```bash
systemctl --user daemon-reload
systemctl --user enable jellyfin-watcher.timer
systemctl --user start jellyfin-watcher.timer
```

The timer triggers every 5 minutes.

## Logs

Logs are written as JSONL to:

```
/mnt/my_passport/Media/.jellyfin_watcher/log/watcher.jsonl
```

Tail them with:

```bash
tail -f /mnt/my_passport/Media/.jellyfin_watcher/log/watcher.jsonl
```

## Jellyfin naming

Movies:

```
Media/Movies/Movie Name (2024)/Movie Name (2024).mkv
Media/Movies/Movie Name (2024)/Movie Name (2024).en.srt
Media/Movies/Movie Name (2024)/poster.jpg
```

TV shows:

```
Media/TV Shows/Show Name/Season 01/Show Name S01E01.mkv
Media/TV Shows/Show Name/Season 01/Show Name S01E02.mkv
Media/TV Shows/Show Name/poster.jpg
```

Anime is treated as TV and placed under `TV Shows`.

## Safety features

- **File lock** prevents overlapping cron runs.
- **Copy verification** checks file size and SHA-256 hash before deleting source files.
- **Retry + quarantine** handles transient failures.
- **Dry-run mode** previews all planned operations without changing anything.
- **Conflict handling** skips folders whose destination already exists.

## License

MIT
