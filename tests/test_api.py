import io
import wave

import numpy as np
from fastapi.testclient import TestClient

from backend.app import app
from backend.generation.generator import GENERATED_DIR

client = TestClient(app)


def make_wav(freq=440.0, dur=1.0, sr=44100) -> bytes:
    t = np.arange(int(sr * dur)) / sr
    y = (0.5 * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    pcm = (y * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def test_health():
    assert client.get("/api/health").json() == {"status": "ok"}


def test_generate_rejects_bad_style():
    files = {"file": ("hum.wav", make_wav(), "audio/wav")}
    data = {"style": "nope"}
    r = client.post("/api/generate", files=files, data=data)
    assert r.status_code == 400


def test_generate_renders_audio():
    files = {"file": ("hum.wav", make_wav(), "audio/wav")}
    r = client.post("/api/generate", files=files, data={"style": "lo-fi"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["audio_url"].startswith("/api/audio/beat_lo-fi_")
    assert (GENERATED_DIR / body["audio_url"].rsplit("/", 1)[-1]).is_file()
    # cleanup rendered artifact
    (GENERATED_DIR / body["audio_url"].rsplit("/", 1)[-1]).unlink()


def test_audio_serves_wav_and_rejects_traversal():
    files = {"file": ("hum.wav", make_wav(), "audio/wav")}
    name = client.post("/api/generate", files=files, data={"style": "edm"}).json()["audio_url"].rsplit("/", 1)[-1]
    try:
        r = client.get(f"/api/audio/{name}")
        assert r.status_code == 200
        assert r.headers["content-type"] == "audio/wav"
        assert r.content[:4] == b"RIFF"
        assert client.get("/api/audio/../app.py").status_code in (400, 404)
        assert client.get("/api/audio/nope.wav").status_code == 404
    finally:
        (GENERATED_DIR / name).unlink(missing_ok=True)
