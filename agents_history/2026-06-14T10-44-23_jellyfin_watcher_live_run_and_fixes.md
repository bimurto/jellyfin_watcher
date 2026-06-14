# Jellyfin Watcher — Live Run & Fixes

**Date:** 2026-06-14  
**Agent session:** Continuation of `jellyfin_watcher` implementation and first live systemd run  
**Status:** Service running, actively copying GATE anime folder

---

## 1. Project Goal

Build an AI-enabled Python service that:
- Watches `/mnt/seedhost_sftp/downloads/finished`
- Classifies each new folder as **movie** or **TV/anime**
- Copies verified files to `/mnt/my_passport/Media/Movies` or `/mnt/my_passport/Media/TV Shows`
- Restructures them into Jellyfin-compatible paths
- Handles sidecars (subtitles, posters, NFOs), extras, and special/OVA episodes
- Retries failures, quarantines persistent failures, sends Telegram notifications via Hermes
- Runs as a systemd user timer every 5 minutes with a file lock

---

## 2. Implementation Timeline

### Phase 1 — Initial Setup (Previous Session)
- Created `uv` project under `/home/bimurto/applications/jellyfin_watcher/`
- Added `pyproject.toml`, `uv.lock`, `.env.example`, `README.md`
- Created core modules:
  - `config.py` — env-driven configuration
  - `logging_setup.py` — JSONL structured logging
  - `lock.py` — `fcntl` PID file lock
  - `metadata.py` — TMDB + AniList clients with SQLite cache
  - `search.py` — SearXNG → Ollama web search → Brave fallback chain
  - `llm.py` — Ollama structured classification
  - `classify.py` — filename pattern → TMDB → AniList → search → LLM
  - `naming.py` — Jellyfin path builder using existing reorg helpers
  - `copy_verify.py` — copy + SHA-256 verification
  - `quarantine.py` — retry tracking and quarantine moves
  - `notify.py` — Hermes Telegram notifications
  - `worker.py` — per-folder processing
  - `main.py` — CLI entrypoint
- Created systemd user service and timer:
  - `~/.config/systemd/user/jellyfin-watcher.service`
  - `~/.config/systemd/user/jellyfin-watcher.timer`
- Created wrapper script `scripts/jellyfin_watcher`

### Phase 2 — Fixes Discovered During First Live Run (2026-06-14)

#### 10:30 — Switched wrapper from `uv` to `.venv/bin/python`
- **Problem:** systemd failed with `uv: not found` because `uv` was not in systemd's PATH.
- **Fix:** `scripts/jellyfin_watcher` now directly executes `.venv/bin/python -m jellyfin_watcher.main --apply --once`.

#### Earlier — Fixed `.env` loading for Ollama model
- **Problem:** `OLLAMA_CLASSIFY_MODEL` stayed at default `gemma4` instead of the configured model.
- **Fix:** In `config.py`, set `load_dotenv` path to `Path(__file__).resolve().parents[1] / ".env"` and added `override=True`.

#### Earlier — Fixed dynamic import of existing reorg scripts
- **Problem:** `reorg_bridge.py` loaded `.codex_jellyfin_reorg.py` and related scripts, but dataclass processing inside them failed with `AttributeError`.
- **Fix:** Added `sys.modules[name] = module` before `exec_module` so submodules resolve correctly.

#### Earlier — Fixed year regex in `classify.py`
- **Problem:** `_YEAR_RE` had an invalid escape (`?\<`) causing regex compilation failure.
- **Fix:** Corrected to `(?<!\d)(19\d{2}|20\d{2})(?!\d)`.

#### Earlier — Improved title cleaning using existing reorg helpers
- **Problem:** Raw noisy folder name `[RH] GATE [Dual Audio] ...` was passed to TMDB, causing classification failure.
- **Fix:** In `classify.py`, imported `strip_bracket_noise` and `strip_noise` from `reorg_bridge.py` and added `_clean_title_for_search()` to reduce folder names to clean search titles like `GATE`.

#### Earlier — Routed unparseable TV videos to `extras`
- **Problem:** Files like `[RH] GATE - Comic2 [...].mkv` had no parseable episode pattern, so they were dropped.
- **Fix:** In `naming.py`, added logic to send unparseable videos to the show's `extras` folder with sequential naming (`Gate - extra 01.mkv`, etc.).

---

## 3. First Live Test — GATE Anime Folder

### Source
`/mnt/seedhost_sftp/downloads/finished/[RH] GATE [Dual Audio] [BDRip] [Hi10] [1080p]`  
Size: ~21 GB

### Classification Result
- Media type: `tv`
- Show title: `Gate`
- Source: `filename_pattern`
- Confidence: 0.9

### Destination Structure Planned
```
/mnt/my_passport/Media/TV Shows/Gate/
├── Season 01/
│   ├── Gate S01E01.mkv
│   ├── Gate S01E02.mkv
│   ├── ...
│   └── Gate S01E24.mkv
├── Season 00/
│   ├── Gate S00E101.mkv  # NCED1
│   ├── Gate S00E102.mkv  # NCED2
│   ├── Gate S00E103.mkv  # NCOP1
│   └── Gate S00E104.mkv  # NCOP2
└── extras/
    ├── Gate - extra 01.mkv  # Comic1
    ├── Gate - extra 02.mkv  # Comic2
    ├── Gate - extra 03.mkv  # Comic3
    └── Gate - extra 04.mkv  # Comic4
```

### Live Run Status (2026-06-14 10:30–10:44)
- `jellyfin-watcher.service` active with PID `287292`
- Memory: ~4.2 GB
- Copied so far: ~2 GB
- `Season 01/Gate S01E01.mkv` complete
- `Season 01/Gate S01E02.mkv` complete
- `Season 01/Gate S01E03.mkv` in progress (`.tmp` file present)
- Source folder still present; will be removed only after all files copy and verify.

### Expected Completion
At observed copy rate, the remaining ~19 GB will likely take another 1–2 hours. The file lock ensures the next 5-minute timer trigger will skip until this run finishes.

---

## 4. Uncommitted Code Changes

Files modified during this session and pending commit:
- `jellyfin_watcher/classify.py` — title cleaning, regex fix
- `jellyfin_watcher/naming.py` — extras fallback for unparseable videos
- `jellyfin_watcher/reorg_bridge.py` — helper imports
- `scripts/jellyfin_watcher` — use `.venv/bin/python` instead of `uv`

---

## 5. Next Steps

1. Wait for the current live run to complete.
2. Verify all 28 video files exist in the destination, with correct sizes and names.
3. Confirm source folder was removed after successful verification.
4. Commit and push all pending changes to GitHub.
5. Monitor systemd timer over the next few cycles to confirm idempotent behavior.
