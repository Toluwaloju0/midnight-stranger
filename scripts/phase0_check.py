#!/usr/bin/env python3
"""Phase 0 smoke test: LLM -> TTS -> .wav, plus baseline numbers for the write-up.

Run from the project root with the venv active:

    python scripts/phase0_check.py              # full check
    python scripts/phase0_check.py --skip-llm   # TTS only (quick)
    python scripts/phase0_check.py --model gemma3:1b

Writes sample audio to cache/phase0/ and prints a BASELINE block to copy
into your notes.
"""
from __future__ import annotations

import argparse
import platform
import shutil
import sys
import time
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config

SAMPLE_TEXT = (
    "The lighthouse keeper counted the ships every night. On the last night of "
    "October, he counted one more than had ever sailed. It had no lights, no "
    "sound, and no wake. It simply waited at the edge of the beam, patient as a "
    "held breath, and when the lamp swept past, it was a little closer."
)
LLM_PROMPT = "Write exactly two sentences of an eerie ghost story set at a lighthouse."

results: dict[str, str] = {}


def machine_info() -> None:
    import os

    mem_total = mem_avail = None
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                mem_total = int(line.split()[1]) / 1024 / 1024
            elif line.startswith("MemAvailable:"):
                mem_avail = int(line.split()[1]) / 1024 / 1024
    except OSError:
        pass
    disk = shutil.disk_usage(ROOT)
    results["Python"] = platform.python_version()
    results["CPU cores"] = str(os.cpu_count())
    if mem_total is not None:
        results["RAM total/available"] = f"{mem_total:.1f} GiB / {mem_avail:.1f} GiB"
    results["Disk free"] = f"{disk.free / 1e9:.1f} GB"
    print("== Machine ==")
    for k in ("Python", "CPU cores", "RAM total/available", "Disk free"):
        if k in results:
            print(f"  {k}: {results[k]}")


def check_llm(model: str) -> bool:
    print(f"\n== LLM ({model}) ==")
    try:
        import ollama
    except ImportError:
        print("  FAIL: the 'ollama' package is not installed in this venv.")
        return False
    try:
        listing = ollama.list()
        names = [getattr(m, "model", None) or m.get("model") for m in listing.models]
    except Exception as exc:  # connection refused, etc.
        print(f"  FAIL: cannot reach Ollama ({exc}).")
        print("  Fix: start it with 'ollama serve' (or check the service), then retry.")
        return False
    if model not in names:
        print(f"  FAIL: model '{model}' not found. Installed: {', '.join(names) or 'none'}")
        print(f"  Fix: ollama pull {model}")
        return False
    print(f"  Ollama reachable, '{model}' is installed.")
    print("  Generating a short sample (the first call also loads the model)...")
    start = time.perf_counter()
    try:
        resp = ollama.chat(
            model=model,
            messages=[{"role": "user", "content": LLM_PROMPT}],
            options={"num_predict": 100},
        )
    except Exception as exc:
        print(f"  FAIL: chat call failed ({exc}).")
        return False
    wall = time.perf_counter() - start
    text = resp.message.content.strip()
    print(f"  Reply: {text}")
    eval_count = getattr(resp, "eval_count", None)
    eval_ns = getattr(resp, "eval_duration", None)
    load_ns = getattr(resp, "load_duration", None) or 0
    if eval_count and eval_ns:
        tps = eval_count / (eval_ns / 1e9)
        results["LLM tokens/sec"] = f"{tps:.1f}"
        results["LLM model load"] = f"{load_ns / 1e9:.1f} s"
        results["LLM sample wall time"] = f"{wall:.1f} s for {eval_count} tokens"
        print(f"  Speed: {tps:.1f} tokens/sec (model load {load_ns / 1e9:.1f} s)")
        words = config.MAX_WORDS
        est_min = (words * 1.35) / tps / 60
        results["Est. story generation"] = f"~{est_min:.1f} min per {words}-word story"
        print(f"  Estimate: ~{est_min:.1f} min to generate a {words}-word story")
    return bool(text)


def find_voices() -> list[Path]:
    found: dict[str, Path] = {}
    for folder in (config.VOICES_DIR, ROOT):
        if folder.is_dir():
            for onnx in sorted(folder.glob("*.onnx")):
                if onnx.with_name(onnx.name + ".json").exists() and onnx.stem not in found:
                    found[onnx.stem] = onnx
    return list(found.values())


def check_tts() -> bool:
    print("\n== TTS (Piper) ==")
    try:
        from piper import PiperVoice
    except ImportError:
        print("  FAIL: 'piper-tts' is not installed in this venv.")
        return False
    voices = find_voices()
    if not voices:
        print(f"  FAIL: no voices (.onnx + .onnx.json) in {config.VOICES_DIR} or {ROOT}")
        print("  Fix: python -m piper.download_voices --download-dir voices en_US-lessac-medium")
        return False
    out_dir = config.CACHE_DIR / "phase0"
    out_dir.mkdir(parents=True, exist_ok=True)
    ok = True
    for onnx in voices:
        name = onnx.stem
        try:
            t0 = time.perf_counter()
            voice = PiperVoice.load(onnx, config_path=onnx.with_name(onnx.name + ".json"))
            load_s = time.perf_counter() - t0
            out = out_dir / f"{name}.wav"
            t1 = time.perf_counter()
            with wave.open(str(out), "wb") as wf:
                voice.synthesize_wav(SAMPLE_TEXT, wf)
            synth_s = time.perf_counter() - t1
            with wave.open(str(out), "rb") as wf:
                dur = wf.getnframes() / wf.getframerate()
                rate = wf.getframerate()
            rtf = synth_s / dur if dur else float("inf")
            results[f"TTS {name}"] = f"{dur:.1f} s audio in {synth_s:.1f} s (x{1 / rtf:.1f} realtime)"
            print(f"  {name}: {dur:.1f} s audio at {rate} Hz, synthesized in {synth_s:.1f} s "
                  f"(x{1 / rtf:.1f} realtime, load {load_s:.1f} s) -> {out.relative_to(ROOT)}")
        except Exception as exc:
            ok = False
            print(f"  FAIL {name}: {exc}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--skip-llm", action="store_true", help="only test Piper")
    parser.add_argument("--model", default=config.MODEL, help="Ollama model to test")
    args = parser.parse_args()

    machine_info()
    llm_ok = True if args.skip_llm else check_llm(args.model)
    tts_ok = check_tts()

    print("\n== BASELINE (copy into your notes) ==")
    for key, value in results.items():
        print(f"  {key}: {value}")

    print("\n== RESULT ==")
    print(f"  LLM: {'skipped' if args.skip_llm else ('OK' if llm_ok else 'FAILED')}")
    print(f"  TTS: {'OK' if tts_ok else 'FAILED'}")
    if llm_ok and tts_ok:
        print("  Phase 0 gate: open the .wav files in cache/phase0/ (VS Code can play them) "
              "and confirm they sound right.")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())