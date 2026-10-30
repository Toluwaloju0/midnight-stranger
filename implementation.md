# Midnight Stranger: Implementation Plan

An offline horror radio: local LLM writes the stories, local TTS reads them, numpy builds the ambience, a browser "dial" tunes between stations.

**Challenge:** Hacktoberfest Open-Source AI Challenge, Week 4 "Ghost in the Machine"
**Deadline:** Sunday Nov 1, 07:59 AM Lagos (Oct 31, 11:59 PM PDT). Target: publish Saturday evening.
**Environment:** Linux over SSH (VS Code). Windows/WSL support is a stretch layer.

Tick a box when its gate is met (`- [x]`). Every phase ends with a **Gate**: do not start the next phase until it passes.

---

## Stack (as installed)

| Part | Choice |
|---|---|
| Story model | `gemma3:4b` via Ollama (fallback: `gemma3:1b` if too slow) |
| TTS | `piper-tts` (voices: `en_US-lessac-medium`, `en_GB-alan-medium`, `en_US-amy-medium`) |
| API | FastAPI + uvicorn |
| Audio DSP | numpy (procedural ambience, mixing), stdlib `wave` |
| Frontend | Single page, vanilla JS/CSS, no CDN, no external fonts |
| License | GPL-3.0-or-later (Piper is GPL) |

## Target layout

```
midnight-stranger/
  app/
    __init__.py  __main__.py  config.py  stations.py
    generator.py  tts.py  ambience.py  mixer.py
    pipeline.py  store.py  worker.py  main.py  cli.py
  static/  index.html  app.js  style.css
  scripts/  phase0_check.py  pregenerate.py
  tests/  test_phase1.py
  voices/   (gitignored)    cache/ (gitignored)
  README.md  IMPLEMENTATION_PLAN.md  LICENSE  requirements.txt  .gitignore
```

---

## Phase 0: Environment check (tonight, ~30 min)

- [x] Ollama installed, `gemma3:4b` pulled
- [x] Repo initialised, venv created, dependencies installed, `requirements.txt` frozen
- [x] Three Piper voices downloaded
- [x] `ollama list` shows `gemma3:4b` (confirmed, 3.4 GB)
- [x] One prompt returns text (`python scripts/phase0_check.py`)
- [x] Voice files found in the project root (alan, amy, lessac)
- [x] Move voices into `voices/`
- [x] Synthesize a sample per voice to .wav and listen to it (confirmed)
- [x] Add `.gitignore`
- [x] Add `app/__init__.py` and `app/config.py`
- [ ] Add `LICENSE` (GPL-3.0-or-later): `curl -fsSL https://www.gnu.org/licenses/gpl-3.0.txt -o LICENSE`, then make the first commit
- [x] Record baseline numbers for the write-up (see Baseline measurements below)

**Gate:** one hard-coded paragraph goes text, then Piper, then a playable .wav.

## Baseline measurements (Oct 29, Linux box over SSH)

| Item | Value |
|---|---|
| Python | 3.12.0 |
| CPU cores | 2 |
| RAM total / available | 11.7 GiB / 8.2 GiB |
| Disk free | 40.7 GB |
| `gemma3:4b` generation | 9.2 tokens/sec |
| `gemma3:4b` model load | 21.4 s (first call) |
| Piper `en_GB-alan-medium` | 19.2 s audio in 1.5 s (12.5x realtime) |
| Piper `en_US-amy-medium` | 18.8 s audio in 1.4 s (13.2x realtime) |
| Piper `en_US-lessac-medium` | 16.1 s audio in 1.3 s (12.9x realtime) |
| Estimated episode time | about 1.5 min (story about 55 s, speech about 12 s, mix about 2 s) |

These are measured on a short 67-token reply; confirm against a real story in the Phase 1 checks.

## Phase 1: Core pipeline (started Wed night, ~4 h)

> Status: all Phase 1 code is written and passes 16 fake-mode tests. It has not yet run against real Ollama and Piper. Code boxes below stay unticked until you have run them on your machine; see **Your checks** at the end of this phase.

- [x] `config.py`: paths (voices, cache), model name, port 8137, queue target, all overridable by env vars
- [ ] `stations.py`: four stations (frequency, name, persona prompt, voice, ambience profile)
  - [ ] 88.1 The Lighthouse
  - [ ] 93.7 Route 13 Overnight
  - [ ] 101.3 Frequency of the Dead (gentle, fictional remembrance)
  - [ ] 107.9 Static Hours
- [ ] `generator.py`
  - [ ] Ollama call with JSON schema (`title`, `paragraphs[]`)
  - [ ] Validate: ask for 4 to 6 paragraphs and about 300 words; accept 3 to 8 paragraphs and 200 to 455 words (80% of min to 130% of max, because retries cost minutes on CPU)
  - [ ] Retry up to 3 times, then fall back to `gemma3:1b`
  - [ ] Content guard: fictional, PG-13, reject and regenerate on banned terms
- [ ] `tts.py`: load each voice once, synthesize per paragraph, return samples and duration
- [ ] `ambience.py`: loopable numpy beds (rumble, drone, crackle, hiss), one profile per station
- [ ] `mixer.py`: static burst intro, paragraphs with pauses, ambience ducked under speech, normalize, write .wav, record per-paragraph start/end times
- [ ] `pipeline.py` and `cli.py`: `python -m app make-episode --station 88.1` writes audio plus metadata JSON
- [ ] Fake mode (`MS_FAKE=1`): canned story and sine-tone TTS so tests need no models

**Your checks (on your machine):**

- [ ] `python -m unittest discover -v` passes
- [ ] `python -m app make-episode --fake --station 88.1` plays (tone "speech" over ambience)
- [ ] Real episode: `python -m app make-episode --station 88.1 -v`; note the story generation time
- [ ] Listen to all four ambience beds; adjust `bed_level` in `stations.py` and `DUCK_DEPTH` in `mixer.py` if needed
- [ ] All four stations produce a real episode; at least 3 of 5 stories read acceptably

**Gate:** `make-episode` produces a finished episode for all four stations; at least 3 of 5 stories read acceptably.

## Phase 2: Service, queue and cache (Thursday, ~2 h)

- [ ] `store.py`: episode folder layout, metadata JSON (id, station, title, text, timings, created, played)
- [ ] `worker.py`: background thread keeps N unplayed episodes per station; one generation at a time; `os.nice` low priority
- [ ] `main.py` (FastAPI):
  - [ ] `GET /api/health`
  - [ ] `GET /api/stations`
  - [ ] `GET /api/stations/{freq}/next` returns metadata and audio URL
  - [ ] `GET /audio/{id}.wav`
  - [ ] `POST /api/pause` and `POST /api/resume` for the worker
  - [ ] Bind to `127.0.0.1` by default; `--lan` opt-in with a printed warning
- [ ] Cache cap (default 300 MB), delete oldest played episodes first
- [ ] Graceful failure: if Ollama is down, serve cached episodes and return a clear status

**Gate:** `curl` the API: `next` returns an episode, the audio plays, and the queue refills in the background.

## Phase 3: Frontend (Thursday night to Friday, ~3 h)

- [ ] Dial UI that snaps between the four stations
- [ ] WebAudio static burst on tune, no audio files needed
- [ ] Audio player with auto-advance to the next episode
- [ ] Captions advance by paragraph timings
- [ ] Status line (generating, queue depth, offline-ok)
- [ ] Works at phone width; no external requests (verify in browser dev tools, Network tab)

**Gate:** open the page, tune stations, hear a full episode with captions.

## Phase 4: Demo content and measurements (Friday, ~2 h)

- [ ] `scripts/pregenerate.py`: build 3 to 4 episodes per station
- [ ] Curate: read every demo story, regenerate weak ones, keep a bad example and its fix for the post
- [ ] Airplane-mode test: disable the network, restart, everything still works (screenshot)
- [ ] Measure for the post: seconds per episode, peak RAM, disk used, cost ($0)
- [ ] Record a short demo video or GIF

**Gate:** a stranger could watch the demo and understand it in 60 seconds.

## Phase 5: Packaging and background service (Friday, ~3 h)

- [ ] `pyproject.toml` with a `midnight-stranger` entry point
- [ ] `cli.py` commands: `serve`, `status`, `doctor`, `open`
- [ ] `doctor`: checks Ollama reachable, model present, voices present, disk space, prints plain-language fixes
- [ ] Logs to a rotating file (not just stdout); single-instance lock
- [ ] `install-service`: write `~/.config/systemd/user/midnight-stranger.service`, enable and start it
- [ ] `uninstall-service`
- [ ] Document `loginctl enable-linger $USER` (otherwise the user service stops at logout)
- [ ] Test on this machine: install the service, log out and in (and reboot if possible), confirm the radio is up
- [ ] Stretch, label as untested unless tested: Windows autostart via `HKCU\...\Run`

**Gate:** service survives a restart, `doctor` passes on a clean venv.

## Phase 6: Tests (alongside, ~1 h)

- [x] Generator validation tests (bad JSON, wrong length, banned terms, retries, fallback) in `tests/test_phase1.py`
- [x] Mixer test: duration matches segments, normalised, no clipping
- [ ] API tests in fake mode
- [ ] Stretch: GitHub Actions on ubuntu-latest running the fake-mode suite

## Phase 7: Submission (Friday night to Saturday)

- [ ] **Feature freeze Friday night.** Later commits go in the README note.
- [ ] README final: install, usage, screenshots, honest limits
- [ ] Verify the repo is public and `LICENSE` is present
- [ ] Draft the DEV post using the Week 4 template (tags: `devchallenge`, `hf26challenge`):
  - [ ] What I Built
  - [ ] Demo (video and/or link)
  - [ ] Code (embed repo)
  - [ ] How I Built It
  - [ ] Why Does Open Innovation Matter? (use the measured numbers: offline, $0, RAM, privacy)
  - [ ] The Spirit of It (the moment a story landed)
  - [ ] Prize Categories: list only categories genuinely used (Gemma; others only if real)
- [ ] Post is written in your own voice, includes one weak output and how you fixed it
- [ ] Publish by Saturday evening (hard deadline Sunday 07:59 AM Lagos)

---

## Cut line (drop in this order if time runs short)

1. Windows autostart, CI, tray icon
2. Compressed audio (OGG), battery-aware throttling
3. `--lan` mode, caption timing polish
4. Fourth station

**Never cut:** the core loop (generate, narrate, mix, dial), pre-generated demo episodes, airplane-mode proof, and the write-up.

## Risks

| Risk | Mitigation |
|---|---|
| CPU generation too slow (only 2 cores here) | Queue plus pre-generated demo; fallback to `gemma3:1b`; measure tokens/sec in Phase 0 before committing to 4B |
| Model returns bad JSON | Schema output, validation, retries |
| Piper API differences | Smoke test in Phase 0; pin versions in `requirements.txt` |
| Mediocre stories | Spend time on persona prompts; curate demo episodes |
| Disk fills with audio | Cache cap and cleanup |
| Dark or gory output | PG-13 system prompt plus content guard |
| Licensing | Repo GPL-3.0-or-later; credit Gemma terms and each voice's license in README |
| Ambience beds not auditioned by the author of the code | Tune `bed_level` per station and `DUCK_DEPTH` after listening |

## Decision log

| Date | Decision |
|---|---|
| Oct 28 | Idea: Midnight Stranger (offline horror radio) |
| Oct 28 | Develop on Linux over SSH; Windows/WSL deferred to stretch |
| Oct 28 | Model: `gemma3:4b` (installed); fallback `gemma3:1b` |
| Oct 28 | License: GPL-3.0-or-later because of Piper |
| Oct 29 | Voices: Lighthouse = alan, Route 13 = lessac, Dead = amy, Static Hours = lessac (slower, flatter) |
| Oct 29 | Episodes open with a spoken station intro and title; each segment gets caption timings |
| Oct 29 | Story length tolerance (200 to 455 words) instead of a strict 250 to 350 |
| Oct 29 | Keep `gemma3:4b` as the main model: 9.2 tokens/sec measured, about 1.5 min per episode |

## Progress log

| Date | Done |
|---|---|
| Oct 28 | Environment installed; plan and README created |
| Oct 28 | Phase 0: model and voices confirmed; `config.py`, `.gitignore`, `scripts/phase0_check.py` written (not yet run against real Ollama/voices) |
| Oct 28 | Phase 0 complete (model and voices confirmed, samples listened to); LICENSE still to add |
| Oct 29 | Phase 1 code written (stations, generator, TTS, ambience, mixer, pipeline, CLI) plus 16 fake-mode tests; awaiting first real run |
| Oct 29 | Baseline recorded: `gemma3:4b` 9.2 tokens/sec, Piper about 13x realtime |