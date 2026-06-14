"""Bridge to import helper functions from the existing reorg scripts."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any


_MEDIA = Path("/mnt/my_passport/Media")


def _load_helpers(path: Path) -> Any:
    name = path.stem.lstrip(".")
    spec = importlib.util.spec_from_file_location(name, str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


_jellyfin_mod = _load_helpers(_MEDIA / ".codex_jellyfin_reorg.py")
_tv_mod = _load_helpers(_MEDIA / ".codex_seedhost_tv_reorg.py")
_movie_mod = _load_helpers(_MEDIA / ".codex_seedhost_movies_reorg.py")

Op = _jellyfin_mod.Op
unique_path = _jellyfin_mod.unique_path
validate_ops = _jellyfin_mod.validate_ops
apply_ops = _jellyfin_mod.apply_ops
infer_episode = _jellyfin_mod.infer_episode
infer_tv_show_from_stem = _jellyfin_mod.infer_tv_show_from_stem
infer_movie_title_year = _jellyfin_mod.infer_movie_title_year
video_quality_label = _jellyfin_mod.video_quality_label
clean_spaces = _jellyfin_mod.clean_spaces
safe_name = _jellyfin_mod.safe_name
title_case = _jellyfin_mod.title_case
strip_release_noise = _jellyfin_mod.strip_release_noise
clean_title_fragment = _jellyfin_mod.clean_title_fragment

normalize_show = _tv_mod.normalize_show
infer_show_from_context = _tv_mod.infer_show_from_context
fix_show = _tv_mod.fix_show
Episode = _tv_mod.Episode
tv_infer_episode = _tv_mod.infer_episode
infer_movie = _tv_mod.infer_movie

_movie_fixes = getattr(_movie_mod, "MANUAL_FIXES", {})
