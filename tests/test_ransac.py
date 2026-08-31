import numpy as np
import pytest

from Processing.ulpin_ingestion.ransac import SimilarityTransform, run_ransac


def test_ransac_excludes_gross_typographical_error() -> None:
    source = np.array([[0.0, 0.0], [20.0, 0.0], [20.0, 20.0], [0.0, 20.0], [10.0, 10.0]])
    truth = SimilarityTransform(a=1.0001, b=0.0002, translate_x=3.0, translate_y=-2.0)
    target = truth.apply(source)
    target[4] += np.array([150.0, -90.0])

    result = run_ransac(
        source,
        target,
        residual_threshold_m=0.05,
        max_trials=100,
        min_inlier_ratio=0.6,
        random_seed=42,
    )

    assert result.inlier_mask.tolist() == [True, True, True, True, False]
    assert result.model.scale == pytest.approx(truth.scale, abs=1e-8)
    assert result.model.rotation_degrees == pytest.approx(truth.rotation_degrees, abs=1e-8)
