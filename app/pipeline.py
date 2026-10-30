"""One call that turns a station into a finished episode on disk."""
from __future__ import annotations

import random
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .generator import generate_story
from .mixer import render_episode, write_wav
from .stations import Station
from .store import episodes_dir, write_json_atomic


def make_episode(station: Station, *, out_dir: Path | None = None, model: str | None = None,
                 seed: int | None = None) -> dict:
    """Generate a story, narrate it, mix it, write <id>.wav and <id>.json. Returns the metadata."""
    out = Path(out_dir) if out_dir else episodes_dir()
    out.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()

    story = generate_story(station, model=model, rng=random.Random(seed))
    render = render_episode(station, story, seed=seed)

    episode_id = (f"{time.strftime('%Y%m%d-%H%M%S')}-{station.freq.replace('.', '_')}"
                  f"-{secrets.token_hex(2)}")
    wav_path = out / f"{episode_id}.wav"
    write_wav(wav_path, render.samples, render.sample_rate)

    meta = {
        "id": episode_id,
        "station": {"freq": station.freq, "name": station.name},
        "title": story.title,
        "paragraphs": story.paragraphs,
        "segments": render.segments,
        "duration": render.duration,
        "sample_rate": render.sample_rate,
        "audio_file": wav_path.name,
        "audio_bytes": wav_path.stat().st_size,
        "words": story.words,
        "model": story.model,
        "attempts": story.attempts,
        "fake": config.FAKE,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seconds": {
            "story": round(story.gen_seconds, 2),
            **render.seconds,
            "total": round(time.perf_counter() - started, 2),
        },
    }
    write_json_atomic(out / f"{episode_id}.json", meta)   # written last, atomically
    return meta