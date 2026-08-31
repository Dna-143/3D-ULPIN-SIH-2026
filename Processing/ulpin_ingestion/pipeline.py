"""Orchestration for the Part 1 ingestion and transformation pipeline."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import numpy as np
from pyproj.exceptions import ProjError

from Processing.ulpin_ingestion.errors import IngestionError
from Processing.ulpin_ingestion.geometry import validate_feature_collection
from Processing.ulpin_ingestion.projection import (
    build_local_tm,
    transform_feature_collection,
)
from Processing.ulpin_ingestion.ransac import RansacResult, run_ransac


def _canonical_sha256(value: dict[str, Any]) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _ransac_report(
    result: RansacResult, control_points: list[dict[str, Any]], threshold_m: float
) -> dict[str, Any]:
    inlier_ids = [
        point["id"]
        for point, is_inlier in zip(control_points, result.inlier_mask, strict=True)
        if is_inlier
    ]
    outlier_ids = [
        point["id"]
        for point, is_inlier in zip(control_points, result.inlier_mask, strict=True)
        if not is_inlier
    ]
    residuals = [
        {
            "id": point["id"],
            "residual_m": float(residual),
            "classification": "inlier" if is_inlier else "outlier",
        }
        for point, residual, is_inlier in zip(
            control_points, result.residuals_m, result.inlier_mask, strict=True
        )
    ]
    inlier_residuals = result.residuals_m[result.inlier_mask]
    return {
        "status": "accepted_with_outliers" if outlier_ids else "accepted",
        "threshold_m": threshold_m,
        "trials": result.trials,
        "inlier_count": len(inlier_ids),
        "outlier_count": len(outlier_ids),
        "inlier_ids": inlier_ids,
        "outlier_ids": outlier_ids,
        "rmse_inliers_m": float(np.sqrt(np.mean(inlier_residuals**2))),
        "max_inlier_residual_m": float(inlier_residuals.max()),
        "model": {
            "type": "2D similarity",
            "scale": result.model.scale,
            "rotation_degrees": result.model.rotation_degrees,
            "translation_m": [result.model.translate_x, result.model.translate_y],
        },
        "residuals": residuals,
    }


def process_ingestion(
    *,
    dataset_name: str,
    source_crs: str,
    geojson: dict[str, Any],
    vertical_reference: str | None = None,
    control_points: list[dict[str, Any]] | None = None,
    ransac_options: dict[str, Any] | None = None,
    apply_control_alignment: bool = False,
) -> dict[str, Any]:
    controls = control_points or []
    options = {
        "residual_threshold_m": 0.75,
        "max_trials": 512,
        "min_inlier_ratio": 0.60,
        "random_seed": 42,
        **(ransac_options or {}),
    }

    validation = validate_feature_collection(geojson)
    projection = build_local_tm(validation.geometries, source_crs)

    ransac_result: RansacResult | None = None
    control_report: dict[str, Any] | None = None
    alignment = None
    if controls:
        try:
            observed = np.array(
                [
                    projection.transformer.transform(*point["observed"], errcheck=True)
                    for point in controls
                ],
                dtype=float,
            )
            reference = np.array(
                [
                    projection.transformer.transform(*point["reference"], errcheck=True)
                    for point in controls
                ],
                dtype=float,
            )
        except ProjError as exc:
            raise IngestionError(
                "INVALID_CONTROL_POINT_COORDINATE",
                "a survey control point could not be projected",
                details={"reason": str(exc)},
            ) from exc
        ransac_result = run_ransac(observed, reference, **options)
        control_report = _ransac_report(ransac_result, controls, options["residual_threshold_m"])
        if apply_control_alignment:
            alignment = ransac_result.model.apply_one

    transformed = transform_feature_collection(
        validation.collection,
        projection.transformer,
        alignment=alignment,
    )

    warnings: list[dict[str, Any]] = []
    if validation.assigned_feature_ids:
        warnings.append(
            {
                "code": "TEMPORARY_FEATURE_IDS_ASSIGNED",
                "message": "features without IDs received temporary source IDs",
                "feature_ids": validation.assigned_feature_ids,
            }
        )
    if validation.three_dimensional_feature_count == 0:
        warnings.append(
            {
                "code": "NO_Z_COORDINATES",
                "message": "input is 2D; vertical parcels require heights in a later stage",
            }
        )
    elif validation.two_dimensional_feature_count:
        warnings.append(
            {
                "code": "MIXED_FEATURE_DIMENSIONS",
                "message": "dataset contains both 2D and 3D features",
            }
        )
    if validation.three_dimensional_feature_count and not vertical_reference:
        warnings.append(
            {
                "code": "VERTICAL_REFERENCE_UNSPECIFIED",
                "message": "Z values were preserved, but their vertical datum is unknown",
            }
        )
    if control_report and control_report["outlier_ids"]:
        warnings.append(
            {
                "code": "CONTROL_POINT_OUTLIERS_EXCLUDED",
                "message": "RANSAC excluded suspect survey control points from calibration",
                "control_point_ids": control_report["outlier_ids"],
            }
        )

    return {
        "dataset_name": dataset_name,
        "status": "accepted_with_warnings" if warnings else "accepted",
        "source_sha256": _canonical_sha256(geojson),
        "projection": projection.metadata(),
        "vertical_handling": {
            "operation": "preserved_without_vertical_transformation",
            "reference": vertical_reference,
            "z_min": validation.z_min,
            "z_max": validation.z_max,
        },
        "quality": {
            "feature_count": validation.feature_count,
            "coordinate_count": validation.coordinate_count,
            "three_dimensional_feature_count": validation.three_dimensional_feature_count,
            "two_dimensional_feature_count": validation.two_dimensional_feature_count,
            "invalid_feature_count": 0,
            "warning_count": len(warnings),
            "warnings": warnings,
        },
        "control_alignment_applied": bool(alignment),
        "control_network": control_report,
        "transformed_geojson": transformed,
    }
