from fastapi.testclient import TestClient

from backend.app import app
from backend.generation.generator import GENERATED_DIR
from backend.generation.lyrics import generate_lyrics, parse_prompt

client = TestClient(app)


def _cleanup(*names):
    for n in names:
        (GENERATED_DIR / n).unlink(missing_ok=True)


def test_parse_prompt_detects_style_and_mood():
    hints = parse_prompt("sad edm night drive, fast club energy")
    assert hints["style"] == "edm"
    assert hints["mood"] in ("dark", "energetic", "driving")
    assert hints["tempo"] in (128, 130)


def test_lyrics_deterministic():
    a = generate_lyrics("midnight rain lo-fi", "dark", "lo-fi", 7)
    b = generate_lyrics("midnight rain lo-fi", "dark", "lo-fi", 7)
    assert a == b
    assert "[Verse]" in a["text"] and "[Chorus]" in a["text"] and "[Bridge]" in a["text"]
    assert a["title"]


def test_song_short_renders_with_vocals_and_stems():
    r = client.post("/api/song", data={
        "prompt": "sad lo-fi midnight rain", "song_length": "short",
        "stems": "true", "vocals": "true", "seed": "11",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["audio_url"].startswith("/api/audio/song_")
    assert body["total_bars"] == 6
    assert [s["name"] for s in body["structure"]] == ["intro", "verse", "chorus", "outro"]
    assert "vocals" in body["tracks"]
    assert set(body["stems"]) == {"drums", "bass", "pads", "lead", "vocals"}
    assert "midnight" in body["lyrics"]["text"].lower() or "rain" in body["lyrics"]["text"].lower() or body["lyrics"]["title"]
    names = [body["audio_url"].rsplit("/", 1)[-1]] + [u.rsplit("/", 1)[-1] for u in body["stems"].values()]
    try:
        audio = client.get(body["audio_url"])
        assert audio.status_code == 200 and audio.content[:4] == b"RIFF"
    finally:
        _cleanup(*names)


def test_song_no_vocals():
    r = client.post("/api/song", data={"prompt": "happy pop summer", "song_length": "short", "vocals": "false"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "vocals" not in body["tracks"]
    _cleanup(body["audio_url"].rsplit("/", 1)[-1])


def test_song_same_seed_same_audio():
    def _get(seed):
        b = client.post("/api/song", data={
            "prompt": "neon highway drive", "song_length": "short", "seed": str(seed)}).json()
        name = b["audio_url"].rsplit("/", 1)[-1]
        try:
            return b["seed"], client.get(b["audio_url"]).content
        finally:
            _cleanup(name)
    s1, a = _get(42)
    s2, c = _get(42)
    assert s1 == s2 == 42
    assert a == c


def test_song_rejects_empty_with_no_hum():
    r = client.post("/api/song", data={"prompt": "", "song_length": "short"})
    assert r.status_code == 400


def test_song_full_is_long_with_bridge_and_finale():
    r = client.post("/api/song", data={
        "prompt": "sad lo-fi midnight rain", "song_length": "full", "seed": "3"})
    assert r.status_code == 200, r.text
    body = r.json()
    try:
        assert body["total_bars"] == 48
        assert [s["name"] for s in body["structure"]] == [
            "intro", "verse", "chorus", "verse", "chorus", "bridge", "chorus", "outro"]
        assert body["duration_s"] > 60  # a real full-length song, never a seconds-long clip
        assert "lead" in body["tracks"] and "vocals" in body["tracks"]
    finally:
        _cleanup(body["audio_url"].rsplit("/", 1)[-1])


def test_song_short_is_not_a_clip():
    r = client.post("/api/song", data={
        "prompt": "happy pop summer", "song_length": "short", "seed": "5"})
    assert r.status_code == 200, r.text
    body = r.json()
    try:
        assert body["duration_s"] > 8
    finally:
        _cleanup(body["audio_url"].rsplit("/", 1)[-1])
