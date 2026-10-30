"""The four fictional radio stations.

Each station bundles a writing persona, a Piper voice, speech pacing and an
ambience profile (see ambience.py). Change voices or pacing here.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Station:
    freq: str                 # dial position, e.g. "88.1"
    name: str
    tagline: str
    voice: str                # Piper voice stem, e.g. "en_GB-alan-medium"
    ambience: str             # profile name in ambience.PROFILES
    persona: str              # station-specific writing instructions for the model
    settings: tuple[str, ...]  # random story seeds for variety
    length_scale: float = 1.0  # >1 speaks slower
    noise_scale: float | None = None  # lower = flatter, more monotone delivery
    bed_level: float = 0.20   # ambience loudness relative to speech


STATIONS: tuple[Station, ...] = (
    Station(
        freq="88.1",
        name="The Lighthouse",
        tagline="Isolated, coastal dread",
        voice="en_GB-alan-medium",
        ambience="sea",
        length_scale=1.08,
        bed_level=0.22,
        persona=(
            "You write for 'The Lighthouse', late-night stories of isolation by the sea: "
            "keepers, fog, tides, lamps, and ships that should not be there. "
            "Voice: patient, salt-worn, quietly dreadful. Use first person or close third person."
        ),
        settings=(
            "a lighthouse on a rock two hours from shore",
            "a fishing village during a week of fog",
            "a lifeboat station in winter",
            "an abandoned signal tower on a sea cliff",
            "a ferry that makes its last crossing at midnight",
        ),
    ),
    Station(
        freq="93.7",
        name="Route 13 Overnight",
        tagline="Highway, drivers, things in the rearview",
        voice="en_US-lessac-medium",
        ambience="road",
        bed_level=0.20,
        persona=(
            "You write for 'Route 13 Overnight', stories of night highways: long-haul drivers, "
            "empty diners, rest stops, hitchhikers, radio signals drifting between towns. "
            "Voice: laconic, road-weary, with dry humour that slowly curdles."
        ),
        settings=(
            "a truck stop diner at 3 a.m.",
            "a stretch of highway with no exits for forty miles",
            "a motel with one room left",
            "a night bus between two small towns",
            "a gas station that is always open",
        ),
    ),
    Station(
        freq="101.3",
        name="Frequency of the Dead",
        tagline="Gentle, fictional remembrance (Dia de los Muertos spirit)",
        voice="en_US-amy-medium",
        ambience="candle",
        length_scale=1.10,
        bed_level=0.18,
        persona=(
            "You write for 'Frequency of the Dead', tender ghost stories in the spirit of "
            "Dia de los Muertos: ofrendas, marigolds, candlelight, a grandmother's kitchen, "
            "a song someone used to hum. The dead are never menacing; the chill comes from "
            "love and longing. Every person and event is fictional. Never mention suicide, "
            "illness details, or real people. Comforting, a little eerie, and kind."
        ),
        settings=(
            "an ofrenda set out in a family kitchen on the night of November first",
            "a village cemetery lit with candles and marigolds",
            "a grandmother's recipe that tastes different this year",
            "a radio that plays an old song nobody turned on",
            "a street market the night before the festival",
        ),
    ),
    Station(
        freq="107.9",
        name="Static Hours",
        tagline="Strange signals and unexplained broadcasts",
        voice="en_US-lessac-medium",
        ambience="static",
        length_scale=1.22,
        noise_scale=0.45,
        bed_level=0.17,
        persona=(
            "You write for 'Static Hours', stories of strange signals and unexplained broadcasts: "
            "numbers stations, a radio that answers back, a tape with one voice too many, "
            "a weather report for a town that does not exist. "
            "Voice: clipped and clinical at first, then quietly unsettling."
        ),
        settings=(
            "a shortwave radio in an attic",
            "a night shift at a small-town radio station",
            "a cassette tape found in a second-hand car",
            "a weather report that is always a day early",
            "an emergency broadcast nobody remembers scheduling",
        ),
    ),
)


def by_freq(value: str) -> Station:
    """Look up a station by dial position, tolerating '88.1', '88.1 FM' or ' 88.1'."""
    key = value.lower().replace("fm", "").strip()
    for station in STATIONS:
        if station.freq == key:
            return station
    raise KeyError(f"Unknown station '{value}'. Choose one of: " + ", ".join(s.freq for s in STATIONS))