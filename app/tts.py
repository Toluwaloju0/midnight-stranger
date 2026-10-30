"""Text-to-speech with Piper (or a tone generator in fake mode).

synthesize() returns (float32 mono samples in [-1, 1], sample_rate).
Voices are loaded once and reused.
"""
from __future__ import annotations

import threading
from pathlib import Path

import numpy as np

from . import config

SENTENCE_GAP_S = 0.22   # Piper returns one chunk per sentence; add a natural pause between them


class VoiceNotFound(FileNotFoundError):
    pass


class VoiceBank:
    def __init__(self) -> None:
        self._voices: dict[str, object] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _locate(stem: str) -> Path:
        for folder in (config.VOICES_DIR, config.ROOT):
            onnx = Path(folder) / f"{stem}.onnx"
            if onnx.exists() and onnx.with_name(onnx.name + ".json").exists():
                return onnx
        raise VoiceNotFound(
            f"Voice '{stem}' not found in {config.VOICES_DIR}. Fix: "
            f"python -m piper.download_voices --download-dir voices {stem}"
        )

    def get(self, stem: str):
        with self._lock:
            if stem not in self._voices:
                from piper import PiperVoice

                onnx = self._locate(stem)
                self._voices[stem] = PiperVoice.load(
                    onnx, config_path=onnx.with_name(onnx.name + ".json")
                )
            return self._voices[stem]

    def synthesize(self, text: str, stem: str, length_scale: float | None = None,
                   noise_scale: float | None = None) -> tuple[np.ndarray, int]:
        from piper import SynthesisConfig

        voice = self.get(stem)
        syn = SynthesisConfig(length_scale=length_scale, noise_scale=noise_scale)
        pieces: list[np.ndarray] = []
        rate = int(voice.config.sample_rate)
        for chunk in voice.synthesize(text, syn_config=syn):
            rate = int(chunk.sample_rate)
            if pieces:
                pieces.append(np.zeros(int(SENTENCE_GAP_S * rate), dtype=np.float32))
            pieces.append(np.asarray(chunk.audio_float_array, dtype=np.float32).reshape(-1))
        if not pieces:
            raise RuntimeError(f"Piper produced no audio for: {text[:60]!r}")
        return np.concatenate(pieces), rate


_bank = VoiceBank()


def _fake(text: str, stem: str, length_scale: float | None) -> tuple[np.ndarray, int]:
    """Pulsing tone whose length follows the word count. Stands in for speech in tests."""
    rate = 22050
    words = max(1, len(text.split()))
    seconds = words / 2.6 * (length_scale or 1.0)
    n = int(seconds * rate)
    t = np.arange(n) / rate
    base = 110.0 + (sum(map(ord, stem)) % 90)
    tone = np.sin(2 * np.pi * base * t) + 0.4 * np.sin(2 * np.pi * base * 2 * t)
    pulse = (0.5 * (1 + np.sin(2 * np.pi * 4.2 * t))) ** 1.5
    audio = (0.5 * pulse * tone).astype(np.float32)
    edge = min(n // 2, int(0.01 * rate))
    if edge:
        ramp = np.linspace(0, 1, edge, dtype=np.float32)
        audio[:edge] *= ramp
        audio[-edge:] *= ramp[::-1]
    return audio, rate


def synthesize(text: str, stem: str, length_scale: float | None = None,
               noise_scale: float | None = None) -> tuple[np.ndarray, int]:
    if config.FAKE:
        return _fake(text, stem, length_scale)
    return _bank.synthesize(text, stem, length_scale, noise_scale)