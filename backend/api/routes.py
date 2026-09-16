"""HTTP API routes."""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from backend.generation.generator import GENERATED_DIR, SUPPORTED_STYLES, generate_beat
from backend.melody.extraction import analyze_melody

router = APIRouter()
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*\.wav$")


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/styles")
def styles() -> dict:
    return {"styles": SUPPORTED_STYLES}


@router.post("/analyze")
async def analyze(file: UploadFile = File(...)) -> dict:
    data = await file.read()
    try:
        return analyze_melody(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/generate")
async def generate(
    file: UploadFile = File(...),
    style: str = Form("lo-fi"),
    tempo: int | None = Form(default=None),
    mood: str = Form(default="chill"),
) -> dict:
    data = await file.read()
    try:
        melody = analyze_melody(data)
        return generate_beat(melody, style, tempo, mood)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/audio/{filename}")
def audio(filename: str):
    if not _SAFE_NAME.match(filename):
        raise HTTPException(status_code=400, detail="invalid filename")
    path: Path = GENERATED_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(path, media_type="audio/wav", filename=filename)
