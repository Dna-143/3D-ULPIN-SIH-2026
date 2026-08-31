"""HTTP entry point for the Part 1 ingestion proof."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from Backend.app.schemas import IngestionRequest
from Processing.ulpin_ingestion.errors import IngestionError
from Processing.ulpin_ingestion.pipeline import process_ingestion

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIR = PROJECT_ROOT / "Frontend"
SAMPLE_PATH = PROJECT_ROOT / "samples" / "pune_ingestion_request.json"

app = FastAPI(
    title="3D ULPIN Ingestion API",
    version="0.1.0",
    description=(
        "Part 1: validated geospatial ingestion, local Transverse Mercator projection, "
        "and robust survey-control outlier detection."
    ),
)


@app.exception_handler(IngestionError)
def handle_ingestion_error(_: Request, exc: IngestionError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": exc.as_dict()})


@app.get("/api/v1/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "part1-ingestion", "version": app.version}


@app.get("/api/v1/samples/pune")
def pune_sample() -> dict:
    return json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))


@app.post("/api/v1/ingestions/preview")
def preview_ingestion(request: IngestionRequest) -> dict:
    return process_ingestion(
        dataset_name=request.dataset_name,
        source_crs=request.source_crs,
        vertical_reference=request.vertical_reference,
        geojson=request.geojson,
        control_points=[point.model_dump() for point in request.control_points],
        ransac_options=request.ransac.model_dump(),
        apply_control_alignment=request.apply_control_alignment,
    )


@app.get("/", include_in_schema=False)
def demo_page() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/assets", StaticFiles(directory=FRONTEND_DIR), name="assets")
