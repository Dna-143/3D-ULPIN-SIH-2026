"""Strict GeoJSON structure and legal-geometry validation."""

from __future__ import annotations

import copy
import math
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any

from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry
from shapely.validation import explain_validity

from Processing.ulpin_ingestion.errors import IngestionError

MAX_FEATURES = 10_000
MAX_COORDINATES = 1_000_000

GEOMETRY_DEPTH = {
    "Point": 0,
    "MultiPoint": 1,
    "LineString": 1,
    "MultiLineString": 2,
    "Polygon": 2,
    "MultiPolygon": 3,
}


@dataclass(frozen=True)
class ValidationResult:
    collection: dict[str, Any]
    geometries: list[BaseGeometry]
    feature_count: int
    coordinate_count: int
    three_dimensional_feature_count: int
    two_dimensional_feature_count: int
    z_min: float | None
    z_max: float | None
    assigned_feature_ids: list[str]


def _fail(message: str, *, path: str, **details: Any) -> None:
    raise IngestionError(
        "INVALID_GEOJSON",
        message,
        details={"path": path, **details},
    )


def _walk_nested_positions(value: Any, depth: int, path: str) -> Iterator[list[float]]:
    if depth == 0:
        if not isinstance(value, (list, tuple)) or len(value) not in (2, 3):
            _fail("each coordinate must contain exactly X,Y or X,Y,Z", path=path)
        position: list[float] = []
        for index, component in enumerate(value):
            if isinstance(component, bool) or not isinstance(component, (int, float)):
                _fail("coordinate components must be numbers", path=f"{path}[{index}]")
            number = float(component)
            if not math.isfinite(number):
                _fail("coordinate components must be finite", path=f"{path}[{index}]")
            position.append(number)
        yield position
        return

    if not isinstance(value, (list, tuple)) or not value:
        _fail("coordinate array must be a non-empty array", path=path)
    for index, child in enumerate(value):
        yield from _walk_nested_positions(child, depth - 1, f"{path}[{index}]")


def iter_geometry_positions(geometry: dict[str, Any]) -> Iterator[list[float]]:
    geometry_type = geometry.get("type")
    if geometry_type not in GEOMETRY_DEPTH:
        raise IngestionError(
            "UNSUPPORTED_GEOMETRY",
            "Only Point, MultiPoint, LineString, MultiLineString, Polygon and "
            "MultiPolygon are accepted in Part 1",
            details={"geometry_type": geometry_type},
        )
    if "coordinates" not in geometry:
        _fail("geometry is missing coordinates", path="geometry.coordinates")
    yield from _walk_nested_positions(
        geometry["coordinates"], GEOMETRY_DEPTH[geometry_type], "geometry.coordinates"
    )


def _validate_line(coordinates: Sequence[Any], path: str) -> None:
    if len(coordinates) < 2:
        _fail("a line must contain at least two positions", path=path)


def _validate_ring(ring: Sequence[Any], path: str) -> None:
    if len(ring) < 4:
        _fail("a polygon ring must contain at least four positions", path=path)
    if list(ring[0][:2]) != list(ring[-1][:2]):
        _fail("polygon rings must be explicitly closed", path=path)


def _validate_geometry_structure(geometry: dict[str, Any], path: str) -> None:
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type == "LineString":
        _validate_line(coordinates, f"{path}.coordinates")
    elif geometry_type == "MultiLineString":
        for index, line in enumerate(coordinates):
            _validate_line(line, f"{path}.coordinates[{index}]")
    elif geometry_type == "Polygon":
        for index, ring in enumerate(coordinates):
            _validate_ring(ring, f"{path}.coordinates[{index}]")
    elif geometry_type == "MultiPolygon":
        for polygon_index, polygon in enumerate(coordinates):
            for ring_index, ring in enumerate(polygon):
                _validate_ring(
                    ring,
                    f"{path}.coordinates[{polygon_index}][{ring_index}]",
                )


def validate_feature_collection(geojson: dict[str, Any]) -> ValidationResult:
    if not isinstance(geojson, dict) or geojson.get("type") != "FeatureCollection":
        _fail("top-level object must be a GeoJSON FeatureCollection", path="$")

    features = geojson.get("features")
    if not isinstance(features, list) or not features:
        _fail("FeatureCollection.features must be a non-empty array", path="$.features")
    if len(features) > MAX_FEATURES:
        _fail(
            "dataset exceeds the Part 1 feature limit",
            path="$.features",
            maximum=MAX_FEATURES,
            received=len(features),
        )

    normalized = copy.deepcopy(geojson)
    normalized_features: list[dict[str, Any]] = []
    geometries: list[BaseGeometry] = []
    seen_ids: set[str] = set()
    assigned_ids: list[str] = []
    coordinate_count = 0
    feature_3d = 0
    feature_2d = 0
    z_values: list[float] = []

    for index, raw_feature in enumerate(features):
        feature_path = f"$.features[{index}]"
        if not isinstance(raw_feature, dict) or raw_feature.get("type") != "Feature":
            _fail("each item must be a GeoJSON Feature", path=feature_path)

        feature = copy.deepcopy(raw_feature)
        properties = feature.get("properties")
        if properties is None:
            feature["properties"] = {}
        elif not isinstance(properties, dict):
            _fail("Feature.properties must be an object or null", path=f"{feature_path}.properties")

        raw_id = feature.get("id")
        if raw_id is None:
            feature_id = f"source-feature-{index + 1:06d}"
            feature["id"] = feature_id
            assigned_ids.append(feature_id)
        elif isinstance(raw_id, (str, int)) and not isinstance(raw_id, bool):
            feature_id = str(raw_id)
        else:
            _fail("Feature.id must be a string or integer", path=f"{feature_path}.id")
        if feature_id in seen_ids:
            _fail("Feature.id values must be unique", path=f"{feature_path}.id", id=feature_id)
        seen_ids.add(feature_id)

        geometry = feature.get("geometry")
        if not isinstance(geometry, dict):
            _fail(
                "Feature.geometry must be a non-null geometry object",
                path=f"{feature_path}.geometry",
            )

        positions = list(iter_geometry_positions(geometry))
        _validate_geometry_structure(geometry, f"{feature_path}.geometry")
        coordinate_count += len(positions)
        if coordinate_count > MAX_COORDINATES:
            _fail(
                "dataset exceeds the Part 1 coordinate limit",
                path=f"{feature_path}.geometry.coordinates",
                maximum=MAX_COORDINATES,
            )

        has_z = any(len(position) == 3 for position in positions)
        has_2d = any(len(position) == 2 for position in positions)
        if has_z and has_2d:
            _fail(
                "a feature cannot mix 2D and 3D positions",
                path=f"{feature_path}.geometry.coordinates",
            )
        if has_z:
            feature_3d += 1
            z_values.extend(position[2] for position in positions)
        else:
            feature_2d += 1

        try:
            parsed = shape(geometry)
        except (TypeError, ValueError) as exc:
            _fail("geometry could not be parsed", path=f"{feature_path}.geometry", reason=str(exc))
        if parsed.is_empty:
            _fail("empty geometries are not accepted", path=f"{feature_path}.geometry")
        if not parsed.is_valid:
            _fail(
                "geometry is topologically invalid and was not auto-repaired",
                path=f"{feature_path}.geometry",
                reason=explain_validity(parsed),
            )
        if parsed.geom_type in {"LineString", "MultiLineString"} and parsed.length == 0:
            _fail("line geometry has zero length", path=f"{feature_path}.geometry")
        if parsed.geom_type in {"Polygon", "MultiPolygon"} and parsed.area == 0:
            _fail("polygon geometry has zero area", path=f"{feature_path}.geometry")

        normalized_features.append(feature)
        geometries.append(parsed)

    normalized["features"] = normalized_features
    return ValidationResult(
        collection=normalized,
        geometries=geometries,
        feature_count=len(normalized_features),
        coordinate_count=coordinate_count,
        three_dimensional_feature_count=feature_3d,
        two_dimensional_feature_count=feature_2d,
        z_min=min(z_values) if z_values else None,
        z_max=max(z_values) if z_values else None,
        assigned_feature_ids=assigned_ids,
    )
