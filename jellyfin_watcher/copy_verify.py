"""Copy files over sshfs/exFAT with size/hash verification."""
from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path
from typing import Iterable

from jellyfin_watcher.reorg_bridge import Op


logger = logging.getLogger("jellyfin_watcher")


CHUNK_SIZE = 1024 * 1024


def _hash_file(path: Path, sample_only: bool = False, sample_bytes: int = 64 * 1024) -> str:
    h = hashlib.sha256()
    size = path.stat().st_size
    with path.open("rb") as f:
        if not sample_only or size <= sample_bytes * 2:
            while True:
                chunk = f.read(CHUNK_SIZE)
                if not chunk:
                    break
                h.update(chunk)
        else:
            h.update(f.read(sample_bytes))
            f.seek(-sample_bytes, 2)
            h.update(f.read(sample_bytes))
    return h.hexdigest()


def copy_with_verify(src: Path, dst: Path, full_hash_max_bytes: int) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)
        return

    tmp = dst.with_suffix(dst.suffix + ".tmp")
    try:
        shutil.copy2(src, tmp)
        src_size = src.stat().st_size
        tmp_size = tmp.stat().st_size
        if src_size != tmp_size:
            raise RuntimeError(f"size mismatch: {src_size} vs {tmp_size}")

        sample_only = src_size > full_hash_max_bytes
        src_hash = _hash_file(src, sample_only=sample_only, sample_bytes=64 * 1024)
        dst_hash = _hash_file(tmp, sample_only=sample_only, sample_bytes=64 * 1024)
        if src_hash != dst_hash:
            raise RuntimeError(f"hash mismatch for {src}")

        tmp.replace(dst)
    except Exception:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise


def copy_tree_with_verify(ops: Iterable[Op], full_hash_max_bytes: int) -> None:
    for op in ops:
        copy_with_verify(op.src, op.dst, full_hash_max_bytes)


def remove_source_tree(src: Path) -> None:
    shutil.rmtree(src, ignore_errors=True)
