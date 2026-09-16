import io
import wave

import numpy as np
import pytest

from backend.melody.extraction import analyze_melody


def make_wav(freqs=(440.0,), dur_each=0.5, sr=44100) -> bytes:
    y = np.concatenate(
        [0.5 * np.sin(2 * np.pi * f * np.arange(int(sr * dur_each)) / sr) for f in freqs]
    )
    pcm = (np.clip(y, -1, 1) * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def test_analyze_rejects_empty():
    with pytest.raises(ValueError):
        analyze_melody(b"")


def test_analyze_rejects_non_wav():
    with pytest.raises(ValueError, match="WAV"):
        analyze_melody(b"fake-bytes-not-wav")


def test_analyze_single_pitch():
    res = analyze_melody(make_wav((440.0,), 1.0))
    assert res["note_count"] >= 1
    assert abs(res["notes"][0]["freq_hz"] - 440.0) < 15.0
    assert res["notes"][0]["name"] == "A4"
    assert 60 <= res["tempo_bpm"] <= 180


def test_analyze_two_notes():
    res = analyze_melody(make_wav((440.0, 523.25), 0.6))
    assert res["note_count"] >= 2
    names = [n["name"] for n in res["notes"]]
    assert "A4" in names and "C5" in names
