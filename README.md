# Midnight Stranger

An offline horror radio. A local language model writes short spooky stories, a local text-to-speech voice narrates them over procedurally generated ambience, and a browser "dial" lets you tune between fictional late-night stations. No cloud, no API keys, no internet needed once set up.

Built for the **Hacktoberfest Open-Source AI Challenge, Week 4: Ghost in the Machine**.

> **Status: early development.** Features below are marked *Planned* or *Done*. This README is updated as the project changes (see the [Changelog](#changelog)).

## Why open-weight AI

- **Works with the lights (and the internet) off.** Everything runs on your own machine.
- **Private.** No prompt, story or log leaves the computer.
- **Free to run.** No API keys, no per-token cost.
- **Swappable.** Change the model or voice with a config setting, or change how a station behaves by editing its prompt.

## How it works

```
Browser dial UI -> FastAPI -> station queue -> Ollama (story JSON)
                                            -> Piper (narration)
                                            -> numpy (ambience + mix)
                                            -> cached audio + captions
```

A background worker keeps a few finished episodes ready per station, so tuning the dial never waits on the model.

## Stations (planned)

| Frequency | Station | Flavour |
|---|---|---|
| 88.1 | The Lighthouse | Isolated, coastal dread |
| 93.7 | Route 13 Overnight | Highway, drivers, things in the rearview |
| 101.3 | Frequency of the Dead | Gentle, fictional remembrance (Día de los Muertos spirit) |
| 107.9 | Static Hours | Strange signals and unexplained broadcasts |

All stories are fictional and kept PG-13.

## Requirements

- Linux (developed and tested on Linux first; Windows/WSL is a stretch goal)
- Python 3.10+
- [Ollama](https://ollama.com) running locally
- Roughly 6 GB of free disk space (model, voices, cache) and 8 GB+ of RAM

## Install

```bash
# 1. Model (Ollama must already be installed and running)
ollama pull gemma3:4b

# 2. Project
git clone <this-repo> midnight-stranger && cd midnight-stranger
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Voices
python -m piper.download_voices --download-dir voices en_US-lessac-medium en_GB-alan-medium en_US-amy-medium
```

## Usage

*Planned. Commands are not implemented yet.*

```bash
midnight-stranger serve            # start the radio at http://127.0.0.1:8137
midnight-stranger doctor           # check Ollama, model, voices, disk
midnight-stranger install-service  # run in the background (systemd user service)
```

## Project layout

```
app/        generator, TTS, ambience, mixer, queue worker, API
static/     the radio dial page (no external requests)
scripts/    pregenerate.py for demo episodes
tests/      fake-mode tests (no models needed)
```

## Roadmap

See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for the phased checklist.

| Feature | Status |
|---|---|
| Environment and dependencies | Done |
| Story generation, TTS, mixer | Planned |
| API, queue, cache | Planned |
| Radio dial UI | Planned |
| Background service (systemd user unit) | Planned |
| Windows autostart | Stretch |

## Licensing and credits

- **This project:** GPL-3.0-or-later, because it uses [Piper](https://github.com/OHF-Voice/piper1-gpl), which is GPL-3.0-or-later.
- **Language model:** Gemma 3 (4B) via Ollama. Gemma 3 is open-weight, released under Google's Gemma Terms of Use, which is not an OSI open-source license.
- **Voices:** `en_US-lessac-medium`, `en_GB-alan-medium`, `en_US-amy-medium`. Each voice has its own license on its model card. *To be checked and listed here before release.*
- Ambience is generated procedurally; no third-party audio samples are used.

## Notes

All code in this repository was started during the Hacktoberfest Week 4 challenge window (Oct 26 to Oct 31, 2026). Any commits made after the submission deadline will be listed here.

## Changelog

| Date | Change |
|---|---|
| 2026-10-28 | Project created. Dependencies installed (`gemma3:4b`, Piper, FastAPI). README and implementation plan added. |
| 2026-10-28 | Added `app/config.py`, `.gitignore` and `scripts/phase0_check.py` (environment smoke test). Install step now downloads voices straight into `voices/`. |