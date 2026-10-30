"""Procedural ambience beds, generated with numpy only (no audio samples, no licensing).

make_bed(profile, seconds, sample_rate) -> float32 mono array, peak-normalised to 1.0.
The mixer decides how loud the bed sits under the voice.
"""
from __future__ import annotations

import numpy as np

TWO_PI = 2.0 * np.pi


# --------------------------------------------------------------------------
# Building blocks
# --------------------------------------------------------------------------

def _fast_len(n: int) -> int:
    """Next power of two >= n, so FFTs stay fast on long arrays."""
    return 1 << max(1, (n - 1).bit_length())


def colored_noise(n: int, alpha: float, rng: np.random.Generator) -> np.ndarray:
    """Noise with a 1/f^alpha spectrum: 0 = white, 1 = pink, 2 = brown. Unit variance."""
    m = _fast_len(n)
    spectrum = np.fft.rfft(rng.standard_normal(m))
    freqs = np.fft.rfftfreq(m)
    freqs[0] = freqs[1]
    out = np.fft.irfft(spectrum / freqs ** (alpha / 2.0), m)[:n]
    out -= out.mean()
    std = out.std()
    return (out / std if std > 0 else out).astype(np.float32)


def moving_average(x: np.ndarray, width: int) -> np.ndarray:
    """Centred moving average in O(n), same length as the input."""
    width = max(1, int(width))
    if width == 1 or len(x) == 0:
        return x.astype(np.float32)
    width = min(width, len(x))
    csum = np.cumsum(np.insert(x.astype(np.float64), 0, 0.0))
    out = (csum[width:] - csum[:-width]) / width
    left = width // 2
    right = len(x) - len(out) - left
    return np.pad(out, (left, right), mode="edge").astype(np.float32)


def _time(n: int, sr: int) -> np.ndarray:
    return np.arange(n, dtype=np.float64) / sr


def _lfo(t: np.ndarray, hz: float, phase: float) -> np.ndarray:
    """Slow oscillator in 0..1."""
    return (0.5 * (1.0 + np.sin(TWO_PI * hz * t + phase))).astype(np.float32)


def _tone(t: np.ndarray, hz: float, vibrato_hz: float = 0.2, depth: float = 0.4) -> np.ndarray:
    return np.sin(TWO_PI * hz * t + depth * np.sin(TWO_PI * vibrato_hz * t)).astype(np.float32)


def crackle(n: int, sr: int, rate_hz: float, rng: np.random.Generator,
            amp: float = 1.0, decay_ms: float = 6.0) -> np.ndarray:
    """Sparse random clicks with a short exponential decay."""
    count = int(rng.poisson(rate_hz * n / sr))
    out = np.zeros(n + int(sr * 0.05), dtype=np.float32)
    k = max(2, int(sr * decay_ms / 1000.0))
    kernel = np.exp(-np.arange(k) / (k / 4.0)).astype(np.float32)
    positions = rng.integers(0, n, size=count)
    amps = rng.uniform(0.2, 1.0, size=count) * rng.choice([-1.0, 1.0], size=count) * amp
    for pos, a in zip(positions, amps):
        out[pos:pos + k] += a * kernel
    return out[:n]


def static_burst(sr: int, seconds: float = 0.9, seed: int | None = None) -> np.ndarray:
    """A quick burst of radio static, used as the tune-in sound at the start of an episode."""
    rng = np.random.default_rng(seed)
    n = int(seconds * sr)
    t = np.arange(n) / sr
    noise = colored_noise(n, 0.2, rng)
    envelope = np.exp(-t * 3.0) * np.minimum(1.0, t * 80.0)
    burst = noise * envelope + crackle(n, sr, 60, rng, amp=0.8, decay_ms=2.0) * envelope
    peak = np.abs(burst).max()
    return (burst / peak).astype(np.float32) if peak > 0 else burst


# --------------------------------------------------------------------------
# Profiles (one per station)
# --------------------------------------------------------------------------

def _sea(n: int, sr: int, rng: np.random.Generator) -> np.ndarray:
    t = _time(n, sr)
    swell = _lfo(t, 0.09, rng.uniform(0, TWO_PI)) ** 2
    surf = colored_noise(n, 1.0, rng) * (0.15 + 0.85 * swell)
    rumble = colored_noise(n, 2.0, rng)
    drone = np.sin(TWO_PI * 55.0 * t).astype(np.float32)
    return 0.7 * rumble + 0.5 * surf + 0.2 * drone


def _road(n: int, sr: int, rng: np.random.Generator) -> np.ndarray:
    t = _time(n, sr)
    rumble = colored_noise(n, 2.0, rng)
    engine = 0.5 * _tone(t, 48) + 0.25 * _tone(t, 96) + 0.12 * _tone(t, 144)
    engine = engine * (0.8 + 0.2 * _lfo(t, 0.13, rng.uniform(0, TWO_PI)))
    thumps = np.zeros(n, dtype=np.float32)
    length = int(0.14 * sr)
    tt = np.arange(length) / sr
    thump = (np.sin(TWO_PI * 55.0 * tt) * np.exp(-tt * 28.0)).astype(np.float32)
    pos = int(sr * rng.uniform(0.5, 1.5))
    while pos + length < n:
        thumps[pos:pos + length] += 0.8 * thump
        pos += int(sr * rng.uniform(1.9, 2.7))
    return 0.6 * rumble + 0.7 * engine + thumps


def _candle(n: int, sr: int, rng: np.random.Generator) -> np.ndarray:
    t = _time(n, sr)
    pad = (_tone(t, 110.0) * 0.5 + _tone(t, 164.81) * 0.3
           + _tone(t, 220.0) * 0.25 + _tone(t, 277.18) * 0.1)
    pad = pad * (0.7 + 0.3 * _lfo(t, 0.07, rng.uniform(0, TWO_PI)))
    soft = colored_noise(n, 1.0, rng) * 0.05
    flame = crackle(n, sr, 6, rng, amp=0.35, decay_ms=9.0)
    return 0.9 * pad + soft + flame


def _static(n: int, sr: int, rng: np.random.Generator) -> np.ndarray:
    t = _time(n, sr)
    hiss = colored_noise(n, 0.3, rng) * 0.55
    clicks = crackle(n, sr, 28, rng, amp=0.6, decay_ms=3.0)
    whine = (np.sin(TWO_PI * 3100.0 * t + 4.0 * np.sin(TWO_PI * 0.31 * t)) * 0.06
             * _lfo(t, 0.05, rng.uniform(0, TWO_PI))).astype(np.float32)
    gate = np.ones(n, dtype=np.float32)
    pos = int(sr * rng.uniform(4, 9))
    while pos < n:
        length = int(sr * rng.uniform(0.3, 1.2))
        gate[pos:pos + length] = 0.15
        pos += length + int(sr * rng.uniform(7, 15))
    gate = moving_average(gate, int(0.03 * sr))
    return (hiss + clicks + whine) * gate


PROFILES = {"sea": _sea, "road": _road, "candle": _candle, "static": _static}


def make_bed(profile: str, seconds: float, sr: int, seed: int | None = None) -> np.ndarray:
    if profile not in PROFILES:
        raise ValueError(f"Unknown ambience profile '{profile}'. Choose: {', '.join(PROFILES)}")
    n = max(1, int(seconds * sr))
    rng = np.random.default_rng(seed)
    bed = PROFILES[profile](n, sr, rng).astype(np.float32)
    fade_in, fade_out = min(n // 2, int(1.5 * sr)), min(n // 2, int(2.5 * sr))
    if fade_in:
        bed[:fade_in] *= np.linspace(0.0, 1.0, fade_in, dtype=np.float32)
    if fade_out:
        bed[-fade_out:] *= np.linspace(1.0, 0.0, fade_out, dtype=np.float32)
    peak = np.abs(bed).max()
    return (bed / peak).astype(np.float32) if peak > 0 else bed