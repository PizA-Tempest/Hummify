"""Beat-generation stubs — swap in real AI model under models/music_model/."""
from __future__ import annotations

SUPPORTED_STYLES = ["lo-fi", "hip-hop", "pop", "r&b", "rock", "edm", "jazz", "ambient"]


def generate_beat(melody: dict, style: str, tempo: int | None = None, mood: str = "chill") -> dict:
    style = style.lower()
    if style not in SUPPORTED_STYLES:
        raise ValueError(f"unsupported style: {style}")
    return {
        "style": style,
        "tempo_bpm": tempo or melody.get("tempo_bpm", 90),
        "mood": mood,
        "tracks": ["drums", "bass", "chords", "melody"],
        "audio_url": None,  # no rendered audio yet
    }
