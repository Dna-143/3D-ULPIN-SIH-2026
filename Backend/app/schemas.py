"""Validated API contracts for Part 1 ingestion."""

from __future__ import annotations

import math
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ControlPoint(BaseModel):
    """A surveyed point and its trusted reference coordinate."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=100)
    observed: tuple[float, float]
    reference: tuple[float, float]

    @field_validator("observed", "reference")
    @classmethod
    def coordinates_must_be_finite(cls, value: tuple[float, float]) -> tuple[float, float]:
        if not all(math.isfinite(component) for component in value):
            raise ValueError("control-point coordinates must be finite")
        return value


class RansacOptions(BaseModel):
    """Limits for deterministic robust control-point fitting."""

    model_config = ConfigDict(extra="forbid")

    residual_threshold_m: float = Field(default=0.75, ge=0.01, le=100.0)
    max_trials: int = Field(default=512, ge=16, le=10_000)
    min_inlier_ratio: float = Field(default=0.60, ge=0.50, le=1.0)
    random_seed: int = 42


class IngestionRequest(BaseModel):
    """One non-persistent ingestion preview job."""

    model_config = ConfigDict(extra="forbid")

    dataset_name: str = Field(min_length=1, max_length=120)
    source_crs: str = Field(default="EPSG:4326", min_length=3, max_length=1_000)
    vertical_reference: str | None = Field(default=None, max_length=200)
    geojson: dict[str, Any]
    control_points: list[ControlPoint] = Field(default_factory=list, max_length=10_000)
    ransac: RansacOptions = Field(default_factory=RansacOptions)
    apply_control_alignment: bool = False

    @field_validator("dataset_name")
    @classmethod
    def dataset_name_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("dataset_name must not be blank")
        return cleaned

    @model_validator(mode="after")
    def validate_control_network(self) -> IngestionRequest:
        count = len(self.control_points)
        if 0 < count < 4:
            raise ValueError(
                "RANSAC needs at least four control points; provide none or four or more"
            )
        ids = [point.id for point in self.control_points]
        if len(ids) != len(set(ids)):
            raise ValueError("control-point IDs must be unique")
        if self.apply_control_alignment and count == 0:
            raise ValueError("apply_control_alignment requires control points")
        return self
