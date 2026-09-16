"""Suno-lite song composer: prompt -> full structured song + sung-lyric lead.

Builds on the rule-based `generator` engine (no ML weights):
sections (intro/verse/chorus/...) with per-section energy, chord
progression roots, and a simple vocal-like lead synth that sings the
generated lyrics' phrasing. Keeps the `audio_url` contract so the
existing `/api/audio/{file}.wav` serving works unchanged.
"""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import numpy as np

from backend.generation import generator as G
from backend.generation.lyrics import generate_lyrics, resolve_song_params

# (name, bars, energy) — Suno-style arc with bridge + finale chorus.
# 48 bars @90bpm ≈ 128s, @128bpm ≈ 90s: a real full-length song.
FULL_STRUCTURE: list[tuple[str, int, float]] = [
    ("intro", 2, 0.5),
    ("verse", 8, 0.8),
    ("chorus", 8, 1.0),
    ("verse", 8, 0.8),
    ("chorus", 8, 1.0),
    ("bridge", 4, 0.65),
    ("chorus", 8, 1.05),
    ("outro", 2, 0.5),
]

SHORT_STRUCTURE: list[tuple[str, int, float]] = [
    ("intro", 1, 0.5),
    ("verse", 2, 0.8),
    ("chorus", 2, 1.0),
    ("outro", 1, 0.5),
]


def _key_offset(prompt: str) -> int:
    h = int(hashlib.sha256((prompt or "").lower().encode()).hexdigest()[:4], 16)
    return (h % 5) - 2  # -2..+2 semitones so prompts sound different


def _progression_roots(style: str, total_bars: int, prompt: str, melody: dict | None) -> list[int]:
    """Per-bar bass roots: hum-guided when available, else prompt-seeded progression."""
    if melody and (melody.get("notes") or []):
        notes = melody["notes"]
        beats = [n["start_s"] for n in notes]
        span = max(1.0, (max(beats) - min(beats) + 1.0))
        step = span / total_bars
        roots: list[int] = []
        for b in range(total_bars):
            midis = [n["midi"] for n in notes
                     if b * step <= n["start_s"] - min(beats) < (b + 1) * step]
            roots.append(int(np.median(midis)) - 12 if midis else (roots[-1] if roots else 45))
        return [max(28, min(55, r)) for r in roots]
    minor = G.PRESETS[style]["minor"]
    base = [45, 43, 41, 43] if minor else [48, 43, 45, 41]  # Am-ish / C-ish movement
    off = _key_offset(prompt)
    return [max(28, min(55, r + off)) for b in range(total_bars) for r in [base[b % len(base)]]][:total_bars]


def _crash(rng: np.random.Generator, dur: float = 1.2) -> np.ndarray:
    """Washy crash cymbal for section downbeats."""
    n = max(1, int(G.SR * dur))
    t = np.arange(n) / G.SR
    hp = np.diff(rng.standard_normal(n), prepend=0.0)
    return (hp * np.exp(-t * 4.0) * 0.55).astype(np.float32)


def _riser(rng: np.random.Generator, dur: float) -> np.ndarray:
    """Noise + rising sweep into a chorus."""
    n = max(1, int(G.SR * dur))
    env = np.linspace(0.02, 0.55, n)
    noise = rng.standard_normal(n) * env * 0.22
    sweep_f = np.linspace(200.0, 2000.0, n)
    sweep = np.sin(np.cumsum(2 * np.pi * sweep_f / G.SR)) * env * 0.25
    return (noise + sweep).astype(np.float32)


def _vocal_tone(freq: float, dur: float, rng: np.random.Generator) -> np.ndarray:
    """Vocal-ish lead: sine + 2nd harmonic, gentle vibrato, soft attack."""
    n = max(1, int(G.SR * dur))
    t = np.arange(n) / G.SR
    vib = 1.0 + 0.006 * np.sin(2 * np.pi * 5.5 * t + rng.random() * 6.28)
    f = freq * vib
    phase = np.cumsum(2 * np.pi * f / G.SR)
    sig = np.sin(phase) + 0.3 * np.sin(2 * phase)
    env = np.minimum(1.0, t / 0.06) * np.exp(-t * 2.2)
    return (sig * env * 0.5).astype(np.float32)


def _render_song(
    style: str,
    bpm: int,
    seed: int,
    sections: list[tuple[str, int, float]],
    roots: list[int],
    lyrics: dict,
    with_vocals: bool,
) -> tuple[np.ndarray, dict]:
    p = G.PRESETS[style]
    rng = np.random.default_rng(seed)
    kick = G._variation(rng, p["kick"], [3, 6, 11, 14])
    snare = G._variation(rng, p["snare"], [7, 15], max_add=1)
    hat = G._variation(rng, p["hat"], [1, 3, 5, 7, 9, 11, 13, 15])
    beat = 60.0 / bpm
    step_dur = beat / 4.0
    total_bars = sum(b for _, b, _ in sections)
    total = int(G.SR * beat * G.BEATS_PER_BAR * total_bars) + G.SR
    drums = np.zeros(total, dtype=np.float32)
    bass = np.zeros(total, dtype=np.float32)
    pads = np.zeros(total, dtype=np.float32)
    vocals = np.zeros(total, dtype=np.float32)
    lead = np.zeros(total, dtype=np.float32)
    third = 3 if p["minor"] else 4
    bass_kind = "saw" if style in ("edm", "rock") else ("sine" if style == "ambient" else "square")

    lyric_lines = lyrics.get("verse", []) + lyrics.get("chorus", []) + lyrics.get("bridge", [])
    line_idx = 0
    bar_global = 0
    cursor = 0.0  # seconds at current bar start
    for si, (name, bars, energy) in enumerate(sections):
        next_name = sections[si + 1][0] if si + 1 < len(sections) else ""
        into_chorus = next_name == "chorus"
        is_break = name in ("intro", "outro")
        is_bridge = name == "bridge"
        is_chorus = name == "chorus"
        for bi in range(bars):
            root = roots[bar_global]
            bar_start = cursor
            last_in_section = bi == bars - 1
            # crash on every section downbeat
            if bi == 0:
                G._add(drums, _crash(rng), int(bar_start * G.SR),
                       0.5 * p["drums"] * (0.5 if is_break else 1.0))
            # riser across the bar that leads into a chorus
            if into_chorus and last_in_section:
                G._add(drums, _riser(rng, G.BEATS_PER_BAR * beat),
                       int(bar_start * G.SR), 0.6 * energy)
            # pads every bar, scaled by energy (bridge: washier)
            for iv in (0, third, 7):
                sig = G._tone(G._midi_to_freq(root + 12 + iv), G.BEATS_PER_BAR * beat, "sine",
                              decay=0.9 if is_bridge else 1.2)
                G._add(pads, sig, int(bar_start * G.SR),
                       0.22 * p["pad"] * (0.6 + 0.4 * energy) * (1.25 if is_bridge else 1.0))
            # bass + sub octave
            bass_steps = [0, 2] if style in ("edm", "rock", "pop") else [0]
            octave_up = rng.random() < 0.35
            for b in range(G.BEATS_PER_BAR):
                for s in bass_steps:
                    at = bar_start + (b * 4 + s) * step_dur
                    note = root + (12 if octave_up and s == 2 else 0)
                    sig = G._tone(G._midi_to_freq(note), step_dur * 3.5, bass_kind, decay=5.0)
                    G._add(bass, sig, int(at * G.SR), 0.5 * p["bass"] * energy)
                    if root - 12 >= 24:
                        sub = G._tone(G._midi_to_freq(root - 12), step_dur * 3.5, "sine", decay=5.0)
                        G._add(bass, sub, int(at * G.SR), 0.20 * p["bass"] * energy)
            # drums (sparse on breaks, half-time feel on bridge)
            for s in range(G.STEPS_PER_BAR):
                at = bar_start + s * step_dur
                if s % 2 == 1:
                    at += p["swing"] * step_dur
                idx = int(at * G.SR)
                drum_e = energy * (0.35 if is_break else 1.0) * (0.6 if is_bridge else 1.0)
                if s in kick and not (is_break and rng.random() < 0.7):
                    G._add(drums, G._kick(), idx, 0.9 * p["drums"] * drum_e)
                if s in snare and not (is_break and rng.random() < 0.7):
                    G._add(drums, G._snare(rng), idx, 0.7 * p["drums"] * drum_e)
                if s in hat:
                    G._add(drums, G._hat(rng), idx, 0.35 * p["drums"] * drum_e)
            # snare fill: 8th-note roll with rising gain into a chorus
            if into_chorus and last_in_section:
                for k, s in enumerate(range(8, 16, 2)):
                    idx = int((bar_start + s * step_dur) * G.SR)
                    G._add(drums, G._snare(rng), idx,
                           (0.25 + 0.45 * k / 3) * p["drums"] * energy)
            # arp lead: sparkling 16ths on chorus (+single echo tap)
            if is_chorus:
                arp = [0, third, 7, 12, 12 + third, 12 + 7]
                for s in range(G.STEPS_PER_BAR):
                    iv = arp[(bar_global + s) % len(arp)]
                    sig = G._tone(G._midi_to_freq(root + 24 + iv), step_dur * 0.9, "square", decay=9.0)
                    at = bar_start + s * step_dur
                    G._add(lead, sig, int(at * G.SR), 0.16 * energy)
                    echo_at = at + 3 * step_dur  # dotted echo
                    if echo_at < bar_start + G.BEATS_PER_BAR * beat:
                        G._add(lead, sig, int(echo_at * G.SR), 0.05 * energy)
            # vocals: verse/chorus full, bridge soft, rest on breaks
            if with_vocals and name in ("verse", "chorus", "bridge"):
                line = lyric_lines[line_idx % max(1, len(lyric_lines))]
                line_idx += 1
                syllables = max(2, min(4, len(line.split()) // 2))
                chord_tones = [0, third, 7, 12]
                v_gain = 0.55 * (1.0 if is_chorus else (0.6 if is_bridge else 0.8))
                for k in range(syllables):
                    iv = chord_tones[(bar_global + k) % len(chord_tones)]
                    freq = G._midi_to_freq(root + 24 + iv)
                    dur = beat * 0.9
                    at = bar_start + k * (G.BEATS_PER_BAR * beat / syllables)
                    sig = _vocal_tone(freq, dur, rng)
                    G._add(vocals, sig, int(at * G.SR), v_gain)
            bar_global += 1
            cursor += G.BEATS_PER_BAR * beat

    raw = drums + bass + pads + vocals + lead
    peak = float(np.max(np.abs(raw))) or 1.0
    scale = 0.89 / peak
    mix = np.tanh(raw / peak * 1.2) * 0.89
    return mix, {"drums": drums * scale, "bass": bass * scale, "pads": pads * scale,
                 "lead": lead * scale, "vocals": vocals * scale}


def compose_song(
    prompt: str,
    style: str | None = None,
    tempo: int | None = None,
    mood: str | None = None,
    seed: int | None = None,
    stems: bool = False,
    vocals: bool = True,
    song_length: str = "full",
    melody: dict | None = None,
) -> dict:
    """Full Suno-lite compose. Returns metadata dict (writes WAVs to generated/)."""
    if not (prompt or "").strip() and melody is None:
        raise ValueError("prompt is required (or hum a melody)")
    params = resolve_song_params(prompt or "", style, tempo, mood)
    style_r, mood_r, bpm = params["style"], params["mood"], params["tempo_bpm"]
    seed = int(seed) & 0xFFFFFFFF if seed is not None else int(
        np.random.default_rng().integers(0, 2**31))
    gain = G.MOOD_GAIN.get(mood_r.lower(), 1.0)

    sections = FULL_STRUCTURE if song_length != "short" else SHORT_STRUCTURE
    total_bars = sum(b for _, b, _ in sections)
    lyrics = generate_lyrics(prompt or "hummed melody", mood_r, style_r, seed)
    roots = _progression_roots(style_r, total_bars, prompt or "", melody)

    audio, stem_audio = _render_song(style_r, bpm, seed, sections, roots, lyrics, vocals)
    audio = audio * gain
    peak = float(np.max(np.abs(audio))) or 1.0
    if peak > 0.99:
        audio = audio / peak * 0.89

    G.GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"song_{style_r.replace('/', '-')}_{bpm}_{uuid.uuid4().hex[:8]}"
    G._write_wav(G.GENERATED_DIR / f"{stem}.wav", audio)

    # section timeline for the UI
    beat = 60.0 / bpm
    timeline, cursor = [], 0.0
    for name, bars, energy in sections:
        dur = bars * G.BEATS_PER_BAR * beat
        timeline.append({"name": name, "bars": bars, "energy": energy,
                         "start_s": round(cursor, 2), "duration_s": round(dur, 2)})
        cursor += dur

    tracks = ["drums", "bass", "chords", "lead"] + (["vocals"] if vocals else [])
    resp = {
        "title": lyrics["title"],
        "prompt": prompt,
        "style": style_r,
        "tempo_bpm": bpm,
        "mood": mood_r,
        "seed": seed,
        "lyrics": lyrics,
        "structure": timeline,
        "total_bars": total_bars,
        "tracks": tracks,
        "duration_s": round(len(audio) / G.SR, 2),
        "audio_url": f"/api/audio/{stem}.wav",
    }
    if stems:
        urls = {}
        for name, sig in stem_audio.items():
            if name == "vocals" and not vocals:
                continue
            G._write_wav(G.GENERATED_DIR / f"{stem}_{name}.wav", sig * gain)
            urls[name] = f"/api/audio/{stem}_{name}.wav"
        resp["stems"] = urls
    return resp
