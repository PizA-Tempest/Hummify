# AGENTS.md — Hummify

> Stack (decided 2026-09-16): Python FastAPI backend + plain static frontend (no npm build, no `package.json`). Product vision lives in `README.md`.

## Commands
- Install: `pip install -r requirements.txt`
- Run API: `uvicorn backend.app:app --reload` (routes under `/api`: `GET /health`, `GET /styles`, `POST /analyze`, `POST /generate`)
- Test: `python -m pytest tests -q`
- Serve frontend: open `frontend/index.html` directly, or `python -m http.server -d frontend 5500` (API must run on `127.0.0.1:8000` — URL is hardcoded as `API` in `frontend/app.js`)

## Architecture
- `backend/app.py` is the entrypoint; `backend/api/routes.py` owns HTTP layer.
- `backend/melody/extraction.py` (`analyze_melody`) is real: stdlib `wave` + `numpy` autocorrelation pitch track (80–1000 Hz) → note events + onset-autocorrelation tempo. WAV-only; non-WAV uploads are rejected 400. `backend/audio/processing.py`, `backend/generation/generator.py` (`SUPPORTED_STYLES`, `generate_beat`) are still stubs — swap in real logic, keep signatures.
- Frontend sends WAV: `frontend/components/recorder.js` `blobToWav()` decodes the MediaRecorder blob via WebAudio and re-encodes 16-bit mono WAV; preview still uses the raw blob.
- Real model code/weights go in `models/music_model/`; never commit large binaries (see its README).
- `generated/` holds output audio; `*.wav|mp3|ogg` are gitignored except `.gitkeep`.
- `frontend/`: `index.html` + `app.js` + `styles.css`; reusable JS in `frontend/components/` (e.g. `recorder.js`); `frontend/pages/` is placeholder-only.
