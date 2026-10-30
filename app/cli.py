"""Command line entry point: python -m app <command>."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from . import config
from .generator import GenerationError
from .stations import STATIONS, by_freq


def _print_summary(meta: dict, out_dir: Path | None) -> None:
    sec = meta["seconds"]
    folder = out_dir or Path(config.CACHE_DIR) / "episodes"
    print(f"\n  {meta['station']['freq']} {meta['station']['name']}: \"{meta['title']}\"")
    print(f"  {meta['words']} words, {meta['duration']:.0f}s audio, "
          f"{meta['audio_bytes'] / 1e6:.1f} MB, model={meta['model']}, attempts={meta['attempts']}")
    print(f"  time: story {sec['story']}s | speech {sec['tts']}s | ambience {sec['ambience']}s | "
          f"mix {sec['mix']}s | total {sec['total']}s")
    print(f"  file: {folder / meta['audio_file']}")
    print(f"  opening: {meta['paragraphs'][0][:140]}...")


def cmd_list(_: argparse.Namespace) -> int:
    for s in STATIONS:
        print(f"{s.freq:>6}  {s.name:<24} voice={s.voice:<22} ambience={s.ambience:<7} {s.tagline}")
    return 0


def cmd_make(args: argparse.Namespace) -> int:
    from .pipeline import make_episode

    if args.fake:
        config.FAKE = True
    out_dir = Path(args.out) if args.out else None
    try:
        stations = list(STATIONS) if args.all else [by_freq(args.station)]
    except KeyError as exc:
        print(exc.args[0], file=sys.stderr)
        return 2

    failures = 0
    for station in stations:
        print(f"Making an episode for {station.freq} {station.name}"
              f"{' (fake mode)' if config.FAKE else ''} ...", flush=True)
        try:
            meta = make_episode(station, out_dir=out_dir, model=args.model, seed=args.seed)
        except (GenerationError, FileNotFoundError, RuntimeError) as exc:
            failures += 1
            print(f"  FAILED: {exc}", file=sys.stderr)
            continue
        _print_summary(meta, out_dir)
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app", description="Midnight Stranger")
    parser.add_argument("-v", "--verbose", action="store_true", help="show generator logs")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list-stations", help="show the stations").set_defaults(func=cmd_list)

    make = sub.add_parser("make-episode", help="generate one finished episode")
    group = make.add_mutually_exclusive_group()
    group.add_argument("--station", default="88.1", help="dial position, e.g. 93.7 (default 88.1)")
    group.add_argument("--all", action="store_true", help="make one episode for every station")
    make.add_argument("--model", help=f"Ollama model (default {config.MODEL})")
    make.add_argument("--fake", action="store_true", help="canned story + tone speech, no models needed")
    make.add_argument("--out", help="output folder (default cache/episodes)")
    make.add_argument("--seed", type=int, help="seed for repeatable prompts and ambience")
    make.set_defaults(func=cmd_make)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="  [%(name)s] %(message)s")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())