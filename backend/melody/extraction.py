"""Melody extraction: WAV -> pitch track -> notes + tempo estimate.

No heavy deps: stdlib `wave` + `numpy` only. Frontend must send WAV
(see `frontend/components/recorder.js` `blobToWav`); other containers
(webm/opus/mp3) are rejected with a clear error instead of guessing.
"""
from __future__ import annotations

import io
import math
import wave

import numpy as np

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

FMIN_HZ = 80.0
FMAX_HZ = 1000.0
FRAME_SIZE = 2048
HOP_SIZE = 512
RMS_THRESHOLD = 0.02
CONF_THRESHOLD = 0.45


def _decode_wav(audio_bytes: bytes) -> tuple[np.ndarray, int]:
    try:
        with wave.open(io.BytesIO(audio_bytes), "rb") as w:
            n_chan, sampwidth, sr, n_frames, _, _ = w.getparams()
            raw = w.readframes(n_frames)
    except Exception as e:
        raise ValueError("unsupported audio format (send 16-bit WAV)") from e
    if not raw:
        raise ValueError("empty audio")
    if sampwidth == 1:  # 8-bit unsigned
        y = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif sampwidth == 2:
        y = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif sampwidth == 3:
        arr = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 3).astype(np.int32)
        ints = arr[:, 0] | (arr[:, 1] << 8) | (arr[:, 2] << 16)
        ints = np.where(ints >= 1 << 23, ints - (1 << 24), ints)
        y = (ints.astype(np.float32) / (1 << 23)).reshape(-1)
    elif sampwidth == 4:
        y = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        raise ValueError("unsupported WAV bit depth")
    if n_chan > 1:
        y = y.reshape(-1, n_chan).mean(axis=1)
    return y.astype(np.float32), sr


def _hz_to_midi(f: float) -> int:
    return int(round(69 + 12 * math.log2(f / 440.0)))


def _midi_to_name(m: int) -> str:
    return f"{NOTE_NAMES[m % 12]}{(m // 12) - 1}"


def _frame_f0(frame: np.ndarray, sr: int) -> tuple[float, float]:
    """Autocorrelation f0 + confidence for one frame. Returns (hz, conf)."""
    frame = frame - frame.mean()
    rms = float(np.sqrt(np.mean(frame * frame)))
    if rms < RMS_THRESHOLD:
        return 0.0, 0.0
    frame = frame * np.hanning(len(frame))
    ac = np.correlate(frame, frame, mode="full")[len(frame) - 1 :]
    if ac[0] <= 0:
        return 0.0, 0.0
    ac = ac / ac[0]
    lo = max(1, int(sr / FMAX_HZ))
    hi = min(len(ac) - 2, int(sr / FMIN_HZ))
    if hi <= lo:
        return 0.0, 0.0
    seg = ac[lo : hi + 1]
    k = int(np.argmax(seg)) + lo
    # parabolic interpolation around peak
    if 0 < k < len(ac) - 1:
        a, b, c = ac[k - 1], ac[k], ac[k + 1]
        denom = a - 2 * b + c
        shift = 0.5 * (a - c) / denom if denom != 0 else 0.0
        k = k + max(-1.0, min(1.0, shift))
    hz = sr / k
    if not (FMIN_HZ <= hz <= FMAX_HZ):
        return 0.0, 0.0
    return float(hz), float(ac[int(round(k))] if 0 <= int(round(k)) < len(ac) else 0.0)


def _estimate_tempo(y: np.ndarray, sr: int) -> int:
    """Onset-envelope autocorrelation in the 60–180 BPM range."""
    hop = 512
    frames = [y[i : i + 2048] for i in range(0, max(0, len(y) - 2048), hop)]
    if len(frames) < 8:
        return 90
    energy = np.array([float(np.sum(f * f)) for f in frames])
    novelty = np.maximum(0.0, np.diff(np.log1p(energy)))
    novelty = novelty - novelty.mean()
    if float(np.sum(novelty * novelty)) < 1e-9:
        return 90
    ac = np.correlate(novelty, novelty, mode="full")[len(novelty) - 1 :]
    ac = ac / max(ac[0], 1e-9)
    fps = sr / hop  # novelty frames per second
    best_bpm, best_v = 90, -1.0
    for bpm in range(60, 181):
        lag = fps * 60.0 / bpm
        i0 = int(lag)
        if 1 <= i0 < len(ac):
            # interpolate neighbouring lags for stability
            v = float(np.mean(ac[max(1, i0 - 1) : i0 + 2]))
            if v > best_v:
                best_bpm, best_v = bpm, v
    return best_bpm if best_v > 0.15 else 90


def analyze_melody(audio_bytes: bytes, sample_rate: int = 44100) -> dict:
    """Analyze WAV bytes -> tempo, note events, pitch stats."""
    if not audio_bytes:
        raise ValueError("empty audio")
    y, sr = _decode_wav(audio_bytes)
    duration = len(y) / float(sr)
    if duration < 0.1:
        raise ValueError("audio too short")

    # frame-wise f0
    track: list[dict] = []
    for i in range(0, max(1, len(y) - FRAME_SIZE), HOP_SIZE):
        hz, conf = _frame_f0(y[i : i + FRAME_SIZE], sr)
        voiced = hz > 0 and conf >= CONF_THRESHOLD
        t = i / float(sr)
        if voiced:
            midi = _hz_to_midi(hz)
            track.append({"t": t, "hz": hz, "midi": midi, "conf": conf})
        else:
            track.append({"t": t, "hz": 0.0, "midi": None, "conf": conf})

    # merge frames into note events (gap <= 2 frames, same midi ±1)
    notes: list[dict] = []
    cur = None
    hop_dur = HOP_SIZE / float(sr)
    for f in track:
        if f["midi"] is None:
            if cur and len(cur["hs"]) >= 3:
                notes.append(_finish_note(cur, hop_dur))
            cur = None
            continue
        if cur is None:
            cur = {"midi": f["midi"], "hs": [f["hz"]], "start": f["t"], "end": f["t"]}
        elif abs(f["midi"] - cur["midi"]) <= 1 and f["t"] - cur["end"] <= 2 * HOP_SIZE / sr + 1e-6:
            cur["hs"].append(f["hz"])
            cur["end"] = f["t"]
            # drift toward new pitch center
            cur["midi"] = _hz_to_midi(float(np.median(cur["hs"])))
        else:
            if len(cur["hs"]) >= 3:
                notes.append(_finish_note(cur, hop_dur))
            cur = {"midi": f["midi"], "hs": [f["hz"]], "start": f["t"], "end": f["t"]}
    if cur and len(cur["hs"]) >= 3:
        notes.append(_finish_note(cur, hop_dur))

    voiced_frames = sum(1 for f in track if f["midi"] is not None)
    hz_vals = [f["hz"] for f in track if f["midi"] is not None]
    return {
        "tempo_bpm": _estimate_tempo(y, sr),
        "note_count": len(notes),
        "notes": notes,
        "sample_rate": sr,
        "duration_s": round(duration, 3),
        "voiced_ratio": round(voiced_frames / max(1, len(track)), 3),
        "mean_f0_hz": round(float(np.mean(hz_vals)), 1) if hz_vals else 0.0,
    }


def _finish_note(cur: dict, hop_dur: float) -> dict:
    midi = int(cur["midi"])
    return {
        "midi": midi,
        "name": _midi_to_name(midi),
        "freq_hz": round(float(np.median(cur["hs"])), 1),
        "start_s": round(float(cur["start"]), 3),
        "duration_s": round(float(cur["end"] - cur["start"]) + hop_dur, 3),
    }
