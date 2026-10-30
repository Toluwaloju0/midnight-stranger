"""Phase 2 tests: store, cache cap, worker and API. All in fake mode, no models needed.

Run from the project root:  python -m unittest discover -v
The API tests need httpx (pip install httpx); they are skipped if it is missing.
"""
from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path

from app import config, store
from app.generator import GenerationError
from app.pipeline import make_episode
from app.stations import STATIONS, by_freq
from app.worker import Worker

try:
    from fastapi.testclient import TestClient
except Exception:  # httpx missing
    TestClient = None


class TempCache(unittest.TestCase):
    """Point the cache at a throwaway folder and force fake mode."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._old = (config.CACHE_DIR, config.FAKE)
        config.CACHE_DIR, config.FAKE = Path(self._tmp.name), True
        self.addCleanup(self._restore)

    def _restore(self):
        config.CACHE_DIR, config.FAKE = self._old
        self._tmp.cleanup()

    def make(self, freq: str = "88.1") -> dict:
        time.sleep(1.05)   # ids carry a seconds-resolution timestamp; keep creation order clear
        return make_episode(by_freq(freq), seed=1)


class StoreTests(TempCache):
    def test_empty(self):
        self.assertEqual(store.list_episodes(), [])
        self.assertIsNone(store.next_for("88.1"))
        self.assertEqual(store.queue_counts()["88.1"], 0)

    def test_oldest_unplayed_first_then_replay(self):
        a, b = self.make(), self.make()
        self.assertEqual(store.queue_counts()["88.1"], 2)

        first, replay = store.next_for("88.1")
        self.assertEqual((first["id"], replay), (a["id"], False))
        second, replay = store.next_for("88.1")
        self.assertEqual((second["id"], replay), (b["id"], False))
        self.assertEqual(store.queue_counts()["88.1"], 0)

        third, replay = store.next_for("88.1")          # everything played: least recently played returns
        self.assertEqual((third["id"], replay), (a["id"], True))
        fourth, replay = store.next_for("88.1")
        self.assertEqual((fourth["id"], replay), (b["id"], True))

    def test_stations_are_separate(self):
        self.make("88.1")
        self.assertIsNone(store.next_for("93.7"))

    def test_bad_ids_are_rejected(self):
        for bad in ("../x", "..%2fx", "", "20261029-000108-88_1-zzzz", "abc"):
            self.assertIsNone(store.get_episode(bad))
            self.assertIsNone(store.wav_path(bad))

    def test_half_written_episode_is_ignored(self):
        folder = store.episodes_dir()
        folder.mkdir(parents=True)
        (folder / "20261029-000108-88_1-aaaa.wav").write_bytes(b"RIFF")          # wav, no json
        (folder / "20261029-000109-88_1-bbbb.json").write_text("{not json")      # corrupt json
        self.assertEqual(store.list_episodes(), [])

    def test_cap_deletes_oldest_played_but_keeps_unplayed_and_one_replay(self):
        eps = [self.make() for _ in range(4)]
        for _ in range(3):
            store.next_for("88.1")                      # play the first three
        self.assertEqual(store.queue_counts()["88.1"], 1)
        deleted = store.enforce_cap(cap_mb=0.0)         # impossible cap: delete everything allowed
        self.assertEqual(deleted, [eps[0]["id"], eps[1]["id"]])   # two oldest played
        remaining = {m["id"] for m in store.list_episodes()}
        self.assertEqual(remaining, {eps[2]["id"], eps[3]["id"]})  # newest played + the unplayed one
        self.assertIsNotNone(store.next_for("88.1"))

    def test_cap_does_nothing_when_under(self):
        self.make()
        self.assertEqual(store.enforce_cap(cap_mb=500), [])

    def test_orphans_are_cleaned(self):
        folder = store.episodes_dir()
        folder.mkdir(parents=True)
        orphan = folder / "20261029-000108-88_1-aaaa.wav"
        orphan.write_bytes(b"RIFF")
        old = time.time() - store.ORPHAN_AGE_S - 60
        import os
        os.utime(orphan, (old, old))
        store.enforce_cap(cap_mb=500)
        self.assertFalse(orphan.exists())


def wait_for(predicate, timeout=30.0, step=0.1) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if predicate():
            return True
        time.sleep(step)
    return False


class WorkerTests(TempCache):
    def test_fills_every_station_to_target(self):
        worker = Worker(target=1, idle_s=0.05)
        worker.start()
        self.addCleanup(worker.shutdown)
        self.assertTrue(wait_for(lambda: all(n >= 1 for n in store.queue_counts().values())),
                        store.queue_counts())
        time.sleep(0.4)
        self.assertTrue(all(n == 1 for n in store.queue_counts().values()), "must not overfill")
        self.assertEqual(worker.status()["episodes_made"], len(STATIONS))

    def test_prioritize_refills_the_listened_station(self):
        worker = Worker(target=1, idle_s=0.05)
        worker.pause()
        worker.start()
        self.addCleanup(worker.shutdown)
        worker.prioritize("107.9")
        worker.resume()
        self.assertTrue(wait_for(lambda: store.queue_counts()["107.9"] == 1))
        first = store.list_episodes()[0]
        self.assertEqual(first["station"]["freq"], "107.9")

    def test_pause_stops_new_work(self):
        worker = Worker(target=1, idle_s=0.05)
        worker.pause()
        worker.start()
        self.addCleanup(worker.shutdown)
        time.sleep(0.5)
        self.assertEqual(sum(store.queue_counts().values()), 0)
        self.assertTrue(worker.status()["paused"])
        worker.resume()
        self.assertTrue(wait_for(lambda: sum(store.queue_counts().values()) >= 1))

    def test_failures_are_reported_then_recover(self):
        calls = {"n": 0}

        def flaky(station):
            calls["n"] += 1
            if calls["n"] <= 2:
                raise GenerationError("Cannot reach Ollama. Start it ('ollama serve') and retry.")
            return make_episode(station)

        worker = Worker(maker=flaky, target=1, backoff_base=0.05, backoff_max=0.2, idle_s=0.05)
        worker.start()
        self.addCleanup(worker.shutdown)
        self.assertTrue(wait_for(lambda: worker.status()["last_error"] is not None, timeout=5))
        self.assertIn("Ollama", worker.status()["last_error"])
        self.assertTrue(wait_for(lambda: sum(store.queue_counts().values()) >= 1, timeout=20))
        self.assertIsNone(worker.status()["last_error"])
        self.assertEqual(worker.status()["fail_streak"], 0)

    def test_unexpected_exception_does_not_kill_the_thread(self):
        def boom(station):
            raise ValueError("kaput")

        worker = Worker(maker=boom, target=1, backoff_base=0.05, backoff_max=0.1, idle_s=0.05)
        worker.start()
        self.addCleanup(worker.shutdown)
        self.assertTrue(wait_for(lambda: worker.status()["fail_streak"] >= 2, timeout=5))
        self.assertTrue(worker.is_alive())
        self.assertIn("ValueError", worker.status()["last_error"])


@unittest.skipIf(TestClient is None, "httpx not installed (pip install httpx)")
class ApiTests(TempCache):
    def setUp(self):
        super().setUp()
        from app.main import create_app

        self.client = TestClient(create_app(start_worker=False))

    def test_health_in_fake_mode(self):
        data = self.client.get("/api/health").json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["fake"])
        self.assertEqual(data["missing_voices"], [])

    def test_stations_listing(self):
        data = self.client.get("/api/stations").json()
        self.assertEqual([s["freq"] for s in data["stations"]], ["88.1", "93.7", "101.3", "107.9"])
        self.assertTrue(all(s["queued"] == 0 for s in data["stations"]))

    def test_unknown_station_is_404(self):
        self.assertEqual(self.client.get("/api/stations/12.3/next").status_code, 404)

    def test_empty_station_is_503_with_retry_hint(self):
        resp = self.client.get("/api/stations/88.1/next")
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.headers["retry-after"], "20")
        self.assertIn("message", resp.json()["detail"])

    def test_next_then_audio_then_replay(self):
        meta = self.make("93.7")
        resp = self.client.get("/api/stations/93.7/next")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["id"], meta["id"])
        self.assertFalse(body["replay"])
        self.assertEqual(body["queue_left"], 0)
        self.assertEqual(body["audio_url"], f"/audio/{meta['id']}.wav")
        self.assertGreater(len(body["segments"]), 2)
        self.assertNotIn("audio_file", body)          # no internal fields leaked

        audio = self.client.get(body["audio_url"])
        self.assertEqual(audio.status_code, 200)
        self.assertEqual(audio.headers["content-type"], "audio/wav")
        self.assertEqual(audio.content[:4], b"RIFF")

        again = self.client.get("/api/stations/93.7/next").json()
        self.assertTrue(again["replay"])

    def test_range_request_for_seeking(self):
        meta = self.make("88.1")
        resp = self.client.get(f"/audio/{meta['id']}.wav", headers={"Range": "bytes=0-99"})
        self.assertEqual(resp.status_code, 206)
        self.assertEqual(len(resp.content), 100)

    def test_audio_path_safety(self):
        for url in ("/audio/..%2f..%2fetc%2fpasswd.wav", "/audio/nope.wav",
                    "/audio/20261029-000108-88_1-ffff.wav"):
            self.assertEqual(self.client.get(url).status_code, 404, url)

    def test_pause_resume_status(self):
        self.assertTrue(self.client.post("/api/pause").json()["paused"])
        status = self.client.get("/api/status").json()
        self.assertTrue(status["worker"]["paused"])
        self.assertIn("bytes", status["cache"])
        self.assertFalse(self.client.post("/api/resume").json()["paused"])

    def test_root_serves_something(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Midnight Stranger", resp.text)


if __name__ == "__main__":
    unittest.main()