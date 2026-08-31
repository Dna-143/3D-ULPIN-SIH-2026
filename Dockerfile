# Minimus is shutting down reg.mini.dev on 2026-10-22.
# Keep this selected-plugin build for the SIH prototype, but migrate the base before that date.
FROM reg.mini.dev/python:3.13.15-dev AS build

USER root
WORKDIR /build

COPY pyproject.toml README.md ./
COPY Backend ./Backend
COPY Processing ./Processing

RUN python -m venv /build/venv \
    && /build/venv/bin/pip install --no-cache-dir .

FROM reg.mini.dev/python:3.13.15

WORKDIR /app

COPY --from=build /build/venv /app/venv
COPY Backend ./Backend
COPY Processing ./Processing
COPY Frontend ./Frontend
COPY samples ./samples

EXPOSE 8000

CMD ["/app/venv/bin/python", "-m", "uvicorn", "Backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
