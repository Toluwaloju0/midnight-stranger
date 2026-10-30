"""Central configuration for Midnight Stranger.

Everything can be overridden with environment variables prefixed MS_.
Ollama's own host is read by the ollama client from OLLAMA_HOST.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _path(name: str, default: Path) -> Path:
    return Path(os.environ.get(name, str(default))).expanduser()


def _int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


# Paths
VOICES_DIR = _path("MS_VOICES_DIR", ROOT / "voices")
CACHE_DIR = _path("MS_CACHE_DIR", ROOT / "cache")

# Models
MODEL = os.environ.get("MS_MODEL", "gemma3:4b")
FALLBACK_MODEL = os.environ.get("MS_FALLBACK_MODEL", "gemma3:1b")

# Server (local only by default)
HOST = os.environ.get("MS_HOST", "127.0.0.1")
PORT = _int("MS_PORT", 8137)

# Queue and cache
QUEUE_TARGET = _int("MS_QUEUE_TARGET", 2)      # finished episodes kept ready per station
CACHE_CAP_MB = _int("MS_CACHE_CAP_MB", 300)    # delete oldest played episodes above this

# Story shape
MIN_WORDS = _int("MS_MIN_WORDS", 250)
MAX_WORDS = _int("MS_MAX_WORDS", 350)

# Background worker
WORKER = os.environ.get("MS_NO_WORKER") != "1"
KEEP_ALIVE = os.environ.get("MS_KEEP_ALIVE", "30m")   # keep the model loaded between stories

# Fake mode: canned story + sine-tone TTS, so tests need no models
FAKE = os.environ.get("MS_FAKE") == "1"