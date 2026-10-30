"""The web service: JSON API, audio files and (from Phase 3) the radio page.

Start it with:  python -m app serve
Interactive API docs (FastAPI built-in) are at /docs while it runs.
"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from . import config, store
from .stations import STATIONS, by_freq
from .worker import Worker

STATIC_DIR = config.ROOT / "static"
HEALTH_CACHE_S = 5.0

_ollama_cache: tuple[float, dict] = (0.0, {})


def _ollama_status() -> dict:
    """Is Ollama reachable and is the model installed? Cached briefly; never raises."""
    global _ollama_cache
    now = time.time()
    if now - _ollama_cache[0] < HEALTH_CACHE_S and _ollama_cache[1]:
        return _ollama_cache[1]
    if config.FAKE:
        result = {"reachable": True, "model_present": True, "note": "fake mode"}
    else:
        try:
            import ollama

            listing = ollama.Client(timeout=2).list()
            names = [getattr(m, "model", None) or m.get("model") for m in listing.models]
            result = {"reachable": True, "model_present": config.MODEL in names}
        except Exception as exc:
            result = {"reachable": False, "model_present": False, "error": str(exc)[:160]}
    _ollama_cache = (now, result)
    return result


def _missing_voices() -> list[str]:
    if config.FAKE:
        return []
    from .tts import VoiceBank, VoiceNotFound

    missing = []
    for stem in sorted({s.voice for s in STATIONS}):
        try:
            VoiceBank._locate(stem)
        except VoiceNotFound:
            missing.append(stem)
    return missing


def _public(meta: dict, replay: bool) -> dict:
    """The fields the radio page needs (no file paths)."""
    freq = meta["station"]["freq"]
    return {
        "id": meta["id"],
        "station": meta["station"],
        "title": meta["title"],
        "duration": meta["duration"],
        "segments": meta["segments"],
        "words": meta.get("words"),
        "created": meta.get("created"),
        "audio_url": f"/audio/{meta['id']}.wav",
        "replay": replay,
        "queue_left": store.queue_counts().get(freq, 0),
    }


def create_app(start_worker: bool | None = None) -> FastAPI:
    run_worker = config.WORKER if start_worker is None else start_worker
    worker = Worker()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if run_worker:
            worker.start()
        yield
        worker.shutdown()

    app = FastAPI(title="Midnight Stranger", version="0.2.0", lifespan=lifespan)
    app.state.worker = worker

    @app.get("/api/health")
    def health() -> dict:
        ollama_state = _ollama_status()
        voices = _missing_voices()
        return {
            "ok": config.FAKE or (ollama_state.get("reachable", False)
                                  and ollama_state.get("model_present", False) and not voices),
            "fake": config.FAKE,
            "model": config.MODEL,
            "ollama": ollama_state,
            "missing_voices": voices,
        }

    @app.get("/api/stations")
    def stations() -> dict:
        queued, total = store.queue_counts(), store.total_counts()
        return {"stations": [
            {"freq": s.freq, "name": s.name, "tagline": s.tagline,
             "queued": queued.get(s.freq, 0), "total": total.get(s.freq, 0)}
            for s in STATIONS
        ], "target_per_station": worker.target}

    @app.get("/api/stations/{freq}/next")
    def next_episode(freq: str) -> dict:
        try:
            station = by_freq(freq)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=exc.args[0])
        picked = store.next_for(station.freq)
        worker.prioritize(station.freq)     # refill this station first
        if picked is None:
            status = worker.status()
            raise HTTPException(
                status_code=503,
                detail={"message": f"No episode is ready for {station.name} yet. Try again shortly.",
                        "last_error": status["last_error"], "generating": status["generating"]},
                headers={"Retry-After": "20"},
            )
        meta, replay = picked
        return _public(meta, replay)

    @app.get("/audio/{episode_id}.wav")
    def audio(episode_id: str) -> FileResponse:
        path = store.wav_path(episode_id)
        if path is None:
            raise HTTPException(status_code=404, detail="No such episode")
        return FileResponse(path, media_type="audio/wav")

    @app.get("/api/status")
    def status() -> dict:
        return {
            "worker": worker.status(),
            "cache": {"bytes": store.total_bytes(), "cap_mb": config.CACHE_CAP_MB,
                      "episodes": sum(store.total_counts().values()),
                      "queued": store.queue_counts(), "total": store.total_counts()},
        }

    @app.post("/api/pause")
    def pause() -> dict:
        worker.pause()
        return worker.status()

    @app.post("/api/resume")
    def resume() -> dict:
        worker.resume()
        return worker.status()

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        page = STATIC_DIR / "index.html"
        if page.is_file():
            return FileResponse(page)
        return HTMLResponse(
            "<h1>Midnight Stranger</h1><p>The service is running. The radio dial page arrives "
            "in Phase 3. Meanwhile see <a href='/api/stations'>/api/stations</a>, "
            "<a href='/api/status'>/api/status</a> and <a href='/docs'>/docs</a>.</p>")

    return app


app = create_app()