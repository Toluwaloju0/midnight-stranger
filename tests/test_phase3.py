"""Phase 3 tests: the radio page is served, and it stays offline.

The real-browser behaviour (dial, captions, playback) was checked with a
Playwright script; these tests guard the parts that are cheap to check anywhere.
"""
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
STATIC_FILES = ("index.html", "style.css", "app.js")


class StaticFilesExist(unittest.TestCase):
    def test_files_present(self):
        for name in STATIC_FILES:
            self.assertTrue((STATIC / name).is_file(), f"missing static/{name}")

    def test_no_external_urls(self):
        """The page must work with no internet: nothing may point at another host."""
        allowed = ("http://www.w3.org/2000/svg",)
        pattern = re.compile(r"https?://[^\s'\"<>)]+")
        for name in STATIC_FILES:
            text = (STATIC / name).read_text(encoding="utf-8")
            for url in pattern.findall(text):
                if url.startswith(allowed):
                    continue
                self.fail(f"static/{name} references an external URL: {url}")

    def test_station_frequencies_match_the_page(self):
        """The dial's range in app.js must cover every real station."""
        from app.stations import STATIONS

        js = (STATIC / "app.js").read_text(encoding="utf-8")
        low = float(re.search(r"MIN_F\s*=\s*([\d.]+)", js).group(1))
        high = float(re.search(r"MAX_F\s*=\s*([\d.]+)", js).group(1))
        for s in STATIONS:
            self.assertTrue(low < float(s.freq) < high, f"{s.freq} is outside the dial")


class ServedByTheApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from fastapi.testclient import TestClient
        except Exception as exc:  # httpx missing
            raise unittest.SkipTest(f"TestClient unavailable: {exc}")
        from app import config
        from app.main import create_app

        cls._tmp = tempfile.TemporaryDirectory()
        config.CACHE_DIR = Path(cls._tmp.name)
        config.FAKE = True
        cls.client = TestClient(create_app(start_worker=False))

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_root_serves_the_radio(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Midnight Stranger", r.text)
        self.assertIn('id="player"', r.text)

    def test_assets_are_served(self):
        for path, kind in (("/static/app.js", "javascript"), ("/static/style.css", "css")):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, path)
            self.assertIn(kind, r.headers["content-type"], path)


if __name__ == "__main__":
    unittest.main()