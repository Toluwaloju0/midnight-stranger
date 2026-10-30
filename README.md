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

Available now (Phases 1 and 2):

```bash
python -m app list-stations
python -m app make-episode --station 88.1          # one real episode (needs Ollama and voices)
python -m app make-episode --fake --station 88.1   # canned story and tone speech, no models
python -m app make-episode --all -v                # one episode per station, with logs
python -m app serve                                # the radio service on http://127.0.0.1:8137
python -m app serve --fake                         # same, with canned stories (no models)
python -m app serve --no-worker                    # serve cached episodes only, generate nothing
python -m unittest discover -v                     # tests (no models needed; API tests need httpx)
```

Episodes are written to `cache/episodes/` as a `.wav` plus a `.json` file with the text and caption timings.

*Planned (not implemented yet):*

```bash
midnight-stranger doctor           # check Ollama, model, voices, disk
midnight-stranger install-service  # run in the background (systemd user service)
```

## API

`python -m app serve` starts a local-only service (use `--lan` to share on your network; there is no password). A background worker keeps two unplayed episodes ready per station, one generation at a time at low priority, and refills the station you are listening to first. Interactive docs are at `/docs`.

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | Is Ollama reachable, is the model installed, are voices present |
| `GET /api/stations` | The four stations with queue depth |
| `GET /api/stations/{freq}/next` | Next episode (title, caption timings, audio URL). Replays an old one if nothing new is ready; 503 with a hint if the station has no episodes yet |
| `GET /audio/{id}.wav` | The audio (supports range requests for seeking) |
| `GET /api/status` | Worker state, last error, cache size |
| `POST /api/pause`, `POST /api/resume` | Stop or restart new generation (a running one finishes) |

If Ollama stops, the service keeps playing cached episodes, reports the error in `/api/status`, and retries with a growing delay. The cache is capped at 300 MB (`MS_CACHE_CAP_MB`); only the oldest played episodes are deleted.

## Project layout

```
app/        stations, generator, TTS, ambience, mixer, pipeline, store, worker, API, CLI
static/     the radio dial page (no external requests)
scripts/    pregenerate.py for demo episodes
tests/      fake-mode tests (no models needed)
```

## Roadmap

See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for the phased checklist.

| Feature | Status |
|---|---|
| Environment and dependencies | Done |
| Story generation, TTS, mixer, CLI | Code written and fake-mode tested; real-hardware run pending |
| API, queue, cache | Code written and tested in fake mode; real-hardware run pending |
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
| 2026-10-29 | Phase 1 code: stations, story generator (JSON schema, validation, retries, fallback model, content guard), Piper TTS wrapper, numpy ambience, mixer with ducking and caption timings, `make-episode` CLI, 16 tests. |
| 2026-10-30 | Phase 2 code: episode store with cache cap, background queue worker, FastAPI service (`serve` command), 22 more tests. |