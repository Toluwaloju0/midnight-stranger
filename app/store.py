"""Episode storage: one <id>.wav plus one <id>.json per episode in cache/episodes/.

The .json is written last (atomically), so an episode only "exists" once both
files are complete. Playing state lives in the json ("played", "played_at").
All functions take a lock because the API threads and the worker thread share
the folder.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path

from . import config
from .stations import STATIONS

ID_RE = re.compile(r"^\d{8}-\d{6}-\d+_\d-[0-9a-f]{4}$")
ORPHAN_AGE_S = 600

_lock = threading.RLock()


def episodes_dir() -> Path:
    return Path(config.CACHE_DIR) / "episodes"


def write_json_atomic(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    os.replace(tmp, path)


def _load(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or "id" not in data or "station" not in data:
        return None
    if not path.with_suffix(".wav").exists():
        return None
    return data


def _save(meta: dict) -> None:
    write_json_atomic(episodes_dir() / f"{meta['id']}.json", meta)


def list_episodes() -> list[dict]:
    """All complete episodes, oldest first."""
    folder = episodes_dir()
    if not folder.is_dir():
        return []
    with _lock:
        return [m for p in sorted(folder.glob("*.json")) if (m := _load(p))]


def get_episode(episode_id: str) -> dict | None:
    if not ID_RE.match(episode_id or ""):
        return None
    with _lock:
        return _load(episodes_dir() / f"{episode_id}.json")


def wav_path(episode_id: str) -> Path | None:
    if not ID_RE.match(episode_id or ""):
        return None
    path = episodes_dir() / f"{episode_id}.wav"
    return path if path.is_file() else None


def queue_counts() -> dict[str, int]:
    """Unplayed episodes per station frequency (every station present, 0 if none)."""
    counts = {s.freq: 0 for s in STATIONS}
    for meta in list_episodes():
        if not meta.get("played"):
            freq = meta["station"]["freq"]
            counts[freq] = counts.get(freq, 0) + 1
    return counts


def total_counts() -> dict[str, int]:
    counts = {s.freq: 0 for s in STATIONS}
    for meta in list_episodes():
        freq = meta["station"]["freq"]
        counts[freq] = counts.get(freq, 0) + 1
    return counts


def next_for(freq: str) -> tuple[dict, bool] | None:
    """Pick the next episode for a station and mark it played.

    Returns (metadata, is_replay). Oldest unplayed first; if everything has been
    played, the least recently played one is replayed so the radio never goes
    silent. None if the station has no episodes at all.
    """
    with _lock:
        mine = [m for m in list_episodes() if m["station"]["freq"] == freq]
        if not mine:
            return None
        unplayed = [m for m in mine if not m.get("played")]
        if unplayed:
            meta, replay = unplayed[0], False
        else:
            meta, replay = min(mine, key=lambda m: m.get("played_at", 0)), True
        meta["played"] = True
        meta["played_at"] = time.time()
        meta["play_count"] = int(meta.get("play_count", 0)) + 1
        _save(meta)
        return meta, replay


def delete_episode(episode_id: str) -> None:
    if not ID_RE.match(episode_id or ""):
        return
    for suffix in (".wav", ".json"):
        try:
            (episodes_dir() / f"{episode_id}{suffix}").unlink()
        except FileNotFoundError:
            pass


def total_bytes() -> int:
    folder = episodes_dir()
    if not folder.is_dir():
        return 0
    total = 0
    for path in folder.iterdir():
        try:
            total += path.stat().st_size
        except OSError:
            pass
    return total


def _remove_orphans() -> None:
    """Delete .wav files with no .json (a crash between the two writes) and stale temp files."""
    folder = episodes_dir()
    if not folder.is_dir():
        return
    now = time.time()
    for path in folder.iterdir():
        try:
            old = now - path.stat().st_mtime > ORPHAN_AGE_S
            orphan_wav = path.suffix == ".wav" and not path.with_suffix(".json").exists()
            if old and (orphan_wav or path.name.endswith(".tmp")):
                path.unlink()
        except OSError:
            pass


def enforce_cap(cap_mb: float | None = None) -> list[str]:
    """Delete the oldest played episodes until the cache fits under the cap.

    Never deletes unplayed episodes, and always keeps the most recently played
    episode of each station so there is something to replay. Returns deleted ids.
    """
    cap = int((cap_mb if cap_mb is not None else config.CACHE_CAP_MB) * 1_000_000)
    deleted: list[str] = []
    with _lock:
        _remove_orphans()
        while total_bytes() > cap:
            episodes = list_episodes()
            newest_played: dict[str, dict] = {}
            for meta in episodes:
                if meta.get("played"):
                    freq = meta["station"]["freq"]
                    best = newest_played.get(freq)
                    if best is None or meta.get("played_at", 0) > best.get("played_at", 0):
                        newest_played[freq] = meta
            protected = {m["id"] for m in newest_played.values()}
            candidates = [m for m in episodes if m.get("played") and m["id"] not in protected]
            if not candidates:
                break
            victim = min(candidates, key=lambda m: m.get("played_at", 0))
            delete_episode(victim["id"])
            deleted.append(victim["id"])
    return deleted