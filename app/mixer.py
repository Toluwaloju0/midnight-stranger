"""Assemble an episode: station intro + story paragraphs over an ambience bed.

Timeline: lead-in (static burst + bed) -> intro line -> paragraphs separated
by pauses -> tail (bed fades out). The bed is ducked under speech, the final
mix is peak-normalised, and each spoken segment gets start/end times so the
page can show captions in sync.
"""
from __future__ import annotations

import time
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from . import tts
from .ambience import make_bed, moving_average, static_burst
from .generator import Story
from .stations import Station

LEAD_IN_S = 1.3
AFTER_INTRO_S = 1.1
BETWEEN_S = 0.9
TAIL_S = 3.0
SPEECH_PEAK = 0.8
DUCK_DEPTH = 0.6          # bed drops to 40% under speech
TARGET_PEAK = 0.89        # about -1 dBFS


@dataclass
class RenderResult:
    samples: np.ndarray       # int16 mono
    sample_rate: int
    segments: list[dict]      # {kind, text, start, end} in seconds
    duration: float
    seconds: dict             # time spent: tts, ambience, mix


def render_episode(station: Station, story: Story, seed: int | None = None) -> RenderResult:
    # 1. Speech parts
    intro = f"{station.name}, {station.freq} FM. Tonight's story: {story.title}."
    parts = [("intro", intro)] + [("paragraph", p) for p in story.paragraphs]

    t0 = time.perf_counter()
    rendered: list[tuple[str, str, np.ndarray]] = []
    rate = None
    for kind, text in parts:
        audio, sr = tts.synthesize(text, station.voice, station.length_scale, station.noise_scale)
        if rate is None:
            rate = sr
        elif sr != rate:
            raise RuntimeError(f"Sample rate changed mid-episode ({rate} vs {sr})")
        rendered.append((kind, text, audio))
    tts_seconds = time.perf_counter() - t0
    assert rate is not None

    # 2. Place speech on a timeline
    cursor = LEAD_IN_S
    placements: list[tuple[int, np.ndarray]] = []
    segments: list[dict] = []
    for i, (kind, text, audio) in enumerate(rendered):
        start = cursor
        end = start + len(audio) / rate
        placements.append((int(start * rate), audio))
        segments.append({"kind": kind, "text": text, "start": round(start, 2), "end": round(end, 2)})
        cursor = end + (AFTER_INTRO_S if i == 0 else BETWEEN_S)
    last_end = segments[-1]["end"]
    total_s = last_end + TAIL_S
    n = int(total_s * rate)

    speech = np.zeros(n, dtype=np.float32)
    for start, audio in placements:
        speech[start:start + len(audio)] += audio[: max(0, n - start)]
    peak = np.abs(speech).max()
    if peak > 0:
        speech *= SPEECH_PEAK / peak

    # 3. Ambience bed, ducked under speech
    t1 = time.perf_counter()
    bed = make_bed(station.ambience, total_s, rate, seed=seed)[:n]
    if len(bed) < n:
        bed = np.pad(bed, (0, n - len(bed)))
    envelope = moving_average(np.abs(speech), int(0.12 * rate))
    gain = 1.0 - DUCK_DEPTH * np.clip(envelope / 0.06, 0.0, 1.0)
    gain = moving_average(gain, int(0.35 * rate))
    bed = bed * station.bed_level * gain
    ambience_seconds = time.perf_counter() - t1

    # 4. Mix, add the tune-in burst, normalise
    t2 = time.perf_counter()
    mix = speech + bed
    burst = static_burst(rate, seed=seed)[:n] * 0.35
    mix[: len(burst)] += burst
    peak = np.abs(mix).max()
    if peak > 0:
        mix *= TARGET_PEAK / peak
    samples = np.clip(mix * 32767.0, -32768, 32767).astype(np.int16)
    mix_seconds = time.perf_counter() - t2

    return RenderResult(
        samples=samples,
        sample_rate=rate,
        segments=segments,
        duration=round(n / rate, 2),
        seconds={"tts": round(tts_seconds, 2), "ambience": round(ambience_seconds, 2),
                 "mix": round(mix_seconds, 2)},
    )


def write_wav(path: Path, samples: np.ndarray, sample_rate: int) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(samples.astype("<i2").tobytes())