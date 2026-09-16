from fastapi.testclient import TestClient

from backend.app import app

client = TestClient(app)


def test_health():
    assert client.get("/api/health").json() == {"status": "ok"}


def test_generate_rejects_bad_style():
    files = {"file": ("hum.webm", b"fake-audio", "audio/webm")}
    data = {"style": "nope"}
    r = client.post("/api/generate", files=files, data=data)
    assert r.status_code == 400
