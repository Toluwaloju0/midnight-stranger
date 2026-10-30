"""Phase 1 tests. Run from the project root:  python -m unittest discover -v

Everything here runs in fake mode or with a stubbed Ollama call, so no model,
voice files or network are needed.
"""
from __future__ import annotations

import json
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

from app import ambience, config, generator, mixer
from app.generator import GenerationError, Story, clean_for_speech, parse_json, validate_story
from app.pipeline import make_episode
from app.stations import STATIONS, by_freq


def good_data(paragraphs: int = 4, words_each: int = 75) -> dict:
    para = " ".join(["quiet"] * (words_each - 1)) + " dark."
    return {"title": "The Quiet Hour", "paragraphs": [para] * paragraphs}


class ValidationTests(unittest.TestCase):
    def test_accepts_good_story(self):
        story, reason = validate_story(good_data())
        self.assertIsNotNone(story, reason)
        self.assertEqual(story.title, "The Quiet Hour")

    def test_rejects_non_object(self):
        self.assertIsNone(validate_story(["nope"])[0])

    def test_rejects_too_few_paragraphs(self):
        self.assertIsNone(validate_story(good_data(paragraphs=2, words_each=150))[0])

    def test_rejects_too_short_and_too_long(self):
        self.assertIsNone(validate_story(good_data(words_each=20))[0])
        self.assertIsNone(validate_story(good_data(paragraphs=6, words_each=120))[0])

    def test_content_guard(self):
        data = good_data()
        data["paragraphs"][1] = data["paragraphs"][1] + " It was a gory scene."
        story, reason = validate_story(data)
        self.assertIsNone(story)
        self.assertIn("gory", reason)

    def test_clean_for_speech(self):
        text = "**Hello** [whisper] world — again \U0001F47B"
        cleaned = clean_for_speech(text)
        self.assertNotIn("*", cleaned)
        self.assertNotIn("[", cleaned)
        self.assertNotIn("\U0001F47B", cleaned)
        self.assertTrue(cleaned.endswith("."))
        self.assertNotIn(" ,", cleaned)

    def test_parse_json_with_fences(self):
        self.assertEqual(parse_json('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(parse_json('Sure! {"a": 2} Enjoy.'), {"a": 2})


class RetryTests(unittest.TestCase):
    def setUp(self):
        self._fake, self._chat = config.FAKE, generator._chat
        config.FAKE = False

    def tearDown(self):
        config.FAKE, generator._chat = self._fake, self._chat

    def test_retries_then_succeeds(self):
        replies = iter(["not json at all", json.dumps(good_data())])
        generator._chat = lambda model, messages: next(replies)
        story = generator.generate_story(STATIONS[0], model="main")
        self.assertEqual(story.attempts, 2)
        self.assertEqual(story.model, "main")

    def test_falls_back_to_smaller_model(self):
        def chat(model, messages):
            return "garbage" if model == "main" else json.dumps(good_data())
        generator._chat = chat
        old = config.FALLBACK_MODEL
        config.FALLBACK_MODEL = "small"
        try:
            story = generator.generate_story(STATIONS[0], model="main")
        finally:
            config.FALLBACK_MODEL = old
        self.assertEqual(story.model, "small")
        self.assertEqual(story.attempts, generator.MAIN_ATTEMPTS + 1)

    def test_gives_up_with_clear_error(self):
        generator._chat = lambda model, messages: "garbage"
        with self.assertRaises(GenerationError):
            generator.generate_story(STATIONS[0], model="main")

    def test_connection_error_is_reported(self):
        def chat(model, messages):
            raise ConnectionError("down")
        generator._chat = chat
        with self.assertRaises(GenerationError) as ctx:
            generator.generate_story(STATIONS[0], model="main")
        self.assertIn("Ollama", str(ctx.exception))


class AudioTests(unittest.TestCase):
    def setUp(self):
        self._fake = config.FAKE
        config.FAKE = True

    def tearDown(self):
        config.FAKE = self._fake

    def test_all_ambience_profiles(self):
        for name in ambience.PROFILES:
            bed = ambience.make_bed(name, 4.0, 22050, seed=1)
            self.assertEqual(len(bed), 4 * 22050, name)
            self.assertTrue(np.isfinite(bed).all(), name)
            self.assertAlmostEqual(float(np.abs(bed).max()), 1.0, places=3, msg=name)

    def test_unknown_profile(self):
        with self.assertRaises(ValueError):
            ambience.make_bed("nope", 1.0, 22050)

    def test_render_every_station(self):
        for station in STATIONS:
            story = generator.fake_story(station)
            result = mixer.render_episode(station, story, seed=3)
            self.assertEqual(result.samples.dtype, np.int16)
            peak = int(np.abs(result.samples.astype(np.int32)).max())
            self.assertLessEqual(peak, 32767)
            self.assertGreater(peak, 20000, "mix should be normalised, not quiet")
            self.assertEqual(len(result.segments), 1 + len(story.paragraphs))
            starts = [s["start"] for s in result.segments]
            self.assertEqual(starts, sorted(starts))
            for a, b in zip(result.segments, result.segments[1:]):
                self.assertLess(a["end"], b["start"])
            self.assertAlmostEqual(
                result.duration, result.segments[-1]["end"] + mixer.TAIL_S, delta=0.05)

    def test_make_episode_writes_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            meta = make_episode(by_freq("101.3"), out_dir=Path(tmp), seed=5)
            wav = Path(tmp) / meta["audio_file"]
            self.assertTrue(wav.exists())
            with wave.open(str(wav), "rb") as wf:
                self.assertEqual(wf.getnchannels(), 1)
                self.assertEqual(wf.getsampwidth(), 2)
                self.assertAlmostEqual(wf.getnframes() / wf.getframerate(), meta["duration"], delta=0.05)
            saved = json.loads((Path(tmp) / f"{meta['id']}.json").read_text())
            self.assertEqual(saved["id"], meta["id"])
            self.assertTrue(saved["fake"])

    def test_by_freq(self):
        self.assertEqual(by_freq("88.1 FM").name, "The Lighthouse")
        with self.assertRaises(KeyError):
            by_freq("12.3")


if __name__ == "__main__":
    unittest.main()