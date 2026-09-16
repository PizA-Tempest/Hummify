"""HTTP API routes."""
from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from backend.generation.generator import SUPPORTED_STYLES, generate_beat
from backend.melody.extraction import analyze_melody

router = APIRouter()


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
