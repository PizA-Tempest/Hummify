# AGENTS.md — Hummify

> Stack (decided 2026-09-16): Python FastAPI backend + plain static frontend (no npm build, no `package.json`). Product vision lives in `README.md`.

## Commands
- Install: `pip install -r requirements.txt`
- Run API: `uvicorn backend.app:app --reload` (routes under `/api`: `GET /health`, `GET /styles`, `POST /analyze`, `POST /generate`, `GET /audio/{file}.wav`)
- Test: `python -m pytest tests -q`
- Serve frontend: open `frontend/index.html` directly, or `python -m http.server -d frontend 5500` (API must run on `127.0.0.1:8000` — URL is hardcoded as `API` in `frontend/app.js`)

## Architecture
- `backend/app.py` is the entrypoint; `backend/api/routes.py` owns HTTP layer.
- `backend/melody/extraction.py` (`analyze_melody`) is real: stdlib `wave` + `numpy` autocorrelation pitch track (80–1000 Hz) → note events + onset-autocorrelation tempo. WAV-only; non-WAV uploads are rejected 400. `backend/audio/processing.py` is still a stub — swap in real logic, keep signatures.
- Frontend sends WAV: `frontend/components/recorder.js` `blobToWav()` decodes the MediaRecorder blob via WebAudio and re-encodes 16-bit mono WAV; preview still uses the raw blob. `POST /generate` now renders a real 4-bar style loop to `generated/beat_*.wav` (served at `GET /api/audio/{file}.wav`, safe-name checked); frontend plays it in `#beat` + download link. Bass roots follow detected melody notes; tempo defaults to detection, else style preset. Optional `seed` form param pins the variation (ghost hits, bass octaves, noise); omitted → random seed returned in the response. Frontend Regenerate reuses the converted WAV with a fresh seed and keeps a version list. `stems=true` form param also writes `beat_*_drums/bass/pads.wav` and returns a `stems` URL map; off by default.
- Suno-lite compose: `POST /api/song` (prompt + optional hum WAV) → full structured song via `backend/generation/song.py` (`compose_song`: intro/verse/chorus arc, prompt-seeded progression, vocal-lead synth) + rule-based lyrics via `backend/generation/lyrics.py` (`parse_prompt`/`generate_lyrics`). `song_length=short` (6 bars) for previews/tests, `full` (36 bars) by default. Frontend compose card posts prompt + shared style/tempo/mood, shows title/structure/lyrics in `#song`/`#lyrics`.
- Real model code/weights go in `models/music_model/`; never commit large binaries (see its README).
- `generated/` holds output audio; `*.wav|mp3|ogg` are gitignored except `.gitkeep`.
- `frontend/`: `index.html` + `app.js` + `styles.css`; reusable JS in `frontend/components/` (e.g. `recorder.js`); `frontend/pages/` is placeholder-only.
