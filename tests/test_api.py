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


def _gen_bytes(seed=None):
    files = {"file": ("hum.wav", make_wav(), "audio/wav")}
    data = {"style": "hip-hop"}
    if seed is not None:
        data["seed"] = str(seed)
    body = client.post("/api/generate", files=files, data=data).json()
    name = body["audio_url"].rsplit("/", 1)[-1]
    try:
        return body["seed"], client.get(f"/api/audio/{name}").content
    finally:
        (GENERATED_DIR / name).unlink(missing_ok=True)


def test_same_seed_same_audio():
    s1, a = _gen_bytes(42)
    s2, b = _gen_bytes(42)
    assert s1 == s2 == 42
    assert a == b


def test_different_seeds_differ():
    _, a = _gen_bytes(1)
    _, b = _gen_bytes(2)
    assert a != b


def test_no_seed_assigns_one():
    seed, _ = _gen_bytes()
    assert isinstance(seed, int) and 0 <= seed < 2**31


def test_stems_export():
    files = {"file": ("hum.wav", make_wav(), "audio/wav")}
    body = client.post("/api/generate", files=files, data={"style": "pop", "stems": "true"}).json()
    assert set(body["stems"]) == {"drums", "bass", "pads"}
    names = [body["audio_url"].rsplit("/", 1)[-1]]
    try:
        for name, url in body["stems"].items():
            fname = url.rsplit("/", 1)[-1]
            names.append(fname)
            r = client.get(url)
            assert r.status_code == 200
            assert r.headers["content-type"] == "audio/wav"
            assert r.content[:4] == b"RIFF"
        assert body["stems"]["drums"] != body["stems"]["bass"]
    finally:
        for n in names:
            (GENERATED_DIR / n).unlink(missing_ok=True)


def test_no_stems_by_default():
    files = {"file": ("hum.wav", make_wav(), "audio/wav")}
    body = client.post("/api/generate", files=files, data={"style": "pop"}).json()
    assert "stems" not in body
    (GENERATED_DIR / body["audio_url"].rsplit("/", 1)[-1]).unlink(missing_ok=True)


def test_beat_is_not_a_clip():
    files = {"file": ("hum.wav", make_wav(), "audio/wav")}
    body = client.post("/api/generate", files=files, data={"style": "lo-fi"}).json()
    try:
        assert body["duration_s"] > 8  # 8-bar loop, never a seconds-long clip
    finally:
        (GENERATED_DIR / body["audio_url"].rsplit("/", 1)[-1]).unlink(missing_ok=True)
