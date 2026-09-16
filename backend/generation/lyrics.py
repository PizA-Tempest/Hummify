"""Suno-lite prompt parsing + rule-based lyrics.

No ML weights: deterministic, seeded template generation so the same
(prompt, seed) always yields the same lyrics. Real LLM/vocal models can
later replace `generate_lyrics` — keep its return contract.
"""
from __future__ import annotations

import hashlib
import re

import numpy as np

from backend.generation.generator import PRESETS, SUPPORTED_STYLES

STYLE_KEYWORDS: dict[str, list[str]] = {
    "lo-fi": ["lo-fi", "lofi", "lo fi", "chillhop", "bedroom"],
    "hip-hop": ["hip-hop", "hip hop", "rap", "boom bap", "trap"],
    "pop": ["pop", "catchy", "radio", "anthem"],
    "r&b": ["r&b", "rnb", "r and b", "soul", "slow jam"],
    "rock": ["rock", "guitar", "punk", "indie rock"],
    "edm": ["edm", "electronic", "dance", "house", "techno", "club"],
    "jazz": ["jazz", "swing", "bossa", "sax"],
    "ambient": ["ambient", "atmospheric", "soundscape", "drone", "minimal", "meditation"],
}

MOOD_KEYWORDS: dict[str, list[str]] = {
    "chill": ["chill", "relax", "mellow", "lazy"],
    "smooth": ["smooth", "silky", "velvet"],
    "dark": ["dark", "sad", "lonely", "midnight", "rain", "blue"],
    "bright": ["bright", "happy", "sunny", "summer", "uplifting"],
    "energetic": ["energetic", "energy", "hype", "workout", "party", "fast", "upbeat"],
    "driving": ["driving", "night drive", "highway", "neon"],
}

TEMPO_HINTS: list[tuple[str, int]] = [
    ("slow", 70),
    ("ballad", 72),
    ("chill", 80),
    ("mid", 95),
    ("upbeat", 118),
    ("fast", 128),
    ("club", 128),
    ("workout", 130),
]

DEFAULT_MOODS = ["chill", "smooth", "dark", "bright", "energetic", "driving"]


def _prompt_seed(prompt: str, seed: int | None) -> int:
    h = int(hashlib.sha256(prompt.lower().encode()).hexdigest()[:8], 16)
    if seed is None:
        return h & 0xFFFFFFFF
    return (int(seed) ^ h) & 0xFFFFFFFF


def parse_prompt(prompt: str) -> dict:
    """Infer style / mood / tempo hints from free text. Never raises."""
    p = (prompt or "").lower()
    style = None
    for s, keys in STYLE_KEYWORDS.items():
        if any(k in p for k in keys):
            style = s
            break
    mood = None
    for m, keys in MOOD_KEYWORDS.items():
        if any(k in p for k in keys):
            mood = m
            break
    tempo = None
    for k, bpm in TEMPO_HINTS:
        if k in p:
            tempo = bpm
            break
    return {"style": style, "mood": mood, "tempo": tempo}


def resolve_song_params(
    prompt: str,
    style: str | None = None,
    tempo: int | None = None,
    mood: str | None = None,
) -> dict:
    """Merge explicit params over prompt hints over style defaults."""
    hints = parse_prompt(prompt)
    s = (style or hints["style"] or "lo-fi").lower()
    if s not in SUPPORTED_STYLES:
        raise ValueError(f"unsupported style: {style}")
    m = (mood or hints["mood"] or "chill").lower()
    if m not in [x.lower() for x in DEFAULT_MOODS] and m not in ("party",):
        m = "chill"
    bpm = int(tempo) if tempo else (hints["tempo"] or PRESETS[s]["bpm"])
    bpm = max(60, min(180, bpm))
    return {"style": s, "mood": m, "tempo_bpm": bpm}


# --- lyric line banks (mood-flavoured, style-neutral) ---
_VERSE_BANK: dict[str, list[str]] = {
    "chill": [
        "Streetlights blur through the window pane",
        "Half-asleep but I feel awake",
        "Coffee cooling in my hands",
        "Tracing maps of other lands",
        "Slow reel of a quiet day",
        "Let the static fade away",
    ],
    "smooth": [
        "Velvet hours, low light glow",
        "Every word moves soft and slow",
        "City hum beneath our feet",
        "Two hearts keeping time with the beat",
        "Silk on skin, the night is ours",
        "Counting falling midnight hours",
    ],
    "dark": [
        "Empty rooms and midnight rain",
        "Echoes calling out your name",
        "Shadows dancing on the wall",
        "I reach out but you don't call",
        "Heavy clouds above the street",
        "Every memory bittersweet",
    ],
    "bright": [
        "Sunlight spilling through the blinds",
        "Golden days and open skies",
        "Barefoot running down the lane",
        "Laughing through the summer rain",
        "Every color feels brand new",
        "The whole world waking up with you",
    ],
    "energetic": [
        "Turn it up, we own the night",
        "Neon hearts burning bright",
        "Feet don't stop, we levitate",
        "No excuses, can't be late",
        "Hands up riding every wave",
        "Loud enough to misbehave",
    ],
    "driving": [
        "Headlights cutting through the haze",
        "Lost inside the neon maze",
        "Engine hum and midnight fuel",
        "Breaking every dated rule",
        "Rearview full of city fire",
        "Chasing something higher",
    ],
}

_CHORUS_BANK: dict[str, list[str]] = {
    "chill": [
        "And we float, and we float away",
        "Let the night turn into day",
        "Hold this feeling, let it stay",
        "We don't need to find a way",
    ],
    "smooth": [
        "Stay with me in this groove",
        "Nothing left for us to prove",
        "Move the way the moonlight moves",
        "Locked inside this velvet groove",
    ],
    "dark": [
        "But I still hear you in the rain",
        "Every drop spells out your name",
        "Hold me through the hurricane",
        "Nothing ever feels the same",
    ],
    "bright": [
        "We shine, we shine brighter",
        "Every day keeps getting lighter",
        "Higher, higher, take me higher",
        "Set the whole sky on fire",
    ],
    "energetic": [
        "We go louder, louder now",
        "Show them all exactly how",
        "No way down, only up",
        "Drink the night, fill your cup",
    ],
    "driving": [
        "Drive, drive into the glow",
        "Anywhere the night wants to go",
        "Don't look back, just let it flow",
        "Faster than we'll ever know",
    ],
}

_BRIDGE_BANK = [
    "Quiet now, let it breathe",
    "Every scar becomes a seed",
    "What we lost, we let it be",
    "What remains is you and me",
]


def _title_from_prompt(prompt: str) -> str:
    words = re.findall(r"[A-Za-z']+", prompt or "")
    words = [w for w in words if len(w) > 2][:4]
    if not words:
        return "Untitled Glow"
    return " ".join(w.capitalize() for w in words)


def generate_lyrics(prompt: str, mood: str = "chill", style: str = "lo-fi", seed: int | None = None) -> dict:
    """Deterministic verse/chorus/bridge built from mood banks + prompt hook."""
    mood = (mood or "chill").lower()
    if mood not in _VERSE_BANK:
        mood = "chill"
    rng = np.random.default_rng(_prompt_seed(prompt or "", seed))
    verse_pool = _VERSE_BANK[mood]
    chorus_pool = _CHORUS_BANK[mood]
    verse = [verse_pool[i] for i in rng.choice(len(verse_pool), size=4, replace=False)]
    chorus = [chorus_pool[i] for i in rng.choice(len(chorus_pool), size=4, replace=False)]
    bridge = [x for x in rng.choice(_BRIDGE_BANK, size=2, replace=False)]
    hook = _title_from_prompt(prompt)
    # weave the hook into the chorus closer (Suno-style title drop)
    chorus[-1] = f"{hook} — we sing it back again"
    text = (
        f"[Verse]\n" + "\n".join(verse)
        + f"\n\n[Chorus]\n" + "\n".join(chorus)
        + f"\n\n[Bridge]\n" + "\n".join(bridge)
        + f"\n\n[Chorus]\n" + "\n".join(chorus)
    )
    return {"title": hook, "verse": verse, "chorus": chorus, "bridge": list(bridge), "text": text}
