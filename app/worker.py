"""Background worker: keeps a few unplayed episodes ready for every station.

One generation at a time (the machine has few cores). When a listener takes an
episode, the API calls prioritize() so that station is refilled first. If
generation fails (for example Ollama is down) the worker records the error and
backs off, and the API keeps serving whatever is already cached.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Callable

from . import config, store
from .generator import GenerationError
from .stations import STATIONS, Station, by_freq

log = logging.getLogger("midnight_stranger.worker")


def _default_maker(station: Station) -> dict:
    from .pipeline import make_episode

    return make_episode(station)


class Worker(threading.Thread):
    def __init__(self, maker: Callable[[Station], dict] | None = None, *,
                 target: int | None = None, backoff_base: float = 15.0,
                 backoff_max: float = 300.0, idle_s: float = 5.0) -> None:
        super().__init__(name="ms-worker", daemon=True)
        self.maker = maker or _default_maker
        self._target = target
        self.backoff_base = backoff_base
        self.backoff_max = backoff_max
        self.idle_s = idle_s
        self._halt = threading.Event()   # NB: Thread already uses the name _stop
        self._wake = threading.Event()
        self._lock = threading.Lock()
        self._paused = False
        self._hint: str | None = None
        self._current: str | None = None
        self._current_since = 0.0
        self._last_error: str | None = None
        self._last_error_at = 0.0
        self._last_ok_at = 0.0
        self._last_episode_id: str | None = None
        self._fail_streak = 0
        self._made = 0
        self._made_seconds = 0.0

    # ---- controls -----------------------------------------------------
    @property
    def target(self) -> int:
        return self._target if self._target is not None else config.QUEUE_TARGET

    @property
    def paused(self) -> bool:
        return self._paused

    def pause(self) -> None:
        """Stop starting new episodes. An episode already being made will finish."""
        self._paused = True

    def resume(self) -> None:
        self._paused = False
        self._wake.set()

    def prioritize(self, freq: str) -> None:
        self._hint = freq
        self._wake.set()

    def shutdown(self) -> None:
        self._halt.set()
        self._wake.set()
        if self.is_alive():
            self.join(timeout=2.0)

    def status(self) -> dict:
        with self._lock:
            now = time.time()
            return {
                "running": self.is_alive(),
                "paused": self._paused,
                "generating": self._current,
                "generating_for_s": round(now - self._current_since, 1) if self._current else 0,
                "target_per_station": self.target,
                "last_error": self._last_error,
                "seconds_since_error": round(now - self._last_error_at) if self._last_error else None,
                "seconds_since_ok": round(now - self._last_ok_at) if self._last_ok_at else None,
                "last_episode_id": self._last_episode_id,
                "fail_streak": self._fail_streak,
                "episodes_made": self._made,
                "avg_seconds_per_episode": round(self._made_seconds / self._made, 1) if self._made else None,
            }

    # ---- internals ----------------------------------------------------
    def _pick(self) -> Station | None:
        counts = store.queue_counts()
        target = self.target
        hint = self._hint
        if hint and counts.get(hint, 0) < target:
            try:
                return by_freq(hint)
            except KeyError:
                self._hint = None
        needy = [s for s in STATIONS if counts.get(s.freq, 0) < target]
        return min(needy, key=lambda s: counts.get(s.freq, 0)) if needy else None

    def _begin(self, station: Station) -> None:
        with self._lock:
            self._current, self._current_since = station.freq, time.time()

    def _end(self) -> None:
        with self._lock:
            self._current = None

    def _succeed(self, meta: dict, seconds: float) -> None:
        with self._lock:
            self._last_ok_at = time.time()
            self._last_episode_id = meta.get("id")
            self._fail_streak = 0
            self._last_error = None
            self._made += 1
            self._made_seconds += seconds

    def _fail(self, message: str) -> None:
        with self._lock:
            self._last_error, self._last_error_at = message, time.time()
            self._fail_streak += 1
        log.warning("generation failed: %s", message)

    def run(self) -> None:
        try:
            os.nice(10)   # Linux: this thread yields to the web server and your other work
        except (AttributeError, OSError):
            pass
        log.info("worker started (target %d per station)", self.target)
        while not self._halt.is_set():
            station = None if self._paused else self._pick()
            if station is None:
                self._wake.wait(self.idle_s)
                self._wake.clear()
                continue
            self._begin(station)
            started = time.perf_counter()
            failed = False
            try:
                meta = self.maker(station)
            except GenerationError as exc:
                failed = True
                self._fail(str(exc))
            except Exception as exc:  # keep the worker alive whatever goes wrong
                failed = True
                log.exception("unexpected error while making an episode")
                self._fail(f"{type(exc).__name__}: {exc}")
            else:
                self._succeed(meta, time.perf_counter() - started)
                try:
                    store.enforce_cap()
                except Exception:
                    log.exception("cache cleanup failed")
            finally:
                self._end()
            if failed:
                delay = min(self.backoff_max, self.backoff_base * 2 ** max(0, self._fail_streak - 1))
                self._halt.wait(delay)
        log.info("worker stopped")