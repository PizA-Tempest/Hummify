"""Rule-based beat synthesis (numpy, no ML weights).

Renders a 4-bar loop to `generated/beat_<id>.wav`:
drums (kick/snare/hat synths) + bass following the detected melody roots
+ chord pads. Style presets change pattern, tempo default, swing and mix.
Real ML model code can later replace `render()` — keep `generate_beat`
signature and the `audio_url` contract.
"""
from __future__ import annotations

import uuid
import wave
from pathlib import Path

import numpy as np

SUPPORTED_STYLES = ["lo-fi", "hip-hop", "pop", "r&b", "rock", "edm", "jazz", "ambient"]

SR = 44100
BARS = 4
BEATS_PER_BAR = 4
STEPS_PER_BAR = 16  # 16th notes

# Per-style: default bpm, 16-step drum patterns (per bar), swing, gains.
# swing shifts every 2nd 16th by swing * step_dur.
PRESETS: dict[str, dict] = {
    "lo-fi": {"bpm": 80, "kick": [0, 7, 10], "snare": [4, 12], "hat": [0, 2, 4, 6, 8, 10, 12, 14],
              "swing": 0.12, "drums": 0.7, "bass": 0.8, "pad": 0.5, "minor": True},
    "hip-hop": {"bpm": 90, "kick": [0, 6, 10], "snare": [4, 12], "hat": [0, 2, 4, 6, 8, 10, 12, 14],
               "swing": 0.08, "drums": 1.0, "bass": 1.0, "pad": 0.35, "minor": True},
    "pop": {"bpm": 120, "kick": [0, 4, 8, 12], "snare": [4, 12], "hat": [0, 2, 4, 6, 8, 10, 12, 14],
            "swing": 0.0, "drums": 0.9, "bass": 0.8, "pad": 0.5, "minor": False},
    "r&b": {"bpm": 95, "kick": [0, 10], "snare": [4, 12], "hat": [0, 3, 6, 8, 11, 14],
            "swing": 0.10, "drums": 0.8, "bass": 0.9, "pad": 0.55, "minor": True},
    "rock": {"bpm": 130, "kick": [0, 8, 10], "snare": [4, 12], "hat": [0, 2, 4, 6, 8, 10, 12, 14],
             "swing": 0.0, "drums": 1.0, "bass": 0.9, "pad": 0.3, "minor": False},
    "edm": {"bpm": 128, "kick": [0, 4, 8, 12], "snare": [4, 12],
            "hat": [2, 6, 10, 14, 0, 4, 8, 12],
            "swing": 0.0, "drums": 1.0, "bass": 0.9, "pad": 0.45, "minor": True},
    "jazz": {"bpm": 110, "kick": [0, 8], "snare": [7, 13], "hat": [0, 2, 4, 6, 8, 10, 12, 14],
             "swing": 0.18, "drums": 0.75, "bass": 0.85, "pad": 0.45, "minor": False},
    "ambient": {"bpm": 70, "kick": [], "snare": [], "hat": [0, 8],
                "swing": 0.0, "drums": 0.25, "bass": 0.5, "pad": 0.9, "minor": True},
}

MOOD_GAIN = {"chill": 0.85, "smooth": 0.9, "dark": 0.9, "bright": 1.0,
             "energetic": 1.15, "driving": 1.15, "party": 1.15}

GENERATED_DIR = Path(__file__).resolve().parents[2] / "generated"


def _midi_to_freq(m: float) -> float:
    return 440.0 * (2.0 ** ((m - 69) / 12.0))


def _kick(dur: float = 0.25) -> np.ndarray:
    n = int(SR * dur)
    t = np.arange(n) / SR
    f = 150.0 * np.exp(-t * 30.0) + 45.0
    phase = np.cumsum(2 * np.pi * f / SR)
    return np.sin(phase) * np.exp(-t * 12.0)


def _snare(dur: float = 0.2) -> np.ndarray:
    n = int(SR * dur)
    t = np.arange(n) / SR
    rng = np.random.default_rng(7)
    noise = rng.standard_normal(n)
    tone = np.sin(2 * np.pi * 190.0 * t) * np.exp(-t * 25.0)
    return (0.6 * noise * np.exp(-t * 22.0) + 0.4 * tone).astype(np.float32)


def _hat(dur: float = 0.06) -> np.ndarray:
    n = int(SR * dur)
    t = np.arange(n) / SR
    rng = np.random.default_rng(13)
    noise = rng.standard_normal(n)
    # crude highpass: differentiate
    hp = np.diff(noise, prepend=0.0)
    return (hp * np.exp(-t * 90.0)).astype(np.float32)


def _tone(freq: float, dur: float, kind: str = "sine", decay: float = 6.0) -> np.ndarray:
    n = max(1, int(SR * dur))
    t = np.arange(n) / SR
    if kind == "square":
        osc = np.sign(np.sin(2 * np.pi * freq * t))
    elif kind == "saw":
        osc = 2.0 * ((freq * t) % 1.0) - 1.0
    else:
        osc = np.sin(2 * np.pi * freq * t)
    return (osc * np.exp(-t * decay)).astype(np.float32)


def _add(buf: np.ndarray, sig: np.ndarray, at: int, gain: float = 1.0) -> None:
    if at >= len(buf):
        return
    end = min(len(buf), at + len(sig))
    buf[at:end] += sig[: end - at] * gain


def _bar_roots(melody: dict) -> list[int]:
    """One bass root per bar from detected notes, else i–VII–VI–VII in A minor."""
    notes = melody.get("notes") or []
    if notes:
        beats = [n["start_s"] for n in notes]
        step = max(1.0, (max(beats) - min(beats) + 1.0) / BARS)
        roots = []
        for b in range(BARS):
            midis = [n["midi"] for n in notes
                     if b * step <= n["start_s"] - min(beats) < (b + 1) * step]
            roots.append(int(np.median(midis)) - 12 if midis else (roots[-1] if roots else 45))
        return [max(28, min(55, r)) for r in roots]
    return [45, 43, 41, 43]  # A2 G2 F2 G2


def render(melody: dict, style: str, bpm: int) -> np.ndarray:
    p = PRESETS[style]
    beat = 60.0 / bpm
    step_dur = beat / 4.0
    total = int(SR * beat * BEATS_PER_BAR * BARS) + SR  # +1s tail
    buf = np.zeros(total, dtype=np.float32)
    roots = _bar_roots(melody)
    third = 3 if p["minor"] else 4
    bass_kind = "saw" if style in ("edm", "rock") else ("sine" if style == "ambient" else "square")

    for bar in range(BARS):
        bar_start = bar * BEATS_PER_BAR * beat
        root = roots[bar]
        # --- pads: root + third + fifth, whole bar ---
        for iv in (0, third, 7):
            sig = _tone(_midi_to_freq(root + 12 + iv), BEATS_PER_BAR * beat, "sine", decay=1.2)
            _add(buf, sig, int((bar_start) * SR), 0.22 * p["pad"])
        # --- bass: root each beat (8ths for driving styles) ---
        bass_steps = [0, 2] if style in ("edm", "rock", "pop") else [0]
        for b in range(BEATS_PER_BAR):
            for s in bass_steps:
                at = bar_start + (b * 4 + s) * step_dur
                sig = _tone(_midi_to_freq(root), step_dur * 3.5, bass_kind, decay=5.0)
                _add(buf, sig, int(at * SR), 0.5 * p["bass"])
        # --- drums ---
        for s in range(STEPS_PER_BAR):
            at = bar_start + s * step_dur
            if s % 2 == 1:  # swing the off-16ths
                at += p["swing"] * step_dur
            idx = int(at * SR)
            if s in p["kick"]:
                _add(buf, _kick(), idx, 0.9 * p["drums"])
            if s in p["snare"]:
                _add(buf, _snare(), idx, 0.7 * p["drums"])
            if s in p["hat"]:
                _add(buf, _hat(), idx, 0.35 * p["drums"])
    # normalize + mood-agnostic soft clip
    peak = float(np.max(np.abs(buf))) or 1.0
    buf = np.tanh(buf / peak * 1.2) * 0.89
    return buf


def generate_beat(melody: dict, style: str, tempo: int | None = None, mood: str = "chill") -> dict:
    style = style.lower()
    if style not in SUPPORTED_STYLES:
        raise ValueError(f"unsupported style: {style}")
    bpm = int(tempo) if tempo else int(melody.get("tempo_bpm", 0) or PRESETS[style]["bpm"])
    bpm = max(60, min(180, bpm))
    gain = MOOD_GAIN.get((mood or "chill").lower(), 1.0)

    audio = render(melody, style, bpm) * gain
    peak = float(np.max(np.abs(audio))) or 1.0
    if peak > 0.99:
        audio = audio / peak * 0.89

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    name = f"beat_{style.replace('/', '-')}_{bpm}_{uuid.uuid4().hex[:8]}.wav"
    path = GENERATED_DIR / name
    pcm = (np.clip(audio, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())

    return {
        "style": style,
        "tempo_bpm": bpm,
        "mood": mood,
        "tracks": ["drums", "bass", "chords", "melody"],
        "duration_s": round(len(audio) / SR, 2),
        "audio_url": f"/api/audio/{name}",
    }
