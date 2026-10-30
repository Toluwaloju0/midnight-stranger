"""Story generation with a local Ollama model.

Flow: build a persona prompt -> ask Ollama for JSON (title + paragraphs) ->
clean the text for speech -> validate length and content -> retry, then fall
back to a smaller model. In fake mode (MS_FAKE=1) canned stories are returned
so the rest of the pipeline can be tested without any model.
"""
from __future__ import annotations

import json
import logging
import random
import re
import time
import unicodedata
from dataclasses import dataclass, field

from . import config
from .stations import Station

log = logging.getLogger("midnight_stranger.generator")

MAIN_ATTEMPTS = 3
FALLBACK_ATTEMPTS = 2
MIN_PARAGRAPHS = 3
MAX_PARAGRAPHS = 8        # we ask for 3 to 6; small models overshoot, so tolerate a few more
LENGTH_LOW = 0.8          # accept down to 80% of MIN_WORDS ...
LENGTH_HIGH = 1.3         # ... and up to 130% of MAX_WORDS (retries cost minutes on CPU)

SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "paragraphs": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["title", "paragraphs"],
}

SYSTEM_RULES = """You are a writer for a late-night fictional horror radio show.
Write ONE short original story to be read aloud by a single narrator.

Rules:
- Length: about {target} words, in {min_p} to {max_p} paragraphs.
- Spoken style: short sentences, concrete sensory detail. No headings, no lists, no markdown, no stage directions, no sound effects in brackets.
- Chilling, not gory. Keep it PG-13: no graphic violence, no sexual content, no real people. Never mention suicide or self-harm.
- Everything is fictional.
- Build dread slowly. End on a quiet, unsettling final line.
- Reply as JSON with a short 'title' (2 to 6 words) and a list of 'paragraphs'."""

NARRATORS = (
    "a tired night-shift worker",
    "an old woman remembering",
    "a teenager who should not have been out so late",
    "a new arrival who does not know the local rules",
    "a retired engineer who distrusts everything",
    "a child, retold years later by an adult",
)
TURNS = (
    "the thing that seemed helpful turns out to be waiting",
    "a small routine slowly goes wrong",
    "the narrator realises they have been here before",
    "a message arrives from someone who cannot have sent it",
    "everything is explained, and the explanation is worse",
    "the ending quietly repeats the beginning",
)

# Content guard: PG-13 for a general audience. Whole-word, case-insensitive.
BANNED_TERMS = (
    "suicide", "suicidal", "kill myself", "kill himself", "kill herself", "self-harm", "self harm",
    "rape", "raped", "sexual", "sexually", "naked", "nude",
    "gore", "gory", "dismember", "dismembered", "disembowel", "entrails", "mutilate", "mutilated",
    "torture", "tortured", "decapitate", "decapitated",
    "child abuse", "molest",
)
_BANNED_RE = re.compile(r"\b(" + "|".join(re.escape(t) for t in BANNED_TERMS) + r")\b", re.IGNORECASE)


class GenerationError(RuntimeError):
    """Raised when no valid story could be produced."""


@dataclass
class Story:
    title: str
    paragraphs: list[str]
    model: str = ""
    attempts: int = 1
    gen_seconds: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def words(self) -> int:
        return sum(len(p.split()) for p in self.paragraphs)


# --------------------------------------------------------------------------
# Text helpers
# --------------------------------------------------------------------------

def clean_for_speech(text: str) -> str:
    """Strip markdown, bracketed directions, emoji and odd symbols so TTS reads cleanly."""
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("“", '"').replace("”", '"')
    text = re.sub(r"\[[^\]]*\]", " ", text)                 # [stage directions]
    text = re.sub(r"[*_#`~>|]+", "", text)                  # markdown marks
    text = text.replace("—", ", ").replace("–", ", ").replace(" - ", ", ")
    text = text.replace("…", "...")
    text = "".join(
        ch for ch in text
        if unicodedata.category(ch) not in ("So", "Sk", "Cs", "Cc", "Cf") or ch in "\n\t"
    )
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)             # no space before punctuation
    text = re.sub(r",\s*,", ",", text)
    if text and text[-1] not in '.!?"\'':
        text += "."
    return text


def find_banned(text: str) -> str | None:
    match = _BANNED_RE.search(text)
    return match.group(1) if match else None


def parse_json(raw: str) -> dict:
    """Parse the model reply, tolerating code fences and stray text around the JSON."""
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start, end = raw.find("{"), raw.rfind("}")
        if start != -1 and end > start:
            return json.loads(raw[start:end + 1])
        raise


def validate_story(data: object) -> tuple[Story | None, str]:
    """Return (story, '') if valid, else (None, reason)."""
    if not isinstance(data, dict):
        return None, "reply is not a JSON object"
    title = data.get("title")
    paragraphs = data.get("paragraphs")
    if not isinstance(title, str) or not title.strip():
        return None, "missing title"
    if not isinstance(paragraphs, list) or not all(isinstance(p, str) for p in paragraphs):
        return None, "paragraphs is not a list of strings"

    title = clean_for_speech(title).rstrip(".")
    cleaned = [clean_for_speech(p) for p in paragraphs]
    cleaned = [p for p in cleaned if p]
    if not (MIN_PARAGRAPHS <= len(cleaned) <= MAX_PARAGRAPHS):
        return None, f"{len(cleaned)} paragraphs (need {MIN_PARAGRAPHS} to {MAX_PARAGRAPHS})"
    if not 1 <= len(title) <= 80:
        return None, "title length out of range"

    story = Story(title=title, paragraphs=cleaned)
    low, high = int(config.MIN_WORDS * LENGTH_LOW), int(config.MAX_WORDS * LENGTH_HIGH)
    if not low <= story.words <= high:
        return None, f"{story.words} words (accepting {low} to {high})"

    banned = find_banned(title + " " + " ".join(cleaned))
    if banned:
        return None, f"content guard matched '{banned}'"
    return story, ""


# --------------------------------------------------------------------------
# Prompting and Ollama
# --------------------------------------------------------------------------

def build_messages(station: Station, rng: random.Random) -> list[dict]:
    system = SYSTEM_RULES.format(
        target=(config.MIN_WORDS + config.MAX_WORDS) // 2, min_p=4, max_p=6
    )
    user = (
        f"Station: {station.name} ({station.freq} FM).\n{station.persona}\n\n"
        f"For tonight's story use: setting: {rng.choice(station.settings)}; "
        f"narrator: {rng.choice(NARRATORS)}; the turn: {rng.choice(TURNS)}.\n"
        "Do not retell a famous ghost story. Write it now."
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _chat(model: str, messages: list[dict]) -> str:
    """One Ollama call. Isolated so tests can replace it."""
    import ollama

    response = ollama.chat(
        model=model,
        messages=messages,
        format=SCHEMA,
        options={"temperature": 0.9, "top_p": 0.95, "num_predict": 900},
        keep_alive=config.KEEP_ALIVE,
    )
    return response.message.content or ""


def generate_story(station: Station, *, model: str | None = None,
                   rng: random.Random | None = None) -> Story:
    rng = rng or random.Random()
    if config.FAKE:
        return fake_story(station)

    main_model = model or config.MODEL
    plan = [(main_model, MAIN_ATTEMPTS)]
    if config.FALLBACK_MODEL and config.FALLBACK_MODEL != main_model:
        plan.append((config.FALLBACK_MODEL, FALLBACK_ATTEMPTS))

    errors: list[str] = []
    attempt = 0
    for model_name, tries in plan:
        for _ in range(tries):
            attempt += 1
            started = time.perf_counter()
            try:
                raw = _chat(model_name, build_messages(station, rng))
            except ConnectionError as exc:
                raise GenerationError(
                    "Cannot reach Ollama. Start it ('ollama serve') and retry."
                ) from exc
            except Exception as exc:
                errors.append(f"{model_name}: call failed ({exc})")
                log.warning("%s call failed: %s", model_name, exc)
                if "not found" in str(exc).lower():
                    break  # this model is missing; move on to the next one
                continue
            seconds = time.perf_counter() - started
            try:
                story, reason = validate_story(parse_json(raw))
            except (ValueError, json.JSONDecodeError) as exc:
                story, reason = None, f"bad JSON ({exc})"
            if story:
                story.model, story.attempts, story.gen_seconds = model_name, attempt, seconds
                log.info("story ok: %d words, %s, attempt %d, %.1fs",
                         story.words, model_name, attempt, seconds)
                return story
            errors.append(f"{model_name} attempt {attempt}: {reason}")
            log.warning("rejected (%s): %s", model_name, reason)

    raise GenerationError("No valid story. " + "; ".join(errors))


# --------------------------------------------------------------------------
# Fake mode: short canned stories (one per station) for tests and demos
# --------------------------------------------------------------------------

FAKE_STORIES: dict[str, tuple[str, list[str]]] = {
    "88.1": ("The Count of Ships", [
        "The keeper counted the ships every night, and every night the number matched his log. "
        "Fourteen on Monday. Nine on Tuesday. He liked the way numbers stayed where he put them.",
        "On the last night of October, he counted fifteen. The extra ship had no lights and "
        "left no wake. It simply waited at the edge of the beam, patient as a held breath.",
        "When the lamp swept past again, the ship was nearer. The keeper wrote the number in his log. "
        "Then he wrote it again, because the ship had learned to wait beside the others.",
    ]),
    "93.7": ("Exit Forty", [
        "The sign said Exit Forty, Mile Marker Nine, which did not make sense, so Dale kept driving. "
        "The radio hummed between stations, and the dashboard clock blinked a time he did not recognise.",
        "At the next ramp, the same sign. Same cracked paint, same hand-written word beneath it: "
        "Welcome back. Dale laughed once, a short sound with nothing in it.",
        "He took the exit the fourth time. The diner was open, and the waitress had already poured his coffee. "
        "She said she had been keeping it warm for years.",
    ]),
    "101.3": ("The Extra Place at the Table", [
        "Marisol set the ofrenda the way her grandmother taught her: marigolds first, then the candles, "
        "then the bread. The kitchen smelled of cinnamon and wax, and the house was very quiet.",
        "She put out the small blue cup, the one with the chip on its rim. Somewhere in the stillness, "
        "a spoon turned slowly in a cup that was still empty.",
        "Marisol did not look up. She only smiled, and said the soup was almost ready. "
        "The candle leaned toward the empty chair and glowed a little warmer.",
    ]),
    "107.9": ("Weather for Elmsworth", [
        "At two in the morning the station played the weather, as it always did. Light rain in Elmsworth, "
        "clearing by dawn. The new engineer wrote it down because it was his first night.",
        "There is no town called Elmsworth within three hundred miles. He checked the maps twice. "
        "Then he checked the window, and found a thin rain running down the glass.",
        "At three o'clock the forecast changed. Tonight, it said, the engineer will notice the rain. "
        "Tomorrow, the engineer will not. The station kept broadcasting after he left.",
    ]),
}


def fake_story(station: Station) -> Story:
    title, paragraphs = FAKE_STORIES.get(station.freq, FAKE_STORIES["88.1"])
    return Story(title=title, paragraphs=[clean_for_speech(p) for p in paragraphs], model="fake")