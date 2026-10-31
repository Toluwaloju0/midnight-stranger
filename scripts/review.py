#!/usr/bin/env python3
"""Phase 4: fill the cache with demo episodes and record the numbers for the write-up.

    python scripts/pregenerate.py                  # 3 unplayed episodes per station (real models)
    python scripts/pregenerate.py --per-station 4
    python scripts/pregenerate.py --station 93.7 --per-station 5
    python scripts/pregenerate.py --fake           # quick dry run, no models

It is safe to stop (Ctrl+C) and run again: it counts the unplayed episodes already
in the cache and only makes the missing ones. Stations are filled in rotation, so a
partial run still covers every station. Stop `python -m app serve` first (or run it
with --no-worker), otherwise two generators compete for 2 CPU cores.

Writes cache/measurements.json: seconds per episode, lowest free RAM seen, cache size.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config, store  # noqa: E402
from app.generator import GenerationError  # noqa: E402
from app.stations import STATIONS, by_freq  # noqa: E402


def mem_available_mb() -> float | None:
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1024
    except OSError:
        pass
    return None


class RamWatcher(threading.Thread):
    """Samples free RAM every second; the lowest value tells you the peak load of everything (Ollama included)."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.lowest = mem_available_mb()
        self.start_free = self.lowest
        self._halt = threading.Event()

    def run(self) -> None:
        while not self._halt.wait(1.0):
            free = mem_available_mb()
            if free is not None and (self.lowest is None or free < self.lowest):
                self.lowest = free

    def stop(self) -> None:
        self._halt.set()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--per-station", type=int, default=3, help="unplayed episodes to have per station (default 3)")
    ap.add_argument("--station", action="append", help="only this dial position (repeatable)")
    ap.add_argument("--fake", action="store_true", help="canned stories and tone speech")
    ap.add_argument("--max-failures", type=int, default=6, help="stop after this many failed episodes (default 6)")
    args = ap.parse_args()

    if args.fake:
        config.FAKE = True
    from app.pipeline import make_episode

    try:
        stations = [by_freq(f) for f in args.station] if args.station else list(STATIONS)
    except KeyError as exc:
        print(exc.args[0], file=sys.stderr)
        return 2

    have = store.queue_counts()
    todo = {s.freq: max(0, args.per_station - have.get(s.freq, 0)) for s in stations}
    total = sum(todo.values())
    print(f"Have: {have}\nTo make: {todo}  ({total} episodes)"
          f"{'  [fake mode]' if config.FAKE else ''}\n", flush=True)
    if not total:
        print("Nothing to do.")
        return 0

    watcher = RamWatcher()
    watcher.start()
    made, failures, t0 = [], 0, time.perf_counter()
    try:
        while any(todo.values()) and failures < args.max_failures:
            for s in stations:
                if not todo[s.freq]:
                    continue
                n = len(made) + failures + 1
                print(f"[{n}/{total}] {s.freq} {s.name} ...", flush=True)
                try:
                    meta = make_episode(s)
                except (GenerationError, FileNotFoundError, RuntimeError) as exc:
                    failures += 1
                    print(f"    FAILED: {exc}", file=sys.stderr, flush=True)
                    if failures >= args.max_failures:
                        break
                    continue
                todo[s.freq] -= 1
                made.append(meta)
                sec = meta["seconds"]
                print(f"    \"{meta['title']}\"  {meta['words']} words, {meta['duration']:.0f}s audio, "
                      f"story {sec['story']}s, total {sec['total']}s, attempts {meta['attempts']}", flush=True)
                store.enforce_cap()
    except KeyboardInterrupt:
        print("\nStopped. Run again to continue; finished episodes are kept.")
    finally:
        watcher.stop()

    wall = time.perf_counter() - t0
    report = {
        "fake": config.FAKE,
        "model": config.MODEL,
        "episodes_made": len(made),
        "failures": failures,
        "wall_seconds": round(wall, 1),
        "avg_total_seconds": round(sum(m["seconds"]["total"] for m in made) / len(made), 1) if made else None,
        "avg_story_seconds": round(sum(m["seconds"]["story"] for m in made) / len(made), 1) if made else None,
        "avg_words": round(sum(m["words"] for m in made) / len(made)) if made else None,
        "avg_audio_seconds": round(sum(m["duration"] for m in made) / len(made)) if made else None,
        "retried_episodes": sum(1 for m in made if m["attempts"] > 1),
        "fallback_model_used": sum(1 for m in made if m["model"] != config.MODEL),
        "free_ram_mb_at_start": round(watcher.start_free) if watcher.start_free else None,
        "lowest_free_ram_mb": round(watcher.lowest) if watcher.lowest else None,
        "cache_mb": round(store.total_bytes() / 1e6, 1),
        "episodes_in_cache": len(store.list_episodes()),
    }
    out = Path(config.CACHE_DIR) / "measurements.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    print("\n=== MEASUREMENTS (copy into the post) ===")
    for k, v in report.items():
        print(f"{k:>24}: {v}")
    print(f"\nSaved to {out}\nNext: python scripts/review.py")
    return 1 if failures and not made else 0


if __name__ == "__main__":
    raise SystemExit(main())