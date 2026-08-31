"""Dynamic, dataset-centred Transverse Mercator projection."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pyproj import CRS, Proj, Transformer
from pyproj.exceptions import CRSError, ProjError
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform as shapely_transform
from shapely.ops import unary_union

from Processing.ulpin_ingestion.errors import IngestionError
from Processing.ulpin_ingestion.geometry import GEOMETRY_DEPTH, iter_geometry_positions

MAX_LONGITUDE_SPAN_DEGREES = 6.0
MAX_LATITUDE_SPAN_DEGREES = 6.0


@dataclass(frozen=True)
class ProjectionContext:
    source_crs: CRS
    target_crs: CRS
    transformer: Transformer
    proj_string: str
    centroid_longitude: float
    centroid_latitude: float
    longitude_span_degrees: float
    latitude_span_degrees: float
    max_scale_error_ppm: float
    max_angular_distortion_degrees: float

    def metadata(self) -> dict[str, Any]:
        source_authority = self.source_crs.to_authority()
        return {
            "source": (
                f"{source_authority[0]}:{source_authority[1]}"
                if source_authority
                else self.source_crs.name
            ),
            "target_name": "ULPIN local centroid Transverse Mercator",
            "target_proj": self.proj_string,
            "target_wkt2_2019": self.target_crs.to_wkt(version="WKT2_2019"),
            "origin": {
                "longitude": self.centroid_longitude,
                "latitude": self.centroid_latitude,
            },
            "extent_degrees": {
                "longitude": self.longitude_span_degrees,
                "latitude": self.latitude_span_degrees,
            },
            "distortion_estimate": {
                "max_scale_error_ppm": self.max_scale_error_ppm,
                "max_angular_distortion_degrees": self.max_angular_distortion_degrees,
            },
            "axis_order": ["X easting (metre)", "Y northing (metre)", "Z preserved"],
        }


def build_local_tm(geometries: list[BaseGeometry], source_crs_input: str) -> ProjectionContext:
    try:
        source_crs = CRS.from_user_input(source_crs_input)
    except CRSError as exc:
        raise IngestionError(
            "INVALID_CRS",
            "source_crs is not recognized by PROJ",
            details={"source_crs": source_crs_input, "reason": str(exc)},
        ) from exc

    if not (source_crs.is_geographic or source_crs.is_projected):
        raise IngestionError(
            "UNSUPPORTED_CRS",
            "Part 1 requires a geographic or projected horizontal source CRS",
            details={"source_crs": source_crs_input, "type": source_crs.type_name},
        )

    wgs84 = CRS.from_epsg(4326)
    try:
        to_wgs84 = Transformer.from_crs(
            source_crs,
            wgs84,
            always_xy=True,
            allow_ballpark=False,
            only_best=True,
        )
        wgs84_geometries = [
            shapely_transform(to_wgs84.transform, geometry) for geometry in geometries
        ]
    except ProjError as exc:
        raise IngestionError(
            "CRS_TRANSFORM_UNAVAILABLE",
            "PROJ could not perform a non-ballpark transformation to WGS 84",
            details={"source_crs": source_crs_input, "reason": str(exc)},
        ) from exc

    footprint = unary_union(wgs84_geometries)
    min_lon, min_lat, max_lon, max_lat = footprint.bounds
    bounds = (min_lon, min_lat, max_lon, max_lat)
    if not all(math.isfinite(value) for value in bounds):
        raise IngestionError("INVALID_EXTENT", "dataset produced a non-finite WGS 84 extent")
    if min_lon < -180.0 or max_lon > 180.0 or min_lat < -90.0 or max_lat > 90.0:
        raise IngestionError(
            "INVALID_GEOGRAPHIC_COORDINATES",
            "coordinates fall outside the valid WGS 84 longitude/latitude range",
            details={"wgs84_bounds": list(bounds)},
        )

    longitude_span = max_lon - min_lon
    latitude_span = max_lat - min_lat
    if longitude_span > MAX_LONGITUDE_SPAN_DEGREES or latitude_span > MAX_LATITUDE_SPAN_DEGREES:
        raise IngestionError(
            "DATASET_TOO_WIDE_FOR_LOCAL_TM",
            "dataset must be partitioned before using a local centroid projection",
            details={
                "longitude_span_degrees": longitude_span,
                "latitude_span_degrees": latitude_span,
                "maximum_each_degrees": MAX_LONGITUDE_SPAN_DEGREES,
            },
        )

    centroid = footprint.centroid
    lon_0 = float(centroid.x)
    lat_0 = float(centroid.y)
    if abs(lat_0) >= 84.0:
        raise IngestionError(
            "POLAR_DATASET_UNSUPPORTED",
            "local Transverse Mercator is not selected automatically for polar data",
            details={"centroid_latitude": lat_0},
        )

    proj_string = (
        f"+proj=tmerc +lat_0={lat_0:.12f} +lon_0={lon_0:.12f} "
        "+k_0=1 +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs +type=crs"
    )
    target_crs = CRS.from_proj4(proj_string)
    transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)

    projection = Proj(target_crs)
    sample_points = [
        (lon_0, lat_0),
        (min_lon, min_lat),
        (min_lon, max_lat),
        (max_lon, min_lat),
        (max_lon, max_lat),
    ]
    scale_errors: list[float] = []
    angular_distortions: list[float] = []
    for longitude, latitude in sample_points:
        factors = projection.get_factors(longitude, latitude)
        scale_errors.extend(
            [abs(factors.meridional_scale - 1.0), abs(factors.parallel_scale - 1.0)]
        )
        angular_distortions.append(abs(factors.angular_distortion))

    return ProjectionContext(
        source_crs=source_crs,
        target_crs=target_crs,
        transformer=transformer,
        proj_string=proj_string,
        centroid_longitude=lon_0,
        centroid_latitude=lat_0,
        longitude_span_degrees=longitude_span,
        latitude_span_degrees=latitude_span,
        max_scale_error_ppm=max(scale_errors) * 1_000_000.0,
        max_angular_distortion_degrees=max(angular_distortions),
    )


def _transform_nested(
    value: Any,
    depth: int,
    transformer: Transformer,
    alignment: Callable[[float, float], tuple[float, float]] | None,
) -> Any:
    if depth == 0:
        x, y = transformer.transform(value[0], value[1], errcheck=True)
        if alignment is not None:
            x, y = alignment(float(x), float(y))
        transformed = [float(x), float(y)]
        if len(value) == 3:
            transformed.append(float(value[2]))
        return transformed
    return [_transform_nested(child, depth - 1, transformer, alignment) for child in value]


def transform_feature_collection(
    collection: dict[str, Any],
    transformer: Transformer,
    alignment: Callable[[float, float], tuple[float, float]] | None = None,
) -> dict[str, Any]:
    transformed = {key: value for key, value in collection.items() if key != "bbox"}
    transformed_features: list[dict[str, Any]] = []
    try:
        for feature in collection["features"]:
            output_feature = {key: value for key, value in feature.items() if key != "bbox"}
            geometry = dict(feature["geometry"])
            geometry_type = geometry["type"]
            geometry["coordinates"] = _transform_nested(
                geometry["coordinates"],
                GEOMETRY_DEPTH[geometry_type],
                transformer,
                alignment,
            )
            output_feature["geometry"] = geometry
            transformed_features.append(output_feature)
    except ProjError as exc:
        raise IngestionError(
            "COORDINATE_TRANSFORM_FAILED",
            "one or more coordinates could not be projected",
            details={"reason": str(exc)},
        ) from exc

    transformed["features"] = transformed_features
    transformed["bbox"] = feature_collection_bbox(transformed)
    return transformed


def feature_collection_bbox(collection: dict[str, Any]) -> list[float]:
    positions = [
        position
        for feature in collection["features"]
        for position in iter_geometry_positions(feature["geometry"])
    ]
    xs = [position[0] for position in positions]
    ys = [position[1] for position in positions]
    zs = [position[2] for position in positions if len(position) == 3]
    if zs and len(zs) == len(positions):
        return [min(xs), min(ys), min(zs), max(xs), max(ys), max(zs)]
    return [min(xs), min(ys), max(xs), max(ys)]
