import copy

import pytest

from Processing.ulpin_ingestion.errors import IngestionError
from Processing.ulpin_ingestion.pipeline import process_ingestion


def _run(request: dict) -> dict:
    return process_ingestion(
        dataset_name=request["dataset_name"],
        source_crs=request["source_crs"],
        vertical_reference=request.get("vertical_reference"),
        geojson=request["geojson"],
        control_points=request.get("control_points"),
        ransac_options=request.get("ransac"),
        apply_control_alignment=request.get("apply_control_alignment", False),
    )


def test_pune_sample_projects_to_metres_and_preserves_z(pune_request: dict) -> None:
    result = _run(pune_request)

    assert result["quality"]["feature_count"] == 2
    assert result["quality"]["three_dimensional_feature_count"] == 2
    assert result["control_network"]["outlier_ids"] == ["cp-typo"]
    assert result["control_network"]["inlier_count"] == 4
    assert result["projection"]["origin"]["longitude"] == pytest.approx(73.85683, abs=0.00002)
    assert result["projection"]["origin"]["latitude"] == pytest.approx(18.52048, abs=0.00002)
    assert result["projection"]["distortion_estimate"]["max_scale_error_ppm"] < 0.1

    first_position = result["transformed_geojson"]["features"][0]["geometry"]["coordinates"][0][0]
    assert abs(first_position[0]) < 20
    assert abs(first_position[1]) < 20
    assert first_position[2] == 560.20
    assert len(result["transformed_geojson"]["bbox"]) == 6


def test_invalid_legal_polygon_is_rejected_not_repaired(pune_request: dict) -> None:
    request = copy.deepcopy(pune_request)
    request["control_points"] = []
    request["geojson"]["features"][0]["geometry"]["coordinates"] = [
        [
            [73.8567, 18.5204, 560.0],
            [73.8569, 18.5206, 560.0],
            [73.8569, 18.5204, 560.0],
            [73.8567, 18.5206, 560.0],
            [73.8567, 18.5204, 560.0],
        ]
    ]

    with pytest.raises(IngestionError) as captured:
        _run(request)

    assert captured.value.code == "INVALID_GEOJSON"
    assert "not auto-repaired" in captured.value.message


def test_large_extent_must_be_partitioned() -> None:
    request = {
        "dataset_name": "too wide",
        "source_crs": "EPSG:4326",
        "geojson": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "id": "wide-line",
                    "properties": {},
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[70.0, 18.0], [77.0, 18.0]],
                    },
                }
            ],
        },
    }

    with pytest.raises(IngestionError) as captured:
        _run(request)

    assert captured.value.code == "DATASET_TOO_WIDE_FOR_LOCAL_TM"


def test_out_of_range_wgs84_coordinate_is_rejected() -> None:
    request = {
        "dataset_name": "invalid longitude",
        "source_crs": "EPSG:4326",
        "geojson": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "id": "bad-point",
                    "properties": {},
                    "geometry": {"type": "Point", "coordinates": [200.0, 18.0]},
                }
            ],
        },
    }

    with pytest.raises(IngestionError) as captured:
        _run(request)

    assert captured.value.code == "INVALID_GEOGRAPHIC_COORDINATES"
