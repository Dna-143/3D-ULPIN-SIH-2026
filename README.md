# 3D ULPIN — SIH 2026

Working prototype for a **3D ULPIN Generation and Vertical Property Mapping System**.

## Implemented: Part 1

The first vertical slice accepts cadastral GeoJSON, validates every geometry, derives a
dataset-centred ellipsoidal Transverse Mercator projection, converts horizontal coordinates
to metres, preserves Z, and uses RANSAC to exclude mistyped survey-control points.

```mermaid
flowchart LR
    A["GeoJSON + CRS"] --> B["Strict validation"]
    B --> C["Centroid local TM"]
    C --> D["RANSAC controls"]
    D --> E["Projected 3D data + QA report"]
```

### Run locally

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
uvicorn Backend.app.main:app --reload
```

Open `http://127.0.0.1:8000`, select **Load Pune demo**, then **Run Part 1**. API docs are at
`http://127.0.0.1:8000/docs`.

### Test

```bash
pytest
ruff check .
```

Technical decisions, the API contract, and judge-demo notes are in
[`Docs/PART1_INGESTION.md`](Docs/PART1_INGESTION.md).
